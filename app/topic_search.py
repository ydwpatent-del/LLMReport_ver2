"""마크다운 문서 섹션 파싱 및 주제별 텍스트·도표 이미지 정밀 검색 모듈.

어휘적(Lexical) 키워드 매칭과 시맨틱(Semantic) 벡터 임베딩을 결합한 하이브리드 지식 검색을 지원합니다.
"""

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils import get_gemini_api_keys_list, is_gemini_key_permanently_exhausted

logger = logging.getLogger("TopicSearch")

# 지원 임베딩 모델 목록 (우선순위 순서)
EMBEDDING_MODELS = ["gemini-embedding-001", "gemini-embedding-2"]


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """두 실수 벡터 간의 코사인 유사도를 계산한다 (-1.0 ~ 1.0)."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class EmbeddingCacheManager:
    """임베딩 벡터를 디스크에 캐싱하여 불필요한 API 호출을 방지하는 관리자."""

    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self._dirty = False
        self._cache = self._load()

    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                content = self.cache_file.read_text(encoding="utf-8")
                return json.loads(content)
            except Exception as e:
                logger.warning(f"임베딩 캐시 로드 실패 (새 캐시 생성): {e}")
        return {}

    def get(self, text: str) -> Optional[list[float]]:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        entry = self._cache.get(key)
        if entry and isinstance(entry, dict) and "embedding" in entry:
            return entry["embedding"]
        return None

    def set(self, text: str, embedding: list[float]) -> None:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        self._cache[key] = {
            "embedding": embedding,
            "dim": len(embedding)
        }
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.cache_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self.cache_file)
            self._dirty = False
        except Exception as e:
            logger.warning(f"임베딩 캐시 디스크 저장 실패: {e}")


_cache_instances: dict[str, EmbeddingCacheManager] = {}

def get_cache_manager(cache_file: Path) -> EmbeddingCacheManager:
    """캐시 파일별 단일 인스턴스를 유지하여 100MB 규모 JSON의 반복 역직렬화를 방지한다."""
    key = str(cache_file.resolve())
    if key not in _cache_instances:
        _cache_instances[key] = EmbeddingCacheManager(cache_file)
    return _cache_instances[key]


def get_embedding(
    text: str,
    client: Optional[object],
    cache: Optional[EmbeddingCacheManager] = None,
    fallback_clients: Optional[list[object]] = None
) -> Optional[list[float]]:
    """텍스트의 임베딩 벡터를 캐시 또는 Gemini API(다중 클라이언트 폴백 지원)로부터 추출한다."""
    clean_text = text.strip()
    if not clean_text:
        return None

    # 1. 캐시 조회
    if cache:
        cached_vec = cache.get(clean_text)
        if cached_vec:
            return cached_vec

    # 2. 호출 대상 클라이언트 목록 구성
    all_clients = []
    if client and getattr(client, "_key_exhausted", False) is not True:
        all_clients.append(client)
    if fallback_clients:
        for fb in fallback_clients:
            if fb not in all_clients and getattr(fb, "_key_exhausted", False) is not True:
                all_clients.append(fb)

    if not all_clients:
        return None

    # 너무 긴 텍스트는 앞 4,000자로 축약
    truncated_text = clean_text[:4000]

    for cli in all_clients:
        for model_name in EMBEDDING_MODELS:
            try:
                response = cli.models.embed_content(
                    model=model_name,
                    contents=truncated_text
                )
                if response and response.embeddings and len(response.embeddings) > 0:
                    values = response.embeddings[0].values
                    if values:
                        if cache:
                            cache.set(clean_text, values)
                        return values
            except Exception as e:
                if is_gemini_key_permanently_exhausted(e):
                    logger.warning(f"Gemini API 키 크레딧 소진(402) 또는 인증 오류 감지 ({e}). 다음 보조 키로 폴백합니다.")
                    try:
                        setattr(cli, "_key_exhausted", True)
                    except Exception:
                        pass
                    break
                logger.debug(f"임베딩 모델 '{model_name}' 호출 오류: {e}")
                continue

    return None


@dataclass
class SectionChunk:
    """헤딩 단위로 분할된 마크다운 섹션 청크."""
    doc_id: str
    doc_title: str
    heading: str
    level: int
    text: str
    images: list[dict] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    category: str = "general"
    relevance_score: float = 0.0

def _classify_section(heading: str, text: str) -> str:
    """섹션 헤딩 및 내용을 바탕으로 5대 목차 영역(overview, tech, market, company)으로 분류한다."""
    h = heading.lower()
    t = text[:400].lower()
    combined = f"{h} {t}"

    if any(k in h for k in ["시장", "규모", "전망", "cagr", "국내 시장", "세계 시장", "매출", "수요", "성장률"]):
        return "market"
    if any(k in h for k in ["업체", "기업", "해외 현황", "국내 현황", "주요업체", "경쟁", "생태계", "플레이어"]):
        return "company"
    if any(k in h for k in ["기술", "동향", "인터커넥트", "패키징", "아키텍처", "표준", "원리", "공정", "소재", "부품", "장비"]):
        return "tech"
    if any(k in h for k in ["개요", "정의", "특징", "구조", "필요성", "배경", "목적"]):
        return "overview"

    # 본문 텍스트 기준 2차 판정
    if any(k in combined for k in ["시장규모", "억 달러", "억 원", "cagr", "시장 규모"]):
        return "market"
    if any(k in combined for k in ["주요 업체", "해외 업체", "국내 업체"]):
        return "company"
    if any(k in combined for k in ["기술", "아키텍처", "패키징"]):
        return "tech"

    return "general"

def _is_cover_or_logo_image(url: str, alt_text: str, caption: str, section_idx: int) -> bool:
    """문서 첫머리의 단순 표지 또는 로고성 이미지를 판별하여 배제한다."""
    lower_url = url.lower()
    lower_alt = alt_text.lower()
    lower_cap = caption.lower()

    # 명시적 표지, 로고 키워드
    cover_keywords = ["표지", "logo", "cover", "아이콘", "icon", "banner", "배너"]
    for kw in cover_keywords:
        if kw in lower_alt or kw in lower_cap:
            return True

    # 문서 최상단 첫 번째 이미지이면서 도표/차트/표 캡션이 없는 경우
    if section_idx == 0 and ("image_001" in lower_url or "image_002" in lower_url):
        is_meaningful = any(term in (lower_alt + " " + lower_cap) for term in ["도표", "그림", "차트", "figure", "chart", "구조", "흐름", "아키텍처"])
        if not is_meaningful:
            return True

    return False

def parse_markdown_sections(md_text: str, doc_id: str, title: str) -> list[SectionChunk]:
    """마크다운 본문을 헤딩 단위로 분할하고 본문, 유의미한 이미지 태그, 표를 추출한다."""
    lines = md_text.split('\n')
    sections: list[SectionChunk] = []
    
    current_heading = "개요"
    current_level = 1
    current_lines: list[str] = []
    section_count = 0

    heading_pattern = re.compile(r'^(#{1,4})\s*(.*?)$')
    img_pattern = re.compile(r'!\[(.*?)\]\((.*?)\)(?:\s*\n\s*\*?\((.*?)\)\*?)?')

    def flush_section():
        nonlocal current_lines, current_heading, current_level, section_count
        if not current_lines:
            return
        
        raw_section_text = '\n'.join(current_lines).strip()
        if not raw_section_text:
            return

        category = _classify_section(current_heading, raw_section_text)

        # 이미지 추출 및 표지/로고 필터링
        images = []
        for match in re.finditer(r'!\[(.*?)\]\((.*?)\)(?:\s*\n\s*\*?\((.*?)\)\*?)?', raw_section_text):
            alt_text = match.group(1) or ""
            img_url = match.group(2) or ""
            caption = match.group(3) or ""
            
            if not _is_cover_or_logo_image(img_url, alt_text, caption, section_count):
                images.append({
                    "alt": alt_text,
                    "url": img_url,
                    "caption": caption
                })

        # 표(Table) 블록 추출 (백트래킹 없는 안전한 라인 스캔)
        tables = []
        table_lines = []
        for line in current_lines:  # l -> line (PEP 8 준수)
            if line.strip().startswith('|') and line.strip().endswith('|'):
                table_lines.append(line)
            else:
                if len(table_lines) >= 2:
                    tables.append('\n'.join(table_lines))
                table_lines = []
        if len(table_lines) >= 2:
            tables.append('\n'.join(table_lines))

        sections.append(SectionChunk(
            doc_id=doc_id,
            doc_title=title,
            heading=current_heading,
            level=current_level,
            text=raw_section_text,
            images=images,
            tables=tables,
            category=category
        ))
        section_count += 1
        current_lines = []

    for line in lines:
        heading_match = heading_pattern.match(line)
        if heading_match:
            flush_section()
            current_level = len(heading_match.group(1))
            extracted_title = heading_match.group(2).strip()
            current_heading = extracted_title if extracted_title else "세부 내용"
        else:
            if current_heading == "세부 내용" and line.strip() and not line.strip().startswith(('!', '<', '>')):
                current_heading = line.strip()
            current_lines.append(line)

    flush_section()
    return sections

def search_relevant_sections(topic: str, docs_dir: Path, top_k: int = 5) -> list[dict]:
    """주제 키워드 및 시맨틱 임베딩을 결합하여 WikiDB 내 관련 마크다운 섹션 및 이미지를 랭킹하여 반환한다.

    1단계: 키워드 매칭 및 문서 단위 시맨틱 유사도로 상위 후보를 압축
    2단계: 선별된 문서의 섹션별 하이브리드(어휘 + 시맨틱) 스코어링 및 이미지 매핑
    """
    if not docs_dir.exists():
        return []

    topic_clean = topic.strip()
    keywords = [k.lower() for k in re.split(r'[\s,._\-+]+', topic_clean) if len(k) >= 2]
    if not keywords:
        keywords = [topic_clean.lower()]

    # 0단계: 임베딩 캐시 및 다중 클라이언트 준비
    cache_file = (docs_dir.parent if docs_dir.name == "docs" else docs_dir) / ".embedding_cache.json"
    cache = get_cache_manager(cache_file)

    clients = []
    keys = get_gemini_api_keys_list()
    if keys:
        try:
            from google import genai
            for k in keys:
                clients.append(genai.Client(api_key=k))
        except Exception as e:
            logger.debug(f"Gemini 클라이언트 초기화 오류: {e}")

    client = clients[0] if clients else None
    fallback_clients = clients[1:] if len(clients) > 1 else []

    # 쿼리 임베딩 추출 (실패 시 None, 다중 클라이언트 자동 폴백)
    query_vector = get_embedding(topic_clean, client, cache, fallback_clients=fallback_clients) if clients else None

    candidate_docs = []
    seen_dedup_keys: dict[str, dict] = {}

    # 1단계: 파일 단위 필터링 및 하이브리드 스코어링 (동일 문헌 중복 방지)
    for md_file in docs_dir.glob("*.md"):
        if ".backup" in str(md_file) or md_file.name.startswith("."):
            continue

        doc_id = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        first_heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else doc_id

        # 무결성 해시 및 원본 파일명 추출을 통한 고유 문헌 식별
        header_sample = content[:2000]
        hash_match = re.search(r'무결성 해시.*?\*\*:\s*`?([a-fA-F0-9]{64})`?', header_sample)
        file_hash = hash_match.group(1).lower() if hash_match else ""

        orig_match = re.search(r'원본 파일명\*\*:\s*`?([^`\r\n]+)`?', header_sample)
        orig_filename = orig_match.group(1).strip() if orig_match else ""

        # 정규화 타이틀 키 (공백, 특수문자, 괄호 등 제거)
        clean_title_key = re.sub(r'[\s_()\[\]\-\.]+', '', title).lower()
        dedup_key = f"hash:{file_hash}" if file_hash else (f"file:{orig_filename.lower()}" if orig_filename else f"title:{clean_title_key}")

        content_lower = content.lower()
        title_lower = title.lower()
        file_lower = md_file.name.lower()

        # 어휘적(Lexical) 점수 계산
        doc_score = 0.0
        for kw in keywords:
            if kw in title_lower:
                doc_score += 60.0
            if kw in file_lower:
                doc_score += 40.0
            freq = content_lower.count(kw)
            doc_score += min(freq * 2.0, 40.0)

        # 시맨틱(Semantic) 벡터 임베딩 유사도 계산 (어휘 불일치 구출)
        if query_vector:
            doc_repr = f"{title}\n{orig_filename}\n{content[:1000]}"
            doc_emb = get_embedding(doc_repr, client, cache, fallback_clients=fallback_clients)
            if doc_emb:
                sim = cosine_similarity(query_vector, doc_emb)
                if sim > 0.55:
                    doc_score += max(0.0, (sim - 0.5) * 100.0)
                # 어휘 키워드가 전혀 없어도 시맨틱 유사도가 높으면 후보로 채택
                if doc_score == 0.0 and sim >= 0.60:
                    doc_score = sim * 50.0

        if doc_score > 0.0:
            doc_entry = {
                "doc_id": doc_id,
                "title": title,
                "file_path": str(md_file),
                "score": doc_score,
                "content": content,
                "file_size": md_file.stat().st_size,
                "mtime": md_file.stat().st_mtime,
                "dedup_key": dedup_key
            }

            # 동일 문헌 중복 제거: 점수가 더 높거나 더 완전한 최신 문서를 우선 유지
            if dedup_key in seen_dedup_keys:
                prev = seen_dedup_keys[dedup_key]
                if doc_score > prev["score"] or (doc_score == prev["score"] and doc_entry["file_size"] > prev["file_size"]):
                    seen_dedup_keys[dedup_key] = doc_entry
            else:
                seen_dedup_keys[dedup_key] = doc_entry

    candidate_docs = list(seen_dedup_keys.values())

    if not candidate_docs:
        cache.save()
        return []

    # 상위 후보 문서 선별 (top_k * 2)
    candidate_docs.sort(key=lambda d: d["score"], reverse=True)
    top_candidates = candidate_docs[:max(top_k * 2, top_k)]

    # 2단계: 선별된 상위 후보 문서들에 대해서만 정밀 섹션 파싱 및 하이브리드 스코어링
    final_matched_docs = []
    for cand in top_candidates:
        sections = parse_markdown_sections(cand["content"], cand["doc_id"], cand["title"])
        relevant_sections = []

        for sec in sections:
            sec_score = 0.0
            sec_text_lower = sec.text.lower()
            sec_heading_lower = sec.heading.lower()

            # 어휘 점수
            for kw in keywords:
                if kw in sec_heading_lower:
                    sec_score += 25.0
                if kw in sec_text_lower:
                    sec_score += min(sec_text_lower.count(kw) * 1.5, 20.0)

            core_topics = ["기술", "동향", "개요", "시장", "업체", "규모", "전망", "특징", "구조", "표준", "분석", "이슈", "개발", "로드맵"]
            if any(core in sec_heading_lower for core in core_topics):
                sec_score += 5.0

            # 도표나 데이터 표가 포함된 섹션은 정보 가치가 높으므로 가산점 부여
            if sec.tables:
                sec_score += 15.0
            if sec.images:
                sec_score += 8.0

            # 이미 1단계에서 선별된 후보 문서의 섹션 기본 기본 점수
            sec_score += 2.0

            # 섹션 단위 시맨틱 임베딩 유사도 반영
            if query_vector:
                sec_repr = f"{sec.heading}\n{sec.text[:800]}"
                sec_emb = get_embedding(sec_repr, client, cache, fallback_clients=fallback_clients)
                if sec_emb:
                    sec_sim = cosine_similarity(query_vector, sec_emb)
                    if sec_sim > 0.55:
                        sec_score += max(0.0, (sec_sim - 0.5) * 80.0)
                    # 어휘 매칭이 없어도 시맨틱 유사도가 높으면 채택
                    if sec_score <= 5.0 and sec_sim >= 0.60:
                        sec_score += sec_sim * 40.0

            if sec_score > 0:
                sec.relevance_score = sec_score
                relevant_sections.append(sec)

        relevant_sections.sort(key=lambda s: s.relevance_score, reverse=True)

        final_matched_docs.append({
            "doc_id": cand["doc_id"],
            "title": cand["title"],
            "file_path": cand["file_path"],
            "score": cand["score"],
            "sections": relevant_sections
        })

    final_matched_docs.sort(key=lambda d: d["score"], reverse=True)
    cache.save()
    return final_matched_docs[:top_k]


# ==============================================================================
# 다차원 지식 프로필 및 LLM 키워드 확장 기반 정밀 검색 체계
# ==============================================================================

@dataclass
class ReportSearchProfile:
    """AI 주제보고서 업데이트 시 지식 DB 검색을 위한 다차원 검색 프로필."""
    primary_topic: str
    synonyms: list[str] = field(default_factory=list)
    technical_terms: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    existing_source_ids: list[str] = field(default_factory=list)
    semantic_query: str = ""


# 주요 첨단 기술 도메인별 표준 동의어 및 핵심 용어 딕셔너리
DOMAIN_SYNONYMS: dict[str, dict[str, list[str]]] = {
    "hbm": {
        "synonyms": ["고대역폭 메모리", "High Bandwidth Memory", "HBM3E", "HBM4"],
        "terms": ["TSV", "실리콘 관통 전극", "DRAM 적층", "첨단 패키징", "로직 다이", "베이스 다이", "CoWoS", "MR-MUF", "하이브리드 본딩", "대역폭", "메모리 병목"],
        "companies": ["SK하이닉스", "삼성전자", "마이크론", "TSMC", "엔비디아", "NVIDIA"]
    },
    "hbf": {
        "synonyms": ["HBF", "High Bandwidth Flash", "고대역폭 플래시"],
        "terms": ["낸드 적층", "NAND", "초고속 플래시", "CXL", "차세대 스토리지", "TSV"],
        "companies": ["SK하이닉스", "삼성전자", "키오시아", "마이크론", "샌디스크"]
    },
    "전고체 배터리": {
        "synonyms": ["전고체 전지", "All-Solid-State Battery", "고체 전해질", "ASSB"],
        "terms": ["황화물계", "산화물계", "고분자계", "음극재", "리튬메탈", "덴드라이트", "이온전도도", "에너지밀도", "양산", "셀"],
        "companies": ["삼성SDI", "LG에너지솔루션", "SK온", "토요타", "CATL"]
    },
    "이차전지 양극재": {
        "synonyms": ["양극재", "양극활물질", "Cathode Active Material", "CAM"],
        "terms": ["하이니켈", "NCM", "NCMA", "LFP", "전구체", "단결정", "리튬", "니켈", "코발트", "망간", "에너지밀도"],
        "companies": ["에코프로비엠", "포스코퓨처엠", "엘앤에프", "LG화학", "코스모신소재"]
    },
    "이차전지 음극재": {
        "synonyms": ["음극재", "음극활물질", "Anode Active Material"],
        "terms": ["실리콘 음극재", "흑연", "인조흑연", "천연흑연", "실리콘 복합소재", "SiOx", "바인더", "초기효율", "팽창"],
        "companies": ["포스코퓨처엠", "대주전자재료", "한솔케미칼", "SKC", "BTR"]
    },
    "인공지능 반도체": {
        "synonyms": ["AI 반도체", "AI 가속기", "NPU", "신경망처리장치", "AI Accelerator"],
        "terms": ["온디바이스 AI", "추론", "학습", "MAC 연산", "저전력", "FP16", "INT8", "SRAM", "PIM", "프로세서"],
        "companies": ["리벨리온", "사피온", "퓨리오사AI", "엔비디아", "삼성전자", "SK텔레콤"]
    },
    "칩렛": {
        "synonyms": ["Chiplet", "칩렛 패키징", "이종 집적", "Heterogeneous Integration"],
        "terms": ["UCIe", "인터커넥트", "2.5D 패키징", "3D 패키징", "다이 투 다이", "D2D", "인터포저", "수율", "모듈화"],
        "companies": ["TSMC", "인텔", "삼성전자", "AMD", "ASE", "앰코"]
    },
    "양자 컴퓨팅": {
        "synonyms": ["Quantum Computing", "양자 컴퓨터", "양자 정보"],
        "terms": ["큐비트", "Qubit", "초전도", "이온트랩", "중성원자", "광자", "양자 얽힘", "양자 중첩", "결맞음", "오류정정"],
        "companies": ["IBM", "구글", "아이온큐", "리게티", "마이크로소프트", "D-Wave"]
    },
    "ai에이전트": {
        "synonyms": ["AI Agent", "자율 에이전트", "Agentic AI"],
        "terms": ["LLM", "추론", "도구 사용", "Tool Use", "Function Calling", "자율 주도", "Multi-Agent", "오케스트레이션", "RAG"],
        "companies": ["OpenAI", "Anthropic", "구글", "마이크로소프트", "메타"]
    },
    "피지컬 ai": {
        "synonyms": ["Physical AI", "임바디드 AI", "Embodied AI"],
        "terms": ["휴머노이드", "로봇", "센서 융합", "월드 모델", "자율제어", "액추에이터", "디지털 트윈", "공간지능"],
        "companies": ["테슬라", "보스턴다이내믹스", "피규어AI", "엔비디아", "현대차"]
    },
    "자율주행차": {
        "synonyms": ["자율주행", "Autonomous Vehicle", "FSD"],
        "terms": ["라이다", "LiDAR", "레이더", "카메라", "End-to-End", "V2X", "ADAS", "레벨4", "레벨3", "센서퓨전"],
        "companies": ["테슬라", "웨이모", "모빌아이", "현대차", "바이두"]
    }
}


def extract_search_profile_rules(report_markdown: str, topic: str) -> ReportSearchProfile:
    """보고서 마크다운 본문의 1~5장 및 각주, 사전 정의된 동의어 매핑을 기반으로
    0.01초 내에 규칙 기반 검색 프로필(Baseline Search Profile)을 추출한다."""
    clean_topic = topic.strip()
    topic_lower = clean_topic.lower()

    synonyms: set[str] = set()
    technical_terms: set[str] = set()
    companies: set[str] = set()
    existing_source_ids: set[str] = set()

    # 1. 표준 도메인 사전 매핑 (일치 또는 포함 관계 탐색)
    for dom_key, dom_data in DOMAIN_SYNONYMS.items():
        if dom_key in topic_lower or topic_lower in dom_key:
            synonyms.update(dom_data.get("synonyms", []))
            technical_terms.update(dom_data.get("terms", []))
            companies.update(dom_data.get("companies", []))
            break

    # 2. 기존 보고서 5장 데이터 출처 문서 ID 수집
    source_matches = re.findall(r'/api/documents/([^\)\s>]+)', report_markdown)
    for sid in source_matches:
        clean_sid = re.sub(r'\[\^(\d+)\][,\]\)]*$', r'\1', sid).rstrip('],>.)')
        if clean_sid:
            existing_source_ids.add(clean_sid)

    # 3. 본문 내 각주 용어 수집: [^1]: **용어**: 설명
    footnote_matches = re.findall(r'\[\^\d+\]:\s*\*\*(.*?)\*\*', report_markdown)
    for fn_term in footnote_matches:
        t = fn_term.strip()
        if len(t) >= 2 and len(t) <= 30:
            technical_terms.add(t)

    # 4. 1장 및 2장 본문 내 영문 대문자 약어(TSV, HBM, GPU 등) 및 볼드체 핵심어 수집
    sec1_2_match = re.search(r'##\s*1\..*?(?=##\s*3\.|\Z)', report_markdown, re.DOTALL)
    if sec1_2_match:
        sec1_2_text = sec1_2_match.group(0)
        # 영문 대문자 약어 (예: TSV, DRAM, GPU, JEDEC, CoWoS 등)
        acronyms = re.findall(r'\b[A-Z][A-Za-z0-9\-]{1,10}\b', sec1_2_text)
        for acr in acronyms:
            if acr.lower() != "the" and acr.lower() != "and" and len(acr) >= 2:
                technical_terms.add(acr)
        # 볼드체 강조어
        bold_terms = re.findall(r'\*\*([가-힣A-Za-z0-9\s_\-\/]{2,20})\*\*', sec1_2_text)
        for bt in bold_terms:
            bt_clean = bt.strip()
            if len(bt_clean) >= 2 and not bt_clean.startswith("출처"):
                technical_terms.add(bt_clean)

    # 5. 4장 주요업체 본문 내 기업명 추출
    sec4_match = re.search(r'##\s*4\..*?(?=##\s*5\.|\Z)', report_markdown, re.DOTALL)
    if sec4_match:
        sec4_text = sec4_match.group(0)
        known_companies = [
            "SK하이닉스", "삼성전자", "마이크론", "TSMC", "엔비디아", "NVIDIA", "인텔", "AMD",
            "삼성SDI", "LG에너지솔루션", "SK온", "토요타", "CATL", "포스코퓨처엠", "에코프로비엠",
            "엘앤에프", "LG화학", "리벨리온", "사피온", "퓨리오사AI", "OpenAI", "Anthropic", "구글", "테슬라"
        ]
        for comp in known_companies:
            if comp in sec4_text:
                companies.add(comp)

    # 6. 기본 시맨틱 쿼리문 구성
    first_p_match = re.search(r'##\s*1\.[^\n]*\n+([^\n]+)', report_markdown)
    first_p = first_p_match.group(1).strip() if first_p_match else ""
    first_p_clean = re.sub(r'<출처:[^>]+>', '', first_p).strip()[:200]
    semantic_query = f"{clean_topic} 핵심 기술동향 및 시장 전망. {first_p_clean}".strip()

    return ReportSearchProfile(
        primary_topic=clean_topic,
        synonyms=sorted(list(synonyms)),
        technical_terms=sorted(list(technical_terms)),
        companies=sorted(list(companies)),
        existing_source_ids=sorted(list(existing_source_ids)),
        semantic_query=semantic_query
    )


def expand_search_profile_with_llm(
    report_markdown: str,
    profile: ReportSearchProfile,
    client: Optional[object] = None,
    fallback_clients: Optional[list[object]] = None
) -> ReportSearchProfile:
    """Gemini LLM을 호출하여 기존 보고서의 문맥을 기반으로 동의어, 핵심 요소기술,
    밸류체인 플레이어 및 풍부한 시맨틱 쿼리문을 심층 확장한다.
    
    오류나 키 소진 발생 시 1단계 규칙 기반 프로필로 안전하게 즉시 폴백(Graceful Fallback)한다."""
    # 호출 가능한 클라이언트 목록 구성
    all_clients = []
    if client and getattr(client, "_key_exhausted", False) is not True:
        all_clients.append(client)
    if fallback_clients:
        for fb in fallback_clients:
            if fb not in all_clients and getattr(fb, "_key_exhausted", False) is not True:
                all_clients.append(fb)

    if not all_clients:
        # LLM 클라이언트가 없으면 기존 프로필 그대로 반환
        return profile

    # 보고서 요약 컨텍스트 생성 (제목 + 1장 개요 첫 600자 + 2장 기술동향 첫 600자)
    summary_snippets = [f"주제: {profile.primary_topic}"]
    first_heading = re.search(r'^#\s+(.+)$', report_markdown, re.MULTILINE)
    if first_heading:
        summary_snippets.append(f"제목: {first_heading.group(1).strip()}")

    sec1_m = re.search(r'##\s*1\.[^\n]*\n+([\s\S]{1,600}?)(?=\n##|\Z)', report_markdown)
    if sec1_m:
        summary_snippets.append(f"개요 발췌:\n{sec1_m.group(1).strip()}")

    sec2_m = re.search(r'##\s*2\.[^\n]*\n+([\s\S]{1,600}?)(?=\n##|\Z)', report_markdown)
    if sec2_m:
        summary_snippets.append(f"기술동향 발췌:\n{sec2_m.group(1).strip()}")

    report_context = "\n\n".join(summary_snippets)

    prompt = f"""당신은 전문 기술 분석가입니다. 지식 데이터베이스(WikiDB)에서 아래 보고서의 최신 증분 업데이트에 필요한 핵심 관련 문헌을 정확하게 검색하기 위해 검색 키워드를 확장해 주십시오.

[보고서 개요]
{report_context}

[기존 기본 수집 키워드]
- 동의어: {", ".join(profile.synonyms[:5]) if profile.synonyms else "없음"}
- 기술용어: {", ".join(profile.technical_terms[:8]) if profile.technical_terms else "없음"}
- 관련기업: {", ".join(profile.companies[:5]) if profile.companies else "없음"}

[요청 사항]
보고서 내용과 밀접하게 연관된 최신 기술 보고서, 산업 분석서, 학술 논문을 찾기 위한 고품질 키워드를 확장하십시오.
반드시 아래 JSON 포맷으로만 응답하십시오 (마크다운 백틱 없이 순수 JSON만 반환):
{{
  "synonyms": ["영문 공식명칭, 한글 공식명칭, 축약어 3~5개"],
  "technical_terms": ["핵심 요소기술, 핵심 공정, 표준 규격, 물리적 부품명 5~10개"],
  "companies": ["핵심 공급망 기업 및 글로벌 주요 플레이어 3~6개"],
  "semantic_query": "문서 벡터 임베딩 유사도 검색을 위한 풍부하고 자연스러운 문장 (1~2문장)"
}}
"""

    model_candidates = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    for cli in all_clients:
        for model_name in model_candidates:
            try:
                response = cli.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                resp_text = (response.text or "").strip()
                # 마크다운 백틱 제거
                if resp_text.startswith("```"):
                    resp_text = re.sub(r'^```(?:json)?\s*', '', resp_text)
                    resp_text = re.sub(r'\s*```$', '', resp_text)

                data = json.loads(resp_text)
                if isinstance(data, dict):
                    # 성공적으로 JSON 파싱 완료 시 프로필과 통합
                    merged_synonyms = set(profile.synonyms)
                    for item in data.get("synonyms", []):
                        if isinstance(item, str) and len(item.strip()) >= 2:
                            merged_synonyms.add(item.strip())

                    merged_terms = set(profile.technical_terms)
                    for item in data.get("technical_terms", []):
                        if isinstance(item, str) and len(item.strip()) >= 2:
                            merged_terms.add(item.strip())

                    merged_companies = set(profile.companies)
                    for item in data.get("companies", []):
                        if isinstance(item, str) and len(item.strip()) >= 2:
                            merged_companies.add(item.strip())

                    semantic_q = data.get("semantic_query", "").strip()
                    if not semantic_q:
                        semantic_q = profile.semantic_query

                    logger.info(
                        f"LLM 키워드 확장 완료 ({model_name}): "
                        f"동의어 {len(merged_synonyms)}개, 기술용어 {len(merged_terms)}개, 기업 {len(merged_companies)}개"
                    )

                    return ReportSearchProfile(
                        primary_topic=profile.primary_topic,
                        synonyms=sorted(list(merged_synonyms)),
                        technical_terms=sorted(list(merged_terms)),
                        companies=sorted(list(merged_companies)),
                        existing_source_ids=profile.existing_source_ids,
                        semantic_query=semantic_q
                    )
            except Exception as e:
                if is_gemini_key_permanently_exhausted(e):
                    logger.warning(f"LLM 키워드 확장 중 API 키 소진(402) 감지: {e}. 다음 보조 키로 전환합니다.")
                    try:
                        setattr(cli, "_key_exhausted", True)
                    except Exception:
                        pass
                    break
                logger.debug(f"LLM 키워드 확장 모델 '{model_name}' 호출 오류 (다음 모델 시도): {e}")
                continue

    # 모든 LLM 호출 실패 시 기본 규칙 기반 프로필 반환 (Graceful Fallback)
    logger.info("LLM 키워드 확장 스킵 또는 오류 -> 규칙 기반 프로필로 안전하게 계속 진행합니다.")
    return profile


def search_relevant_sections_with_profile(
    profile: ReportSearchProfile,
    docs_dir: Path,
    report_mtime: float = 0.0,
    top_k: int = 5
) -> list[dict]:
    """다차원 검색 프로필(주제어, 동의어, 기술용어, 기업명, 시맨틱 쿼리문)을 바탕으로
    비선형 포화 어휘 스코어링 및 최신성(Recency) 부스팅을 결합한 하이브리드 검색을 수행한다."""
    if not docs_dir.exists():
        return []

    # 1. 어휘 검색군 분류 및 정규화
    primary_topic_clean = profile.primary_topic.strip().lower()
    core_keywords = set()
    for kw in [profile.primary_topic] + profile.synonyms:
        k_clean = kw.strip().lower()
        if len(k_clean) >= 2:
            core_keywords.add(k_clean)
            for sub_k in re.split(r'[\s,._\-+]+', k_clean):
                if len(sub_k) >= 2:
                    core_keywords.add(sub_k)

    tech_keywords = set()
    for term in profile.technical_terms:
        t_clean = term.strip().lower()
        if len(t_clean) >= 2:
            tech_keywords.add(t_clean)

    company_keywords = set()
    for comp in profile.companies:
        c_clean = comp.strip().lower()
        if len(c_clean) >= 2:
            company_keywords.add(c_clean)

    # 2. 임베딩 캐시 및 클라이언트 준비
    cache_file = (docs_dir.parent if docs_dir.name == "docs" else docs_dir) / ".embedding_cache.json"
    cache = get_cache_manager(cache_file)

    clients = []
    keys = get_gemini_api_keys_list()
    if keys:
        try:
            from google import genai
            for k in keys:
                clients.append(genai.Client(api_key=k))
        except Exception as e:
            logger.debug(f"Gemini 클라이언트 초기화 오류: {e}")

    client = clients[0] if clients else None
    fallback_clients = clients[1:] if len(clients) > 1 else []

    # 시맨틱 쿼리 임베딩 추출 (프로필의 풍부한 시맨틱 쿼리문 활용)
    semantic_q_text = profile.semantic_query or f"{profile.primary_topic} 핵심 기술 및 시장 전망"
    query_vector = get_embedding(semantic_q_text, client, cache, fallback_clients=fallback_clients) if clients else None

    candidate_docs = []
    seen_dedup_keys: dict[str, dict] = {}

    # 3. 1단계: 파일 단위 비선형 포화 어휘 스코어링 및 시맨틱 유사도 계산
    for md_file in docs_dir.glob("*.md"):
        if ".backup" in str(md_file) or md_file.name.startswith("."):
            continue

        doc_id = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            file_stat = md_file.stat()
            file_mtime = file_stat.st_mtime
            file_size = file_stat.st_size
        except Exception:
            continue

        first_heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else doc_id

        header_sample = content[:2000]
        hash_match = re.search(r'무결성 해시.*?\*\*:\s*`?([a-fA-F0-9]{64})`?', header_sample)
        file_hash = hash_match.group(1).lower() if hash_match else ""

        orig_match = re.search(r'원본 파일명\*\*:\s*`?([^`\r\n]+)`?', header_sample)
        orig_filename = orig_match.group(1).strip() if orig_match else ""

        clean_title_key = re.sub(r'[\s_()\[\]\-\.]+', '', title).lower()
        dedup_key = f"hash:{file_hash}" if file_hash else (f"file:{orig_filename.lower()}" if orig_filename else f"title:{clean_title_key}")

        content_lower = content.lower()
        title_lower = title.lower()
        file_lower = md_file.name.lower()

        doc_score = 0.0

        # A. 핵심 주제어(Primary Topic + Synonyms) 어휘 스코어링
        core_hit_count = 0
        core_total_freq = 0
        for kw in core_keywords:
            if kw in title_lower:
                doc_score += 80.0
                core_hit_count += 1
            if kw in file_lower:
                doc_score += 50.0
                core_hit_count += 1
            freq = content_lower.count(kw)
            if freq > 0:
                core_total_freq += freq
                core_hit_count += 1

        # 비선형 포화 함수 적용: S = (freq * 3.0 / (freq + 2.0)) * 30.0 (40점 플랫 방지)
        if core_total_freq > 0:
            doc_score += (core_total_freq * 3.0 / (core_total_freq + 2.0)) * 30.0

        # B. 핵심 요소기술(Technical Terms) 어휘 스코어링
        tech_hit_count = 0
        tech_total_freq = 0
        for term in tech_keywords:
            if term in title_lower:
                doc_score += 35.0
                tech_hit_count += 1
            freq = content_lower.count(term)
            if freq > 0:
                tech_total_freq += freq
                tech_hit_count += 1

        # 요소기술 비선형 포화 함수 적용: S = (freq * 2.0 / (freq + 3.0)) * 25.0
        if tech_total_freq > 0:
            doc_score += (tech_total_freq * 2.0 / (tech_total_freq + 3.0)) * 25.0

        # C. 주요 플레이어(Companies) 어휘 스코어링
        comp_hit_count = 0
        for comp in company_keywords:
            if comp in title_lower:
                doc_score += 20.0
                comp_hit_count += 1
            elif comp in content_lower:
                doc_score += 5.0
                comp_hit_count += 1
        doc_score += min(comp_hit_count * 5.0, 25.0)

        # D. 복합 일치 시너지 보너스 (Compound Match Bonus):
        # 주 주제어와 핵심 요소기술이 같은 문서에 동시에 풍부하게 공존할 때 강력한 가산점 부여
        if core_hit_count > 0 and tech_hit_count > 0:
            doc_score += 50.0
            if tech_hit_count >= 2:
                doc_score += 30.0
            if comp_hit_count > 0:
                doc_score += 20.0

        # E. 기존 보고서 5장 출처 연관 가중치
        if doc_id in profile.existing_source_ids:
            doc_score += 20.0

        # F. 시맨틱(Semantic) 벡터 임베딩 유사도 계산
        if query_vector:
            doc_repr = f"{title}\n{orig_filename}\n{content[:1500]}"
            doc_emb = get_embedding(doc_repr, client, cache, fallback_clients=fallback_clients)
            if doc_emb:
                sim = cosine_similarity(query_vector, doc_emb)
                if sim > 0.50:
                    doc_score += max(0.0, (sim - 0.45) * 100.0)
                if doc_score == 0.0 and sim >= 0.58:
                    doc_score = sim * 50.0

        # G. 최신성(Recency) 부스팅: 보고서 작성 시점(report_mtime) 이후 문서에 가산점 부여
        if doc_score > 0.0 and report_mtime > 0:
            if file_mtime > report_mtime:
                doc_score *= 1.35  # 최신 문서에 35% 부스팅
                doc_score += 30.0  # 기본 최신성 가산점 30점

        if doc_score > 0.0:
            doc_entry = {
                "doc_id": doc_id,
                "title": title,
                "file_path": str(md_file),
                "score": doc_score,
                "content": content,
                "file_size": file_size,
                "mtime": file_mtime,
                "dedup_key": dedup_key
            }

            if dedup_key in seen_dedup_keys:
                prev = seen_dedup_keys[dedup_key]
                if doc_score > prev["score"] or (doc_score == prev["score"] and file_size > prev["file_size"]):
                    seen_dedup_keys[dedup_key] = doc_entry
            else:
                seen_dedup_keys[dedup_key] = doc_entry

    candidate_docs = list(seen_dedup_keys.values())
    if not candidate_docs:
        cache.save()
        return []

    # 상위 후보 선별 (top_k * 2)
    candidate_docs.sort(key=lambda d: d["score"], reverse=True)
    top_candidates = candidate_docs[:max(top_k * 2, top_k)]

    # 4. 2단계: 선별된 상위 후보 문서 정밀 섹션 파싱 및 스코어링
    final_matched_docs = []
    for cand in top_candidates:
        sections = parse_markdown_sections(cand["content"], cand["doc_id"], cand["title"])
        relevant_sections = []

        for sec in sections:
            sec_score = 0.0
            sec_text_lower = sec.text.lower()
            sec_heading_lower = sec.heading.lower()

            for kw in core_keywords:
                if kw in sec_heading_lower:
                    sec_score += 30.0
                if kw in sec_text_lower:
                    sec_score += min(sec_text_lower.count(kw) * 2.0, 25.0)

            for term in tech_keywords:
                if term in sec_heading_lower:
                    sec_score += 20.0
                if term in sec_text_lower:
                    sec_score += min(sec_text_lower.count(term) * 1.5, 15.0)

            core_topics = ["기술", "동향", "개요", "시장", "업체", "규모", "전망", "특징", "구조", "표준", "분석", "이슈", "개발", "로드맵"]
            if any(core in sec_heading_lower for core in core_topics):
                sec_score += 5.0

            if sec.tables:
                sec_score += 15.0
            if sec.images:
                sec_score += 8.0

            sec_score += 2.0

            if query_vector:
                sec_repr = f"{sec.heading}\n{sec.text[:800]}"
                sec_emb = get_embedding(sec_repr, client, cache, fallback_clients=fallback_clients)
                if sec_emb:
                    sec_sim = cosine_similarity(query_vector, sec_emb)
                    if sec_sim > 0.50:
                        sec_score += max(0.0, (sec_sim - 0.45) * 80.0)

            if sec_score > 0:
                sec.relevance_score = sec_score
                relevant_sections.append(sec)

        relevant_sections.sort(key=lambda s: s.relevance_score, reverse=True)

        final_matched_docs.append({
            "doc_id": cand["doc_id"],
            "title": cand["title"],
            "file_path": cand["file_path"],
            "score": cand["score"],
            "mtime": cand["mtime"],
            "sections": relevant_sections
        })

    final_matched_docs.sort(key=lambda d: d["score"], reverse=True)
    cache.save()
    return final_matched_docs[:top_k]


def search_relevant_sections_for_report(
    report_markdown: str,
    topic: str,
    docs_dir: Path,
    report_mtime: float = 0.0,
    top_k: int = 7,
    api_key: Optional[str] = None
) -> list[dict]:
    """보고서 본문을 바탕으로 규칙 기반 프로필 추출 및 LLM 키워드 확장을 거쳐
    지식 DB(WikiDB) 내에서 최신 증분 업데이트에 가장 적합한 관련 문헌을 정밀 검색한다."""
    # 1. 1차 규칙 기반 프로필 추출 (0.01초 소요 안전망)
    profile = extract_search_profile_rules(report_markdown, topic)

    # 2. 2차 Gemini LLM 클라이언트 준비 및 키워드 확장
    clients = []
    keys = get_gemini_api_keys_list()
    if api_key and api_key not in keys:
        keys.insert(0, api_key)

    if keys:
        try:
            from google import genai
            for k in keys:
                clients.append(genai.Client(api_key=k))
        except Exception as e:
            logger.debug(f"LLM 키워드 확장 클라이언트 초기화 오류: {e}")

    client = clients[0] if clients else None
    fallback_clients = clients[1:] if len(clients) > 1 else []

    if client:
        profile = expand_search_profile_with_llm(
            report_markdown=report_markdown,
            profile=profile,
            client=client,
            fallback_clients=fallback_clients
        )

    # 3. 비선형 포화 어휘 스코어링, 시맨틱 임베딩 및 최신성 부스팅 기반 정밀 검색 수행
    return search_relevant_sections_with_profile(
        profile=profile,
        docs_dir=docs_dir,
        report_mtime=report_mtime,
        top_k=top_k
    )

