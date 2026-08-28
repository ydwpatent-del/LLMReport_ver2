"""kordoc-wiki-ingest 전용 에이전트 단위 테스트."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.kordoc_wiki_agent import KordocWikiAgent, KORDOC_WIKI_INGEST_SYSTEM_PROMPT

def test_system_prompt_contains_required_sections():
    """시스템 프롬프트에 Phase 3~6 및 Mistakes & Rationalizations 표 키워드가 포함되어 있는지 검증한다."""
    required_keywords = [
        "Phase 3",
        "Phase 4",
        "Phase 5",
        "전수 복원",
        "Dual-Mode",
        "TOC",
        "재무제표가 너무 길어서",
        "차트 이미지를 넣었으니",
        "부록에 한꺼번에",
    ]
    for keyword in required_keywords:
        assert keyword in KORDOC_WIKI_INGEST_SYSTEM_PROMPT, f"누락된 키워드: {keyword}"


def test_kordoc_wiki_agent_rule_based_pipeline(tmp_path: Path):
    """KordocWikiAgent가 kordoc-wiki-ingest 5대 원칙에 따라 무삭제 마크다운을 산출하는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)

    source_file = tmp_path / "LS증권_반도체_2026.md"
    source_file.write_text(
        "# 산업 분석\n\n"
        "2026.06.30\n\n"
        "I. 개요\n"
        "HBM 및 DRAM 공급 부족이 심화되고 있습니다.\n\n"
        "1. 세부 전망\n"
        "소부장 밸류체인의 실적 개선이 기대됩니다.\n",
        encoding="utf-8"
    )

    target_md, images, title = agent.execute_ingest(
        source_path=source_file,
        doc_id="test_ingest_001",
        file_hash="hash987654321"
    )

    assert target_md.exists()
    assert target_md.parent == docs_dir
    content = target_md.read_text(encoding="utf-8")

    # 1. 메타데이터 헤더 검증
    assert "LS증권_반도체_2026" in content
    assert "**발행기관**" in content
    assert "**데이터 보존 원칙**" in content
    assert "100% 무삭제 완본" in content

    # 2. 내용 보존 검증
    assert "HBM" in content
    assert "DRAM" in content


def test_pdf_routes_to_file_api(tmp_path: Path):
    """PDF 문서 인제스트 시 Files API 파이프라인으로 우선 라우팅되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key="fake-api-key")

    pdf_file = tmp_path / "테스트보고서.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test dummy content")

    expected_content = "# 테스트보고서\n\n> - **원본 파일명**: `테스트보고서.pdf`\n\nPDF 본문 내용입니다."
    with patch.object(agent, "_process_pdf_via_file_api", return_value=expected_content) as mock_file_api:
        target_md, images, title = agent.execute_ingest(
            source_path=pdf_file,
            doc_id="test_pdf_001",
            file_hash="pdfhash123"
        )

        mock_file_api.assert_called_once_with(
            source_path=pdf_file,
            doc_id="test_pdf_001",
            file_hash="pdfhash123"
        )
        assert target_md.exists()
        assert target_md.read_text(encoding="utf-8") == expected_content
        assert title == "테스트보고서"


def test_pdf_file_api_cleanup_on_failure(tmp_path: Path):
    """PDF Files API 처리 중 오류 발생 시 finally 블록에서 파일이 삭제되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key="fake-api-key")

    pdf_file = tmp_path / "오류테스트.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy error test content")

    mock_client = MagicMock()
    mock_file = MagicMock()
    mock_file.name = "files/test_temp_file_id"
    mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/test_temp_file_id"
    mock_client.files.upload.return_value = mock_file
    mock_client.chats.create.return_value.send_message.side_effect = RuntimeError("Chat API Failure")

    with patch("google.genai.Client", return_value=mock_client):
        result = agent._process_pdf_via_file_api(
            source_path=pdf_file,
            doc_id="test_pdf_err",
            file_hash="pdfhash_err"
        )

        assert result is None
        mock_client.files.delete.assert_called_once_with(name="files/test_temp_file_id")
