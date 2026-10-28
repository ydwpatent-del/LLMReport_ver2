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
