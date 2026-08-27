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
