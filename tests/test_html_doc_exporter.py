"""/html-doc 규격 기반 HTML 및 PDF 내보내기 모듈 및 라우터 엔드포인트 테스트."""

import io
import urllib.parse
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import pymupdf

from app.config import Settings
from app.manifest import ManifestManager
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent
from app.server import create_app
from app.html_doc_exporter import HtmlDocExporter
from app.topic_generator import TopicReportGenerator

SAMPLE_REPORT_MD = """# AI 기술 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 차세대 반도체

## 1. 기술 개요
차세대 반도체 기술은 미세 공정의 물리적 한계를 극복하기 위해 다각도로 발전하고 있습니다.

| 항목 | 기존 공정 | 차세대 공정 |
|---|---|---|
| 미세화 | 3nm FinFET | 2nm GAA / MBCFET |
| 인터커넥트 | 금속 배선 | 광 인터커넥트 / CPO |

> 핵심 요약: 성능 및 전력 효율 향상이 핵심 과제입니다.

![샘플 다이어그램](/api/assets/sample_doc/sample_diagram.png)
*(도표 1: 차세대 아키텍처 다이어그램)*
"""

def test_html_doc_exporter_contract(tmp_path: Path):
    """html-doc 스킬의 핵심 통합 계약(7대 크롬, #doc-content 단일 루트, 히스토리, 스크립트) 충족 검증."""
    exporter = HtmlDocExporter(assets_dir=tmp_path / "assets")
    html_output = exporter.export_html(
        report_markdown=SAMPLE_REPORT_MD,
        title="테스트 기술 보고서",
        embed_images=False
    )

    # 1. 단일 본문 컨테이너 및 속성 검증
    assert '<main id="doc-content"' in html_output
    assert 'contenteditable="false"' in html_output

    # 2. 7대 에디터 크롬 UI 블록 검증
    chrome_ids = [
        'id="doc-controls"',
        'id="doc-editbar"',
        'id="doc-inspector"',
        'id="doc-editflag"',
        'id="doc-restore-banner"',
        'id="doc-history-modal"',
        'id="doc-toast"',
    ]
    for cid in chrome_ids:
        assert cid in html_output, f"누락된 크롬 UI 요소: {cid}"

    # 3. 히스토리 스토어 및 엔진 스크립트 검증
    assert 'id="doc-history"' in html_output
    assert 'id="doc-editor-script"' in html_output

    # 4. 마크다운 요소(표, 제목, 인용구)의 정상 변환 검증
    assert "<table" in html_output
    assert "<th>기존 공정</th>" in html_output
    assert "<blockquote" in html_output
    assert "차세대 반도체 기술" in html_output
    assert "<title>테스트 기술 보고서</title>" in html_output

def test_html_doc_exporter_image_embedding(tmp_path: Path):
    """로컬 이미지 파일이 존재할 때 Base64 Data URI로 정상 치환되는지 검증."""
    assets_dir = tmp_path / "assets"
    doc_asset_dir = assets_dir / "sample_doc"
    doc_asset_dir.mkdir(parents=True, exist_ok=True)
    
    # 1x1 투명 PNG 더미 생성
    sample_img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    (doc_asset_dir / "sample_diagram.png").write_bytes(sample_img_bytes)

    exporter = HtmlDocExporter(assets_dir=assets_dir)
    html_output = exporter.export_html(
        report_markdown=SAMPLE_REPORT_MD,
        title="이미지 임베딩 테스트",
        embed_images=True
    )

    # Base64 Data URI 포함 여부 확인
    assert "data:image/png;base64," in html_output
    assert "/api/assets/sample_doc/sample_diagram.png" not in html_output

def test_html_doc_exporter_pdf_generation(tmp_path: Path):
    """pymupdf.Story 엔진을 통한 A4 PDF 바이너리 생성 및 무결성 검증."""
    exporter = HtmlDocExporter(assets_dir=tmp_path / "assets")
    pdf_bytes = exporter.export_pdf(
        report_markdown=SAMPLE_REPORT_MD,
        title="PDF 생성 테스트"
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")

    # PyMuPDF로 PDF 바이너리 파싱 가능 여부 및 내용 확인
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) >= 1
    page_text = doc[0].get_text()
    assert "AI 기술 분석 보고서" in page_text or "차세대 반도체" in page_text

def test_router_export_endpoints(tmp_path: Path):
    """FastAPI 라우터를 통한 HTML 및 PDF 보고서 내보내기 엔드포인트 종합 검증."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        reports_dir=tmp_path / "WikiDB" / "reports",
        manifest_path=tmp_path / "WikiDB" / "manifest.json"
    )
    settings.ensure_directories()

    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocEngine(settings.docs_dir, settings.assets_dir)
    agent = IngestAgent(settings.source_dir, manifest_mgr, engine, settings.supported_extensions)

    # 더미 생성 보고서 파일 저장
    report_id = "REPORT_차세대_반도체_1234567890"
    report_file = settings.reports_dir / f"{report_id}.md"
    report_file.write_text(SAMPLE_REPORT_MD, encoding="utf-8")

    app = create_app(settings, manifest_mgr, agent)
    client = TestClient(app)

    # 1. HTML 내보내기 (브라우저 직접 보기 모드)
    res_html = client.get(f"/api/topic/reports/{report_id}/export/html")
    assert res_html.status_code == 200
    assert "text/html" in res_html.headers.get("content-type", "")
    assert '<main id="doc-content"' in res_html.text
    assert 'id="doc-controls"' in res_html.text

    # 2. HTML 내보내기 (다운로드 모드)
    res_html_dl = client.get(f"/api/topic/reports/{report_id}/export/html?download=true")
    assert res_html_dl.status_code == 200
    assert "attachment" in res_html_dl.headers.get("content-disposition", "")
    quoted_id = urllib.parse.quote(report_id)
    assert f"{quoted_id}.html" in res_html_dl.headers.get("content-disposition", "")

    # 3. PDF 내보내기 (다운로드 모드)
    res_pdf = client.get(f"/api/topic/reports/{report_id}/export/pdf")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers.get("content-type", "")
    assert "attachment" in res_pdf.headers.get("content-disposition", "")
    assert f"{quoted_id}.pdf" in res_pdf.headers.get("content-disposition", "")
    assert res_pdf.content.startswith(b"%PDF-")

    # 4. 존재하지 않는 보고서 조회 시 404 확인
    res_404 = client.get("/api/topic/reports/NON_EXISTING_REPORT/export/html")
    assert res_404.status_code == 404
