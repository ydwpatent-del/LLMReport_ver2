"""kordoc 지식 변환 엔진 단위 테스트."""

import pytest
from pathlib import Path
from app.kordoc_engine import KordocEngine

def test_convert_markdown_and_text_direct(tmp_path: Path):
    """일반 텍스트 및 마크다운 파일 변환 시 메타데이터 헤더와 본문이 정확히 보존되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    engine = KordocEngine(docs_dir=docs_dir, assets_dir=assets_dir)
    
    source_file = tmp_path / "sample.txt"
    source_file.write_text("이것은 원본 문서 내용입니다.\n\n| 항목 | 수치 |\n|---|---|\n| 매출 | 500억 |", encoding="utf-8")
    
    md_path, images, title = engine.convert(source_file, doc_id="test_doc_1", file_hash="hash123456")
    
    assert md_path.exists()
    assert md_path.parent == docs_dir
    content = md_path.read_text(encoding="utf-8")
    
    # 1. 메타데이터 헤더 검증
    assert "# sample" in content
    assert "sample.txt" in content
    assert "hash123456" in content
    assert "100% 무삭제 완본" in content
    
    # 2. 본문 내용 무삭제 보존 검증
    assert "이것은 원본 문서 내용입니다." in content
    assert "| 매출 | 500억 |" in content
    assert title == "sample"

def test_metadata_header_generation(tmp_path: Path):
    """표준 메타데이터 헤더 포맷이 올바른지 검증한다."""
    engine = KordocEngine(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")
    header = engine._generate_metadata_header("신규 사업 계획서", "business_plan.hwpx", "hash_abc")
    
    assert "# 신규 사업 계획서" in header
    assert "business_plan.hwpx" in header
    assert "hash_abc" in header
    assert "---" in header
