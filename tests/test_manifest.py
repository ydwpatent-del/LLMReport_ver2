"""SHA-256 해시 계산 및 매니페스트 중복 방지 테스트."""

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
    assert len(manager.get_all_documents()) == 1

def test_manifest_persistence(tmp_path: Path):
    """Manifest 파일이 디스크에 정상 저장되고 재로드되는지 검증한다."""
    manifest_file = tmp_path / "manifest.json"
    manager = ManifestManager(manifest_file)
    
    doc = DocumentEntry(
        id="doc_persist",
        original_filename="persist.docx",
        source_path="Source/persist.docx",
        file_hash="persist_hash_456",
        file_size=2048,
        modified_time=1700000001.0,
        target_md_path="WikiDB/docs/doc_persist.md",
        assets_dir="WikiDB/assets/doc_persist",
        status="completed",
        title="영속성 테스트"
    )
    manager.add_or_update_document(doc)
    
    # 새 인스턴스로 로드
    manager2 = ManifestManager(manifest_file)
    loaded_doc = manager2.get_document("doc_persist")
    assert loaded_doc is not None
    assert loaded_doc.title == "영속성 테스트"
    assert loaded_doc.file_hash == "persist_hash_456"

def test_cleanup_zombie_processing(tmp_path: Path):
    """오래된 processing 상태의 좀비 문서가 failed로 안전 전환되는지 검증한다."""
    manifest_file = tmp_path / "manifest.json"
    manager = ManifestManager(manifest_file)
    
    # 과거 날짜의 processing 문서 등록
    doc = DocumentEntry(
        id="zombie_doc",
        original_filename="stuck.pdf",
        source_path="Source/stuck.pdf",
        file_hash="zombie_hash",
        file_size=1024,
        modified_time=1700000000.0,
        target_md_path="",
        assets_dir="",
        status="processing",
        ingested_at="2020-01-01T00:00:00+00:00",
        title="고착된 문서"
    )
    manager.add_or_update_document(doc)
    
    cleaned = manager.cleanup_zombie_processing(timeout_seconds=60)
    assert cleaned == 1
    
    updated = manager.get_document("zombie_doc")
    assert updated.status == "failed"
    assert "처리 시간 초과" in updated.error_message
    # failed 상태이므로 중복 검사에서 통과(새로 처리 가능)
    assert manager.is_duplicate("zombie_hash") is False

def test_reconcile_with_disk(tmp_path: Path):
    """디스크 상의 마크다운 파일과 Manifest 불일치 시 자가 치유(Self-Healing)되는지 검증한다."""
    manifest_file = tmp_path / "manifest.json"
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    docs_dir.mkdir()
    assets_dir.mkdir()
    
    manager = ManifestManager(manifest_file)
    
    # 1. Manifest에는 잘못된(구버전) target_md_path가 적혀 있음
    broken_doc = DocumentEntry(
        id="sample_doc_old_id",
        original_filename="sample_doc.pdf",
        source_path="Source/sample_doc.pdf",
        file_hash="sample_hash",
        file_size=2048,
        modified_time=1700000000.0,
        target_md_path=str(docs_dir / "non_existent.md"),
        assets_dir=str(assets_dir / "sample_doc_old_id"),
        status="completed",
        title="샘플 문서"
    )
    manager.add_or_update_document(broken_doc)
    
    # 2. 디스크에는 실제 유효 완본 파일이 존재함
    real_md = docs_dir / "sample_doc_1788000000_abcd1234.md"
    real_md.write_text("# 샘플 문서\n\n완본 본문 내용입니다.", encoding="utf-8")
    
    # 3. 자가 치유 실행
    res = manager.reconcile_with_disk(docs_dir, assets_dir)
    assert res["reconciled"] >= 1
    
    # 4. 검증: target_md_path가 실존 파일로 갱신되고 ID도 일치화됨
    healed = manager.get_document("sample_doc_1788000000_abcd1234")
    assert healed is not None
    assert healed.target_md_path == str(real_md.resolve())
    assert healed.status == "completed"

def test_get_all_documents_deduplicates_alias_entries(tmp_path: Path):
    """alias 항목이 등록되어도 get_all_documents는 고유 파일당 1건만 반환해야 한다."""
    manifest_file = tmp_path / "manifest.json"
    mgr = ManifestManager(manifest_file)
    base = DocumentEntry(
        id="old_id", original_filename="report.pdf", source_path="/src/report.pdf",
        file_hash="a" * 64, file_size=1000, modified_time=1000.0,
        target_md_path="/docs/old_id.md", assets_dir="/assets/old_id",
        status="completed", title="보고서"
    )
    alias = base.model_copy()
    alias.id = "new_id"
    alias.target_md_path = "/docs/new_id_longer_path.md"

    mgr.add_or_update_document(base)
    mgr.add_or_update_document(alias)

    docs = mgr.get_all_documents()
    completed = [d for d in docs if d.status == "completed" and d.file_hash == base.file_hash]
    assert len(completed) == 1, f"alias 중복 포함됨: {[d.id for d in completed]}"
    assert completed[0].id == "new_id"


def test_touch_processing_prevents_zombie_timeout(tmp_path: Path):
    """대형 문서 처리 중 touch_processing 호출 시 ingested_at이 갱신되어 좀비 판정 및 중복 재파싱이 방지되는지 검증한다."""
    manifest_file = tmp_path / "manifest.json"
    manager = ManifestManager(manifest_file)

    doc = DocumentEntry(
        id="large_doc_1",
        original_filename="large_report.pdf",
        source_path="Source/large_report.pdf",
        file_hash="large_hash_999",
        file_size=5000000,
        modified_time=1700000000.0,
        target_md_path="",
        assets_dir="",
        status="processing",
        ingested_at="2020-01-01T00:00:00+00:00",
        title="대형 보고서"
    )
    manager.add_or_update_document(doc)

    # 하트비트 갱신 전에는 600초 경과로 중복이 아닌 것(False)으로 판정됨
    assert manager.is_duplicate("large_hash_999") is False

    # 하트비트 갱신 실행
    manager.touch_processing("large_doc_1")

    # 하트비트 갱신 후에는 활성 processing 상태로 인정되어 중복 재시작(True)이 차단되고 좀비 정리에서도 제외됨
    assert manager.is_duplicate("large_hash_999") is True
    assert manager.cleanup_zombie_processing(timeout_seconds=600) == 0

