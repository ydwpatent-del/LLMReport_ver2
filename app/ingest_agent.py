"""watchdog 기반 실시간 파일 감시 및 자동 인제스트 에이전트."""

import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Union
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from app.hasher import calculate_file_hash
from app.manifest import ManifestManager, DocumentEntry
from app.kordoc_wiki_agent import KordocWikiAgent
from app.kordoc_engine import KordocEngine

logger = logging.getLogger("IngestAgent")

def sanitize_doc_id(filename: str) -> str:
    """파일명으로부터 안전하고 고유한 문서 ID를 생성한다.
    
    밀리초 단위 이벤트 중복이나 동시 처리 시에도 고유성을 보장하기 위해 UUID를 결합한다.
    """
    base = Path(filename).stem
    clean = re.sub(r'[^a-zA-Z0-9_\uac00-\ud7a3-]', '_', base)
    uid = uuid.uuid4().hex[:8]
    timestamp = int(time.time())
    return f"{clean}_{timestamp}_{uid}"

class SourceFileHandler(FileSystemEventHandler):
    """Source 디렉토리의 파일 변경 이벤트를 처리하는 핸들러."""

    def __init__(self, agent: "IngestAgent"):
        self.agent = agent

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.agent.process_file(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.agent.process_file(Path(event.src_path))

class IngestAgent:
    """파일 실시간 감시 및 kordoc 자동 변환을 총괄하는 에이전트."""

    def __init__(
        self,
        source_dir: Path,
        manifest_mgr: ManifestManager,
        engine: Union[KordocWikiAgent, KordocEngine],
        supported_exts: set[str],
        auto_sync_gdrive: bool = True,
        storage: Optional[object] = None,
    ):
        self.source_dir = source_dir
        self.manifest_mgr = manifest_mgr
        self.engine = engine
        self.supported_exts = {ext.lower() for ext in supported_exts}
        self.auto_sync_gdrive = auto_sync_gdrive
        self.storage = storage
        self.observer: Optional[Observer] = None
        # 동시 처리 방지를 위한 파일 경로 집합 및 락 (TOCTOU 방지)
        self._processing_files: set[Path] = set()
        self._lock = threading.Lock()
        # Google Drive 동기화 및 번들 생성 동시성 제어용 상호 배제 락
        self._sync_lock = threading.Lock()

    def process_file(self, file_path: Path, debounce: float = 0.2) -> bool:
        """단일 파일에 대해 해시 계산 및 중복 방지 검사 후 마크다운 변환을 수행한다."""
        if not file_path.exists() or file_path.is_dir():
            return False

        if file_path.suffix.lower() not in self.supported_exts:
            return False

        # 동일 파일 동시 처리 방지 상호 배제 (Mutex)
        with self._lock:
            resolved_path = file_path.resolve()
            if resolved_path in self._processing_files:
                logger.info(f"[건너뜀] 이미 처리 중인 파일입니다: {file_path.name}")
                return False
            self._processing_files.add(resolved_path)

        # 사전 초기화: except 블록에서 미초기화 변수 참조로 인한 NameError 방지
        doc_id: str = ""
        file_hash: str = ""
        stat = None

        try:
            if debounce > 0:
                time.sleep(debounce)

            try:
                file_hash = calculate_file_hash(file_path)
            except Exception as e:
                logger.warning(f"파일 해시 계산 실패 또는 파일 잠김: {e}")
                return False

            # 동일한 내용의 완료된 문서가 이미 존재하는 경우 스킵
            if self.manifest_mgr.is_duplicate(file_hash):
                logger.info(f"[건너뜀] 이미 변환된 파일입니다: {file_path.name} (Hash: {file_hash[:8]}...)")
                return False

            # 동일 파일에 대해 기존에 실패(failed)했거나 고착된 좀비 항목이 있다면 매니페스트 및 고아 에셋 폴더 정리
            for old_doc in self.manifest_mgr.get_all_documents():
                if (old_doc.file_hash == file_hash or old_doc.original_filename == file_path.name) and old_doc.status != "completed":
                    if hasattr(self.engine, "assets_dir") and old_doc.id:
                        old_asset_dir = Path(self.engine.assets_dir) / old_doc.id
                        if old_asset_dir.exists() and old_asset_dir.is_dir():
                            import shutil
                            shutil.rmtree(old_asset_dir, ignore_errors=True)
                    self.manifest_mgr.delete_document(old_doc.id)

            doc_id = sanitize_doc_id(file_path.name)
            stat = file_path.stat()

            logger.info(f"[시작] kordoc-wiki-ingest 에이전트 가동: {file_path.name} (ID: {doc_id})")
            
            # 1. 처리 중(processing) 상태 먼저 기록
            init_entry = DocumentEntry(
                id=doc_id,
                original_filename=file_path.name,
                source_path=str(file_path),
                file_hash=file_hash,
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                target_md_path="",
                assets_dir=str(self.engine.assets_dir / doc_id),
                status="processing",
                title=file_path.stem
            )
            self.manifest_mgr.add_or_update_document(init_entry)

            heartbeat = lambda: self.manifest_mgr.touch_processing(doc_id)
            is_pdf = file_path.suffix.lower() == ".pdf"
            if hasattr(self.engine, "execute_ingest"):
                try:
                    target_md, images, title = self.engine.execute_ingest(
                        file_path, doc_id, file_hash, heartbeat_cb=heartbeat
                    )
                except TypeError:
                    target_md, images, title = self.engine.execute_ingest(file_path, doc_id, file_hash)

                # 스캔본 PDF 자동 감지: 추출 텍스트가 500자 미만이면 OCR 재시도
                if is_pdf:
                    md_path = target_md
                    extracted_text = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""
                    content_body = extracted_text[300:] if len(extracted_text) > 300 else extracted_text
                    if len(content_body.strip()) < 500:
                        logger.warning(f"[스캔본 감지] '{file_path.name}' 텍스트 추출량 부족 ({len(content_body)}자) → OCR 모드 재시도")
                        try:
                            target_md, images, title = self.engine.execute_ingest(
                                file_path, doc_id, file_hash, enable_ocr=True, heartbeat_cb=heartbeat
                            )
                        except TypeError:
                            target_md, images, title = self.engine.execute_ingest(
                                file_path, doc_id, file_hash, enable_ocr=True
                            )
            else:
                target_md, images, title = self.engine.convert(file_path, doc_id, file_hash)

            entry = DocumentEntry(
                id=doc_id,
                original_filename=file_path.name,
                source_path=str(file_path),
                file_hash=file_hash,
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                target_md_path=str(target_md),
                assets_dir=str(self.engine.assets_dir / doc_id),
                status="completed",
                title=title
            )
            self.manifest_mgr.add_or_update_document(entry)
            logger.info(f"[성공] kordoc-wiki-ingest 완본 생성 및 WikiDB 등록: {target_md.name}")
            self._trigger_auto_sync(doc_id=doc_id, target_md=target_md)
            return True

        except Exception as e:
            logger.error(f"[오류] 문서 변환 실패 {file_path.name}: {e}")
            # stat이 초기화되지 않은 경우(해시 계산 이전 예외) 크기/시간을 0으로 기록
            file_size = stat.st_size if stat is not None else 0
            modified_time = stat.st_mtime if stat is not None else 0.0
            if doc_id:  # doc_id가 초기화된 경우에만 failed 항목 기록
                entry = DocumentEntry(
                    id=doc_id,
                    original_filename=file_path.name,
                    source_path=str(file_path),
                    file_hash=file_hash,
                    file_size=file_size,
                    modified_time=modified_time,
                    target_md_path="",
                    assets_dir="",
                    status="failed",
                    title=file_path.stem,
                    error_message=str(e)
                )
                self.manifest_mgr.add_or_update_document(entry)
            return False

        finally:
            with self._lock:
                self._processing_files.discard(resolved_path)

    def _trigger_auto_sync(self, doc_id: str, target_md: Optional[Path] = None) -> None:
        """인제스트 완료 후 Google Drive 연동(번들 갱신 및 자동 전송)을 비동기 백그라운드 스레드로 실행한다."""
        if not getattr(self, "auto_sync_gdrive", True):
            return

        def _worker():
            with self._sync_lock:
                try:
                    from app.gdrive_storage import get_gdrive_storage
                    from app.config import get_settings

                    settings = get_settings()
                    storage = self.storage or get_gdrive_storage()
                    wiki_db_dir = self.manifest_mgr.manifest_path.parent

                    # 1. 텍스트 번들(3.7MB) 자동 갱신
                    bundle_info = storage.create_text_bundle(wiki_db_dir)
                    logger.info(
                        f"📦 [자동 훅] 신규 문서 인제스트 후 텍스트 번들 자동 갱신 완료 "
                        f"({bundle_info['bundle_size_bytes'] / (1024 * 1024):.2f}MB, 문서 {bundle_info['docs_count']}건)"
                    )

                    # 실제 운영 WikiDB 경로와 일치하지 않는 임시 경로(테스트 등)인 경우 원격 Google Drive API 자동 푸시 원천 차단
                    is_prod_db = (wiki_db_dir.resolve() == settings.wiki_db_dir.resolve())

                    # 2. 로컬 구글 드라이브 데스크톱 폴더가 설정된 경우 즉시 복사/동기화 (운영 DB인 경우에만)
                    if storage.has_mirror_dir and is_prod_db:
                        sync_res = storage.sync_with_mirror_dir(
                            wiki_db_dir,
                            storage.settings.gdrive_local_mirror_dir,
                            include_assets=True,
                        )
                        logger.info(f"✨ [자동 훅] Google Drive 데스크톱 폴더 자동 동기화 완료: {sync_res}")

                    # 3. Google Drive API가 설정되어 있고 운영 DB인 경우에만 원격 업로드 시도
                    elif storage.is_api_configured and is_prod_db:
                        try:
                            push_res = storage.push_all_to_gdrive_api(wiki_db_dir=wiki_db_dir, upload_assets=True)
                            logger.info(f"✨ [자동 훅] Google Drive API 원격 동기화 완료: {push_res}")
                        except Exception as api_err:
                            logger.debug(f"원격 API 자동 푸시 스킵 또는 오류 (로컬 번들 유지): {api_err}")
                    elif not is_prod_db:
                        logger.debug("비운영/테스트 WikiDB 경로이므로 원격 Google Drive API 동기화를 건너뜁니다.")
                except Exception as e:
                    logger.warning(f"인제스트 후 Google Drive 자동 동기화 훅 처리 중 오류 (인제스트는 정상 완료): {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def scan_now(self) -> tuple[int, int]:
        """Source 폴더의 모든 파일을 즉시 검사하여 신규 파일을 변환한다. (성공건수, 스킵건수 반환)"""
        # 고착된 processing 좀비 항목 자동 정리
        self.manifest_mgr.cleanup_zombie_processing()

        processed_count = 0
        skipped_count = 0
        for file_path in sorted(self.source_dir.glob("*.*")):
            if file_path.suffix.lower() in self.supported_exts:
                if self.process_file(file_path, debounce=0.0):
                    processed_count += 1
                else:
                    skipped_count += 1

        if processed_count > 0:
            self._trigger_auto_sync("batch_scan", None)

        return processed_count, skipped_count

    def start(self) -> None:
        """백그라운드 파일 감시자를 가동한다."""
        if self.observer is None:
            self.observer = Observer()
            handler = SourceFileHandler(self)
            self.observer.schedule(handler, str(self.source_dir), recursive=False)
            self.observer.start()
            logger.info(f"Source 폴더 실시간 감시 시작: {self.source_dir}")

    def stop(self) -> None:
        """백그라운드 파일 감시자를 안전하게 종료한다."""
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("Source 폴더 감시 정지")
