"""E2E 전체 파이프라인 통합 테스트."""

import time
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import Settings
from app.manifest import ManifestManager
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent
from app.server import create_app

def test_full_ingestion_and_api_workflow(tmp_path: Path):
    """Source 파일 투입 -> 감시/변환 -> WikiDB 적재 -> 웹 API 및 프론트 서빙 전체 워크플로우를 테스트한다."""
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

    # 1. 초기 상태 확인
    res_init = client.get("/api/documents")
    assert res_init.json() == []

    # 2. Source 폴더에 다양한 문서 투입
    file1 = settings.source_dir / "2026_strategy.md"
    file1.write_text("# 2026 전략 기획서\n\n## 1. 개요\nLLM Wiki 지식 허브 구축 계획입니다.", encoding="utf-8")

    file2 = settings.source_dir / "financial_data.txt"
    file2.write_text("재무 분석 보고서\n\n| 분기 | 매출(억) |\n|---|---|\n| 1Q | 120 |\n| 2Q | 150 |", encoding="utf-8")

    # 3. 인제스트 에이전트 스캔 실행
    proc, skip = agent.scan_now()
    assert proc == 2
    assert skip == 0

    # 4. WikiDB 결과물 검증
    all_docs = client.get("/api/documents").json()
    assert len(all_docs) == 2
    
    doc_ids = [d["id"] for d in all_docs]
    titles = [d["title"] for d in all_docs]
    assert "2026_strategy" in titles
    assert "financial_data" in titles

    # 5. 개별 문서 상세 내용 검증
    doc1_detail = client.get(f"/api/documents/{doc_ids[0]}").json()
    assert "100% 무삭제 완본" in doc1_detail["content"]
    assert "SHA-256" in doc1_detail["content"]

    # 6. 동일 파일 재투입 시 중복 방지 검증
    proc2, skip2 = agent.scan_now()
    assert proc2 == 0
    assert skip2 == 2
    assert len(client.get("/api/documents").json()) == 2
