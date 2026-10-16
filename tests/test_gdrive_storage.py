"""클라우드/Google Drive 하이브리드 스토리지, 온디맨드 이미지 캐싱 및 선택적 PIN 보안 단위/통합 테스트."""

import json
from pathlib import Path
from fastapi.testclient import TestClient

from app.config import Settings
from app.gdrive_storage import GDriveStorageManager, BUNDLE_FILENAME, ASSETS_MAP_FILENAME
from app.html_doc_exporter import HtmlDocExporter
from app.manifest import ManifestManager, DocumentEntry
from app.server import create_app
from app.topic_generator import TopicReportGenerator


class FakeDriveRequest:
    """테스트용 Google Drive API 요청 래퍼."""

    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeDriveFilesResource:
    """메모리 기반 Mock Google Drive files() 리소스."""

    def __init__(self, remote_store: dict[str, bytes], file_index: dict[str, dict]):
        self.remote_store = remote_store
        self.file_index = file_index
        self._counter = 100

    def list(self, q: str = "", spaces: str = "drive", fields: str = "", pageSize: int = 10):
        matched = []
        for fid, meta in self.file_index.items():
            name_cond = f"name = '{meta['name']}'" in q
            parent_cond = f"'{meta['parent_id']}'" in q
            if name_cond and parent_cond:
                matched.append({"id": fid, "name": meta["name"], "modifiedTime": "2026-10-16T00:00:00Z"})
            elif parent_cond and "name =" not in q:
                matched.append({"id": fid, "name": meta["name"], "modifiedTime": "2026-10-16T00:00:00Z"})
        return FakeDriveRequest({"files": matched})

    def get_media(self, fileId: str):
        return FakeDriveRequest(self.remote_store.get(fileId, b""))

    def create(self, body: dict, media_body=None, fields: str = "id"):
        self._counter += 1
        new_id = f"gdrive_id_{self._counter}"
        parent_id = (body.get("parents") or ["root"])[0]
        self.file_index[new_id] = {
            "name": body["name"],
            "parent_id": parent_id,
            "mimeType": body.get("mimeType", "application/octet-stream"),
        }
        return FakeDriveRequest({"id": new_id})

    def update(self, fileId: str, media_body=None, fields: str = "id"):
        return FakeDriveRequest({"id": fileId})

    def delete(self, fileId: str):
        self.file_index.pop(fileId, None)
        self.remote_store.pop(fileId, None)
        return FakeDriveRequest({})


class FakeDriveService:
    """메모리 기반 Mock Google Drive v3 서비스."""

    def __init__(self, remote_store: dict[str, bytes], file_index: dict[str, dict]):
        self._files = FakeDriveFilesResource(remote_store, file_index)

    def files(self):
        return self._files


def test_text_bundle_pack_and_extract(tmp_path: Path):
    """manifest.json, docs/*.md, reports/*.md, assets_map.json이 단일 번들로 압축 및 무손실 복원되는지 검증한다."""
    src_wiki = tmp_path / "src_wiki"
    (src_wiki / "docs").mkdir(parents=True)
    (src_wiki / "reports").mkdir(parents=True)

    (src_wiki / "manifest.json").write_text('{"version":"1.0.0","documents":{}}', encoding="utf-8")
    (src_wiki / ASSETS_MAP_FILENAME).write_text('{"doc1/chart.png":"fid_123"}', encoding="utf-8")
    (src_wiki / "docs" / "doc1.md").write_text("# 문서 1 본문\n내용입니다.", encoding="utf-8")
    (src_wiki / "reports" / "REPORT_반도체_100.md").write_text("# 반도체 종합 보고서", encoding="utf-8")

    # 1. 번들 생성
    bundle_info = GDriveStorageManager.create_text_bundle(src_wiki)
    bundle_path = Path(bundle_info["bundle_path"])
    assert bundle_path.exists()
    assert bundle_info["docs_count"] == 1
    assert bundle_info["reports_count"] == 1

    # 2. 빈 클라우드 컨테이너 WikiDB 디렉토리에 번들 압축 해제
    dst_wiki = tmp_path / "cloud_wiki"
    ext_info = GDriveStorageManager.extract_text_bundle(bundle_path, dst_wiki)
    assert ext_info["docs_count"] == 1
    assert ext_info["reports_count"] == 1
    assert (dst_wiki / "manifest.json").exists()
    assert (dst_wiki / ASSETS_MAP_FILENAME).exists()
    assert (dst_wiki / "docs" / "doc1.md").read_text(encoding="utf-8").startswith("# 문서 1 본문")
    assert (dst_wiki / "reports" / "REPORT_반도체_100.md").exists()


def test_mirror_dir_bidirectional_sync(tmp_path: Path):
    """인증 없이 로컬 Google Drive 데스크톱 폴더(mirror_dir)와 양방향 보고서 및 에셋 동기화가 작동하는지 검증한다."""
    local_wiki = tmp_path / "local_wiki"
    mirror_dir = tmp_path / "gdrive_mirror"
    (local_wiki / "docs").mkdir(parents=True)
    (local_wiki / "reports").mkdir(parents=True)
    (local_wiki / "assets" / "doc_a").mkdir(parents=True)

    (local_wiki / "docs" / "doc_a.md").write_text("# A 문서", encoding="utf-8")
    (local_wiki / "assets" / "doc_a" / "fig1.png").write_bytes(b"PNG_DATA_1")

    # 스마트폰(클라우드)에서 생성되어 미러 폴더에 저장된 신규 보고서 시뮬레이션
    (mirror_dir / "reports").mkdir(parents=True)
    (mirror_dir / "reports" / "REPORT_모바일생성_999.md").write_text("# 모바일에서 만든 보고서", encoding="utf-8")

    settings = Settings(wiki_db_dir=local_wiki, gdrive_local_mirror_dir=mirror_dir)
    storage = GDriveStorageManager(settings=settings)
    res = storage.sync_with_mirror_dir(local_wiki, mirror_dir)

    assert res["pulled_reports"] == 1
    assert (local_wiki / "reports" / "REPORT_모바일생성_999.md").exists()
    assert (mirror_dir / BUNDLE_FILENAME).exists()
    assert (mirror_dir / "assets" / "doc_a" / "fig1.png").read_bytes() == b"PNG_DATA_1"


def test_on_demand_asset_serving_and_html_embedding(tmp_path: Path):
    """로컬 assets 폴더가 비어 있는 클라우드 서버에서 이미지 요청 및 HTML 내보내기 시
    Google Drive에서 온디맨드로 이미지를 내려받아 캐싱 및 Base64 임베딩하는지 검증한다.
    """
    wiki_db = tmp_path / "WikiDB"
    docs_dir = wiki_db / "docs"
    assets_dir = wiki_db / "assets"
    reports_dir = wiki_db / "reports"
    docs_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # 1x1 PNG 바이너리
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
        b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    # assets_map.json 설정 (로컬 assets/sample_doc/chart_01.png 파일은 없는 상태)
    (wiki_db / ASSETS_MAP_FILENAME).write_text(
        json.dumps({"sample_doc/chart_01.png": "remote_img_001"}),
        encoding="utf-8",
    )

    remote_store = {"remote_img_001": png_bytes}
    file_index = {
        "remote_img_001": {"name": "chart_01.png", "parent_id": "folder_sample_doc", "mimeType": "image/png"}
    }
    fake_service = FakeDriveService(remote_store, file_index)

    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=wiki_db,
        docs_dir=docs_dir,
        assets_dir=assets_dir,
        reports_dir=reports_dir,
        manifest_path=wiki_db / "manifest.json",
        storage_mode="gdrive",
        gdrive_folder_id="root_folder_123",
    )
    settings.ensure_directories()

    storage = GDriveStorageManager(settings=settings, drive_client_factory=lambda: fake_service)
    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings=settings, manifest_mgr=manifest_mgr, agent=None, gdrive_storage=storage)
    client = TestClient(app)

    # 1. 초기에는 로컬 디스크에 이미지가 없음
    expected_local_file = assets_dir / "sample_doc" / "chart_01.png"
    assert not expected_local_file.exists()

    # 2. 스마트폰에서 /api/assets/sample_doc/chart_01.png 요청 시 온디맨드 다운로드 및 서빙
    res = client.get("/api/assets/sample_doc/chart_01.png")
    assert res.status_code == 200
    assert res.content == png_bytes
    assert expected_local_file.exists()

    # 3. 다른 이미지(remote_img_002)에 대해 HtmlDocExporter가 온디맨드 페치 후 Base64 임베딩하는지 검증
    (wiki_db / ASSETS_MAP_FILENAME).write_text(
        json.dumps({"sample_doc/chart_02.png": "remote_img_002"}),
        encoding="utf-8",
    )
    remote_store["remote_img_002"] = png_bytes
    storage._assets_map_cache = None

    exporter = HtmlDocExporter(assets_dir=assets_dir)
    exporter.gdrive_storage = storage
    md_text = "# 테스트 보고서\n\n![도표2](/api/assets/sample_doc/chart_02.png)\n"
    html_out = exporter.export_html(md_text, title="클라우드 내보내기", embed_images=True)

    assert "data:image/png;base64," in html_out
    assert (assets_dir / "sample_doc" / "chart_02.png").exists()


def test_optional_pin_security_middleware(tmp_path: Path):
    """WIKI_ACCESS_PIN 설정 시 미인증 요청이 차단되고 로그인 후 정상 접근되는지 검증한다."""
    settings = Settings(
        base_dir=tmp_path,
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path / "WikiDB",
        docs_dir=tmp_path / "WikiDB" / "docs",
        assets_dir=tmp_path / "WikiDB" / "assets",
        reports_dir=tmp_path / "WikiDB" / "reports",
        manifest_path=tmp_path / "WikiDB" / "manifest.json",
        wiki_access_pin="7788",
    )
    settings.ensure_directories()

    manifest_mgr = ManifestManager(settings.manifest_path)
    app = create_app(settings=settings, manifest_mgr=manifest_mgr, agent=None)
    client = TestClient(app)

    # 1. 미인증 상태에서 API 호출 시 401 반환
    res_unauth_api = client.get("/api/documents")
    assert res_unauth_api.status_code == 401

    # 2. 미인증 상태에서 메인 페이지 접속 시 PIN 입력 화면(401) 반환
    res_unauth_root = client.get("/")
    assert res_unauth_root.status_code == 401
    assert "LLM Wiki 보안 잠금" in res_unauth_root.text

    # 3. 잘못된 PIN 로그인 시도 시 401
    res_bad = client.post("/api/auth/login", json={"pin": "0000"})
    assert res_bad.status_code == 401

    # 4. 올바른 PIN 로그인 시 쿠키 발급 및 이후 API 정상 호출(200)
    res_ok = client.post("/api/auth/login", json={"pin": "7788"})
    assert res_ok.status_code == 200
    assert "wiki_auth_token" in res_ok.cookies

    res_docs = client.get("/api/documents")
    assert res_docs.status_code == 200


def test_report_remote_backup_and_delete_hooks(tmp_path: Path):
    """TopicReportGenerator가 보고서 저장 및 삭제 시 Google Drive 원격 백업/삭제를 호출하는지 검증한다."""
    wiki_db = tmp_path / "WikiDB"
    mirror_dir = tmp_path / "gdrive_mirror"
    reports_dir = wiki_db / "reports"
    reports_dir.mkdir(parents=True)
    mirror_dir.mkdir(parents=True)

    settings = Settings(
        wiki_db_dir=wiki_db,
        reports_dir=reports_dir,
        storage_mode="gdrive",
        gdrive_local_mirror_dir=mirror_dir,
    )
    storage = GDriveStorageManager(settings=settings)

    gen = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")
    gen.gdrive_storage = storage

    saved = gen.save_report(
        topic="양자암호통신",
        markdown="# 양자암호통신 종합 기술 및 시장 분석 보고서\n\n## 1. 기술 개요\n본문",
        sources=[],
    )
    report_id = saved["id"]
    mirror_report_file = mirror_dir / "reports" / f"{report_id}.md"

    # 저장 시 미러 폴더(Google Drive)에 즉시 백업되었는지 확인
    assert mirror_report_file.exists()

    # 삭제 시 미러 폴더에서도 함께 삭제되는지 확인
    deleted = gen.delete_report(report_id)
    assert deleted is True
    assert not mirror_report_file.exists()
