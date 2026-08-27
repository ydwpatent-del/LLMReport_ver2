"""설정 모듈 및 디렉토리 자동 생성 테스트."""

from pathlib import Path
from app.config import get_settings

def test_settings_paths():
    """기본 디렉토리 경로 및 자동 생성 여부를 테스트한다."""
    settings = get_settings()
    assert settings.source_dir.exists()
    assert settings.wiki_db_dir.exists()
    assert settings.docs_dir.exists()
    assert settings.assets_dir.exists()
    assert settings.manifest_path == settings.wiki_db_dir / "manifest.json"
