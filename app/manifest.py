import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

class DocumentEntry(BaseModel):
    """개별 인제스트 문서 메타데이터 모델."""
    id: str
    original_filename: str
    source_path: str
    file_hash: str
    file_size: int
    modified_time: float
    target_md_path: str
    assets_dir: str
    status: str = "completed"  # completed, failed, processing
    ingested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    title: str
    error_message: Optional[str] = None

class ManifestData(BaseModel):
    """Manifest 전체 데이터 스키마."""
    version: str = "1.0.0"
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    documents: dict[str, DocumentEntry] = Field(default_factory=dict)

class ManifestManager:
    """manifest.json 파일 읽기/쓰기 및 중복 방지 관리 클래스 (스레드 안전)."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self._lock = threading.Lock()
        with self._lock:
            self._data = self._load()

    def _load(self) -> ManifestData:
        """manifest.json을 로드하거나 새로 생성한다."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                return ManifestData.model_validate(content)
            except Exception:
                pass
        return ManifestData()

    def _save(self) -> None:
        """manifest.json을 원자적으로 파일에 저장한다."""
        self._data.last_updated = datetime.now(timezone.utc).isoformat()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.manifest_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self._data.model_dump(), f, ensure_ascii=False, indent=2)
        temp_path.replace(self.manifest_path)

    def is_duplicate(self, file_hash: str) -> bool:
        """해당 해시를 가진 완료 상태의 문서가 이미 존재하는지 검사한다."""
        with self._lock:
            return any(
                doc.file_hash == file_hash and doc.status == "completed"
                for doc in self._data.documents.values()
            )

    def get_document(self, doc_id: str) -> Optional[DocumentEntry]:
        """문서 ID로 메타데이터를 조회한다."""
        with self._lock:
            return self._data.documents.get(doc_id)

    def get_all_documents(self) -> list[DocumentEntry]:
        """모든 문서 목록을 반환한다."""
        with self._lock:
            return list(self._data.documents.values())

    def add_or_update_document(self, doc: DocumentEntry) -> None:
        """문서 메타데이터를 추가하거나 갱신하고 저장한다."""
        with self._lock:
            self._data.documents[doc.id] = doc
            self._save()

    def delete_document(self, doc_id: str) -> bool:
        """문서 메타데이터를 삭제한다."""
        with self._lock:
            if doc_id in self._data.documents:
                del self._data.documents[doc_id]
                self._save()
                return True
            return False
