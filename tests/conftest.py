"""pytest 공통 설정 및 테스트 환경 격리 fixture."""

import pytest
from app.config import reset_settings_cache

@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """테스트 실행 시 실제 인증 및 외부 Google Drive 연동이 호출되지 않도록 완벽히 격리한다."""
    monkeypatch.delenv("WIKI_ACCESS_PIN", raising=False)
    monkeypatch.delenv("GDRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("GDRIVE_CREDENTIALS_JSON", raising=False)
    monkeypatch.setenv("STORAGE_MODE", "local")
    reset_settings_cache()
    yield
    reset_settings_cache()
