"""FastAPI 백엔드 REST API 단위 테스트."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.config import Settings
from app.manifest import ManifestManager, DocumentEntry
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent
from app.server import create_app

def test_api_endpoints(tmp_path: Path):
    """문서 목록 조회, 상세 조회, 스캔, 통계 API 엔드포인트를 종합 검증한다."""
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

    # 2. 문서 1건 추가 후 목록 조회
    doc_md = settings.docs_dir / "sample.md"
    doc_md.write_text("# 본문 내용\n\n- 항목 1", encoding="utf-8")
    entry = DocumentEntry(
        id="sample_doc",
        original_filename="sample.txt",
        source_path=str(settings.source_dir / "sample.txt"),
        file_hash="hash_12345",
        file_size=128,
        modified_time=1700000000.0,
        target_md_path=str(doc_md),
        assets_dir=str(settings.assets_dir / "sample_doc"),
        title="샘플 문서 제목"
    )
    manifest_mgr.add_or_update_document(entry)

    res = client.get("/api/documents")
    assert res.status_code == 200
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["id"] == "sample_doc"
    assert docs[0]["title"] == "샘플 문서 제목"

    # 3. 상세 및 마크다운 본문 조회
    res_doc = client.get("/api/documents/sample_doc")
    assert res_doc.status_code == 200
    detail = res_doc.json()
    assert detail["title"] == "샘플 문서 제목"
    assert "# 본문 내용" in detail["content"]

    # 4. 통계 조회
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_documents"] == 1
    assert stats["completed_count"] == 1

    # 5. 수동 스캔 트리거
    res_scan = client.post("/api/scan")
    assert res_scan.status_code == 200
    assert "processed_count" in res_scan.json()

    # 6. 문서 및 에셋 삭제 API 검증 (DELETE)
    # 에셋 디렉터리 및 임시 이미지 생성
    asset_dir = settings.assets_dir / "sample_doc"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "image_001.png").write_bytes(b"fake_image_bytes")

    assert doc_md.exists()
    assert asset_dir.exists()

    res_del = client.delete("/api/documents/sample_doc")
    assert res_del.status_code == 200
    del_data = res_del.json()
    assert del_data["deleted_id"] == "sample_doc"

    # 삭제 후 파일 및 에셋, manifest 부재 검증
    assert not doc_md.exists()
    assert not asset_dir.exists()
    assert manifest_mgr.get_document("sample_doc") is None

    # 재조회 시 목록 0건
    res_after = client.get("/api/documents")
    assert len(res_after.json()) == 0

    # 6. 루트 HTML 및 정적 파일 라우팅 검증
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "LLM Wiki" in res_root.text
    assert "docListContainer" in res_root.text
