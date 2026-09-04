"""app.utils 모듈에 대한 단위 테스트."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.utils import (
    get_pdf_page_count,
    generate_standard_metadata_header,
    generate_toc_and_anchors,
    validate_red_flags,
    run_kordoc_lint,
    safe_remove_file,
    safe_remove_dir,
)

def test_get_pdf_page_count(tmp_path: Path):
    """PDF 바이너리에서 페이지 수를 올바르게 파싱하는지 검증한다."""
    # 1. /Count 정규식 매칭
    pdf_file = tmp_path / "test1.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n/Type /Pages /Count 42 /Kids []\n%%EOF")
    assert get_pdf_page_count(pdf_file) == 42

    # 2. /Page 개수 카운팅
    pdf_file2 = tmp_path / "test2.pdf"
    pdf_file2.write_bytes(b"%PDF-1.4\n/Type /Page \n/Type /Page \n/Type /Page \n%%EOF")
    assert get_pdf_page_count(pdf_file2) == 3

    # 3. 비 PDF 파일
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("일반 텍스트", encoding="utf-8")
    assert get_pdf_page_count(txt_file) == 1


def test_generate_standard_metadata_header():
    """스킬 Phase 5 표준 메타데이터 헤더가 올바르게 생성되는지 검증한다."""
    header = generate_standard_metadata_header(
        title="반도체 산업 전망",
        original_filename="semiconductor.pdf",
        file_hash="sha256_abcdef123456",
        ext=".pdf",
        publisher="LS증권",
        date_str="2026년 06월 02일",
        category="산업 분석 보고서",
        entity_tags="#반도체 #HBM #AI",
        page_info="전체 120페이지 완본"
    )

    assert "# 반도체 산업 전망" in header
    assert "**원본 파일명**: `semiconductor.pdf`" in header
    assert "**발행기관**: LS증권" in header
    assert "**발행일자**: 2026년 06월 02일" in header
    assert "**핵심 엔티티**: #반도체 #HBM #AI" in header
    assert "**원본형식**: `PDF (전체 120페이지 완본)`" in header
    assert "**무결성 해시 (SHA-256)**: `sha256_abcdef123456`" in header
    assert "**데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)" in header
    assert "---\n\n" in header


def test_generate_toc_and_anchors():
    """헤딩 구조로부터 전체 목차(TOC)와 앵커 링크가 올바르게 삽입되는지 검증한다."""
    md = (
        "# 문서 제목\n\n"
        "> - **메타데이터**: 내용\n\n"
        "---\n\n"
        "## I. 산업 동향\n"
        "내용입니다.\n\n"
        "### 1. HBM 시장 전망\n"
        "상세 내용입니다.\n\n"
        "## II. 밸류체인 분석\n"
        "결론입니다.\n"
    )

    toc_md = generate_toc_and_anchors(md)
    assert "## 📑 전체 목차 (Table of Contents)" in toc_md
    assert "- [I. 산업 동향](#i-산업-동향)" in toc_md
    assert "  - [1. HBM 시장 전망](#1-hbm-시장-전망)" in toc_md
    assert "- [II. 밸류체인 분석](#ii-밸류체인-분석)" in toc_md


def test_validate_red_flags():
    """스킬 Red Flags 표현 및 결함을 정확히 탐지하는지 검증한다."""
    # 1. 생략 표현이 포함된 불완전 마크다운
    bad_md = (
        "# 제목\n\n"
        "주요 내용 요약입니다...\n"
        "세부 지표는 등... 외 생략함.\n"
    )
    flags = validate_red_flags(bad_md)
    assert any("생략 표현" in f for f in flags)
    assert any("표준 메타데이터 누락" in f for f in flags)

    # 2. 이미지는 있는데 수치 표가 없는 Dual-Mode 위반
    bad_dual_md = (
        "# 제목\n\n"
        "> - **원본 파일명**: `test.pdf`\n"
        "> - **발행기관**: 기관\n"
        "> - **무결성 해시 (SHA-256)**: `hash`\n"
        "> - **데이터 보존 원칙**: 완본\n\n"
        "![차트](/api/assets/doc/chart.png)\n"
    )
    flags2 = validate_red_flags(bad_dual_md)
    assert any("Dual-Mode" in f for f in flags2)

    # 3. 완벽한 마크다운
    good_md = (
        "# 제목\n\n"
        "> - **원본 파일명**: `test.pdf`\n"
        "> - **발행기관**: 기관\n"
        "> - **무결성 해시 (SHA-256)**: `hash`\n"
        "> - **데이터 보존 원칙**: 완본\n\n"
        "![차트](/api/assets/doc/chart.png)\n\n"
        "| 연도 | 수치 |\n|---|---|\n| 2026 | 100 |\n"
    )
    flags3 = validate_red_flags(good_md)
    assert len(flags3) == 0


def test_run_kordoc_lint():
    """kordoc lint 실행기 래퍼가 subprocess 호출 결과를 올바르게 처리하는지 검증한다."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Lint OK"

    with patch("subprocess.run", return_value=mock_res):
        passed, out = run_kordoc_lint(Path("dummy.md"))
        assert passed is True
        assert out == "Lint OK"


def test_safe_remove_file_and_dir(tmp_path: Path):
    """안전 파일 및 디렉터리 삭제 유틸리티 동작 검증."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("sample", encoding="utf-8")
    assert test_file.exists()
    assert safe_remove_file(test_file) is True
    assert not test_file.exists()

    # 이미 존재하지 않는 파일 삭제 시도 시에도 True 반환
    assert safe_remove_file(test_file) is True

    test_dir = tmp_path / "sub_dir"
    test_dir.mkdir()
    (test_dir / "child.txt").write_text("child", encoding="utf-8")
    assert test_dir.exists()
    assert safe_remove_dir(test_dir) is True
    assert not test_dir.exists()

    # 이미 존재하지 않는 디렉터리 삭제 시도 시에도 True 반환
    assert safe_remove_dir(test_dir) is True


def test_run_kordoc_lint_prefers_local_cli():
    """kordoc CLI가 시스템에 존재하는 경우 npx 대신 직접 kordoc 명령을 우선 실행하는지 검증한다."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "OK"

    with patch("shutil.which", return_value="C:\\tools\\kordoc.cmd"):
        with patch("subprocess.run", return_value=mock_res) as mock_run:
            passed, _ = run_kordoc_lint(Path("dummy.md"))
            assert passed is True
            # 호출된 명령어에 'cmd /c kordoc lint'가 포함되어야 함
            assert mock_run.call_args[0][0].startswith("cmd /c kordoc lint")
