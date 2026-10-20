# Gemini API 다중 키 로테이션/폴백 및 배치 스크립트 인코딩 정상화 구현 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.env`에 설정된 다중 Gemini API 키(유료 결제 키 및 무료 백업 키)가 문서 인제스트(`KordocWikiAgent`), 원문 대조 검수(`AuditAgent`), 검색(`topic_search`), 정돈(`AIRefiner`) 전반에서 쉼표 오염 없이 분리 로드되고 유료 키 소진 시 무료 키로 자동 전환(Fallback)되도록 수정하며, Windows 배치 파일(`start_wiki.bat`)의 인코딩 및 개행(CRLF) 오류를 원천 해결한다.

**Architecture:** 
- `app/utils.py`의 `get_gemini_api_keys_list()`를 전 모듈의 단일 API 키 수집 진실원(Single Source of Truth)으로 적용하여 쉼표(`,`) 및 세미콜론(`;`) 구분 키를 안전하게 개별 분리한다.
- `TopicReportGenerator`에 검증 완료된 키 로테이션 및 `is_gemini_key_exhausted_or_invalid` 판별 로직을 `KordocWikiAgent` 및 `AuditAgent`의 멀티모달 / Files API 호출 파이프라인에 이식한다.
- `start_wiki.bat`의 LF 개행을 Windows 표준 CRLF 개행으로 통일하고 UTF-8 전환 구문을 재정비하여 `cmd.exe`의 바이트 오프셋 계산 착오를 제거한다.

**Tech Stack:** Python 3.14, google-genai SDK, pytest, Windows Batch (cmd.exe)

**Spec:** 사용자 요구사항 (글로벌 규칙 준수: 한국어 주석/문서화, 외과적 최소 변경, TDD 검증 선행)

## Global Constraints

- TARGET_LANGUAGE = Korean: 모든 응답, 생각 과정, 코드 내 주석과 독스트링을 한국어로 작성한다.
- Code Identifiers: 변수명, 함수명, 클래스명 등 식별자는 표준 영문 표기법을 준수한다.
- Read Before Write & Surgical Changes: 불필요한 파일이나 무관한 로직을 수정하지 않고 목적에 부합하는 최소 단위 diff만 작성한다.
- Verification Before Completion: 수정 전 실패하는 테스트(TDD)를 먼저 확인하고, 수정 후 모든 테스트가 통과하는지 직접 실행 검증한다.

---

### Task 1: API 키 로테이션 및 폴백 동작을 검증하는 단위 테스트 작성

**Files:**
- Create: `tests/test_api_key_fallback.py`

**Interfaces:**
- Consumes: `app.kordoc_wiki_agent.KordocWikiAgent`, `app.audit_agent.AuditAgent`, `app.utils.get_gemini_api_keys_list`
- Produces: API 키 분리 로드 및 에러 발생 시 다중 키 자동 폴백 검증 테스트 케이스

- [x] **Step 1: 실패하는 단위 테스트 작성 (`tests/test_api_key_fallback.py`)**

```python
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

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")

    # 1번 키 호출 시 401 오류 발생, 2번 키 호출 시 성공하도록 모킹
    call_counts = {"bad_key_1": 0, "good_key_2": 0}

    def mock_generate_content(model, contents, config=None):
        return MagicMock(text="# 변환 성공 본문")

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
    agent = AuditAgent(docs_dir=tmp_path / "docs")
    refiner = AIRefiner()

    assert agent.api_key == "key_paid_abc"
    assert hasattr(agent, "api_keys")
    assert "key_free_def" in agent.api_keys
    assert refiner.api_key == "key_paid_abc"
```

- [x] **Step 2: 테스트 실행하여 실패 확인**

Run: `.\.venv\Scripts\pytest.exe tests/test_api_key_fallback.py -v`
Expected: FAIL (AttributeError: 'KordocWikiAgent' object has no attribute 'api_keys')

---

### Task 2: `KordocWikiAgent`에 다중 API 키 수집 및 자동 폴백 로테이션 구현

**Files:**
- Modify: `app/kordoc_wiki_agent.py:150-355, 580-650`

**Interfaces:**
- Consumes: `app.utils.get_gemini_api_keys_list`, `app.utils.is_gemini_key_exhausted_or_invalid`
- Produces: 다중 키 순회 및 키별 재시도/폴백이 적용된 `_call_llm_for_wiki_ingest`, `_ingest_pdf_via_files_api`

- [x] **Step 1: `KordocWikiAgent.__init__`에서 `api_keys` 목록 수집 및 단일 진실원 적용**

```python
        if api_keys:
            self.api_keys = api_keys
        elif api_key:
            self.api_keys = [api_key]
        else:
            self.api_keys = get_gemini_api_keys_list()
        self.api_key = self.api_keys[0] if self.api_keys else None
```

- [x] **Step 2: `_call_llm_for_wiki_ingest`에 API 키 로테이션 루프 적용**
- 1번 키에서 `401/402/429/RESOURCE_EXHAUSTED` 등 인증 실패나 크레딧 소진 발생 시 다음 백업 키(`key_idx + 1`)로 즉시 전환
- 모델 fallback 목록(`gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-2.5-flash`)과 결합하여 안정적 생성 보장

- [x] **Step 3: `_ingest_pdf_via_files_api`에 API 키 로테이션 루프 적용**
- PDF 업로드 및 대화 세션 호출 시 유료 키 실패 시 무료 키로 자동 전환

---

### Task 3: `AuditAgent`, `topic_search.py`, `ai_refiner.py` API 키 수집 정돈

**Files:**
- Modify: `app/audit_agent.py:164-180`
- Modify: `app/topic_search.py:285-300`
- Modify: `app/ai_refiner.py:17-25`

**Interfaces:**
- Consumes: `app.utils.get_gemini_api_keys_list`
- Produces: 쉼표 오염 없는 단일 키 및 다중 키 리스트 관리

- [x] **Step 1: `AuditAgent.__init__`에서 `get_gemini_api_keys_list()` 적용 및 `self.api_keys` 저장**
- [x] **Step 2: `topic_search.py`에서 단일 키 대신 `get_gemini_api_keys_list()`의 첫 번째 정제된 키 사용**
- [x] **Step 3: `ai_refiner.py`에서 `get_gemini_api_keys_list()`를 통한 안전한 키 로드**

---

### Task 4: Windows 배치 파일(`start_wiki.bat`) 인코딩 및 개행(CRLF) 정상화

**Files:**
- Modify: `start_wiki.bat`

**Interfaces:**
- Consumes: Windows `cmd.exe`
- Produces: `'맻쑀?묐뜡'` 에러 없이 깔끔하게 서버를 구동하는 배치 스크립트 (CRLF 개행 및 UTF-8 보장)

- [x] **Step 1: `start_wiki.bat`를 CRLF 개행과 온전한 UTF-8 바이트로 재작성**
- `chcp 65001 > nul` 전후의 줄바꿈과 한글 주석/출력문 분리

---

### Task 5: 전체 통합 검증 및 테스트 실행

**Files:**
- Verify: `tests/test_api_key_fallback.py`
- Verify: `tests/test_kordoc_wiki_agent.py`
- Verify: `tests/test_audit_agent.py`
- Verify: `tests/test_topic_generator_prompt.py`

- [x] **Step 1: 신규 단위 테스트 실행**
Run: `.\.venv\Scripts\pytest.exe tests/test_api_key_fallback.py -v`
Expected: ALL PASS

- [x] **Step 2: 기존 핵심 테스트 스위트 회귀 검증**
Run: `.\.venv\Scripts\pytest.exe -k "test_kordoc_wiki_agent or test_topic_generator_prompt or test_audit_agent" --tb=short`
Expected: ALL PASS

- [x] **Step 3: 배치 파일 및 실제 API 키 로테이션 실동작 검증**
Run: Python 명령으로 실제 `.env`의 키 2개 분리 및 `KordocWikiAgent` 인스턴스화 검증
