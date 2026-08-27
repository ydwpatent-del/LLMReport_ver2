"""시스템 전역 설정 및 경로 관리 모듈."""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

class Settings(BaseModel):
    """프로젝트 설정 모델."""
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    source_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "Source")
    wiki_db_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB")
    docs_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "docs")
    assets_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "assets")
    manifest_path: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "manifest.json")
    host: str = "0.0.0.0"
    port: int = 8000
    supported_extensions: set[str] = {".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".md", ".txt"}

    def ensure_directories(self) -> None:
        """필수 디렉토리들이 존재하지 않으면 생성한다."""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_db_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

_settings_instance: Optional[Settings] = None

def get_settings() -> Settings:
    """설정 싱글톤 인스턴스를 반환하고 필수 디렉토리를 생성한다."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        _settings_instance.ensure_directories()
    return _settings_instance
