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

def test_convert_markdown_with_images(tmp_path: Path):
    """마크다운 본문에 포함된 다양한 이미지 경로가 /api/assets/<doc_id>/로 올바르게 치환되고 에셋이 복사되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    source_dir = tmp_path / "Source"
    source_dir.mkdir(parents=True, exist_ok=True)

    # Source에 테스트 이미지 생성
    img_dir = source_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "chart_01.png").write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
    (source_dir / "diagram.jpg").write_bytes(b"\xff\xd8\xfffakejpg")

    engine = KordocEngine(docs_dir=docs_dir, assets_dir=assets_dir)

    md_file = source_dir / "report_with_images.md"
    md_file.write_text(
        "## 실적 분석 보고서\n\n"
        "다음은 분기별 실적 차트입니다.\n\n"
        "![분기별 매출 차트](images/chart_01.png)\n"
        "*(자료: 재무기획팀)*\n\n"
        "시스템 아키텍처 다이어그램:\n"
        '<img src="./diagram.jpg" alt="아키텍처 다이어그램">\n',
        encoding="utf-8"
    )

    md_path, images, title = engine.convert(md_file, doc_id="doc_img_test", file_hash="hash_img_123")

    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")

    # 인라인 웹 경로 치환 검증
    assert "![\ubd84\uae30\ubcc4 \ub9e4\ucd9c \ucc28\ud2b8](/api/assets/doc_img_test/chart_01.png)" in content or "/api/assets/doc_img_test/chart_01.png" in content
    assert "/api/assets/doc_img_test/diagram.jpg" in content

    # WikiDB/assets/doc_img_test/ 폴더에 실제 이미지 복사 여부 검증
    doc_asset_folder = assets_dir / "doc_img_test"
    assert (doc_asset_folder / "chart_01.png").exists()
    assert (doc_asset_folder / "diagram.jpg").exists()


def test_convert_uses_list_args_not_shell_string(tmp_path):
    """convert()는 shell=False + 리스트 인자 방식으로 subprocess를 호출해야 한다."""
    from app.kordoc_engine import KordocEngine
    from unittest.mock import patch, MagicMock

    engine = KordocEngine(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-1.4 dummy")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        r = MagicMock()
        r.returncode = 1
        r.stderr = "mock"
        r.stdout = ""
        return r

    with patch("subprocess.run", side_effect=fake_run):
        try:
            engine.convert(src, "doc_id", "hash123")
        except RuntimeError:
            pass

    assert isinstance(captured.get("args"), list), "리스트 인자 방식을 사용해야 합니다"
    assert captured.get("kwargs", {}).get("shell") is not True, "shell=True를 사용하면 안 됩니다"

