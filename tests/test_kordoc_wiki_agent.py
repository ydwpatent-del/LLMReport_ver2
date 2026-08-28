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


def test_pdf_routes_to_multimodal_ingest(tmp_path: Path):
    """PDF 문서 인제스트 시 kordoc CLI 1차 에셋 추출 후 멀티모달 LLM으로 정돈되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key="fake-api-key")

    pdf_file = tmp_path / "테스트보고서.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test dummy content")

    expected_content = "# 테스트보고서\n\n> - **원본 파일명**: `테스트보고서.pdf`\n\n![차트](/api/assets/test_pdf_001/image_001.png)\n\nPDF 본문 내용입니다."

    def fake_subprocess_run(cmd, *args, **kwargs):
        # cmd 내 output_raw.md 경로를 찾아 더미 파일 생성
        import re
        m = re.search(r'-o\s+"([^"]+)"', cmd)
        if m:
            out_file = Path(m.group(1))
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text("# 1차 Raw 변환\n\n![img](images/image_001.png)", encoding="utf-8")
        res = MagicMock()
        res.returncode = 0
        return res

    with patch.object(agent, "_call_llm_for_wiki_ingest", return_value=expected_content) as mock_llm:
        with patch.object(agent, "_extract_and_inline_images", return_value=("Raw MD", [{"filename": "image_001.png", "path": tmp_path / "image_001.png"}])):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                target_md, images, title = agent.execute_ingest(
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


def test_chat_session_used_for_chunked_docs(tmp_path: Path):
    """25,000자를 초과하여 분할 처리되는 대형 문서에 대해 단일 Chat Session을 유지하며 처리하는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key="fake-api-key")

    # 25,000자 초과 텍스트 구성 (2개 이상의 청크 분할 유도)
    section1 = "# 섹션 1: 반도체 산업 개요\n" + ("HBM DRAM 낸드플래시 공급망 분석 내용입니다. " * 700) + "\n"
    section2 = "# 섹션 2: 밸류체인 전망\n" + ("소부장 기업들의 실적 개선 전망 분석 내용입니다. " * 700) + "\n"
    raw_md = section1 + section2
    assert len(raw_md) > 25000

    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_response_1 = MagicMock()
    mock_response_1.text = "# 변환 결과 1"
    mock_response_2 = MagicMock()
    mock_response_2.text = "## 변환 결과 2"
    mock_chat.send_message.side_effect = [mock_response_1, mock_response_2]
    mock_client.chats.create.return_value = mock_chat

    with patch("google.genai.Client", return_value=mock_client):
        result = agent._call_llm_for_wiki_ingest(
            raw_md=raw_md,
            doc_id="test_chunked_doc",
            original_filename="대형문서.md",
            file_hash="hash_chunked_123",
            images_info=[]
        )

        assert result is not None
        assert "# 변환 결과 1" in result
        assert "## 변환 결과 2" in result
        mock_client.chats.create.assert_called_once()
        assert mock_chat.send_message.call_count >= 2


def test_validate_and_fix_image_links(tmp_path: Path):
    """실존하지 않는 허구의 이미지 링크가 실제 에셋 파일로 정확히 안전 보정되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)

    doc_id = "test_doc_001"
    doc_asset_dir = assets_dir / doc_id
    doc_asset_dir.mkdir(parents=True, exist_ok=True)

    # 실제 디스크에 image_001.png ~ image_003.png 생성
    (doc_asset_dir / "image_001.png").write_bytes(b"fake1")
    (doc_asset_dir / "image_002.png").write_bytes(b"fake2")
    (doc_asset_dir / "image_003.png").write_bytes(b"fake3")

    md_with_invalid_link = (
        "# 제목\n\n"
        "![차트 1](/api/assets/test_doc_001/image_001.png)\n\n"
        "![차트 99](/api/assets/test_doc_001/image_099.png)\n"
    )

    fixed_md = agent._validate_and_fix_image_links(
        final_md=md_with_invalid_link,
        doc_id=doc_id,
        doc_asset_dir=doc_asset_dir
    )

    assert "image_001.png" in fixed_md
    assert "image_099.png" not in fixed_md
    assert "image_003.png" in fixed_md  # 마지막 실제 파일로 안전 매핑됨


