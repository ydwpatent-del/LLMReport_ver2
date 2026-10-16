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
        file_hash="hash987654321",
        skip_lint=True
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

    # 실제 에셋 디렉터리에 이미지 생성 (_validate_and_fix_image_links 검증 통과)
    (assets_dir / "test_pdf_001").mkdir(parents=True, exist_ok=True)
    (assets_dir / "test_pdf_001" / "image_001.png").write_bytes(b"dummy png data")

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


def test_stateless_generate_content_used_for_chunked_docs(tmp_path: Path):
    """분할 처리되는 대형 문서에 대해 히스토리 누적 없이 청크별 독립 generate_content 호출 및 하트비트가 수행되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key="fake-api-key")

    # 25,000자 초과 텍스트 구성 (2개 이상의 청크 분할 유도)
    section1 = "# 섹션 1: 반도체 산업 개요\n" + ("HBM DRAM 낸드플래시 공급망 분석 내용입니다. " * 700) + "\n"
    section2 = "# 섹션 2: 밸류체인 전망\n" + ("소부장 기업들의 실적 개선 전망 분석 내용입니다. " * 700) + "\n"
    raw_md = section1 + section2
    assert len(raw_md) > 25000

    mock_client = MagicMock()
    mock_response_1 = MagicMock()
    mock_response_1.text = "# 변환 결과 1"
    mock_response_2 = MagicMock()
    mock_response_2.text = "## 변환 결과 2"
    mock_response_3 = MagicMock()
    mock_response_3.text = "### 변환 결과 3"
    mock_client.models.generate_content.side_effect = [mock_response_1, mock_response_2, mock_response_3]

    heartbeat_calls = []

    with patch("google.genai.Client", return_value=mock_client):
        result = agent._call_llm_for_wiki_ingest(
            raw_md=raw_md,
            doc_id="test_chunked_doc",
            original_filename="대형문서.md",
            file_hash="hash_chunked_123",
            images_info=[],
            heartbeat_cb=lambda: heartbeat_calls.append(1)
        )

        assert result is not None
        assert "# 변환 결과 1" in result
        assert "## 변환 결과 2" in result
        mock_client.chats.create.assert_not_called()
        assert mock_client.models.generate_content.call_count >= 2
        assert len(heartbeat_calls) >= 2


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
    assert "![차트 99]" not in fixed_md  # 허구의 이미지는 다른 파일로 오인 덮어쓰지 않고 안전하게 제거됨


def test_is_meaningful_image_filtering(tmp_path: Path):
    """노이즈 아이콘 및 유효 차트 이미지를 정확히 판별하는지 검증한다."""
    import struct

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    # 1. 2500바이트 미만의 초소형 파일 -> False
    tiny_file = tmp_path / "tiny.png"
    tiny_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert agent._is_meaningful_image(tiny_file) is False

    # 2. 50x50 크기의 노이즈/아이콘 PNG -> False
    small_png = tmp_path / "icon.png"
    # PNG 시그니처(8바이트) + IHDR 청크 길이(4바이트) + "IHDR"(4바이트) + 너비(4바이트) + 높이(4바이트)
    ihdr_small = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 50, 50)
    small_png.write_bytes(ihdr_small + b"\x00" * 3000)
    assert agent._is_meaningful_image(small_png) is False

    # 3. 800x600 크기의 정상 차트 PNG (밀도 기준 만족) -> True
    valid_png = tmp_path / "valid_chart.png"
    ihdr_valid = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 800, 600)
    valid_png.write_bytes(ihdr_valid + b"\x00" * 15000)
    assert agent._is_meaningful_image(valid_png) is True


def test_abnormal_chunk_does_not_discard_previous_results(tmp_path):
    """마지막 청크가 비정상(30,000자 초과)이어도 이전 청크의 결과가 보존되어야 한다."""
    from unittest.mock import MagicMock, patch
    from app.kordoc_wiki_agent import KordocWikiAgent

    agent = KordocWikiAgent(
        docs_dir=tmp_path / "docs",
        assets_dir=tmp_path / "assets",
        api_key="fake-key"
    )

    mock_response_ok = MagicMock()
    mock_response_ok.text = "## 섹션 1 변환 결과\n" + ("처리됨. " * 100)

    mock_response_bad = MagicMock()
    mock_response_bad.text = "X" * 30001

    raw_md = "## 섹션 1\n" + ("내용. " * 1400) + "\n\n## 섹션 2\n" + ("내용. " * 1400)

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [mock_response_ok, mock_response_bad]
        mock_client_cls.return_value = mock_client

        result = agent._call_llm_for_wiki_ingest(
            raw_md=raw_md,
            doc_id="test_doc",
            original_filename="test.pdf",
            file_hash="abc123",
            images_info=[]
        )

    assert result is not None, "비정상 청크 1개로 인해 전체 결과가 폐기되었습니다"
    assert "섹션 1 변환 결과" in result


def test_truncated_llm_output_is_rejected_and_falls_back(tmp_path):
    """원본 청크가 충분히 긴데 LLM 응답이 목차 작성 도중 조기 절단된 경우
    정상 변환으로 오인하지 않고 None을 반환(룰베이스 폴백 유도)하는지 검증."""
    from unittest.mock import MagicMock, patch
    from app.kordoc_wiki_agent import KordocWikiAgent

    agent = KordocWikiAgent(
        docs_dir=tmp_path / "docs",
        assets_dir=tmp_path / "assets",
        api_key="fake-key"
    )

    truncated_resp = MagicMock()
    truncated_resp.text = (
        "# [이슈브리프]AI 추론 효율화를 위한 HBF의 등장\n"
        "> - **원본 파일명**: test.pdf\n"
        "---\n\n"
        "## 목차\n"
        "- [AI 추론 효율화를 위한 HBF의 등장](#ai-추"
    )

    raw_md = "# AI 추론 효율화를 위한 HBF의 등장\n\n" + ("본문 상세 단락 텍스트입니다. " * 200)

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = truncated_resp
        mock_client_cls.return_value = mock_client

        result = agent._call_llm_for_wiki_ingest(
            raw_md=raw_md,
            doc_id="test_hbf",
            original_filename="test.pdf",
            file_hash="hash123",
            images_info=[]
        )

    assert result is None, "조기 절단된 불완전 LLM 출력이 정상 결과로 채택되었습니다."


def test_large_pdf_chunked_parsing_preserves_image_paths_and_context(tmp_path: Path):
    """100페이지 이상 대형 PDF 분할 파싱 시:
    1) p1_image_001.png 경로가 이중 치환(/p1_/api/assets/...)되지 않아야 하며,
    2) extracted_images_info에 문맥(context_before/after/nearest_heading)이 보존되어
       본문 말미 덤프가 아닌 원래 문맥 위치에 정확히 재주입되는지 검증."""
    import struct
    from unittest.mock import MagicMock, patch
    from app.kordoc_wiki_agent import KordocWikiAgent

    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir, api_key=None)

    pdf_file = tmp_path / "large_report.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy large pdf")

    ihdr_valid = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 800, 600)
    valid_png_bytes = ihdr_valid + b"\x00" * 15000

    def fake_subprocess_run(cmd, *args, **kwargs):
        import re
        m = re.search(r'-o\s+"([^"]+)"', cmd)
        if m:
            out_file = Path(m.group(1))
            out_file.parent.mkdir(parents=True, exist_ok=True)
            img_dir = out_file.parent / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            (img_dir / "image_001.png").write_bytes(valid_png_bytes)
            out_file.write_text(
                "## 1. AI 반도체 시장 현황\n\n"
                "전 세계 AI 반도체 시장 규모 추이 설명 문단입니다.\n\n"
                "![도표 1](images/image_001.png)\n\n"
                "후속 단락 설명 텍스트가 이어집니다.\n\n"
                "## 2. 결론 및 시사점\n\n"
                "마무리 결론 텍스트입니다.\n",
                encoding="utf-8"
            )
        res = MagicMock()
        res.returncode = 0
        return res

    # LLM이 변환 중 이미지 태그를 누락한 상황 시뮬레이션 (스크린샷의 '💉 LLM 누락 이미지' 상황)
    llm_output_without_img = (
        "# large_report\n"
        "> - **원본 파일명**: large_report.pdf\n"
        "> - **발행기관**: 기관\n"
        "> - **무결성 해시 (SHA-256)**: largehash123\n"
        "> - **데이터 보존 원칙**: 100% 무삭제 완본\n"
        "---\n\n"
        "## 목차\n"
        "- [1. AI 반도체 시장 현황](#1-ai-반도체-시장-현황)\n"
        "- [2. 결론 및 시사점](#2-결론-및-시사점)\n\n"
        "---\n\n"
        "## 1. AI 반도체 시장 현황\n\n"
        "전 세계 AI 반도체 시장 규모 추이 설명 문단입니다.\n\n"
        "후속 단락 설명 텍스트가 이어집니다.\n\n"
        "## 2. 결론 및 시사점\n\n"
        "마무리 결론 텍스트입니다.\n"
    )

    with patch("app.kordoc_wiki_agent.get_pdf_page_count", return_value=100):
        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch.object(agent, "_call_llm_for_wiki_ingest", return_value=llm_output_without_img):
                target_md, images, title = agent.execute_ingest(
                    source_path=pdf_file,
                    doc_id="large_doc_001",
                    file_hash="largehash123",
                    skip_lint=True
                )

    content = target_md.read_text(encoding="utf-8")
    assert "/api/assets/large_doc_001/p1_image_001.png" in content

    # 이미지가 문서 맨 끝(## 2. 결론 및 시사점 뒤)에 말미 덤프되지 않고, 원래 문맥(## 1. AI 반도체 시장 현황 내부)에 재주입되어야 함
    pos_img = content.find("/api/assets/large_doc_001/p1_image_001.png")
    pos_sec2 = content.find("## 2. 결론 및 시사점")
    assert pos_img != -1 and pos_sec2 != -1
    assert pos_img < pos_sec2, f"누락 이미지가 문맥 정보 부재로 인해 문서 말미(섹션 2 뒤)로 일괄 덤프되었습니다:\n{content}"






