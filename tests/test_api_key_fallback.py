"""Gemini API 다중 키 로드 및 자동 폴백 동작 검증 테스트."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from app.kordoc_wiki_agent import KordocWikiAgent
from app.audit_agent import AuditAgent
from app.ai_refiner import AIRefiner


def test_kordoc_wiki_agent_loads_multiple_keys_from_env(monkeypatch, tmp_path):
    """KordocWikiAgent가 쉼표로 연결된 GEMINI_API_KEY를 개별 키 리스트로 정상 분리하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "key_paid_123,key_free_456")
    monkeypatch.setenv("GEMINI_API_KEY_FALLBACK", "key_backup_789")

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")
    assert hasattr(agent, "api_keys")
    assert "key_paid_123" in agent.api_keys
    assert "key_free_456" in agent.api_keys
    assert "key_backup_789" in agent.api_keys
    assert agent.api_key == "key_paid_123"


def test_kordoc_wiki_agent_rotates_key_on_auth_or_exhaustion_error(monkeypatch, tmp_path):
    """1번 키가 401 인증 오류 또는 할당량 소진 시 2번 키로 자동 전환하여 호출 성공하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "bad_key_1,good_key_2")
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    # 1번 키 호출 시 401 오류 발생, 2번 키 호출 시 성공하도록 모킹
    call_counts = {"bad_key_1": 0, "good_key_2": 0}

    def mock_generate_content(model, contents, config=None):
        return MagicMock(text="# 변환 성공 본문\n\n- 본문 내용이 정상적으로 복원되었습니다.")

    def mock_client_factory(api_key=None, **kwargs):
        mock_c = MagicMock()
        if api_key == "bad_key_1":
            call_counts["bad_key_1"] += 1
            mock_c.models.generate_content.side_effect = Exception("401 UNAUTHENTICATED: API key not valid")
        else:
            call_counts["good_key_2"] += 1
            mock_c.models.generate_content.side_effect = mock_generate_content
        return mock_c

    with patch("google.genai.Client", side_effect=mock_client_factory):
        result = agent._call_llm_for_wiki_ingest(
            raw_md="## 섹션 1\n내용입니다.",
            doc_id="test_doc",
            original_filename="test.pdf",
            file_hash="hash123",
            images_info=[]
        )
        assert result is not None
        assert "# 변환 성공 본문" in result
        assert call_counts["bad_key_1"] > 0
        assert call_counts["good_key_2"] > 0


def test_audit_agent_and_refiner_load_keys_safely(monkeypatch, tmp_path):
    """AuditAgent와 AIRefiner가 쉼표 오염 없는 정제된 키를 사용하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "key_paid_abc,key_free_def")
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)

    agent = AuditAgent(docs_dir=tmp_path / "docs")
    refiner = AIRefiner()

    assert agent.api_key == "key_paid_abc"
    assert hasattr(agent, "api_keys")
    assert "key_free_def" in agent.api_keys
    assert refiner.api_key == "key_paid_abc"


def test_process_pdf_via_file_api_rotates_key(monkeypatch, tmp_path):
    """Files API 사용 시 1번 키가 실패하면 2번 키로 자동 전환하여 처리하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "bad_key_1,good_key_2")
    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy content")

    call_keys = []

    def mock_client_factory(api_key=None, **kwargs):
        mock_c = MagicMock()
        call_keys.append(api_key)
        if api_key == "bad_key_1":
            mock_c.files.upload.side_effect = Exception("401 UNAUTHENTICATED")
        else:
            mock_file = MagicMock()
            mock_file.uri = "https://files/dummy"
            mock_file.name = "files/dummy_123"
            mock_c.files.upload.return_value = mock_file
            mock_chat = MagicMock()
            mock_chat.send_message.return_value = MagicMock(text="# 완본 마크다운 결과")
            mock_c.chats.create.return_value = mock_chat
        return mock_c

    with patch("google.genai.Client", side_effect=mock_client_factory):
        res = agent._process_pdf_via_file_api(
            source_path=dummy_pdf,
            doc_id="dummy_doc",
            file_hash="hash_dummy"
        )
        assert res == "# 완본 마크다운 결과"
        assert "bad_key_1" in call_keys
        assert "good_key_2" in call_keys


def test_is_gemini_key_permanently_exhausted_vs_rate_limited():
    """402 선불 크레딧 소진과 429 일시적 모델 쿼터 초과가 명확히 분리 판정되는지 검증한다."""
    from app.utils import is_gemini_key_permanently_exhausted, is_gemini_rate_limited

    err_402 = Exception("402 RESOURCE_EXHAUSTED: Your prepayment credits are depleted.")
    err_429 = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for metric: free_tier_requests")

    assert is_gemini_key_permanently_exhausted(err_402) is True
    assert is_gemini_rate_limited(err_402) is False

    assert is_gemini_key_permanently_exhausted(err_429) is False
    assert is_gemini_rate_limited(err_429) is True


def test_kordoc_wiki_agent_falls_back_to_next_model_on_429(monkeypatch, tmp_path):
    """무료 보조 키에서 1순위 모델(3.8-flash)이 429 한도 초과 시 키를 버리지 않고 다음 모델(3.5-flash)로 폴백 성공하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "free_key_1")
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    attempted_models = []

    def mock_generate_content(model, contents, config=None):
        attempted_models.append(model)
        if model == "gemini-3.8-flash":
            raise Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for gemini-3.8-flash")
        return MagicMock(text="# 3.5-flash로 변환된 완본 마크다운\n\n내용입니다.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    with patch("google.genai.Client", return_value=mock_client):
        result = agent._call_llm_for_wiki_ingest(
            raw_md="## 본문\n내용",
            doc_id="test_doc_429",
            original_filename="test429.pdf",
            file_hash="hash429",
            images_info=[]
        )
        assert result is not None
        assert "# 3.5-flash로 변환된 완본 마크다운" in result
        assert "gemini-3.8-flash" in attempted_models
        assert "gemini-3.5-flash" in attempted_models


def test_kordoc_wiki_agent_preserves_failed_chunks_with_raw_text(monkeypatch, tmp_path):
    """멀티 청크 처리 중 파트 2가 429 등으로 실패해도 파트 1만 덜렁 남지 않고, 실패 청크를 원본 텍스트로 보존하여 내용 누락 없는 완본을 반환하는지 검증한다."""
    monkeypatch.setenv("GEMINI_API_KEY", "single_key")
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    # 청크 2개 분량의 텍스트
    large_raw = "## 섹션 1\n" + ("가나다라마바사 " * 600) + "\n\n## 섹션 2\n" + ("아자차카타파하 " * 600)

    chunk_call_count = [0]

    def mock_generate_content(model, contents, config=None):
        chunk_call_count[0] += 1
        if chunk_call_count[0] == 1:
            return MagicMock(text="## 파트 1 변환 완료")
        else:
            raise Exception("429 RESOURCE_EXHAUSTED")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    with patch("google.genai.Client", return_value=mock_client):
        result = agent._call_llm_for_wiki_ingest(
            raw_md=large_raw,
            doc_id="test_large_doc",
            original_filename="large.pdf",
            file_hash="hash_large",
            images_info=[]
        )
        # 파트 1(LLM 변환)과 파트 2(원본 텍스트)가 모두 보존되어 내용 누락 없이 완본이 반환되어야 함
        assert result is not None
        assert "## 파트 1 변환 완료" in result
        assert "## 섹션 2" in result


