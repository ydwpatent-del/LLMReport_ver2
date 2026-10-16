import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("ManifestManager")

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
            except Exception as e:
                # 손상 파일을 조용히 버리지 않는다 — 반드시 로그와 백업 흔적을 남긴다
                logger.error(f"manifest.json 파싱 실패 (데이터 유실 방지 백업 진행): {e}")
                try:
                    backup_path = self.manifest_path.with_suffix(
                        f".corrupted_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                    )
                    self.manifest_path.replace(backup_path)
                    logger.error(f"손상된 manifest 백업 저장: {backup_path.name}")
                except Exception as backup_e:
                    logger.error(f"manifest 백업 저장 실패 (추가 조치 필요): {backup_e}")
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
        """해당 해시를 가진 완료(completed) 또는 최근 처리 중(processing) 상태의 문서가 이미 존재하는지 검사한다.
        
        좀비 방지: processing 상태여도 10분(600초) 이상 지연된 경우 중복으로 간주하지 않고 재처리를 허용한다.
        """
        with self._lock:
            self._data = self._load()
            now = datetime.now(timezone.utc)
            for doc in self._data.documents.values():
                if doc.file_hash == file_hash:
                    if doc.status == "completed":
                        return True
                    if doc.status == "processing":
                        try:
                            ingested_dt = datetime.fromisoformat(doc.ingested_at)
                            if (now - ingested_dt).total_seconds() < 600:
                                return True
                        except Exception:
                            return True
            return False

    def get_document(self, doc_id: str) -> Optional[DocumentEntry]:
        """문서 ID로 메타데이터를 조회한다. 인메모리 캐시를 사용한다."""
        with self._lock:
            # 단일 프로세스 환경: 디스크 재로드 없이 인메모리 상태 반환
            return self._data.documents.get(doc_id)

    def get_all_documents(self) -> list[DocumentEntry]:
        """모든 문서 목록을 반환한다.

        alias 중복 제거: 동일 file_hash + completed 상태 항목이 여러 개인 경우
        target_md_path가 더 긴 항목(실존 파일에 가까운 경로) 1건만 반환한다.
        """
        with self._lock:
            all_docs = list(self._data.documents.values())

        seen_hashes: dict[str, DocumentEntry] = {}
        result: list[DocumentEntry] = []
        for doc in all_docs:
            if doc.status == "completed" and doc.file_hash:
                existing = seen_hashes.get(doc.file_hash)
                if existing is None:
                    seen_hashes[doc.file_hash] = doc
                    result.append(doc)
                elif len(doc.target_md_path) > len(existing.target_md_path):
                    result.remove(existing)
                    seen_hashes[doc.file_hash] = doc
                    result.append(doc)
            else:
                result.append(doc)

        return result

    def add_or_update_document(self, doc: DocumentEntry) -> None:
        """문서 메타데이터를 추가하거나 갱신하고 저장한다."""
        with self._lock:
            self._data = self._load()
            self._data.documents[doc.id] = doc
            self._save()

    def delete_document(self, doc_id: str) -> bool:
        """문서 메타데이터를 삭제한다."""
        with self._lock:
            self._data = self._load()
            if doc_id in self._data.documents:
                del self._data.documents[doc_id]
                self._save()
                return True
            return False

    def touch_processing(self, doc_id: str) -> None:
        """처리 중(processing)인 문서의 하트비트 시각(ingested_at)을 현재 시각으로 갱신하여 대형 문서 처리 중 타임아웃 오판을 방지한다."""
        with self._lock:
            self._data = self._load()
            doc = self._data.documents.get(doc_id)
            if doc and doc.status == "processing":
                doc.ingested_at = datetime.now(timezone.utc).isoformat()
                self._save()

    def cleanup_zombie_processing(self, timeout_seconds: int = 600) -> int:
        """지정된 시간 이상 'processing' 상태로 멈춰있는 고착(좀비) 문서를 'failed' 상태로 안전 전환한다."""
        with self._lock:
            self._data = self._load()
            now = datetime.now(timezone.utc)
            updated_count = 0
            for doc in self._data.documents.values():
                if doc.status == "processing":
                    try:
                        ingested_dt = datetime.fromisoformat(doc.ingested_at)
                        elapsed = (now - ingested_dt).total_seconds()
                    except Exception:
                        elapsed = timeout_seconds + 1

                    if elapsed >= timeout_seconds:
                        doc.status = "failed"
                        doc.error_message = f"처리 시간 초과({int(elapsed)}초 경과)로 인한 자동 복구 (재시도 가능)"
                        updated_count += 1

            if updated_count > 0:
                self._save()
            return updated_count

    def reconcile_with_disk(self, docs_dir: Path, assets_dir: Path) -> dict[str, int]:
        """디스크 상의 마크다운(.md) 파일 및 에셋 폴더와 매니페스트 간의 정합성을 검사하고 자가 치유(Self-Healing)한다."""
        with self._lock:
            self._data = self._load()
            reconciled_count = 0
            new_registered_count = 0

            # 1. 고착된 processing 항목 1차 정리
            now = datetime.now(timezone.utc)
            for doc in list(self._data.documents.values()):
                if doc.status == "processing":
                    try:
                        ingested_dt = datetime.fromisoformat(doc.ingested_at)
                        if (now - ingested_dt).total_seconds() >= 600:
                            doc.status = "failed"
                            doc.error_message = "처리 시간 초과로 인한 자동 복구 (재시도 가능)"
                            reconciled_count += 1
                    except Exception:
                        pass

            if not docs_dir.exists():
                if reconciled_count > 0:
                    self._save()
                return {"reconciled": reconciled_count, "new_registered": new_registered_count}

            disk_md_files = list(docs_dir.glob("*.md"))

            # 2. 매니페스트 항목 중 target_md_path가 없거나 디스크에 존재하지 않는 경우 복구
            for doc_id, doc in list(self._data.documents.items()):
                target_path = Path(doc.target_md_path) if doc.target_md_path else None
                if not target_path or not target_path.exists():
                    # stem 기반 디스크 매칭 파일 탐색
                    orig_stem = Path(doc.original_filename).stem if doc.original_filename else doc.title
                    clean_stem = re.sub(r'[^a-zA-Z0-9_\uac00-\ud7a3-]', '_', orig_stem)
                    
                    matched_candidates = []
                    for f in disk_md_files:
                        if clean_stem.lower() in f.name.lower() or f.stem.startswith(clean_stem):
                            matched_candidates.append(f)

                    if matched_candidates:
                        # 파일 크기가 가장 크고 최신인 유효 완본 선택
                        best_md = max(matched_candidates, key=lambda p: (p.stat().st_size, p.stat().st_mtime))
                        matched_doc_id = best_md.stem
                        
                        # 기존 ID 항목의 target_md_path와 상태 갱신 (구 ID 요청 호환성 유지)
                        doc.target_md_path = str(best_md.resolve())
                        doc.status = "completed"
                        doc.error_message = None

                        # 에셋 디렉터리 동기화
                        candidate_asset = assets_dir / matched_doc_id
                        if candidate_asset.exists() and candidate_asset.is_dir():
                            doc.assets_dir = str(candidate_asset.resolve())

                        # 새 ID로도 별칭 항목 등록 (신규/구버전 양방향 호환)
                        if doc.id != matched_doc_id:
                            alias_entry = doc.model_copy()
                            alias_entry.id = matched_doc_id
                            self._data.documents[matched_doc_id] = alias_entry

                        reconciled_count += 1

            # 3. 디스크에는 존재하나 매니페스트에 누락된 고아 마크다운 파일 등록
            registered_targets = {
                Path(d.target_md_path).resolve() for d in self._data.documents.values() if d.target_md_path
            }
            for md_file in disk_md_files:
                resolved_md = md_file.resolve()
                if resolved_md not in registered_targets and md_file.stat().st_size > 0:
                    # 마크다운 헤더 파싱
                    try:
                        content_sample = md_file.read_text(encoding="utf-8", errors="replace")[:3000]
                        orig_fn_match = re.search(r'원본 파일명\*\*:\s*(.+)', content_sample)
                        hash_match = re.search(r'무결성 해시.*?\*\*:\s*([a-fA-F0-9]{64})', content_sample)
                        title_match = re.search(r'^#\s*(.+)', content_sample)

                        extracted_orig = orig_fn_match.group(1).strip() if orig_fn_match else md_file.stem
                        extracted_hash = hash_match.group(1).strip() if hash_match else ""
                        extracted_title = title_match.group(1).strip() if title_match else md_file.stem

                        # 이미 동일 해시의 정상 문서가 등록되어 있다면 중복 방지 및 디스크 잔여 파일 정리
                        if extracted_hash and any(d.file_hash == extracted_hash and d.status == "completed" for d in self._data.documents.values()):
                            try:
                                md_file.unlink(missing_ok=True)
                                orphan_asset = assets_dir / md_file.stem
                                if orphan_asset.exists() and orphan_asset.is_dir():
                                    import shutil
                                    shutil.rmtree(orphan_asset, ignore_errors=True)
                                logger.info(f"디스크 상의 동일 해시 중복 고아 파일 및 에셋 정리 완료: {md_file.name}")
                            except Exception as del_err:
                                logger.warning(f"중복 고아 파일 정리 실패 ({md_file.name}): {del_err}")
                            continue

                        orphan_id = md_file.stem
                        candidate_asset = assets_dir / orphan_id
                        entry = DocumentEntry(
                            id=orphan_id,
                            original_filename=extracted_orig,
                            source_path="",
                            file_hash=extracted_hash,
                            file_size=md_file.stat().st_size,
                            modified_time=md_file.stat().st_mtime,
                            target_md_path=str(resolved_md),
                            assets_dir=str(candidate_asset.resolve()) if candidate_asset.exists() else "",
                            status="completed",
                            title=extracted_title
                        )
                        self._data.documents[orphan_id] = entry
                        new_registered_count += 1
                    except Exception:
                        pass

            # 4. 실존하지 않는 타깃 경로를 가진 항목 중 동일 해시의 정상 항목이 이미 있는 경우 정리
            for doc_id, doc in list(self._data.documents.items()):
                if doc.status == "completed" and doc.file_hash:
                    doc_path = Path(doc.target_md_path) if doc.target_md_path else None
                    if not doc_path or not doc_path.exists():
                        has_valid_peer = any(
                            peer.id != doc_id and peer.file_hash == doc.file_hash and
                            peer.target_md_path and Path(peer.target_md_path).exists()
                            for peer in self._data.documents.values()
                        )
                        if has_valid_peer:
                            del self._data.documents[doc_id]
                            reconciled_count += 1

            if reconciled_count > 0 or new_registered_count > 0:
                self._save()

            return {"reconciled": reconciled_count, "new_registered": new_registered_count}

