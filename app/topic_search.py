"""마크다운 문서 섹션 파싱 및 주제별 텍스트·도표 이미지 정밀 검색 모듈."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    """주제 키워드를 바탕으로 WikiDB 내 관련 마크다운 섹션 및 이미지를 랭킹하여 반환한다.
    
    성능 최적화: 1단계로 파일 텍스트 키워드 매칭으로 상위 후보를 압축한 뒤,
    선별된 문서에 대해서만 정밀 섹션 파싱 및 이미지 매핑을 수행한다.
    """
    if not docs_dir.exists():
        return []

    topic_clean = topic.strip()
    keywords = [k.lower() for k in re.split(r'[\s,._\-+]+', topic_clean) if len(k) >= 2]
    if not keywords:
        keywords = [topic_clean.lower()]

    candidate_docs = []

    # 1단계: 초고속 파일 단위 필터링 및 스코어링
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

        content_lower = content.lower()
        title_lower = title.lower()
        file_lower = md_file.name.lower()

        doc_score = 0.0
        for kw in keywords:
            if kw in title_lower:
                doc_score += 60.0
            if kw in file_lower:
                doc_score += 40.0
            freq = content_lower.count(kw)
            doc_score += min(freq * 2.0, 40.0)

        if doc_score > 0.0:
            candidate_docs.append({
                "doc_id": doc_id,
                "title": title,
                "file_path": str(md_file),
                "score": doc_score,
                "content": content
            })

    if not candidate_docs:
        return []

    # 상위 후보 문서 선별 (top_k * 2)
    candidate_docs.sort(key=lambda d: d["score"], reverse=True)
    top_candidates = candidate_docs[:max(top_k * 2, top_k)]

    # 2단계: 선별된 상위 후보 문서들에 대해서만 정밀 섹션 파싱
    final_matched_docs = []
    for cand in top_candidates:
        sections = parse_markdown_sections(cand["content"], cand["doc_id"], cand["title"])
        relevant_sections = []

        for sec in sections:
            sec_score = 0.0
            sec_text_lower = sec.text.lower()
            sec_heading_lower = sec.heading.lower()

            for kw in keywords:
                if kw in sec_heading_lower:
                    sec_score += 25.0
                if kw in sec_text_lower:
                    sec_score += min(sec_text_lower.count(kw) * 1.5, 20.0)

            core_topics = ["기술", "동향", "개요", "시장", "업체", "규모", "전망", "특징", "구조"]
            if any(core in sec_heading_lower for core in core_topics):
                sec_score += 5.0

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
    return final_matched_docs[:top_k]
