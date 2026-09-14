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
        supported_exts: set[str]
    ):
        self.source_dir = source_dir
        self.manifest_mgr = manifest_mgr
        self.engine = engine
        self.supported_exts = {ext.lower() for ext in supported_exts}
        self.observer: Optional[Observer] = None
        # 동시 처리 방지를 위한 파일 경로 집합 및 락 (TOCTOU 방지)
        self._processing_files: set[Path] = set()
        self._lock = threading.Lock()

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

            # 동일 파일에 대해 기존에 실패(failed)했거나 고착된 좀비 항목이 있다면 정리
            for old_doc in self.manifest_mgr.get_all_documents():
                if (old_doc.file_hash == file_hash or old_doc.original_filename == file_path.name) and old_doc.status != "completed":
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

            is_pdf = file_path.suffix.lower() == ".pdf"
            if hasattr(self.engine, "execute_ingest"):
                target_md, images, title = self.engine.execute_ingest(file_path, doc_id, file_hash)

                # 스캔본 PDF 자동 감지: 추출 텍스트가 500자 미만이면 OCR 재시도
                if is_pdf:
                    md_path = target_md
                    extracted_text = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""
                    content_body = extracted_text[300:] if len(extracted_text) > 300 else extracted_text
                    if len(content_body.strip()) < 500:
                        logger.warning(f"[스캔본 감지] '{file_path.name}' 텍스트 추출량 부족 ({len(content_body)}자) → OCR 모드 재시도")
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
