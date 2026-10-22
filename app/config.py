"""시스템 전역 설정 및 경로 관리 모듈."""

import os
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

class Settings(BaseModel):
    """프로젝트 설정 모델."""
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    source_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "Source")
    wiki_db_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB")
    docs_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "docs")
    assets_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "assets")
    reports_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "reports")
    manifest_path: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "WikiDB" / "manifest.json")
    host: str = "0.0.0.0"
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8001")))
    supported_extensions: set[str] = {".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".md", ".txt"}
    storage_mode: str = Field(default_factory=lambda: os.getenv("STORAGE_MODE", "local"))
    gdrive_folder_id: Optional[str] = Field(default_factory=lambda: os.getenv("GDRIVE_FOLDER_ID") or None)
    gdrive_credentials_json: Optional[str] = Field(default_factory=lambda: os.getenv("GDRIVE_CREDENTIALS_JSON") or None)
    gdrive_credentials_path: Optional[Path] = Field(
        default_factory=lambda: Path(os.getenv("GDRIVE_CREDENTIALS_PATH", "gdrive_credentials.json"))
    )
    gdrive_local_mirror_dir: Optional[Path] = Field(
        default_factory=lambda: Path(os.getenv("GDRIVE_LOCAL_MIRROR_DIR").strip('\'"')) if os.getenv("GDRIVE_LOCAL_MIRROR_DIR") else None
    )
    wiki_access_pin: Optional[str] = Field(default_factory=lambda: os.getenv("WIKI_ACCESS_PIN") or None)

    @property
    def gemini_api_keys(self) -> list[str]:
        """주 키와 대체(Fallback) 무료 키 목록을 순서대로 수집한다."""
        keys: list[str] = []
        for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_FALLBACK", "GEMINI_API_KEYS"):
            raw_val = os.getenv(env_var)
            if raw_val:
                for k in re.split(r"[,;]+", raw_val):
                    clean_k = k.strip().strip("'\"")
                    if clean_k and clean_k not in keys:
                        keys.append(clean_k)
        return keys

    def ensure_directories(self) -> None:
        """필수 디렉토리들이 존재하지 않으면 생성한다."""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_db_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


# 공통 Gemini Fallback 모델 체인
DEFAULT_GEMINI_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

_settings_instance: Optional[Settings] = None

def get_settings() -> Settings:
    """설정 싱글톤 인스턴스를 반환하고 필수 디렉토리를 생성한다."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        _settings_instance.ensure_directories()
    return _settings_instance

def reset_settings_cache() -> None:
    """설정 싱글톤 캐시를 초기화한다 (테스트 환경 격리 및 런타임 설정 리로드 지원)."""
    global _settings_instance
    _settings_instance = None
