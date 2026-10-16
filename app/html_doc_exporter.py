"""/html-doc 스킬 규격 기반 독립 실행형 편집 가능 HTML 보고서 생성 및 pymupdf A4 PDF 내보내기 모듈."""

import base64
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Optional
import urllib.parse
import io

import markdown
import pymupdf

logger = logging.getLogger("HtmlDocExporter")

# 기술 보고서 전용 고품질 문서 타이포그래피 및 스타일 시트
REPORT_DOCUMENT_STYLE = """
/* ===== 보고서 맞춤형 문서 디자인 (html-doc 규격 호환) ===== */
:root {
  color-scheme: light;
  --report-font-family: -apple-system, 'Pretendard', 'Segoe UI', system-ui, sans-serif;
  --report-primary: #1e3a8a;
  --report-accent: #2563eb;
  --report-text: #1f2937;
  --report-subtext: #4b5563;
  --report-bg: #ffffff;
  --report-border: #e5e7eb;
}

body {
  margin: 0;
  font-family: var(--report-font-family);
  color: var(--report-text);
  background: var(--report-bg);
  line-height: 1.75;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}

#doc-content {
  max-width: 880px;
  margin: 0 auto;
  padding: 48px 24px 120px;
}

#doc-content h1 {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.4px;
  color: var(--report-primary);
  margin: 0 0 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #e2e8f0;
}

#doc-content h2 {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.2px;
  color: #1e293b;
  margin: 36px 0 14px;
  padding-left: 10px;
  border-left: 4px solid var(--report-accent);
}

#doc-content h3 {
  font-size: 16.5px;
  font-weight: 700;
  color: #334155;
  margin: 26px 0 10px;
}

#doc-content h4 {
  font-size: 15px;
  font-weight: 600;
  color: #475569;
  margin: 18px 0 8px;
}

#doc-content p {
  margin: 12px 0;
  text-align: justify;
  word-break: keep-all;
}

#doc-content hr {
  border: none;
  border-top: 1px solid var(--report-border);
  margin: 28px 0;
}

#doc-content blockquote {
  margin: 16px 0;
  padding: 12px 18px;
  border-left: 4px solid var(--report-accent);
  background: #f8fafc;
  border-radius: 4px;
  color: #334155;
  font-size: 14px;
}

#doc-content blockquote p {
  margin: 4px 0;
}

#doc-content ul, #doc-content ol {
  margin: 12px 0;
  padding-left: 24px;
}

#doc-content li {
  margin: 6px 0;
}

#doc-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 20px 0;
  font-size: 14px;
  line-height: 1.5;
  border: 1px solid var(--report-border);
  border-radius: 6px;
  overflow: hidden;
}

#doc-content th, #doc-content td {
  padding: 6px 10px;
  border: 1px solid #e5e7eb;
  text-align: left;
  vertical-align: top;
}

#doc-content th {
  background-color: #f1f5f9;
  font-weight: 700;
  color: #1e293b;
}

#doc-content tr:nth-child(even) {
  background-color: #f8fafc;
}

#doc-content code {
  font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
  font-size: 13.5px;
  background-color: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  color: #0f172a;
}

#doc-content pre {
  background-color: #1e293b;
  color: #f8fafc;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
}

#doc-content pre code {
  background-color: transparent;
  color: inherit;
  padding: 0;
}

#doc-content img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 18px auto 8px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

#doc-content em {
  color: var(--report-subtext);
}

/* 도표 캡션 단락 스타일 */
#doc-content p > em:only-child {
  display: block;
  text-align: center;
  font-size: 13px;
  margin-top: 4px;
  margin-bottom: 20px;
}

/* 출처 인용 태그 스타일 */
#doc-content a {
  color: var(--report-accent);
  text-decoration: none;
}
#doc-content a:hover {
  text-decoration: underline;
}

/* 인쇄 및 PDF 페이지 설정 */
@media print {
  @page {
    margin: 15mm;
    size: A4 portrait;
  }
  body {
    background: #fff;
    font-size: 13px;
    line-height: 1.6;
  }
  #doc-content {
    max-width: 100%;
    padding: 0;
  }
  #doc-content h1, #doc-content h2, #doc-content h3 {
    page-break-after: avoid;
  }
  #doc-content table {
    page-break-inside: auto;
  }
  #doc-content tr, #doc-content pre, #doc-content blockquote, #doc-content img {
    page-break-inside: avoid;
  }
  #doc-controls, #doc-editbar, #doc-inspector, #doc-editflag,
  #doc-restore-banner, #doc-toast, .doc-ed-modal {
    display: none !important;
  }
}
"""


class HtmlDocExporter:
    """마크다운 보고서를 /html-doc 스킬 규격의 편집 가능 HTML 및 A4 PDF로 변환하는 클래스."""

    def __init__(self, skeleton_path: Optional[Path] = None, assets_dir: Optional[Path] = None):
        """
        초기화 메서드.

        Args:
            skeleton_path: html-doc 스킬의 skeleton.html 절대 경로 (없을 경우 자동 탐색).
            assets_dir: 도표 및 이미지 원본이 저장된 WikiDB/assets 디렉토리 경로.
        """
        self.skeleton_path = self._resolve_skeleton_path(skeleton_path)
        self.assets_dir = assets_dir or (Path(__file__).resolve().parent.parent / "WikiDB" / "assets")
        self._skeleton_template: Optional[str] = None

    def _resolve_skeleton_path(self, explicit_path: Optional[Path]) -> Path:
        """skeleton.html 템플릿 파일의 위치를 순차적으로 탐색하여 확정한다."""
        if explicit_path and explicit_path.exists():
            return explicit_path

        # 1. 표준 사용자 홈 gemini config skills 경로 탐색
        home_skill_path = Path.home() / ".gemini" / "config" / "skills" / "html-doc" / "assets" / "skeleton.html"
        if home_skill_path.exists():
            return home_skill_path

        # 2. 프로젝트 내부 assets 경로 탐색
        local_assets_path = Path(__file__).resolve().parent.parent / "assets" / "skeleton.html"
        if local_assets_path.exists():
            return local_assets_path

        # 3. 환경 변수 또는 폴백 기본 경로 반환
        return home_skill_path

    def _load_skeleton_template(self) -> str:
        """skeleton.html 원본 내용을 로드하여 캐시한다."""
        if self._skeleton_template is not None:
            return self._skeleton_template

        if self.skeleton_path.exists():
            try:
                self._skeleton_template = self.skeleton_path.read_text(encoding="utf-8")
                return self._skeleton_template
            except Exception as e:
                logger.warning(f"skeleton.html 파일 읽기 실패 ({self.skeleton_path}): {e}")

        # 파일이 없을 경우 html-doc 계약을 충족하는 미니멀 스켈레톤 폴백 제공
        logger.warning("skeleton.html을 찾을 수 없어 인라인 미니멀 템플릿을 폴백으로 사용합니다.")
        self._skeleton_template = self._create_fallback_skeleton()
        return self._skeleton_template

    def _create_fallback_skeleton(self) -> str:
        """skeleton.html 원본이 없는 비상 상황용 최소 규격 스켈레톤 생성."""
        return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>보고서</title>
<style>
/* 기본 문서 디자인 */
:root{ color-scheme:light; }
body{ margin:0; font-family:-apple-system,'Pretendard','Segoe UI',system-ui,sans-serif; color:#1f2937; background:#fff; line-height:1.7; font-size:15px; }
#doc-content{ max-width:880px; margin:0 auto; padding:48px 24px 120px; }
</style>
<style id="doc-editor-style">
@media print{ #doc-controls, #doc-editbar, #doc-inspector, #doc-editflag, #doc-restore-banner, #doc-toast, .doc-ed-modal{ display:none !important; } }
</style>
</head>
<body>
<div id="doc-controls" style="display:none;"></div>
<div id="doc-editbar" style="display:none;"></div>
<div id="doc-inspector" style="display:none;"></div>
<div id="doc-editflag" style="display:none;"></div>
<div id="doc-restore-banner" style="display:none;"></div>
<div id="doc-history-modal" style="display:none;"></div>
<div id="doc-toast" style="display:none;"></div>
<main id="doc-content" contenteditable="false">
</main>
<script type="application/json" id="doc-history">[]</script>
<script id="doc-editor-script">
/* Fallback Minimal Engine */
</script>
</body>
</html>"""

    def find_local_image_file(self, doc_id: str, filename: str) -> Optional[Path]:
        """WikiDB/assets 내에서 doc_id와 파일명을 기준으로 실제 이미지 파일 경로를 조회한다."""
        clean_doc_id = urllib.parse.unquote(doc_id)
        clean_filename = urllib.parse.unquote(filename)
        safe_filename = Path(clean_filename).name

        target_dir = self.assets_dir / clean_doc_id
        if not target_dir.exists():
            target_dir = self.assets_dir / doc_id

        # 디렉토리 부분 매칭 탐색
        if not target_dir.exists() and self.assets_dir.exists():
            for d in self.assets_dir.iterdir():
                if d.is_dir() and (d.name == clean_doc_id or d.name == doc_id or clean_doc_id in d.name):
                    target_dir = d
                    break

        file_path = target_dir / safe_filename
        if file_path.exists() and file_path.is_file():
            return file_path

        # 파일명 대소문자 무시 탐색
        if target_dir.exists() and target_dir.is_dir():
            for f in target_dir.iterdir():
                if f.is_file() and (f.name.lower() == safe_filename.lower() or f.name.lower() == clean_filename.lower()):
                    return f

        # 전체 assets 폴더 내에서 파일명으로 역탐색
        if self.assets_dir.exists():
            for f in self.assets_dir.glob(f"*/{safe_filename}"):
                if f.is_file():
                    return f

        # 로컬에 없을 경우 Google Drive / 미러 스토리지에서 온디맨드 페치 폴백
        try:
            from app.gdrive_storage import get_gdrive_storage

            storage = getattr(self, "gdrive_storage", None) or get_gdrive_storage()
            if storage is not None:
                fetched = storage.ensure_asset_file(
                    doc_id=clean_doc_id,
                    filename=safe_filename,
                    assets_dir=self.assets_dir,
                )
                if fetched and fetched.exists() and fetched.is_file():
                    return fetched
        except Exception as e:
            logger.debug(f"원격 스토리지 이미지 조회 폴백 스킵 ({clean_doc_id}/{safe_filename}): {e}")

        return None

    def embed_images_as_base64(self, html_content: str) -> str:
        """HTML 내의 /api/assets/ 이미지 링크를 Base64 Data URI로 치환하여 자립형으로 만든다."""
        def replace_img_src(match: re.Match) -> str:
            full_tag = match.group(0)
            prefix = match.group(1)
            doc_id = match.group(2)
            filename = match.group(3)
            suffix = match.group(4)

            img_file = self.find_local_image_file(doc_id, filename)
            if img_file and img_file.exists():
                try:
                    mime_type, _ = mimetypes.guess_type(str(img_file))
                    if not mime_type:
                        ext = img_file.suffix.lower()
                        mime_type = "image/png" if ext == ".png" else ("image/jpeg" if ext in (".jpg", ".jpeg") else "image/svg+xml")

                    b64_data = base64.b64encode(img_file.read_bytes()).decode("utf-8")
                    data_uri = f"data:{mime_type};base64,{b64_data}"
                    return f"{prefix}{data_uri}{suffix}"
                except Exception as e:
                    logger.warning(f"이미지 base64 변환 실패 ({img_file}): {e}")

            return full_tag

        pattern = r'(<img\s+[^>]*?src=[\"\'])/api/assets/([^/\"\']+)/([^\"\']+)([\"\'][^>]*>)'
        return re.sub(pattern, replace_img_src, html_content)

    def markdown_to_html_body(self, report_markdown: str, embed_images: bool = True) -> str:
        """마크다운 본문을 HTML 조각으로 변환하고 필요시 이미지를 임베딩한다."""
        # 들여쓰기 왜곡 및 누락된 출처 링크 사전 보정
        from app.utils import clean_markdown_typography, resolve_citation_links
        target_docs_dir = self.assets_dir.parent / "docs" if self.assets_dir else None
        preprocessed_md = resolve_citation_links(report_markdown, docs_dir=target_docs_dir)
        preprocessed_md = clean_markdown_typography(preprocessed_md)

        html_body = markdown.markdown(
            preprocessed_md,
            extensions=[
                "markdown.extensions.tables",
                "markdown.extensions.fenced_code",
                "markdown.extensions.toc",
                "markdown.extensions.nl2br",
                "markdown.extensions.sane_lists",
            ],
            output_format="html5",
        )

        if embed_images:
            html_body = self.embed_images_as_base64(html_body)

        return html_body

    def export_html(
        self,
        report_markdown: str,
        title: str = "AI 기술 보고서",
        embed_images: bool = True
    ) -> str:
        """
        /html-doc 스킬 규격을 완벽히 충족하는 독립 실행형 편집 가능 HTML 문서를 생성한다.

        Args:
            report_markdown: 원본 보고서 마크다운 문자열.
            title: 문서 제목.
            embed_images: 이미지를 Base64 Data URI로 임베딩할지 여부.

        Returns:
            완전한 독립 실행형 HTML 문서 문자열.
        """
        template = self._load_skeleton_template()

        # 1. 문서 제목 교체
        template = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", template, count=1)

        # 2. 첫 번째 <style>...</style> 태그를 전문 보고서 스타일로 교체
        style_match = re.search(r"<style\b[^>]*>(.*?)</style>", template, flags=re.DOTALL)
        if style_match:
            start, end = style_match.span()
            new_style = f"<style>\n{REPORT_DOCUMENT_STYLE}\n</style>"
            template = template[:start] + new_style + template[end:]

        # 3. 마크다운 본문을 HTML로 변환
        html_body = self.markdown_to_html_body(report_markdown, embed_images=embed_images)

        # 4. <main id="doc-content" contenteditable="false"> 태그 안의 본문 치환
        doc_content_pattern = r'(<main\s+id=[\"\']doc-content[\"\'][^>]*>)(.*?)(</main>)'
        doc_content_match = re.search(doc_content_pattern, template, flags=re.DOTALL)

        if doc_content_match:
            open_tag = doc_content_match.group(1)
            close_tag = doc_content_match.group(3)
            new_content = f"{open_tag}\n\n{html_body}\n\n{close_tag}"
            start, end = doc_content_match.span()
            template = template[:start] + new_content + template[end:]
        else:
            logger.error("스켈레톤 템플릿에서 <main id=\"doc-content\"> 컨테이너를 찾지 못했습니다.")
            raise ValueError("html-doc 규격에 맞는 #doc-content 컨테이너가 스켈레톤에 존재하지 않습니다.")

        return template

    def export_pdf(self, report_markdown: str, title: str = "AI 기술 보고서") -> bytes:
        """
        마크다운 보고서를 pymupdf.Story 엔진을 통해 A4 규격 PDF 바이너리로 변환한다.
        (PDF 렌더링 시에는 에디터 크롬 UI를 배제하고 고품질 본문 스타일만 적용하여 가볍고 빠르게 생성)

        Args:
            report_markdown: 원본 보고서 마크다운 문자열.
            title: 문서 제목.

        Returns:
            생성된 PDF 바이너리 bytes.
        """
        # 1. 도표 이미지가 Base64로 인라인화된 순수 본문 HTML 생성
        html_body = self.markdown_to_html_body(report_markdown, embed_images=True)

        # 2. PDF 인쇄 전용 클린 HTML 구조 조립 (에디터 크롬 및 비호환 CSS 구문 배제)
        clean_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{REPORT_DOCUMENT_STYLE}
</style>
</head>
<body>
<main id="doc-content">
{html_body}
</main>
</body>
</html>"""

        # 3. pymupdf.Story 및 DocumentWriter로 A4 페이지 조판
        story = pymupdf.Story(html=clean_html)
        out_buffer = io.BytesIO()
        writer = pymupdf.DocumentWriter(out_buffer)
        a4_rect = pymupdf.paper_rect("A4")
        content_rect = a4_rect + (36, 36, -36, -36)

        page_no = 0
        more = 1
        max_pages = 80  # 비정상적 조판 지연 및 무한 루프 방지를 위한 최대 페이지 안전 가드
        while more and page_no < max_pages:
            page_no += 1
            device = writer.begin_page(a4_rect)
            more, filled_rect = story.place(content_rect)
            story.draw(device, content_rect)
            writer.end_page()

        writer.close()

        pdf_bytes = out_buffer.getvalue()
        logger.info(f"PDF 생성 완료: {title} (크기: {len(pdf_bytes)} bytes)")
        return pdf_bytes
