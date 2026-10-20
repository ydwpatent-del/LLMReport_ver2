"""FastAPI 백엔드 REST API 단위 테스트."""

import os
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.config import Settings
from app.manifest import ManifestManager, DocumentEntry
from app.kordoc_engine import KordocEngine
from app.ingest_agent import IngestAgent
from app.server import create_app


@pytest.fixture(autouse=True)
def clean_env_pin(monkeypatch):
    """단위 테스트 실행 시 .env의 WIKI_ACCESS_PIN이 기본 활성화되어 401이 발생하는 것을 방지한다."""
    monkeypatch.delenv("WIKI_ACCESS_PIN", raising=False)


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

    # 7. 루트 HTML 및 정적 파일 라우팅 검증
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "LLM Wiki" in res_root.text
    assert "docListContainer" in res_root.text


def test_upload_path_traversal_prevention(tmp_path: Path):
    """파일 업로드 시 경로 순회(Path Traversal) 공격이 차단되고 안전하게 파일명만 남는지 검증한다."""
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

    # 1. 경로 순회 시도 (../../evil.txt) -> Source 폴더 내 evil.txt로만 안전 저장되어야 함
    file_content = b"malicious content"
    files = {"file": ("../../evil.txt", file_content, "text/plain")}
    res = client.post("/api/upload", files=files)
    assert res.status_code == 200
    assert res.json()["filename"] == "evil.txt"
    assert (settings.source_dir / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()  # 상위 디렉터리에 생성되지 않음

    # 2. 빈 파일명 또는 점(.)으로 시작하는 숨김 파일 거부 (400)
    files_invalid = {"file": (".hidden", file_content, "text/plain")}
    res_inv = client.post("/api/upload", files=files_invalid)
    assert res_inv.status_code == 400


def test_serve_asset_path_traversal_prevention(tmp_path: Path):
    """에셋 서빙 시 assets_dir 외부 경로 순회 접근 시도가 404 또는 403으로 차단되는지 검증한다."""
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

    # assets 디렉터리 외부의 파일 접근 시도
    res = client.get("/api/assets/doc1/../../secret.txt")
    assert res.status_code in (403, 404)


def test_server_reconcile_and_detail_self_healing(tmp_path: Path):
    """서버의 자가 치유 엔드포인트 및 상세 조회 시 자동 복구를 검증한다."""
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

    # 1. Manifest에 깨진 target_md_path 등록
    broken_entry = DocumentEntry(
        id="broken_doc_id",
        original_filename="ai_report.pdf",
        source_path=str(settings.source_dir / "ai_report.pdf"),
        file_hash="hash_ai_123",
        file_size=5000,
        modified_time=1700000000.0,
        target_md_path=str(settings.docs_dir / "wrong_path.md"),
        assets_dir=str(settings.assets_dir / "broken_doc_id"),
        status="completed",
        title="AI 리포트"
    )
    manifest_mgr.add_or_update_document(broken_entry)

    # 2. 디스크 상에는 유효한 최신 완본 마크다운이 존재
    real_md = settings.docs_dir / "ai_report_1788999999_xyz12345.md"
    real_md.write_text("# AI 리포트\n\n완본 텍스트 및 도표", encoding="utf-8")

    app = create_app(settings, manifest_mgr, agent)
    client = TestClient(app)

    # 3. 상세 조회 시 자가 치유로 본문 정상 반환
    res_detail = client.get("/api/documents/broken_doc_id")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert "# AI 리포트" in detail["content"]
    assert "완본 텍스트 및 도표" in detail["content"]

    # 4. /api/reconcile 엔드포인트 호출 검증
    res_rec = client.post("/api/reconcile")
    assert res_rec.status_code == 200
    assert "자가 치유" in res_rec.json()["message"]


def test_audit_and_heal_endpoints(tmp_path: Path):
    """개별 문서에 대한 /api/documents/{doc_id}/audit 및 /heal 엔드포인트를 검증한다."""
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

    # 1. 서식 결함(이중 불릿 및 들여쓰기 누락)이 있는 문서 생성
    doc_md = settings.docs_dir / "audit_target.md"
    doc_md.write_text(
        "> - **원본 파일명**: `sample_report.txt`\n"
        "> - **발행기관**: 미상 (원문 기재)\n"
        "> - **원본형식**: `TXT`\n"
        "> - **무결성 해시 (SHA-256)**: `hash_audit_999`\n"
        "> - **데이터 보존 원칙**: 100% 무삭제 완본\n"
        "---\n\n"
        "### 1. 개요\n\n"
        "□ 대항목 내용\n"
        "- ○ 중항목 내용\n"
        "- - 소항목 내용\n",
        encoding="utf-8"
    )

    entry = DocumentEntry(
        id="audit_target",
        original_filename="sample_report.txt",
        source_path=str(settings.source_dir / "sample_report.txt"),
        file_hash="hash_audit_999",
        file_size=256,
        modified_time=1700000000.0,
        target_md_path=str(doc_md),
        assets_dir=str(settings.assets_dir / "audit_target"),
        title="감사 대상 문서"
    )
    manifest_mgr.add_or_update_document(entry)

    app = create_app(settings, manifest_mgr, agent)
    client = TestClient(app)

    # 2. 품질 검수(Audit) 엔드포인트 호출 (Dry-Run)
    res_audit = client.post("/api/documents/audit_target/audit")
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert audit_data["doc_id"] == "audit_target"
    # 이중 불릿(- ○) 결함으로 인해 is_healthy=False
    assert audit_data["is_healthy"] is False
    assert any("이중 불릿" in f for f in audit_data["red_flags"])

    # 3. 자율 치유(Heal) 엔드포인트 호출
    res_heal = client.post("/api/documents/audit_target/heal")
    assert res_heal.status_code == 200
    heal_data = res_heal.json()
    assert heal_data["success"] is True
    assert "Tier 1" in heal_data["message"]
    # 치유된 본문 검증: '- ○' 이중 불릿 제거되고 하드 브레이크 공백 적용
    content = heal_data["document"]["content"]
    assert "- ○" not in content
    assert "  ○ 중항목 내용" in content

    # 4. 치유 후 재검수 시 100% 합격 검증
    res_re_audit = client.post("/api/documents/audit_target/audit")
    assert res_re_audit.status_code == 200
    re_audit_data = res_re_audit.json()
    assert re_audit_data["is_healthy"] is True
    assert len(re_audit_data["red_flags"]) == 0


def test_security_headers_and_https_cookie(tmp_path: Path):
    """표준 웹 보안 헤더(MIME 스니핑 방지, 클릭재킹 방지) 및 HTTPS 환경 Secure 쿠키를 검증한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        wiki_access_pin="999888"
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings, manifest_mgr)
    client = TestClient(app)

    # 1. 루트 요청 시 보안 헤더 검증
    res = client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    # 2. HTTPS 프록시 환경에서 PIN 로그인 시 Secure 플래그 검증
    login_res = client.post(
        "/api/auth/login",
        json={"pin": "999888"},
        headers={"x-forwarded-proto": "https"}
    )
    assert login_res.status_code == 200
    set_cookie = login_res.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie


def test_pin_brute_force_lockout(tmp_path: Path):
    """PIN 연속 5회 오류 시 6번째 시도부터 429 Too Many Requests로 차단되는지 검증한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        wiki_access_pin="123456"
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings, manifest_mgr)
    client = TestClient(app)

    # 1. 5회 연속 틀린 PIN 전송 -> 401 반환
    for i in range(1, 6):
        res = client.post("/api/auth/login", json={"pin": f"wrong_{i}"})
        assert res.status_code == 401
        detail = res.json()["detail"]
        assert "일치하지 않습니다" in detail or "차단됩니다" in detail

    # 2. 6번째 시도 -> 429 Too Many Requests로 차단
    res_blocked = client.post("/api/auth/login", json={"pin": "wrong_6"})
    assert res_blocked.status_code == 429
    assert "접근이 잠겼습니다" in res_blocked.json()["detail"]

    # 3. 차단 상태에서는 올바른 PIN을 넣어도 429로 거부
    res_blocked_valid = client.post("/api/auth/login", json={"pin": "123456"})
    assert res_blocked_valid.status_code == 429


def test_cloud_mode_protections(tmp_path: Path):
    """클라우드 모드(gdrive)에서 원본 문서 삭제 및 직접 업로드가 차단되는지 검증한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        storage_mode="gdrive",
        wiki_access_pin=None
    )

    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings, manifest_mgr)
    client = TestClient(app)

    # 1. 클라우드 모드에서 원본 문서 삭제 시도 -> 403 Forbidden
    res_del = client.delete("/api/documents/doc_original_001")
    assert res_del.status_code == 403
    assert "클라우드(웹) 모드에서는 원본 지식 DB 문서를 삭제할 수 없습니다" in res_del.json()["detail"]

    # 2. 클라우드 모드에서 직접 파일 업로드 시도 -> 403 Forbidden
    files = {"file": ("test.pdf", b"%PDF fake", "application/pdf")}
    res_up = client.post("/api/upload", files=files)
    assert res_up.status_code == 403
    assert "직접 파일 업로드가 비활성화되어 있습니다" in res_up.json()["detail"]

    # 3. 로컬 모드로 전환 시 미지원 확장자(.exe) 차단 검증
    settings_local = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        storage_mode="local"
    )
    app_local = create_app(settings_local, manifest_mgr)
    client_local = TestClient(app_local)

    res_exe = client_local.post("/api/upload", files={"file": ("malware.exe", b"MZ fake", "application/octet-stream")})
    assert res_exe.status_code == 400
    assert "지원되지 않는 파일 형식" in res_exe.json()["detail"]


def test_pwa_endpoints_and_pin_bypass(tmp_path: Path):
    """PWA 필수 엔드포인트(매니페스트, 서비스 워커, 파비콘) 서빙 및 PIN 인증 면제 동작을 검증한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        storage_mode="local",
        wiki_access_pin="123456"
    )
    settings.ensure_directories()
    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings, manifest_mgr)
    client = TestClient(app)

    # 1. PIN 잠금 상태에서 보호된 API는 401 Unauthorized
    res_api = client.get("/api/documents")
    assert res_api.status_code == 401

    # 2. PWA 필수 파일은 PIN 미인증 상태에서도 200 OK 반환
    res_manifest = client.get("/manifest.webmanifest")
    assert res_manifest.status_code == 200
    assert "application/manifest+json" in res_manifest.headers["content-type"]

    res_sw = client.get("/service-worker.js")
    assert res_sw.status_code == 200
    assert "application/javascript" in res_sw.headers["content-type"]
    assert res_sw.headers.get("Service-Worker-Allowed") == "/"

    res_favicon = client.get("/favicon.ico")
    assert res_favicon.status_code == 200
    assert "image/png" in res_favicon.headers["content-type"]




