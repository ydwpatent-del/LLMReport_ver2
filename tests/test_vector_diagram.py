"""PDF 본문 텍스트 추출 페이지의 전면 이미지 중복 삽입 방지 단위 테스트 모듈."""

import tempfile
from pathlib import Path
import pymupdf
import pytest

from app.utils import render_vector_diagram_pages


def create_dummy_pdf_with_dense_diagram(pdf_path: Path) -> None:
    """테스트용 PDF 생성."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    text = (
        "Next Generation Packaging Technology\n"
        "Step 1: Solder bump formation\n"
        "Step 2: Fluxless bonding process\n"
        "Step 3: Die attach mechanism\n"
        "Source: LS Securities Research, Research 35"
    )
    page.insert_text((50, 100), text, fontsize=12)
    doc.save(pdf_path)
    doc.close()


def test_text_extracted_pages_skip_full_image_injection():
    """본문에 텍스트로 이미 추출된 페이지는 전면 통 이미지 스냅샷 중복 삽입이 배제되는지 검증."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        pdf_path = temp_path / "test_diag.pdf"
        asset_dir = temp_path / "assets" / "test_doc"
        create_dummy_pdf_with_dense_diagram(pdf_path)

        initial_md = "# Semiconductor Analysis\n\nSource: LS Securities Research\n\nDetailed contents."
        doc_id = "test_doc"

        updated_md, diagrams = render_vector_diagram_pages(
            pdf_path=pdf_path,
            markdown_text=initial_md,
            doc_id=doc_id,
            doc_asset_dir=asset_dir
        )

        # 본문 텍스트가 이미 있으므로 전면 페이지 스냅샷은 0개이고 본문이 원형 유지되어야 함
        assert len(diagrams) == 0
        assert "diagram.png" not in updated_md
        assert updated_md == initial_md
