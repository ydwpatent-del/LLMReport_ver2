# LLM Wiki 무삭제 지식 인제스트 에이전트 및 반응형 웹 뷰어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Source/` 폴더에 투입되는 다양한 문서(HWP, HWPX, PDF, DOCX, XLSX 등)를 `kordoc`을 활용하여 100% 무삭제 마크다운으로 자동 변환하고, 중복을 방지하며 `WikiDB/`에 축적하고, 모바일 및 PC에서 시각적으로 열람 가능한 반응형 로컬 웹 대시보드를 구축한다.

**Architecture:** Python `watchdog` 기반 백그라운드 파일 감시 에이전트와 `FastAPI` 기반 비동기 REST 백엔드를 결합하고, 빌드 도구 없이 브라우저에서 구동되는 Tailwind CSS + Marked.js + KaTeX 반응형 SPA 웹 뷰어를 단일 패키지로 서빙한다.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Watchdog, Pytest, Node.js (`npx kordoc`), Tailwind CSS (CDN), Marked.js, KaTeX, Highlight.js.

**Spec:** `docs/superpowers/specs/2026-08-27-llm-wiki-ingest-agent-design.md`

## Global Constraints

- **TARGET_LANGUAGE**: 모든 주석, docstring, UI 텍스트, 안내 메시지는 자연스러운 한국어로 통일한다.
- **IDENTIFIERS**: 파이썬 함수/변수/클래스명 등 식별자는 영어 표준(PEP 8)을 따른다.
- **ZERO_INFO_LOSS**: 텍스트, 표, 수치, 이미지의 축약 및 생략을 절대 금지한다.
- **DEDUPLICATION**: SHA-256 해시를 기준으로 중복 인제스트를 방지한다.
- **SIMPLICITY**: 불필요한 프레임워크 빌드 체인을 지양하고, 브라우저 직접 로드 방식을 사용한다.

---

### Task 1: 환경 설정 및 기본 디렉토리/설정 모듈 구성

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces: `app.config.Settings`, 기본 디렉토리 구조 (`Source/`, `WikiDB/docs/`, `WikiDB/assets/`)

- [ ] **Step 1: Write the failing test for config and directories**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app')

- [ ] **Step 3: Write minimal implementation**

```python
# requirements.txt
fastapi>=0.110.0
uvicorn>=0.28.0
watchdog>=4.0.0
pydantic>=2.6.0
python-multipart>=0.0.9
pytest>=8.0.0
httpx>=0.27.0
```

```python
# app/__init__.py
"""LLM Wiki 지식 인제스트 에이전트 및 웹 대시보드 패키지."""
```

```python
# app/config.py
"""시스템 전역 설정 및 경로 관리 모듈."""

from pathlib import Path
from pydantic import BaseModel

class Settings(BaseModel):
    """프로젝트 설정 모델."""
    base_dir: Path = Path(__file__).resolve().parent.parent
    source_dir: Path = Path(__file__).resolve().parent.parent / "Source"
    wiki_db_dir: Path = Path(__file__).resolve().parent.parent / "WikiDB"
    docs_dir: Path = Path(__file__).resolve().parent.parent / "WikiDB" / "docs"
    assets_dir: Path = Path(__file__).resolve().parent.parent / "WikiDB" / "assets"
    manifest_path: Path = Path(__file__).resolve().parent.parent / "WikiDB" / "manifest.json"
    host: str = "0.0.0.0"
    port: int = 8000
    supported_extensions: set[str] = {".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".md", ".txt"}

    def ensure_directories(self) -> None:
        """필수 디렉토리들이 존재하지 않으면 생성한다."""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_db_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

_settings_instance = None

def get_settings() -> Settings:
    """설정 싱글톤 인스턴스를 반환하고 디렉토리를 생성한다."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        _settings_instance.ensure_directories()
    return _settings_instance
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/__init__.py app/config.py tests/test_config.py
git commit -m "feat: add project configuration and directory initialization"
```

---

### Task 2: SHA-256 해시 계산 및 Manifest 관리자 (`app/manifest.py`)

**Files:**
- Create: `app/hasher.py`
- Create: `app/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `app.config.get_settings`
- Produces: `calculate_file_hash(path) -> str`, `ManifestManager` 클래스 (문서 추가, 조회, 중복 체크)

- [ ] **Step 1: Write the failing test for hasher and manifest**

```python
# tests/test_manifest.py
import pytest
from pathlib import Path
from app.hasher import calculate_file_hash
from app.manifest import ManifestManager, DocumentEntry

def test_calculate_file_hash(tmp_path: Path):
    """파일 내용에 대한 SHA-256 해시가 정확히 계산되는지 검증한다."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello LLM Wiki", encoding="utf-8")
    hash1 = calculate_file_hash(test_file)
    assert len(hash1) == 64
    assert hash1 == calculate_file_hash(test_file)

    test_file.write_text("Modified Content", encoding="utf-8")
    hash2 = calculate_file_hash(test_file)
    assert hash1 != hash2

def test_manifest_deduplication(tmp_path: Path):
    """Manifest를 통해 동일 해시 파일의 중복 여부를 감지하는지 검증한다."""
    manifest_file = tmp_path / "manifest.json"
    manager = ManifestManager(manifest_file)
    
    assert manager.is_duplicate("sample_hash_123") is False
    
    doc = DocumentEntry(
        id="doc_1",
        original_filename="sample.pdf",
        source_path="Source/sample.pdf",
        file_hash="sample_hash_123",
        file_size=1024,
        modified_time=1700000000.0,
        target_md_path="WikiDB/docs/doc_1.md",
        assets_dir="WikiDB/assets/doc_1",
        status="completed",
        title="샘플 문서"
    )
    manager.add_or_update_document(doc)
    
    assert manager.is_duplicate("sample_hash_123") is True
    assert manager.get_document("doc_1") is not None
    assert manager.get_document("doc_1").title == "샘플 문서"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app.hasher')

- [ ] **Step 3: Write minimal implementation**

```python
# app/hasher.py
"""파일 무결성 검증 및 해시 계산 모듈."""

import hashlib
from pathlib import Path

def calculate_file_hash(file_path: Path, chunk_size: int = 65536) -> str:
    """주어진 파일의 SHA-256 해시값을 16진수 문자열로 반환한다."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()
```

```python
# app/manifest.py
"""WikiDB 메타데이터 및 중복 방지 매니페스트 관리 모듈."""

import json
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
    """manifest.json 파일 읽기/쓰기 및 중복 관리 클래스."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
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
        """해당 해시를 가진 완료된 문서가 이미 존재하는지 검사한다."""
        return any(
            doc.file_hash == file_hash and doc.status == "completed"
            for doc in self._data.documents.values()
        )

    def get_document(self, doc_id: str) -> Optional[DocumentEntry]:
        """문서 ID로 메타데이터를 조회한다."""
        return self._data.documents.get(doc_id)

    def get_all_documents(self) -> list[DocumentEntry]:
        """모든 문서 목록을 반환한다."""
        return list(self._data.documents.values())

    def add_or_update_document(self, doc: DocumentEntry) -> None:
        """문서 메타데이터를 추가하거나 갱신하고 저장한다."""
        self._data.documents[doc.id] = doc
        self._save()

    def delete_document(self, doc_id: str) -> bool:
        """문서 메타데이터를 삭제한다."""
        if doc_id in self._data.documents:
            del self._data.documents[doc_id]
            self._save()
            return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/hasher.py app/manifest.py tests/test_manifest.py
git commit -m "feat: implement SHA-256 hasher and ManifestManager for deduplication"
```

---

### Task 3: kordoc 기반 지식 변환 엔진 (`app/kordoc_engine.py`)

**Files:**
- Create: `app/kordoc_engine.py`
- Test: `tests/test_kordoc_engine.py`

**Interfaces:**
- Consumes: `app.config.Settings`
- Produces: `KordocEngine.convert(file_path, doc_id) -> tuple[Path, list[Path], str]` (마크다운 파일 경로, 추출 이미지 목록, 제목)

- [ ] **Step 1: Write the test for kordoc engine with mock and text fallback**

```python
# tests/test_kordoc_engine.py
import pytest
from pathlib import Path
from app.kordoc_engine import KordocEngine

def test_convert_markdown_and_text_direct(tmp_path: Path):
    """일반 텍스트나 마크다운 파일 투입 시 메타데이터 헤더와 함께 올바르게 저장되는지 테스트한다."""
    engine = KordocEngine(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")
    
    source_file = tmp_path / "sample.txt"
    source_file.write_text("이것은 테스트 문서 본문입니다.\n\n| 항목 | 내용 |\n|---|---|\n| 값 | 100 |", encoding="utf-8")
    
    md_path, images, title = engine.convert(source_file, doc_id="test_doc_1", file_hash="hash123")
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "# sample" in content
    assert "이것은 테스트 문서 본문입니다." in content
    assert "hash123" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kordoc_engine.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app.kordoc_engine')

- [ ] **Step 3: Write minimal implementation**

```python
# app/kordoc_engine.py
"""kordoc CLI를 호출하여 문서를 100% 무삭제 마크다운으로 변환하는 엔진."""

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

class KordocEngine:
    """kordoc CLI 기반 문서 파싱 및 이미지 추출 엔진."""

    def __init__(self, docs_dir: Path, assets_dir: Path):
        self.docs_dir = docs_dir
        self.assets_dir = assets_dir

    def _generate_metadata_header(self, title: str, original_name: str, file_hash: str) -> str:
        """LLM Wiki 및 RAG용 표준 메타데이터 헤더를 생성한다."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"# {title}\n\n"
            f"> - **원본 파일명**: `{original_name}`\n"
            f"> - **인제스트 일시**: `{now}`\n"
            f"> - **파일 무결성 해시 (SHA-256)**: `{file_hash}`\n"
            f"> - **데이터 보존**: 100% 무삭제 완본 (Full-Text Ingestion)\n\n"
            f"---\n\n"
        )

    def convert(self, source_path: Path, doc_id: str, file_hash: str) -> tuple[Path, list[Path], str]:
        """원본 파일을 마크다운 및 이미지 에셋으로 변환하여 저장한다."""
        title = source_path.stem
        target_md_path = self.docs_dir / f"{doc_id}.md"
        doc_asset_dir = self.assets_dir / doc_id
        doc_asset_dir.mkdir(parents=True, exist_ok=True)
        extracted_images: list[Path] = []

        ext = source_path.suffix.lower()

        # 순수 텍스트 또는 마크다운 파일인 경우 직접 처리
        if ext in {".txt", ".md"}:
            raw_content = source_path.read_text(encoding="utf-8", errors="replace")
            header = self._generate_metadata_header(title, source_path.name, file_hash)
            final_content = header + raw_content
            target_md_path.write_text(final_content, encoding="utf-8")
            return target_md_path, extracted_images, title

        # HWP, HWPX, PDF, DOCX, XLSX 등 복합 문서는 kordoc CLI 호출
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_out_md = Path(temp_dir) / "output_raw.md"
            cmd = f'cmd /c npx -y kordoc@^4 "{source_path.resolve()}" -o "{temp_out_md.resolve()}"'
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            if not temp_out_md.exists():
                raise RuntimeError(f"kordoc 변환 실패 (반환코드: {result.returncode}): {result.stderr or result.stdout}")

            raw_md = temp_out_md.read_text(encoding="utf-8", errors="replace")

            # 임시 폴더의 images/ 를 대상 assets/doc_id/ 폴더로 복사하고 마크다운 경로 치환
            temp_images_dir = Path(temp_dir) / "images"
            if temp_images_dir.exists():
                for img_file in temp_images_dir.glob("*.*"):
                    target_img = doc_asset_dir / img_file.name
                    shutil.copy2(img_file, target_img)
                    extracted_images.append(target_img)

            # 이미지 상대 경로를 웹 API 경로로 보정: images/foo.png -> /api/assets/<doc_id>/foo.png
            adjusted_md = re.sub(
                r'!\[(.*?)\]\(images/(.*?)\)',
                rf'![\1](/api/assets/{doc_id}/\2)',
                raw_md
            )

            # 상단 제목 추출 (만약 본문에 이미 # 제목이 있으면 활용)
            header = self._generate_metadata_header(title, source_path.name, file_hash)
            final_content = header + adjusted_md
            target_md_path.write_text(final_content, encoding="utf-8")

        return target_md_path, extracted_images, title
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kordoc_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/kordoc_engine.py tests/test_kordoc_engine.py
git commit -m "feat: implement KordocEngine for complete markdown conversion"
```

---

### Task 4: 실시간 파일 감시 및 자동 인제스트 에이전트 (`app/ingest_agent.py`)

**Files:**
- Create: `app/ingest_agent.py`
- Test: `tests/test_ingest_agent.py`

**Interfaces:**
- Consumes: `app.config`, `app.hasher`, `app.manifest`, `app.kordoc_engine`
- Produces: `IngestAgent` 클래스 (`start()`, `stop()`, `scan_now()`)

- [ ] **Step 1: Write the test for IngestAgent scan and processing**

```python
# tests/test_ingest_agent.py
import time
import pytest
from pathlib import Path
from app.config import Settings
from app.manifest import ManifestManager
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent

def test_ingest_agent_scan(tmp_path: Path):
    """Source 디렉토리 스캔 시 신규 파일이 WikiDB에 정상 등록되는지 테스트한다."""
    source_dir = tmp_path / "Source"
    wiki_db = tmp_path / "WikiDB"
    docs_dir = wiki_db / "docs"
    assets_dir = wiki_db / "assets"
    manifest_path = wiki_db / "manifest.json"

    source_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    manifest_mgr = ManifestManager(manifest_path)
    engine = KordocEngine(docs_dir, assets_dir)
    agent = IngestAgent(
        source_dir=source_dir,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts={".txt", ".md"}
    )

    # 신규 파일 투입
    doc_file = source_dir / "notice.md"
    doc_file.write_text("## 긴급 공지사항\n\n내용입니다.", encoding="utf-8")

    # 수동 스캔 실행
    processed_count, skipped_count = agent.scan_now()
    assert processed_count == 1
    assert skipped_count == 0

    # 동일 파일 재스캔 시 스킵 확인
    processed_count2, skipped_count2 = agent.scan_now()
    assert processed_count2 == 0
    assert skipped_count2 == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_agent.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app.ingest_agent')

- [ ] **Step 3: Write minimal implementation**

```python
# app/ingest_agent.py
"""watchdog 기반 실시간 파일 감시 및 자동 인제스트 에이전트."""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from app.hasher import calculate_file_hash
from app.manifest import ManifestManager, DocumentEntry
from app.kordoc_engine import KordocEngine

logger = logging.getLogger("IngestAgent")

def sanitize_doc_id(filename: str) -> str:
    """파일명으로부터 안전한 고유 문서 ID를 생성한다."""
    base = Path(filename).stem
    clean = re.sub(r'[^a-zA-Z0-9_\uac00-\ud7a3-]', '_', base)
    timestamp = int(time.time())
    return f"{clean}_{timestamp}"

class SourceFileHandler(FileSystemEventHandler):
    """Source 디렉토리 파일 변경 이벤트를 처리하는 핸들러."""

    def __init__(self, agent: "IngestAgent"):
        self.agent = agent

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.agent.process_file(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.agent.process_file(Path(event.src_path))

class IngestAgent:
    """파일 감시 및 자동 변환 오케스트레이션 에이전트."""

    def __init__(
        self,
        source_dir: Path,
        manifest_mgr: ManifestManager,
        engine: KordocEngine,
        supported_exts: set[str]
    ):
        self.source_dir = source_dir
        self.manifest_mgr = manifest_mgr
        self.engine = engine
        self.supported_exts = {ext.lower() for ext in supported_exts}
        self.observer: Optional[Observer] = None

    def process_file(self, file_path: Path) -> bool:
        """단일 파일에 대해 해시 검사 및 변환을 실행한다."""
        if not file_path.exists() or file_path.is_dir():
            return False

        if file_path.suffix.lower() not in self.supported_exts:
            return False

        # 파일 쓰기 완료 대기 (안정화)
        time.sleep(0.5)

        try:
            file_hash = calculate_file_hash(file_path)
        except Exception as e:
            logger.warning(f"파일 해시 계산 대기 중: {e}")
            return False

        # 중복 검사
        if self.manifest_mgr.is_duplicate(file_hash):
            logger.info(f"[건너뜀] 이미 변환된 파일입니다: {file_path.name}")
            return False

        doc_id = sanitize_doc_id(file_path.name)
        stat = file_path.stat()

        logger.info(f"[시작] 신규 파일 변환 시작: {file_path.name} (ID: {doc_id})")
        try:
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
            logger.info(f"[성공] 변환 완료 및 WikiDB 적재: {target_md.name}")
            return True
        except Exception as e:
            logger.error(f"[오류] 변환 실패 {file_path.name}: {e}")
            entry = DocumentEntry(
                id=doc_id,
                original_filename=file_path.name,
                source_path=str(file_path),
                file_hash=file_hash,
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                target_md_path="",
                assets_dir="",
                status="failed",
                title=file_path.stem,
                error_message=str(e)
            )
            self.manifest_mgr.add_or_update_document(entry)
            return False

    def scan_now(self) -> tuple[int, int]:
        """Source 폴더의 모든 파일을 검사하여 미등록 파일을 인제스트한다."""
        processed_count = 0
        skipped_count = 0
        for file_path in self.source_dir.glob("*.*"):
            if file_path.suffix.lower() in self.supported_exts:
                if self.process_file(file_path):
                    processed_count += 1
                else:
                    skipped_count += 1
        return processed_count, skipped_count

    def start(self) -> None:
        """백그라운드 디렉토리 감시기를 시작한다."""
        if self.observer is None:
            self.observer = Observer()
            handler = SourceFileHandler(self)
            self.observer.schedule(handler, str(self.source_dir), recursive=False)
            self.observer.start()
            logger.info(f"Source 폴더 실시간 감시 시작: {self.source_dir}")

    def stop(self) -> None:
        """백그라운드 감시기를 정지한다."""
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("Source 폴더 감시 종료")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingest_agent.py tests/test_ingest_agent.py
git commit -m "feat: implement IngestAgent with watchdog file watcher"
```

---

### Task 5: FastAPI 백엔드 REST API 및 파일 서빙 (`app/server.py`)

**Files:**
- Create: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `app.config`, `app.manifest`, `app.ingest_agent`
- Produces: `create_app() -> FastAPI`

- [ ] **Step 1: Write API endpoint tests**

```python
# tests/test_server.py
from fastapi.testclient import TestClient
from pathlib import Path
from app.config import Settings
from app.manifest import ManifestManager, DocumentEntry
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent
from app.server import create_app

def test_api_endpoints(tmp_path: Path):
    """문서 목록 조회 및 스캔 API 엔드포인트를 테스트한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json"
    )
    settings.ensure_directories()

    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocEngine(settings.docs_dir, settings.assets_dir)
    agent = IngestAgent(settings.source_dir, manifest_mgr, engine, settings.supported_extensions)
    
    app = create_app(settings, manifest_mgr, agent)
    client = TestClient(app)

    # 1. 초기 문서 목록 조회
    res = client.get("/api/documents")
    assert res.status_code == 200
    assert res.json() == []

    # 2. 문서 1건 추가 후 조회
    doc_md = settings.docs_dir / "sample.md"
    doc_md.write_text("# 본문 내용", encoding="utf-8")
    entry = DocumentEntry(
        id="sample",
        original_filename="sample.txt",
        source_path=str(settings.source_dir / "sample.txt"),
        file_hash="hash_123",
        file_size=100,
        modified_time=1700000000.0,
        target_md_path=str(doc_md),
        assets_dir=str(settings.assets_dir / "sample"),
        title="샘플"
    )
    manifest_mgr.add_or_update_document(entry)

    res = client.get("/api/documents")
    assert len(res.json()) == 1

    # 3. 마크다운 본문 조회
    res_doc = client.get("/api/documents/sample")
    assert res_doc.status_code == 200
    assert "# 본문 내용" in res_doc.json()["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'app.server')

- [ ] **Step 3: Write minimal implementation**

```python
# app/server.py
"""FastAPI 웹 서버 및 REST API 라우터."""

import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.manifest import ManifestManager, DocumentEntry
from app.ingest_agent import IngestAgent

class DocumentResponse(BaseModel):
    id: str
    original_filename: str
    file_size: int
    modified_time: float
    status: str
    ingested_at: str
    title: str
    error_message: Optional[str] = None

class DocumentDetailResponse(DocumentResponse):
    content: str

def create_app(
    settings: Optional[Settings] = None,
    manifest_mgr: Optional[ManifestManager] = None,
    agent: Optional[IngestAgent] = None
) -> FastAPI:
    """FastAPI 애플리케이션 인스턴스를 팩토리 패턴으로 생성한다."""
    if settings is None:
        settings = get_settings()
    if manifest_mgr is None:
        manifest_mgr = ManifestManager(settings.manifest_path)

    app = FastAPI(
        title="LLM Wiki Knowledge Ingestion Server",
        description="무삭제 문서 변환 및 지식 데이터베이스 서빙 API",
        version="1.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        """대시보드 메인 HTML을 반환한다."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>LLM Wiki Server is Running</h1>")

    @app.get("/api/documents", response_model=list[DocumentResponse])
    async def list_documents():
        """인제스트된 모든 문서 목록을 반환한다."""
        docs = manifest_mgr.get_all_documents()
        return sorted(docs, key=lambda d: d.ingested_at, reverse=True)

    @app.get("/api/documents/{doc_id}", response_model=DocumentDetailResponse)
    async def get_document_detail(doc_id: str):
        """특정 문서의 메타데이터와 마크다운 본문을 반환한다."""
        doc = manifest_mgr.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        md_path = Path(doc.target_md_path)
        content = ""
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8", errors="replace")

        return DocumentDetailResponse(
            id=doc.id,
            original_filename=doc.original_filename,
            file_size=doc.file_size,
            modified_time=doc.modified_time,
            status=doc.status,
            ingested_at=doc.ingested_at,
            title=doc.title,
            error_message=doc.error_message,
            content=content
        )

    @app.get("/api/assets/{doc_id}/{filename}")
    async def serve_asset(doc_id: str, filename: str):
        """추출된 이미지 및 도표 에셋 파일을 반환한다."""
        file_path = settings.assets_dir / doc_id / filename
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없습니다.")
        return FileResponse(file_path)

    @app.post("/api/scan")
    async def trigger_scan():
        """Source 폴더를 즉시 수동 스캔한다."""
        if agent is None:
            raise HTTPException(status_code=500, detail="인제스트 에이전트가 초기화되지 않았습니다.")
        processed, skipped = agent.scan_now()
        return {
            "message": "스캔 완료",
            "processed_count": processed,
            "skipped_count": skipped
        }

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        """웹 화면에서 Source 폴더로 직접 파일을 업로드한다."""
        target_path = settings.source_dir / file.filename
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 즉시 변환 처리
        if agent is not None:
            agent.process_file(target_path)

        return {"filename": file.filename, "message": "파일 업로드 및 처리 완료"}

    @app.get("/api/stats")
    async def get_stats():
        """저장소 및 문서 통계 요약을 반환한다."""
        docs = manifest_mgr.get_all_documents()
        completed = sum(1 for d in docs if d.status == "completed")
        failed = sum(1 for d in docs if d.status == "failed")
        return {
            "total_documents": len(docs),
            "completed_count": completed,
            "failed_count": failed,
            "source_dir": str(settings.source_dir),
            "wiki_db_dir": str(settings.wiki_db_dir)
        }

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: implement FastAPI endpoints and static routing"
```

---

### Task 6: 모바일/PC 반응형 모던 웹 대시보드 UI (`app/static/`)

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/style.css`
- Create: `app/static/app.js`

**Interfaces:**
- Consumes: `/api/documents`, `/api/documents/{id}`, `/api/scan`, `/api/upload`, `/api/stats`
- Produces: 모바일/PC 반응형 실시간 문서 뷰어, Markdown/Table/KaTeX/이미지 라이트박스 렌더링

- [ ] **Step 1: Create index.html with responsive layout, mobile navbar, sidebar, and viewer**
- [ ] **Step 2: Create style.css with clean typography, mobile touch styling, and table formatting**
- [ ] **Step 3: Create app.js with Marked.js parser, KaTeX math rendering, search filtering, and polling**
- [ ] **Step 4: Verify static file loading via FastAPI test**
- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/style.css app/static/app.js
git commit -m "feat: implement responsive mobile/desktop web dashboard"
```

---

### Task 7: 통합 실행기 (`run.py`) 및 전체 E2E 검증

**Files:**
- Create: `run.py`
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: `app.config`, `app.manifest`, `app.kordoc_engine`, `app.ingest_agent`, `app.server`
- Produces: `python run.py` 단일 명령어로 백그라운드 파일 감시 + 웹 서버 기동

- [ ] **Step 1: Write E2E integration test**
- [ ] **Step 2: Implement run.py**
- [ ] **Step 3: Run all pytest suites**
- [ ] **Step 4: Create sample document in Source/ and verify automatic conversion and WikiDB output**
- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_e2e.py
git commit -m "feat: create run.py entrypoint and verify end-to-end pipeline"
```
