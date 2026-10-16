"""kordoc-wiki-ingest 스킬 규격에 맞춘 AI 및 룰베이스 위키 지식 리파이너 모듈."""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.utils import generate_standard_metadata_header, generate_toc_and_anchors, KNOWN_PUBLISHERS

logger = logging.getLogger("AIRefiner")

class AIRefiner:
    """kordoc 1차 파싱 결과를 LLM Wiki Ground Truth 고품질 완본으로 승화시키는 정돈 엔진."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY 환경변수가 설정되지 않았습니다. LLM 기반 정돈 기능이 비활성화됩니다.")

    def _extract_metadata_info(self, text: str, filename: str) -> dict:
        """문서 텍스트와 파일명으로부터 발행기관, 발행일자, 엔티티 태그, 분류를 추출한다."""
        info = {
            "title": Path(filename).stem,
            "publisher": "미상 (원문 기재)",
            "date": datetime.now(timezone.utc).strftime("%Y년 %m월 %d일"),
            "category": "리서치 보고서 / 기술 문서",
            "entities": []
        }

        # 1. 발행기관 탐지 (utils.KNOWN_PUBLISHERS 단일 진실원 사용)
        for pub in KNOWN_PUBLISHERS:
            if pub in filename or pub in text[:1000]:
                info["publisher"] = pub
                break

        # 2. 발행일자 탐지
        date_match = re.search(r'(202[0-9])[.\-_년\s]+(0?[1-9]|1[0-2])[.\-_월\s]+(0?[1-9]|[12][0-9]|3[01])', text[:1500] + " " + filename)
        if date_match:
            y, m, d = date_match.groups()
            info["date"] = f"{y}년 {int(m):02d}월 {int(d):02d}일"

        # 3. 핵심 엔티티 추출 (영문 대문자 약어 및 주요 키워드)
        keywords = set()
        clean_name = re.sub(r'[0-9_\-\.]', ' ', Path(filename).stem)
        for w in clean_name.split():
            if len(w) >= 2 and not w.isdigit():
                keywords.add(w)

        found_abbrs = re.findall(r'\b[A-Z]{2,10}(?:[0-9]{1,3})?\b', text[:3000])
        common_exclude = {"THE", "AND", "FOR", "WITH", "FROM", "PDF", "DOCX", "HWPX", "PAGE", "TOC", "HTTP", "HTTPS", "COM"}
        for abbr in found_abbrs:
            if abbr not in common_exclude and len(abbr) >= 2:
                keywords.add(abbr)

        industry_words = ["반도체", "인공지능", "생성형AI", "전력망", "이차전지", "소부장", "공급망", "재무제표", "습도센서", "자율주행", "바이오"]
        for ind in industry_words:
            if ind in text[:3000] or ind in filename:
                keywords.add(ind)

        info["entities"] = sorted(list(keywords))[:8]
        return info

    def _normalize_headings_and_structure(self, text: str) -> str:
        """엄격한 헤딩 위계(# I., ## 1., ### 가.)와 문단 흐름을 정돈한다."""
        lines = text.split('\n')
        normalized_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                normalized_lines.append("")
                continue

            if re.match(r'^(?:[#\s]*)(?:[I|V|X]+|[Ⅰ-Ⅻ]+)\.\s*(.+)$', stripped):
                match = re.match(r'^(?:[#\s]*)(?:[I|V|X]+|[Ⅰ-Ⅻ]+)\.\s*(.+)$', stripped)
                normalized_lines.append(f"\n## {match.group(0).lstrip('#').strip()}")
                continue

            if re.match(r'^(?:[#\s]*)\d+\.\s+([가-힣A-Za-z0-9].{2,40})$', stripped) and not stripped.endswith(('.', '억원', '%', '달러')):
                clean_title = stripped.lstrip('#').strip()
                normalized_lines.append(f"\n### {clean_title}")
                continue

            if re.match(r'^(?:[#\s]*)(?:[가-하]\.|\(\d+\)|\d+\))\s+([가-힣A-Za-z0-9].{2,40})$', stripped):
                clean_title = stripped.lstrip('#').strip()
                normalized_lines.append(f"\n#### {clean_title}")
                continue

            normalized_lines.append(line)

        return '\n'.join(normalized_lines)

    def _refine_inline_image_captions(self, text: str) -> str:
        """도표 및 차트 이미지 링크 주변의 캡션(도표 제목, 출처, 단위)을 매끄럽게 인라인 결합한다."""
        def replace_caption_after(match):
            img_tag = match.group(1)
            caption_line = match.group(2).strip()
            return f"{img_tag}\n*({caption_line.strip('()*<>')})*"

        text = re.sub(
            r'(!\[.*?\]\(.*?\))\n+([<\[\(]?(?:도표|그림|차트|표|Figure|Chart)\s*\d+.*?[\)\]>]?)\b',
            replace_caption_after,
            text,
            flags=re.IGNORECASE
        )

        return text

    def refine_text(
        self,
        raw_md: str,
        doc_id: str,
        original_filename: str,
        file_hash: str
    ) -> tuple[str, dict]:
        """kordoc-wiki-ingest 5대 원칙에 따라 마크다운을 고품질 위키 Ground Truth 완본으로 정돈한다."""
        # 1. 메타데이터 분석
        meta = self._extract_metadata_info(raw_md, original_filename)
        ext = Path(original_filename).suffix.lstrip('.').upper() or "문서"

        # 2. 구조화 및 헤딩 위계 정돈
        structured_md = self._normalize_headings_and_structure(raw_md)

        # 3. 도표 캡션 및 인라인 이미지 문맥 결합
        captioned_md = self._refine_inline_image_captions(structured_md)

        # 4. 엔티티 태그 문자열 생성
        entity_tags = " ".join([f"#{e}" for e in meta["entities"]]) if meta["entities"] else "#지식베이스 #전수복원"

        # 5. kordoc-wiki-ingest 표준 메타데이터 헤더 구성 (단일 함수 일원화)
        header = generate_standard_metadata_header(
            title=meta["title"],
            original_filename=original_filename,
            file_hash=file_hash,
            ext=ext,
            publisher=meta["publisher"],
            date_str=meta["date"],
            category=meta["category"],
            entity_tags=entity_tags
        )

        full_doc = header + captioned_md.strip() + "\n"
        final_doc_with_toc = generate_toc_and_anchors(full_doc)
        return final_doc_with_toc, meta
