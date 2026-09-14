"""실시간 파일 감시 및 자동 인제스트 에이전트 단위 테스트."""

import time
import pytest
from pathlib import Path
from app.manifest import ManifestManager
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent

def test_ingest_agent_scan(tmp_path: Path):
    """Source 디렉토리 스캔 시 신규 파일이 WikiDB에 정상 등록되고 중복 시 스킵되는지 테스트한다."""
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

    # 1. 신규 파일 투입
    doc_file = source_dir / "notice.md"
    doc_file.write_text("## 긴급 공지사항\n\n중요 내용입니다.", encoding="utf-8")

    # 수동 스캔 실행
    processed_count, skipped_count = agent.scan_now()
    assert processed_count == 1
    assert skipped_count == 0

    docs = manifest_mgr.get_all_documents()
    assert len(docs) == 1
    assert docs[0].original_filename == "notice.md"
    assert docs[0].status == "completed"

    # 2. 동일 파일 재스캔 시 중복 스킵 확인
    processed_count2, skipped_count2 = agent.scan_now()
    assert processed_count2 == 0
    assert skipped_count2 == 1

def test_ingest_agent_file_modification(tmp_path: Path):
    """내용이 수정된 파일은 새로운 해시로 정상 갱신 인제스트되는지 테스트한다."""
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

    doc_file = source_dir / "report.txt"
    doc_file.write_text("버전 1 내용", encoding="utf-8")
    assert agent.process_file(doc_file) is True

    # 내용 변경
    doc_file.write_text("버전 2 수정된 내용", encoding="utf-8")
    assert agent.process_file(doc_file) is True

    docs = manifest_mgr.get_all_documents()
    assert len(docs) == 2  # 두 버전이 각각 기록됨


def test_sanitize_doc_id_uniqueness():
    """동일한 파일명으로 연속 호출 시에도 UUID 결합으로 고유한 doc_id가 생성되는지 검증한다."""
    from app.ingest_agent import sanitize_doc_id

    ids = [sanitize_doc_id("공문서_2026.pdf") for _ in range(100)]
    assert len(set(ids)) == 100  # 100개 모두 중복 없이 고유함


def test_ingest_agent_concurrency_lock(tmp_path: Path):
    """동일한 파일에 대해 동시에 process_file이 호출될 때 상호 배제(Lock)되어 1회만 처리되는지 검증한다."""
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

    doc_file = source_dir / "parallel_test.txt"
    doc_file.write_text("동시성 테스트 내용", encoding="utf-8")

    # 인위적으로 processing_files에 등록된 상태를 모사
    with agent._lock:
        agent._processing_files.add(doc_file.resolve())

    # 이미 처리 중인 파일은 즉시 False 반환 (중복 처리 방지)
    result = agent.process_file(doc_file, debounce=0.0)
    assert result is False

    # 락 해제 후에는 정상 처리 가능
    with agent._lock:
        agent._processing_files.discard(doc_file.resolve())

    result_after = agent.process_file(doc_file, debounce=0.0)
    assert result_after is True


def test_process_file_except_does_not_raise_name_error(tmp_path):
    """is_duplicate 호출 중 예외가 발생해도 NameError 없이 False를 반환해야 한다."""
    from app.ingest_agent import IngestAgent
    from app.manifest import ManifestManager
    from unittest.mock import MagicMock

    src = tmp_path / "test.pdf"
    src.write_bytes(b"%PDF-1.4 test content here for hashing purposes only")

    manifest_mgr = MagicMock(spec=ManifestManager)
    manifest_mgr.is_duplicate.side_effect = RuntimeError("DB 오류 시뮬레이션")

    engine = MagicMock()
    engine.assets_dir = tmp_path / "assets"

    agent = IngestAgent(
        source_dir=tmp_path,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts={".pdf"}
    )

    result = agent.process_file(src, debounce=0.0)
    assert result is False

