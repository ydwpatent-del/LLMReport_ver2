"""pytest 공통 설정 및 테스트 환경 격리 fixture."""

import pytest

@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """테스트 실행 시 .env의 WIKI_ACCESS_PIN이 자동 활성화되어 401이 발생하는 것을 방지한다."""
    monkeypatch.delenv("WIKI_ACCESS_PIN", raising=False)
