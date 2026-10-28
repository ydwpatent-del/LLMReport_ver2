"""클라우드(Google Drive) 및 로컬 환경 동기화 엔드포인트(/api/scan) 단위 테스트."""

import inspect
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.manifest import ManifestManager
from app.server import create_app


def execute_coroutine(coro):
    """파이썬 3.14 윈도우 환경에서도 이벤트루프 블로킹 없이 순수 코루틴을 즉시 평가하는 헬퍼."""
    if inspect.iscoroutine(coro):
        try:
            coro.send(None)
        except StopIteration as e:
            return e.value
    return coro


def test_scan_endpoint_cloud_mode_triggers_gdrive_sync(tmp_path: Path):
    """클라우드 환경(agent=None, gdrive_storage 존재)에서 /api/scan 호출 시
    500 에러 없이 Google Drive 원격 동기화가 정상 트리거되는지 검증."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        storage_mode="gdrive",
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)

    mock_storage = MagicMock()
    mock_storage.bootstrap_from_remote.return_value = {
        "bootstrapped": True,
        "source": "gdrive_api",
        "docs_count": 5,
        "pulled_reports": 2,
    }

    app = create_app(
        settings=settings,
        manifest_mgr=manifest_mgr,
        agent=None,
        gdrive_storage=mock_storage,
    )

    route_handler = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/scan" and "POST" in getattr(route, "methods", []):
            route_handler = route.endpoint
            break

    assert route_handler is not None, "/api/scan 엔드포인트가 등록되어 있어야 합니다."

    res = execute_coroutine(route_handler())
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert res.get("storage_mode") == "gdrive"
    assert "Google Drive 동기화 완료" in res.get("message", "")
    assert res.get("pulled_reports") == 2
    mock_storage.bootstrap_from_remote.assert_called_once_with(settings.wiki_db_dir)


def test_scan_endpoint_local_mode_triggers_agent_scan(tmp_path: Path):
    """로컬 환경(agent 존재)에서 /api/scan 호출 시 agent.scan_now()가 정상 트리거되는지 검증."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        storage_mode="local",
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)

    mock_agent = MagicMock()
    mock_agent.scan_now.return_value = (3, 1)

    app = create_app(
        settings=settings,
        manifest_mgr=manifest_mgr,
        agent=mock_agent,
        gdrive_storage=None,
    )

    route_handler = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/scan" and "POST" in getattr(route, "methods", []):
            route_handler = route.endpoint
            break

    assert route_handler is not None

    res = execute_coroutine(route_handler())
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert res.get("storage_mode") == "local"
    assert res.get("processed_count") == 3
    assert res.get("skipped_count") == 1
    mock_agent.scan_now.assert_called_once()


def test_scan_endpoint_no_agent_no_storage_raises_500(tmp_path: Path):
    """에이전트와 gdrive_storage가 모두 없을 때 명확한 500 에러를 반환하는지 검증."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)

    app = create_app(
        settings=settings,
        manifest_mgr=manifest_mgr,
        agent=None,
        gdrive_storage=None,
    )

    route_handler = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/scan" and "POST" in getattr(route, "methods", []):
            route_handler = route.endpoint
            break

    with pytest.raises(HTTPException) as exc_info:
        execute_coroutine(route_handler())

    assert exc_info.value.status_code == 500
