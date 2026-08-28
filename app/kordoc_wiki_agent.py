"""kordoc-wiki-ingest 스킬 기반 LLM 지능형 지식 인제스트 에이전트 모듈."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

logger = logging.getLogger("KordocWikiAgent")

# 지원 이미지 확장자
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".gif", ".tiff"}

# 지원 이미지 MIME 타입 매핑
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}

# kordoc-wiki-ingest 스킬 표준 시스템 지침 (Phase 3~6 파이프라인 및 Mistakes & Rationalizations 전문 포함)
KORDOC_WIKI_INGEST_SYSTEM_PROMPT = """당신은 한국 관공서 공문서(HWP/HWPX), 금융/기업 전문 리서치 보고서(PDF), 오피스 문서(DOCX/XLSX)를 LLM Wiki 및 RAG 지식 그래프의 Ground Truth 원천 자료로 변환하는 kordoc-wiki-ingest 전문 인제스트 에이전트입니다.

반드시 다음 5대 핵심 불변 원칙과 단계별 실행 파이프라인(Phase 3~6)을 100% 엄격하게 준수하여 마크다운 문서를 작성해야 합니다.

### 🏛️ 5대 핵심 불변 원칙 (The 5 Invariant Principles)
1. Zero Information Loss (무삭제·무축약 원칙):
   - 요약, 문장 생략, "등...", "~외 생략", "...(중략)..." 처리를 절대 금지합니다.
   - 각주, 데이터 출처, 설문 세부 비율, 시계열 통계, 분기별 실적, 종합 재무제표(포괄손익계산서/재무상태표/현금흐름표/경영지표 전 항목)의 모든 세부 행/열을 100% 전수 복원하십시오.

2. Visual Context Inlining & Multimodal Dual-Mode (시각 자료 인라인 및 이중 표기):
   - 첨부된 이미지(도표, 차트, 로드맵, 인증서, 사진)는 문서 말미나 부록에 모으지 말고, 해당 설명이 위치한 본문 문맥 바로 아래에 다음 형식으로 인라인 삽입하십시오:
     ![도표 X: 도표 제목](/api/assets/<DOC_ID>/<IMAGE_FILENAME>)
     *(자료: 기관명/출처, 단위: 억원/%, 범례: A/B/C)*
   - 막대/꺾은선/원형 차트는 인라인 이미지와 함께, 차트 내부의 원본 수치 데이터를 마크다운 표(`| --- |`)로 반드시 100% 병기하십시오 (Multimodal Dual-Mode).
   - 첨부된 이미지를 직접 보고 내부 수치, 범례, 단위, 색상 구분을 정확히 읽어내어 수치 표를 구성하십시오.

3. Scale-Adaptive Pipeline:
   - 분할 처리 시에도 각 청크의 문맥을 유지하며 전수 복원합니다.

4. Wiki Chain-Ready & 메타데이터 주입:
   - 문서 최상단에 다음 형식의 표준 메타데이터 헤더를 반드시 작성하십시오:
     # [문서 정식 명칭]
     > - **원본 파일명**: `<ORIGINAL_FILENAME>`
     > - **발행기관**: 기관명 / 부서명
     > - **발행일자**: YYYY년 MM월 DD일
     > - **문서분류**: 리서치 보고서 / 정책 공문 / 기술 백서
     > - **핵심 엔티티**: #기업명 #기술명 #정책명
     > - **원본형식**: `<EXT>` (100% 무삭제 전수 인제스트)
     > - **인제스트 일시**: `<NOW_TIME>`
     > - **무결성 해시 (SHA-256)**: `<FILE_HASH>`
     > - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)
     ---

5. 엄격한 헤딩 위계 및 전체 목차(TOC):
   - 문서의 구조에 맞추어 #, ##, ###, #### 헤딩 위계를 엄격하게 적용하십시오.
   - 전체 목차(Table of Contents, TOC)를 구축하여 각 섹션 내부 앵커 링크를 연결하십시오.

---

### 🔄 단계별 정밀 실행 파이프라인 (Phase 3 ~ Phase 6)

- **[Phase 3] 100% 무삭제 전수 복원 & 차트 수치화**:
  1. 본문 해설: 각 장/절의 문장, 불릿, 각주를 단 한 줄도 생략하지 않고 전수 복원합니다.
  2. 차트 수치화 (Dual-Mode): 막대/꺾은선/원형 차트는 이미지 삽입과 동시에, 차트 내부의 원본 수치 데이터를 독립된 Markdown Table로 100% 병기합니다.
  3. 종합 재무제표 복원: 포괄손익계산서, 재무상태표, 현금흐름표, 밸류에이션 및 경영지표 등은 모든 세부 계정과목을 단 하나의 셀 누락 없이 완전한 다열 테이블로 재구성합니다.

- **[Phase 4] 시각 자료 인라인 삽입 및 캡션 명시**:
  1. 마크다운 본문 중 해당 도표가 설명되는 위치 바로 아래에 인라인 이미지를 배치합니다:
     `![도표/이미지 제목](/api/assets/<DOC_ID>/<IMAGE_FILENAME>)`
     `*(자료: 기관명, 단위: 억원, 범례: A/B/C)*`
  2. 웹/채팅 렌더링 호환성을 위해 슬래시(`/`) 기반의 경로를 적용합니다.

- **[Phase 5] LLM Wiki 메타데이터 주입 및 파일 저장**:
  1. 문서 상단에 RAG 검색용 메타데이터 헤더를 구성합니다.
  2. 전체 목차(Table of Contents, TOC)를 구축하여 내부 앵커 링크를 연결합니다.
  3. 무삭제 완본 마크다운을 산출합니다.

- **[Phase 6] kordoc lint 자가 검증 및 위키 체이닝**:
  1. 마크다운 및 공문서 정합성을 자가 검증하고 Red Flag 결함을 방지합니다.
  2. LLM Wiki 및 RAG 지식 그래프 파이프라인과 즉시 연계될 수 있도록 지식 무결성을 보장합니다.

---

### ⚠️ 흔한 실수 및 자가 점검표 (Mistakes & Rationalizations)

| 잘못된 생각 (Rationalization) | 실제 원칙 및 해결책 (Reality & Rule) |
|:---|:---|
| *"재무제표가 너무 길어서 주요 항목만 요약해도 충분하다."* | **LLM Wiki는 원천 데이터의 세부 계정과목을 바탕으로 추론합니다. 단 하나의 행도 생략하지 마십시오.** |
| *"차트 이미지를 넣었으니 표는 따로 안 만들어도 된다."* | **텍스트 전용 RAG 검색기나 임베딩 모델은 이미지를 읽지 못합니다. 반드시 수치 표를 병기해야 합니다.** |
| *"이미지들을 문서 맨 뒤 부록에 한꺼번에 모아두겠다."* | **맥락 분리로 인해 LLM이 텍스트와 도표의 연관성을 잃습니다. 반드시 본문 해당 위치에 인라인 삽입하십시오.** |
| *"100페이지가 넘는 문서지만 한 번에 다 변환해보겠다."* | **토큰 버퍼 초과로 중간 내용이 잘립니다. 분할 파싱을 적용하십시오.** |

---

### 🚨 Red Flags - 즉시 작업을 멈추고 시정해야 할 신호:
- 본문에 ~등, ~외 생략, ...(중략)... 표현이 존재하는 경우
- 재무제표나 시계열 표의 중간 행들이 생략된 경우
- 이미지가 본문 위치가 아닌 문서 맨 끝에 몰려 있는 경우
- 차트 이미지는 삽입되었으나 차트 원본 수치 테이블이 누락된 경우
- 상단 메타데이터 블록(발행기관, 일자, 엔티티 태그 등)이 누락된 경우

오직 최종 완성된 마크다운 본문만을 출력하십시오 (별도의 인사말이나 사족 생략).
"""

class KordocWikiAgent:
    """kordoc-wiki-ingest 스킬을 완전 자율 실행하는 전용 에이전트."""

    def __init__(
        self,
        docs_dir: Path,
        assets_dir: Path,
        api_key: Optional[str] = None
    ):
        self.docs_dir = docs_dir
        self.assets_dir = assets_dir
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _split_into_smart_chunks(self, text: str, max_chunk_size: int = 25000) -> list[str]:
        """대형 문서를 챕터 및 섹션 헤딩 경계를 기준으로 자연스럽게 청크 분할한다."""
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []
        # 섹션 헤딩 단위로 분할 시도
        sections = re.split(r'(\n(?=#{1,3}\s|[I|V|X|Ⅰ-Ⅻ]+\.\s|\d+\.\s+[가-힣A-Z]))', text)
        current_chunk = []
        current_len = 0

        for sec in sections:
            if current_len + len(sec) > max_chunk_size and current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = [sec]
                current_len = len(sec)
            else:
                current_chunk.append(sec)
                current_len += len(sec)

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks

    def _call_llm_for_wiki_ingest(
        self,
        raw_md: str,
        doc_id: str,
        original_filename: str,
        file_hash: str,
        images_info: list[dict]
    ) -> Optional[str]:
        """Gemini 멀티모달 API를 호출하여 kordoc-wiki-ingest 스킬 기준의 최고 품질 마크다운을 생성한다.
        
        A안 (완전 멀티모달): 추출된 이미지를 바이트로 직접 Gemini에 전달.
        LLM이 차트/도표 이미지를 직접 보고 수치·범례를 읽어 Dual-Mode 표를 생성한다.
        """
        if not self.api_key:
            return None

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            ext = Path(original_filename).suffix.lstrip('.').upper() or "문서"

            # 로드 가능한 이미지 바이트 목록 준비 (path 키가 있고 실제 파일이 존재하는 것만)
            image_parts = []
            images_index_text = ""
            valid_images = []

            for img in images_info:
                img_path = img.get("path")
                if img_path and Path(img_path).exists():
                    img_file = Path(img_path)
                    mime = MIME_MAP.get(img_file.suffix.lower(), "image/png")
                    try:
                        img_bytes = img_file.read_bytes()
                        image_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                        valid_images.append(img)
                    except Exception as e:
                        logger.warning(f"이미지 로드 실패 ({img_file.name}): {e}")

            # 이미지 목록 인덱스 텍스트 생성 (LLM이 파일명과 웹 경로를 알 수 있도록)
            if valid_images:
                lines = [f"[첨부 이미지 {i+1}] {img['filename']} -> /api/assets/{doc_id}/{img['filename']}"
                         for i, img in enumerate(valid_images)]
                images_index_text = "위에 첨부된 이미지 목록 (순서대로):\n" + "\n".join(lines)
                logger.info(f"멀티모달 인제스트: '{original_filename}' ({len(valid_images)}개 이미지 직접 전달)")
            else:
                images_index_text = "(추출된 이미지 없음 - 텍스트 기반으로만 처리)"
                logger.info(f"텍스트 전용 인제스트: '{original_filename}' (이미지 없음)")

            # 대형 문서 청크 분할 (25,000자 기준)
            chunks = self._split_into_smart_chunks(raw_md, max_chunk_size=25000)
            logger.info(f"총 {len(raw_md)}자, {len(chunks)}개 청크로 분할 처리")

            # 단일 Chat Session을 생성하여 청크 간 문맥 및 연속성 유지
            chat = client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=KORDOC_WIKI_INGEST_SYSTEM_PROMPT,
                    temperature=0.2,
                )
            )

            processed_parts = []
            for idx, chunk in enumerate(chunks):
                is_first = (idx == 0)
                part_label = f"파트 {idx+1}/{len(chunks)}" if len(chunks) > 1 else "전체"

                # 텍스트 프롬프트 구성
                text_prompt = (
                    f"다음은 '{original_filename}' ({part_label}) kordoc 1차 Raw 추출 데이터와 "
                    f"{'위에 첨부된 실제 이미지 파일들' if valid_images and is_first else '이미지 참조 정보'}입니다.\n\n"
                    f"[문서 메타데이터]\n"
                    f"- DOC_ID: {doc_id}\n"
                    f"- ORIGINAL_FILENAME: {original_filename}\n"
                    f"- EXT: {ext}\n"
                    f"- NOW_TIME: {now_str}\n"
                    f"- FILE_HASH: {file_hash}\n"
                    f"- IS_FIRST_CHUNK: {'예 (메타데이터 헤더 및 전체 TOC 작성 필요)' if is_first else '아니오 (본문만 연속 작성, 메타데이터 헤더 불필요)'}\n\n"
                    f"[이미지 에셋 경로 인덱스]\n"
                    f"{images_index_text}\n\n"
                    f"[kordoc Raw 추출 텍스트 ({part_label})]\n"
                    f"```markdown\n"
                    f"{chunk}\n"
                    f"```\n\n"
                    f"위 Raw 텍스트와 첨부 이미지를 모두 활용하여 kordoc-wiki-ingest 5대 원칙에 따라 "
                    f"100% 무삭제 완본 마크다운을 작성하십시오. "
                    f"첨부 이미지의 차트를 직접 보고 내부 수치·범례·단위를 정확히 읽어내어 Dual-Mode 수치 표를 구성하십시오."
                )

                # 멀티모달 콘텐츠 배열 구성:
                # - 첫 청크: 텍스트 + 전체 이미지 (LLM이 이미지-텍스트 위치 맥락 파악)
                # - 후속 청크: 텍스트만 (세션이 이전 대화 컨텍스트 유지)
                if is_first and image_parts:
                    message_content = [types.Part.from_text(text=text_prompt)] + image_parts
                else:
                    message_content = [types.Part.from_text(text=text_prompt)]

                response = chat.send_message(message_content)

                if response and response.text:
                    processed_parts.append(response.text.strip())
                    logger.info(f"청크 {idx+1}/{len(chunks)} 변환 성공 ({len(response.text)}자 생성)")
                else:
                    logger.warning(f"청크 {idx+1} LLM 응답 없음, 룰베이스 폴백 전환")
                    return None

            full_result = "\n\n".join(processed_parts)
            logger.info(f"멀티모달 kordoc-wiki-ingest 완성 ({original_filename}, 총 {len(full_result)}자)")
            return full_result

        except Exception as e:
            logger.warning(f"LLM API 호출 중 오류 발생 (룰베이스 폴백 가동): {e}")

        return None

    def _rule_based_wiki_ingest(
        self,
        raw_md: str,
        doc_id: str,
        original_filename: str,
        file_hash: str
    ) -> str:
        """API 키가 없거나 호출 실패 시 kordoc-wiki-ingest 5대 원칙을 정밀 룰베이스로 수행한다."""
        title = Path(original_filename).stem
        ext = Path(original_filename).suffix.lstrip('.').upper() or "문서"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. 발행기관 및 일자 탐지
        publisher = "미상 (원문 기재)"
        publishers = [
            "LS증권", "미래에셋증권", "삼성증권", "KB증권", "NH투자증권", "신한투자증권",
            "하나증권", "한국투자증권", "메리츠증권", "키움증권", "한국은행", "산업통상자원부",
            "과학기술정보통신부", "금융감독원", "기획재정부", "ETRI", "KDI"
        ]
        for pub in publishers:
            if pub in original_filename or pub in raw_md[:1000]:
                publisher = pub
                break

        date_str = datetime.now(timezone.utc).strftime("%Y년 %m월 %d일")
        date_match = re.search(r'(202[0-9])[.\-_년\s]+(0?[1-9]|1[0-2])[.\-_월\s]+(0?[1-9]|[12][0-9]|3[01])', raw_md[:1500] + " " + original_filename)
        if date_match:
            y, m, d = date_match.groups()
            date_str = f"{y}년 {int(m):02d}월 {int(d):02d}일"

        # 2. 엔티티 태그 추출
        keywords = set()
        clean_name = re.sub(r'[0-9_\-\.]', ' ', title)
        for w in clean_name.split():
            if len(w) >= 2 and not w.isdigit():
                keywords.add(w)

        found_abbrs = re.findall(r'\b[A-Z]{2,10}(?:[0-9]{1,3})?\b', raw_md[:3000])
        common_exclude = {"THE", "AND", "FOR", "WITH", "FROM", "PDF", "DOCX", "HWPX", "PAGE", "TOC", "HTTP", "HTTPS", "COM"}
        for abbr in found_abbrs:
            if abbr not in common_exclude and len(abbr) >= 2:
                keywords.add(abbr)

        industry_words = ["반도체", "인공지능", "생성형AI", "전력망", "이차전지", "소부장", "공급망", "재무제표", "습도센서", "자율주행", "바이오"]
        for ind in industry_words:
            if ind in raw_md[:3000] or ind in original_filename:
                keywords.add(ind)

        entity_tags = " ".join([f"#{e}" for e in sorted(list(keywords))[:8]]) if keywords else "#지식베이스 #전수복원"

        # 3. 헤딩 위계 정돈
        lines = raw_md.split('\n')
        normalized_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                normalized_lines.append("")
                continue

            if re.match(r'^(?:[#\s]*)(?:[I|V|X]+|[Ⅰ-Ⅻ]+)\.\s*(.+)$', stripped):
                match = re.match(r'^(?:[#\s]*)(?:[I|V|X]+|[Ⅰ-Ⅻ]+)\.\s*(.+)$', stripped)
                normalized_lines.append(f"\n## {match.group(0).lstrip('#').strip()}")
            elif re.match(r'^(?:[#\s]*)\d+\.\s+([가-힣A-Za-z0-9].{2,40})$', stripped) and not stripped.endswith(('.', '억원', '%', '달러')):
                normalized_lines.append(f"\n### {stripped.lstrip('#').strip()}")
            elif re.match(r'^(?:[#\s]*)(?:[가-하]\.|\(\d+\)|\d+\))\s+([가-힣A-Za-z0-9].{2,40})$', stripped):
                normalized_lines.append(f"\n#### {stripped.lstrip('#').strip()}")
            else:
                normalized_lines.append(line)

        structured_text = '\n'.join(normalized_lines)

        # 4. 도표 캡션 결합
        def replace_caption(match):
            img_tag = match.group(1)
            caption = match.group(2).strip()
            return f"{img_tag}\n*({caption.strip('()*<>')})*"

        captioned_text = re.sub(
            r'(!\[.*?\]\(.*?\))\n+([<\[\(]?(?:도표|그림|차트|표|Figure|Chart)\s*\d+.*?[\)\]>]?)\b',
            replace_caption,
            structured_text,
            flags=re.IGNORECASE
        )

        # 5. 상단 표준 메타데이터 헤더
        header = (
            f"# {title}\n\n"
            f"> - **원본 파일명**: `{original_filename}`\n"
            f"> - **발행기관**: {publisher}\n"
            f"> - **발행일자**: {date_str}\n"
            f"> - **문서분류**: 기업 및 산업 분석 보고서 / 기술 문서\n"
            f"> - **핵심 엔티티**: {entity_tags}\n"
            f"> - **원본형식**: `{ext}`\n"
            f"> - **인제스트 일시**: `{now_str}`\n"
            f"> - **무결성 해시 (SHA-256)**: `{file_hash}`\n"
            f"> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)\n\n"
            f"---\n\n"
        )

        return header + captioned_text.strip() + "\n"

    def _extract_and_inline_images(
        self,
        raw_md: str,
        doc_id: str,
        doc_asset_dir: Path,
        search_dirs: list[Path]
    ) -> tuple[str, list[dict]]:
        """모든 이미지 에셋을 추출 및 복사하고 /api/assets/ 경로로 100% 인라인 매핑한다."""
        doc_asset_dir.mkdir(parents=True, exist_ok=True)
        images_info: list[dict] = []
        available_images: dict[str, Path] = {}

        for search_dir in search_dirs:
            if search_dir and search_dir.exists():
                for img_path in search_dir.rglob("*"):
                    if img_path.is_file() and img_path.suffix.lower() in IMAGE_EXTENSIONS:
                        available_images[img_path.name.lower()] = img_path

        def resolve_img(src_ref: str) -> str:
            clean = src_ref.strip().strip("'\"").replace("\\", "/")
            if clean.startswith(("http://", "https://", "data:", "/api/assets/")):
                return clean

            filename = Path(clean).name
            matched = None
            for s_dir in search_dirs:
                direct = (s_dir / clean).resolve()
                if direct.exists() and direct.is_file():
                    matched = direct
                    break

            if not matched:
                matched = available_images.get(clean.lower()) or available_images.get(filename.lower())

            if matched and matched.exists():
                target = doc_asset_dir / matched.name
                shutil.copy2(matched, target)
                images_info.append({"filename": matched.name, "path": target})
                return f"/api/assets/{doc_id}/{matched.name}"

            return f"/api/assets/{doc_id}/{filename}"

        # 마크다운 및 HTML 치환
        adjusted = re.sub(
            r'!\[(.*?)\]\((.*?)\)',
            lambda m: f'![{m.group(1)}]({resolve_img(m.group(2))})',
            raw_md
        )
        adjusted = re.sub(
            r'<img\s+([^>]*?)src=["\'](.*?)["\']([^>]*?)>',
            lambda m: f'<img {m.group(1)}src="{resolve_img(m.group(2))}"{m.group(3)}>',
            adjusted,
            flags=re.IGNORECASE
        )

        return adjusted, images_info

    def _run_kordoc_lint(self, md_path: Path) -> None:
        """kordoc-wiki-ingest Phase 6: 생성된 마크다운에 대해 kordoc lint 자가 검증을 수행한다."""
        try:
            cmd = f'cmd /c npx -y kordoc@^4 lint "{md_path.resolve()}"'
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
            if res.returncode == 0:
                logger.info(f"kordoc lint 자가 검증 통과: {md_path.name}")
            else:
                logger.warning(f"kordoc lint 검증 경고 ({md_path.name}): {res.stdout or res.stderr}")
        except Exception as e:
            logger.warning(f"kordoc lint 실행 오류 (무시됨): {e}")

    def _process_pdf_via_file_api(
        self,
        source_path: Path,
        doc_id: str,
        file_hash: str
    ) -> Optional[str]:
        """Gemini Files API를 통해 PDF를 업로드하고 Chat 세션에서 무삭제 마크다운으로 변환한다."""
        if not self.api_key:
            return None

        # 50MB 초과 파일은 kordoc CLI 폴백 유도
        if source_path.stat().st_size > 50 * 1024 * 1024:
            logger.info(f"PDF 파일이 50MB를 초과하여 kordoc CLI 경로로 폴백: {source_path.name}")
            return None

        uploaded_file = None
        client = None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            logger.info(f"PDF Files API 업로드 시작: {source_path.name}")
            # 한글 파일명으로 인한 HTTP 헤더 ascii 인코딩 오류 방지용 안전한 display_name 생성
            safe_display_name = re.sub(r"[^\w\.\-]", "_", source_path.name.encode("ascii", "ignore").decode("ascii")) or f"doc_{doc_id}.pdf"
            uploaded_file = client.files.upload(
                file=source_path,
                config={"mime_type": "application/pdf", "display_name": safe_display_name}
            )

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            prompt = (
                f"다음 첨부된 PDF 문서('{source_path.name}')를 kordoc-wiki-ingest 5대 원칙에 따라 100% 무삭제 완본 마크다운으로 변환하십시오.\n\n"
                f"[문서 메타데이터]\n"
                f"- DOC_ID: {doc_id}\n"
                f"- ORIGINAL_FILENAME: {source_path.name}\n"
                f"- EXT: PDF\n"
                f"- NOW_TIME: {now_str}\n"
                f"- FILE_HASH: {file_hash}\n"
                f"- IS_FIRST_CHUNK: 예 (메타데이터 헤더 및 전체 TOC 작성 필요)\n\n"
                f"문서 내 모든 텍스트, 각주, 도표, 차트(Dual-Mode 수치 표 포함), 종합 재무제표를 단 하나의 생략 없이 완전하게 복원하십시오."
            )

            chat = client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=KORDOC_WIKI_INGEST_SYSTEM_PROMPT,
                    temperature=0.2,
                )
            )

            response = chat.send_message([
                types.Part.from_uri(file_uri=uploaded_file.uri, mime_type="application/pdf"),
                types.Part.from_text(text=prompt)
            ])

            if response and response.text:
                logger.info(f"PDF Files API 변환 성공: {source_path.name} ({len(response.text)}자)")
                return response.text.strip()

            logger.warning(f"PDF Files API 응답 비어있음: {source_path.name}")
            return None

        except Exception as e:
            logger.warning(f"PDF Files API 처리 중 오류 발생 (폴백 진행): {e}")
            return None
        finally:
            if client and uploaded_file and hasattr(uploaded_file, "name"):
                try:
                    client.files.delete(name=uploaded_file.name)
                    logger.info(f"Files API 임시 파일 삭제 완료: {uploaded_file.name}")
                except Exception as del_e:
                    logger.warning(f"Files API 임시 파일 삭제 실패: {del_e}")

    def execute_ingest(
        self,
        source_path: Path,
        doc_id: str,
        file_hash: str,
        enable_ocr: bool = False,
        page_range: Optional[str] = None
    ) -> tuple[Path, list[Path], str]:
        """kordoc-wiki-ingest 전체 파이프라인(1차 CLI 추출 -> 2차 LLM 에이전트 정돈 -> Lint)을 실행한다."""
        title = source_path.stem
        target_md_path = self.docs_dir / f"{doc_id}.md"
        doc_asset_dir = self.assets_dir / doc_id
        ext = source_path.suffix.lower()
        source_parent = source_path.parent

        # 0. PDF 파일이고 API 키가 있는 경우 Gemini Files API 기반 직접 변환 우선 시도
        if ext == ".pdf" and self.api_key:
            pdf_result_md = self._process_pdf_via_file_api(
                source_path=source_path,
                doc_id=doc_id,
                file_hash=file_hash
            )
            if pdf_result_md:
                target_md_path.write_text(pdf_result_md, encoding="utf-8")
                self._run_kordoc_lint(target_md_path)
                return target_md_path, [], title

        raw_md = ""
        extracted_images_info = []

        # 1. 원본 형식별 1차 추출
        if ext in {".txt", ".md"}:
            raw_content = source_path.read_text(encoding="utf-8", errors="replace")
            search_dirs = [source_parent, source_parent / "images", self.assets_dir / doc_id]
            raw_md, extracted_images_info = self._extract_and_inline_images(
                raw_content, doc_id, doc_asset_dir, search_dirs
            )
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_out_md = Path(temp_dir) / "output_raw.md"
                flags = []
                if enable_ocr:
                    flags.append("--ocr --formula-ocr")
                if page_range:
                    flags.append(f"-p {page_range}")

                flag_str = " " + " ".join(flags) if flags else ""
                cmd = f'cmd /c npx -y kordoc@^4 "{source_path.resolve()}" -o "{temp_out_md.resolve()}"{flag_str}'
                
                logger.info(f"[kordoc-wiki-ingest 1단계] kordoc CLI 고속 파싱: {cmd}")
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )

                if not temp_out_md.exists():
                    error_detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(f"kordoc 1차 변환 실패 (코드: {result.returncode}): {error_detail}")

                temp_raw = temp_out_md.read_text(encoding="utf-8", errors="replace")
                search_dirs = [Path(temp_dir), Path(temp_dir) / "images", source_parent, source_parent / "images"]
                raw_md, extracted_images_info = self._extract_and_inline_images(
                    temp_raw, doc_id, doc_asset_dir, search_dirs
                )

        # 2. kordoc-wiki-ingest 2단계: LLM 에이전트 기반 지능형 정돈 (Dual-Mode, 엔티티, 헤딩 위계)
        logger.info(f"[kordoc-wiki-ingest 2단계] 지능형 위키 인제스트 정돈 시작 ({source_path.name})")
        final_md = self._call_llm_for_wiki_ingest(
            raw_md=raw_md,
            doc_id=doc_id,
            original_filename=source_path.name,
            file_hash=file_hash,
            images_info=extracted_images_info
        )

        if not final_md:
            final_md = self._rule_based_wiki_ingest(
                raw_md=raw_md,
                doc_id=doc_id,
                original_filename=source_path.name,
                file_hash=file_hash
            )

        # 3. 마크다운 파일 디스크 저장
        target_md_path.write_text(final_md, encoding="utf-8")

        # 4. kordoc-wiki-ingest 3단계: kordoc lint 자가 검증
        self._run_kordoc_lint(target_md_path)

        extracted_img_paths = [img["path"] for img in extracted_images_info if "path" in img]
        return target_md_path, extracted_img_paths, title
