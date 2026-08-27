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
