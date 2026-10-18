"""Google Drive 하이브리드 스토리지, 텍스트 번들 패키징 및 온디맨드 에셋 캐시 관리 모듈.

설계 원칙:
1. 로컬 PC 기본 모드(STORAGE_MODE=local)에서는 일절 개입하지 않아 기존 동작에 영향을 주지 않는다.
2. Google Drive 인증 정보가 아직 설정되지 않은 상태(Deferred Auth)에서도 예외를 발생시키지 않고
   안전하게 폴백(Graceful Fallback)한다.
3. 24MB 규모의 텍스트 데이터(manifest.json, docs/*.md, reports/*.md, assets_map.json)는
   단일 압축 번들(wiki_text_bundle.zip, 약 5MB)로 묶어 클라우드 서버 기동 시 1회 초고속 동기화하고,
   1.42GB 규모의 도표 이미지(assets/*/*)는 열람/내보내기 시점에 온디맨드(On-Demand)로 가져와 로컬 캐싱한다.
"""

import io
import json
import logging
import shutil
import threading
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.config import Settings, get_settings

logger = logging.getLogger("GDriveStorage")

BUNDLE_FILENAME = "wiki_text_bundle.zip"
ASSETS_MAP_FILENAME = "assets_map.json"


class GDriveStorageManager:
    """Google Drive API 및 로컬 미러 폴더 기반 하이브리드 스토리지 매니저."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        drive_client_factory: Optional[Callable[[], object]] = None,
    ):
        self.settings = settings or get_settings()
        self._drive_client_factory = drive_client_factory
        self._drive_service = None
        self._lock = threading.Lock()
        self._assets_map_cache: Optional[dict[str, str]] = None
        self._reports_folder_id_cache: Optional[str] = None

    @property
    def is_cloud_mode(self) -> bool:
        """현재 실행 모드가 클라우드/Google Drive 연동 모드인지 여부를 반환한다."""
        return (self.settings.storage_mode or "local").strip().lower() == "gdrive"

    @property
    def has_mirror_dir(self) -> bool:
        """로컬 Google Drive 데스크톱 마운트(미러) 폴더가 설정되어 있고 존재하는지 확인한다."""
        mirror = self.settings.gdrive_local_mirror_dir
        return bool(mirror and mirror.exists() and mirror.is_dir())

    @property
    def is_api_configured(self) -> bool:
        """Google Drive API 인증 정보와 대상 폴더 ID가 유효하게 설정되어 있는지 확인한다."""
        if self._drive_client_factory is not None:
            return True
        if not self.settings.gdrive_folder_id:
            return False
        if self.settings.gdrive_credentials_json:
            return True
        cred_path = self.settings.gdrive_credentials_path
        if cred_path and cred_path.exists() and cred_path.is_file():
            return True
        return False

    @property
    def is_configured(self) -> bool:
        """API 또는 로컬 미러 폴더 중 하나라도 연동 가능한 상태인지 반환한다."""
        return self.is_api_configured or self.has_mirror_dir

    def _get_drive_service(self):
        """Google Drive v3 API 서비스 객체를 지연 초기화하여 반환한다. 미설정 시 None 반환."""
        if self._drive_service is not None:
            return self._drive_service

        if self._drive_client_factory is not None:
            self._drive_service = self._drive_client_factory()
            return self._drive_service

        if not self.is_api_configured:
            return None

        try:
            from google.oauth2 import service_account
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/drive"]
            raw_json = self.settings.gdrive_credentials_json
            if not raw_json and self.settings.gdrive_credentials_path and self.settings.gdrive_credentials_path.exists():
                raw_json = self.settings.gdrive_credentials_path.read_text(encoding="utf-8")

            if not raw_json:
                return None

            cred_info = json.loads(raw_json)
            if cred_info.get("type") == "service_account":
                creds = service_account.Credentials.from_service_account_info(cred_info, scopes=scopes)
            else:
                creds = Credentials.from_authorized_user_info(cred_info, scopes=scopes)

            self._drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return self._drive_service
        except Exception as e:
            logger.warning(f"Google Drive API 클라이언트 초기화 폴백 (인증 미완료 또는 패키지 미설치): {e}")
            return None

    # -------------------------------------------------------------------------
    # 1. 텍스트 번들 (wiki_text_bundle.zip) 생성 및 압축 해제 (인증 불필요)
    # -------------------------------------------------------------------------
    @staticmethod
    def create_text_bundle(wiki_db_dir: Path, bundle_path: Optional[Path] = None) -> dict:
        """WikiDB 내의 텍스트 데이터(manifest.json, docs/*.md, reports/*.md, assets_map.json)를
        단일 압축 파일(wiki_text_bundle.zip)로 패키징한다.
        """
        wiki_db_dir = wiki_db_dir.resolve()
        out_path = (bundle_path or (wiki_db_dir / BUNDLE_FILENAME)).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        temp_zip = out_path.with_suffix(".zip.tmp")

        docs_count = 0
        reports_count = 0
        total_files = 0

        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # 1) manifest.json 및 assets_map.json 포함
            for root_file in ("manifest.json", ASSETS_MAP_FILENAME):
                f_path = wiki_db_dir / root_file
                if f_path.exists() and f_path.is_file():
                    zf.write(f_path, arcname=root_file)
                    total_files += 1

            # 2) docs/*.md 포함
            docs_dir = wiki_db_dir / "docs"
            if docs_dir.exists():
                for md_file in sorted(docs_dir.glob("*.md")):
                    if md_file.is_file():
                        zf.write(md_file, arcname=f"docs/{md_file.name}")
                        docs_count += 1
                        total_files += 1

            # 3) reports/*.md 포함
            reports_dir = wiki_db_dir / "reports"
            if reports_dir.exists():
                for rep_file in sorted(reports_dir.glob("*.md")):
                    if rep_file.is_file():
                        zf.write(rep_file, arcname=f"reports/{rep_file.name}")
                        reports_count += 1
                        total_files += 1

        temp_zip.replace(out_path)
        size_bytes = out_path.stat().st_size
        logger.info(
            f"텍스트 번들 생성 완료: {out_path.name} "
            f"(문서 {docs_count}건, 보고서 {reports_count}건, 크기 {size_bytes / (1024 * 1024):.2f}MB)"
        )
        return {
            "bundle_path": str(out_path),
            "docs_count": docs_count,
            "reports_count": reports_count,
            "total_files": total_files,
            "bundle_size_bytes": size_bytes,
        }

    @staticmethod
    def extract_text_bundle(bundle_path: Path, wiki_db_dir: Path, preserve_newer_reports: bool = True) -> dict:
        """wiki_text_bundle.zip을 지정된 WikiDB 경로에 안전하게 압축 해제한다."""
        if not bundle_path.exists() or not bundle_path.is_file():
            raise FileNotFoundError(f"텍스트 번들 파일이 존재하지 않습니다: {bundle_path}")

        target_root = wiki_db_dir.resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        (target_root / "docs").mkdir(parents=True, exist_ok=True)
        (target_root / "reports").mkdir(parents=True, exist_ok=True)

        extracted_count = 0
        docs_count = 0
        reports_count = 0

        with zipfile.ZipFile(bundle_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue

                # Zip Slip 경로 이탈 방지 검증
                dest_path = (target_root / member.filename).resolve()
                try:
                    dest_path.relative_to(target_root)
                except ValueError:
                    logger.warning(f"비정상적인 압축 경로 차단: {member.filename}")
                    continue

                # 기존 로컬 보고서가 더 최신인 경우 덮어쓰기 방지
                if preserve_newer_reports and member.filename.startswith("reports/") and dest_path.exists():
                    try:
                        zip_dt = datetime(*member.date_time).timestamp()
                        if dest_path.stat().st_mtime > zip_dt > 0:
                            continue
                    except Exception:
                        pass

                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                extracted_count += 1
                if member.filename.startswith("docs/"):
                    docs_count += 1
                elif member.filename.startswith("reports/"):
                    reports_count += 1

        logger.info(
            f"텍스트 번들 압축 해제 완료: 총 {extracted_count}건 "
            f"(문서 {docs_count}건, 보고서 {reports_count}건)"
        )
        return {
            "extracted_files": extracted_count,
            "docs_count": docs_count,
            "reports_count": reports_count,
        }

    # -------------------------------------------------------------------------
    # 2. 로컬 Google Drive 데스크톱 폴더(Mirror Dir) 양방향 동기화
    # -------------------------------------------------------------------------
    def sync_with_mirror_dir(self, wiki_db_dir: Path, mirror_dir: Path, include_assets: bool = True) -> dict:
        """PC에 마운트된 구글 드라이브 폴더(mirror_dir)와 로컬 WikiDB를 동기화한다."""
        wiki_db_dir = wiki_db_dir.resolve()
        mirror_dir = mirror_dir.resolve()
        mirror_dir.mkdir(parents=True, exist_ok=True)

        # 1) 클라우드(스마트폰)에서 생성되어 mirror_dir/reports에 저장된 신규 보고서를 로컬로 먼저 가져오기(Pull)
        mirror_reports = mirror_dir / "reports"
        local_reports = wiki_db_dir / "reports"
        local_reports.mkdir(parents=True, exist_ok=True)
        pulled_reports = 0
        if mirror_reports.exists():
            for remote_rep in mirror_reports.glob("*.md"):
                local_rep = local_reports / remote_rep.name
                if not local_rep.exists() or remote_rep.stat().st_mtime > local_rep.stat().st_mtime + 1.0:
                    shutil.copy2(remote_rep, local_rep)
                    pulled_reports += 1

        # 2) 최신 상태의 텍스트 번들 생성 후 mirror_dir로 복사
        bundle_info = self.create_text_bundle(wiki_db_dir)
        local_bundle = Path(bundle_info["bundle_path"])
        shutil.copy2(local_bundle, mirror_dir / BUNDLE_FILENAME)

        local_map = wiki_db_dir / ASSETS_MAP_FILENAME
        if local_map.exists():
            shutil.copy2(local_map, mirror_dir / ASSETS_MAP_FILENAME)

        # 3) 로컬 reports/*.md를 mirror_dir/reports로 복사(Push)
        mirror_reports.mkdir(parents=True, exist_ok=True)
        pushed_reports = 0
        for local_rep in local_reports.glob("*.md"):
            remote_rep = mirror_reports / local_rep.name
            if not remote_rep.exists() or local_rep.stat().st_mtime > remote_rep.stat().st_mtime + 1.0:
                shutil.copy2(local_rep, remote_rep)
                pushed_reports += 1

        # 4) 에셋 이미지 증분 복사 (신규/변경분만 복사)
        copied_assets = 0
        skipped_assets = 0
        if include_assets:
            local_assets = wiki_db_dir / "assets"
            mirror_assets = mirror_dir / "assets"
            if local_assets.exists():
                for src_file in local_assets.rglob("*"):
                    if not src_file.is_file():
                        continue
                    rel = src_file.relative_to(local_assets)
                    dst_file = mirror_assets / rel
                    if dst_file.exists() and dst_file.stat().st_size == src_file.stat().st_size:
                        skipped_assets += 1
                        continue
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    copied_assets += 1

        return {
            "bundle_size_bytes": bundle_info["bundle_size_bytes"],
            "docs_count": bundle_info["docs_count"],
            "pulled_reports": pulled_reports,
            "pushed_reports": pushed_reports,
            "copied_assets": copied_assets,
            "skipped_assets": skipped_assets,
        }

    # -------------------------------------------------------------------------
    # 3. 클라우드 서버 부트스트랩 (기동 시 텍스트 번들 & 최신 보고서 로드)
    # -------------------------------------------------------------------------
    def bootstrap_from_remote(self, wiki_db_dir: Optional[Path] = None) -> dict:
        """클라우드 컨테이너 기동 시 Google Drive(또는 미러 폴더/로컬 번들)에서 텍스트 번들과 최신 보고서를 로드한다."""
        target_db = (wiki_db_dir or self.settings.wiki_db_dir).resolve()
        target_db.mkdir(parents=True, exist_ok=True)
        result = {"mode": self.settings.storage_mode, "bootstrapped": False, "source": "none", "pulled_reports": 0}

        docs_dir = target_db / "docs"
        local_bundle = target_db / BUNDLE_FILENAME
        manifest_file = target_db / "manifest.json"

        # 0) 선제적 로컬 번들 복원: docs가 비어있거나 manifest가 없는 상태에서 내장 번들이 존재하면 즉시 1차 압축 해제
        has_docs = docs_dir.exists() and any(docs_dir.glob("*.md"))
        if local_bundle.exists() and (not has_docs or not manifest_file.exists()):
            try:
                ext_res = self.extract_text_bundle(local_bundle, target_db)
                result.update({"bootstrapped": True, "source": "local_bundle", **ext_res})
                logger.info(f"내장 로컬 번들 선제 복원 성공: 문서 {ext_res.get('docs_count', 0)}건")
            except Exception as e:
                logger.warning(f"내장 로컬 번들 선제 해제 실패: {e}")

        # 1) 로컬 미러 폴더가 있는 경우
        if self.has_mirror_dir and self.settings.gdrive_local_mirror_dir:
            mirror_dir = self.settings.gdrive_local_mirror_dir
            mirror_bundle = mirror_dir / BUNDLE_FILENAME
            if mirror_bundle.exists():
                ext_res = self.extract_text_bundle(mirror_bundle, target_db)
                result.update({"bootstrapped": True, "source": "mirror_dir", **ext_res})

            mirror_reports = mirror_dir / "reports"
            if mirror_reports.exists():
                local_reports = target_db / "reports"
                local_reports.mkdir(parents=True, exist_ok=True)
                for r_file in mirror_reports.glob("*.md"):
                    dst = local_reports / r_file.name
                    if not dst.exists() or r_file.stat().st_mtime > dst.stat().st_mtime:
                        shutil.copy2(r_file, dst)
                        result["pulled_reports"] += 1
            self._assets_map_cache = None
            return result

        # 2) Google Drive API가 설정된 경우
        service = self._get_drive_service()
        if service is not None and self.settings.gdrive_folder_id:
            try:
                bundle_file_id = self._find_remote_file_id(
                    service, name=BUNDLE_FILENAME, parent_id=self.settings.gdrive_folder_id
                )
                if bundle_file_id:
                    bundle_bytes = self._download_file_bytes(service, bundle_file_id)
                    if bundle_bytes:
                        if zipfile.is_zipfile(io.BytesIO(bundle_bytes)):
                            temp_download = local_bundle.with_suffix(".zip.download")
                            temp_download.write_bytes(bundle_bytes)
                            ext_res = self.extract_text_bundle(temp_download, target_db)
                            temp_download.replace(local_bundle)
                            result.update({"bootstrapped": True, "source": "gdrive_api", **ext_res})
                        else:
                            logger.warning("⚠️ Google Drive에서 다운로드한 번들이 유효한 ZIP 파일이 아닙니다.")

                # Google Drive 내 reports 하위 폴더에서 추가/최신 보고서 동기화
                reports_folder_id = self._find_remote_file_id(
                    service,
                    name="reports",
                    parent_id=self.settings.gdrive_folder_id,
                    mime_type="application/vnd.google-apps.folder",
                )
                if reports_folder_id:
                    self._reports_folder_id_cache = reports_folder_id
                    remote_reports = self._list_remote_files(service, parent_id=reports_folder_id)
                    local_reports_dir = target_db / "reports"
                    local_reports_dir.mkdir(parents=True, exist_ok=True)
                    for r_item in remote_reports:
                        r_name = r_item.get("name", "")
                        if not r_name.endswith(".md"):
                            continue
                        r_bytes = self._download_file_bytes(service, r_item["id"])
                        if r_bytes:
                            (local_reports_dir / r_name).write_bytes(r_bytes)
                            result["pulled_reports"] += 1

                self._assets_map_cache = None
                return result
            except Exception as e:
                logger.warning(f"Google Drive 원격 부트스트랩 중 오류 (로컬 캐시로 폴백): {e}")

        # 3) 사후 안전장치: 혹시라도 여전히 비어있고 번들이 남아있는 경우 재확인
        has_docs_now = docs_dir.exists() and any(docs_dir.glob("*.md"))
        if local_bundle.exists() and not has_docs_now:
            try:
                ext_res = self.extract_text_bundle(local_bundle, target_db)
                result.update({"bootstrapped": True, "source": "local_bundle", **ext_res})
            except Exception as e:
                logger.warning(f"로컬 번들 자동 해제 실패: {e}")

        self._assets_map_cache = None
        return result

    # -------------------------------------------------------------------------
    # 4. 온디맨드(On-Demand) 이미지 에셋 페치 및 로컬 디스크 캐싱
    # -------------------------------------------------------------------------
    def _load_assets_map(self, wiki_db_dir: Path) -> dict[str, str]:
        """WikiDB/assets_map.json 매핑 테이블을 메모리에 로드한다."""
        if self._assets_map_cache is not None:
            return self._assets_map_cache

        map_file = wiki_db_dir / ASSETS_MAP_FILENAME
        if map_file.exists() and map_file.is_file():
            try:
                self._assets_map_cache = json.loads(map_file.read_text(encoding="utf-8"))
                return self._assets_map_cache
            except Exception as e:
                logger.warning(f"assets_map.json 로드 실패: {e}")

        self._assets_map_cache = {}
        return self._assets_map_cache

    def ensure_asset_file(
        self,
        doc_id: str,
        filename: str,
        assets_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """요청된 에셋 이미지가 로컬 디스크에 없으면 Google Drive(또는 미러 폴더)에서 온디맨드로 내려받아 캐싱 후 반환한다."""
        target_assets_dir = (assets_dir or self.settings.assets_dir).resolve()
        clean_doc_id = urllib.parse.unquote(doc_id).strip()
        clean_filename = urllib.parse.unquote(filename).strip()
        safe_filename = Path(clean_filename).name

        # 0) 로컬 디스크에 이미 존재하면 즉시 반환 (0ms 캐시 히트)
        local_candidate = target_assets_dir / clean_doc_id / safe_filename
        if local_candidate.exists() and local_candidate.is_file():
            return local_candidate

        # 1) 로컬 미러 폴더가 설정된 경우 미러에서 온디맨드 복사
        if self.has_mirror_dir and self.settings.gdrive_local_mirror_dir:
            mirror_assets = self.settings.gdrive_local_mirror_dir / "assets"
            for cand_doc in (clean_doc_id, doc_id):
                mirror_file = mirror_assets / cand_doc / safe_filename
                if mirror_file.exists() and mirror_file.is_file():
                    local_candidate.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(mirror_file, local_candidate)
                    return local_candidate

        # 2) Google Drive API에서 온디맨드 다운로드
        service = self._get_drive_service()
        if service is None:
            return None

        wiki_db_dir = target_assets_dir.parent
        assets_map = self._load_assets_map(wiki_db_dir)

        # 2-a) assets_map.json에서 O(1) file_id 조회 (대소문자/인코딩 변형 대응)
        file_id = None
        lookup_keys = [
            f"{clean_doc_id}/{safe_filename}",
            f"{doc_id}/{safe_filename}",
            f"{clean_doc_id}/{clean_filename}",
        ]
        for key in lookup_keys:
            if key in assets_map:
                file_id = assets_map[key]
                break

        if not file_id and assets_map:
            lower_target = f"{clean_doc_id}/{safe_filename}".lower()
            for k, v in assets_map.items():
                if k.lower() == lower_target or (clean_doc_id.lower() in k.lower() and k.lower().endswith(f"/{safe_filename.lower()}")):
                    file_id = v
                    break

        # 2-b) 매핑에 없을 경우 Google Drive 폴더 트리에서 직접 탐색 폴백
        if not file_id and self.settings.gdrive_folder_id:
            file_id = self._search_remote_asset_id(service, clean_doc_id, safe_filename)

        if not file_id:
            return None

        try:
            img_bytes = self._download_file_bytes(service, file_id)
            if not img_bytes:
                return None

            local_candidate.parent.mkdir(parents=True, exist_ok=True)
            temp_file = local_candidate.with_suffix(local_candidate.suffix + ".tmp")
            temp_file.write_bytes(img_bytes)
            temp_file.replace(local_candidate)
            logger.info(f"Google Drive 온디맨드 이미지 캐싱 완료: {clean_doc_id}/{safe_filename} ({len(img_bytes)} bytes)")
            return local_candidate
        except Exception as e:
            logger.warning(f"Google Drive 이미지 다운로드 실패 ({clean_doc_id}/{safe_filename}): {e}")
            return None

    # -------------------------------------------------------------------------
    # 5. AI 생성 보고서 양방향 백업 (생성/보정 시 업로드, 삭제 시 원격 삭제)
    # -------------------------------------------------------------------------
    def upload_report(self, report_path: Path) -> bool:
        """생성되거나 보정된 AI 주제 보고서(.md)를 미러 폴더 및 Google Drive에 즉시 백업한다."""
        if not report_path.exists() or not report_path.is_file():
            return False

        uploaded = False

        # 1) 로컬 미러 폴더 백업
        if self.has_mirror_dir and self.settings.gdrive_local_mirror_dir:
            try:
                mirror_reports = self.settings.gdrive_local_mirror_dir / "reports"
                mirror_reports.mkdir(parents=True, exist_ok=True)
                shutil.copy2(report_path, mirror_reports / report_path.name)
                uploaded = True
            except Exception as e:
                logger.warning(f"미러 폴더 보고서 백업 실패 ({report_path.name}): {e}")

        # 2) Google Drive API 백업
        service = self._get_drive_service()
        if service is not None and self.settings.gdrive_folder_id:
            try:
                reports_folder_id = self._ensure_remote_folder(
                    service, name="reports", parent_id=self.settings.gdrive_folder_id
                )
                if reports_folder_id:
                    self._upload_or_update_file(
                        service,
                        local_path=report_path,
                        parent_id=reports_folder_id,
                        mime_type="text/markdown",
                    )
                    uploaded = True
                    logger.info(f"Google Drive 원격 보고서 백업 완료: {report_path.name}")
            except Exception as e:
                logger.warning(f"Google Drive 원격 보고서 업로드 실패 ({report_path.name}): {e}")

        return uploaded

    def delete_report(self, report_id: str) -> bool:
        """삭제된 AI 주제 보고서를 미러 폴더 및 Google Drive에서도 함께 삭제한다."""
        clean_stem = Path(report_id).stem
        target_name = f"{clean_stem}.md"
        deleted = False

        # 1) 로컬 미러 폴더에서 삭제
        if self.has_mirror_dir and self.settings.gdrive_local_mirror_dir:
            mirror_file = self.settings.gdrive_local_mirror_dir / "reports" / target_name
            if mirror_file.exists():
                try:
                    mirror_file.unlink()
                    deleted = True
                except Exception as e:
                    logger.warning(f"미러 폴더 보고서 삭제 실패 ({target_name}): {e}")

        # 2) Google Drive API에서 삭제
        service = self._get_drive_service()
        if service is not None and self.settings.gdrive_folder_id:
            try:
                reports_folder_id = self._reports_folder_id_cache or self._find_remote_file_id(
                    service,
                    name="reports",
                    parent_id=self.settings.gdrive_folder_id,
                    mime_type="application/vnd.google-apps.folder",
                )
                if reports_folder_id:
                    file_id = self._find_remote_file_id(service, name=target_name, parent_id=reports_folder_id)
                    if file_id:
                        service.files().delete(fileId=file_id).execute()
                        deleted = True
                        logger.info(f"Google Drive 원격 보고서 삭제 완료: {target_name}")
            except Exception as e:
                logger.warning(f"Google Drive 원격 보고서 삭제 실패 ({target_name}): {e}")

        return deleted

    # -------------------------------------------------------------------------
    # 6. Google Drive API 전체 Push 동기화 (sync_gdrive.py CLI용)
    # -------------------------------------------------------------------------
    def push_all_to_gdrive_api(self, wiki_db_dir: Optional[Path] = None, upload_assets: bool = True) -> dict:
        """로컬 WikiDB의 에셋 이미지, 보고서, 텍스트 번들을 Google Drive API로 증분 업로드한다."""
        service = self._get_drive_service()
        if service is None or not self.settings.gdrive_folder_id:
            raise RuntimeError(
                "Google Drive API 인증 정보(GDRIVE_CREDENTIALS_JSON/PATH) 또는 폴더 ID(GDRIVE_FOLDER_ID)가 설정되지 않았습니다."
            )

        target_db = (wiki_db_dir or self.settings.wiki_db_dir).resolve()
        root_id = self.settings.gdrive_folder_id
        assets_map = self._load_assets_map(target_db)

        uploaded_assets = 0
        skipped_assets = 0

        if upload_assets and (target_db / "assets").exists():
            assets_root_id = self._ensure_remote_folder(service, name="assets", parent_id=root_id)
            all_doc_dirs = sorted([d for d in (target_db / "assets").iterdir() if d.is_dir()])
            total_dirs = len(all_doc_dirs)
            logger.info(f"에셋 업로드 준비: 총 {total_dirs}개 문서 에셋 디렉터리 검사 시작...")

            for idx, doc_dir in enumerate(all_doc_dirs, 1):
                doc_folder_id = None
                img_files = sorted([f for f in doc_dir.iterdir() if f.is_file()])
                for img_file in img_files:
                    rel_key = f"{doc_dir.name}/{img_file.name}"
                    if rel_key in assets_map:
                        skipped_assets += 1
                        continue
                    if doc_folder_id is None:
                        doc_folder_id = self._ensure_remote_folder(service, name=doc_dir.name, parent_id=assets_root_id)
                    fid = self._upload_or_update_file(service, local_path=img_file, parent_id=doc_folder_id)
                    if fid:
                        assets_map[rel_key] = fid
                        uploaded_assets += 1
                        if uploaded_assets % 25 == 0:
                            logger.info(f"에셋 업로드 진행 중: {uploaded_assets}건 신규 업로드 완료 ({doc_dir.name}/{img_file.name})")
                            # 증분 중간 저장 (네트워크 중단 시에도 재개 가능)
                            map_path = target_db / ASSETS_MAP_FILENAME
                            map_path.write_text(json.dumps(assets_map, ensure_ascii=False, indent=2), encoding="utf-8")

                if idx % 10 == 0 or idx == total_dirs:
                    logger.info(f"문서 에셋 처리 진행: [{idx}/{total_dirs}] 폴더 완료 (누적 업로드: {uploaded_assets}건, 기존 유지: {skipped_assets}건)")

            # 최종 assets_map.json 저장
            map_path = target_db / ASSETS_MAP_FILENAME
            map_path.write_text(json.dumps(assets_map, ensure_ascii=False, indent=2), encoding="utf-8")
            self._assets_map_cache = assets_map

        # reports/*.md 동기화
        uploaded_reports = 0
        reports_dir = target_db / "reports"
        if reports_dir.exists():
            reports_folder_id = self._ensure_remote_folder(service, name="reports", parent_id=root_id)
            for rep_file in sorted(reports_dir.glob("*.md")):
                if rep_file.is_file():
                    self._upload_or_update_file(
                        service, local_path=rep_file, parent_id=reports_folder_id, mime_type="text/markdown"
                    )
                    uploaded_reports += 1
            logger.info(f"보고서 동기화 완료: {uploaded_reports}건")

        # 텍스트 번들 생성 및 업로드
        bundle_info = self.create_text_bundle(target_db)
        bundle_path = Path(bundle_info["bundle_path"])
        bundle_fid = self._upload_or_update_file(
            service, local_path=bundle_path, parent_id=root_id, mime_type="application/zip"
        )

        return {
            "bundle_file_id": bundle_fid,
            "bundle_size_bytes": bundle_info["bundle_size_bytes"],
            "docs_count": bundle_info["docs_count"],
            "uploaded_reports": uploaded_reports,
            "uploaded_assets": uploaded_assets,
            "skipped_assets": skipped_assets,
        }

    # -------------------------------------------------------------------------
    # Google Drive REST API 내부 헬퍼
    # -------------------------------------------------------------------------
    @staticmethod
    def _escape_q(val: str) -> str:
        return val.replace("\\", "\\\\").replace("'", "\\'")

    def _find_remote_file_id(
        self,
        service,
        name: str,
        parent_id: str,
        mime_type: Optional[str] = None,
    ) -> Optional[str]:
        escaped_name = self._escape_q(name)
        q = f"'{parent_id}' in parents and name = '{escaped_name}' and trashed = false"
        if mime_type:
            q += f" and mimeType = '{mime_type}'"
        res = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=5).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    def _list_remote_files_all(self, service, parent_id: str, mime_type: Optional[str] = None) -> list[dict]:
        """지정된 부모 폴더 내의 모든 자식 파일/폴더를 페이지네이션으로 전수 수집한다."""
        files = []
        page_token = None
        q = f"'{parent_id}' in parents and trashed = false"
        if mime_type:
            q += f" and mimeType = '{mime_type}'"
        while True:
            res = service.files().list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            files.extend(res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return files

    def build_remote_assets_index(self, wiki_db_dir: Optional[Path] = None) -> dict:
        """Google Drive의 assets/ 하위 폴더들을 스캔하여 assets_map.json 및 wiki_text_bundle.zip을 최신화한다."""
        service = self._get_drive_service()
        if service is None or not self.settings.gdrive_folder_id:
            raise RuntimeError("Google Drive API가 설정되지 않았습니다.")

        target_db = (wiki_db_dir or self.settings.wiki_db_dir).resolve()
        folder_mime = "application/vnd.google-apps.folder"

        assets_folder_id = self._find_remote_file_id(
            service, name="assets", parent_id=self.settings.gdrive_folder_id, mime_type=folder_mime
        )
        if not assets_folder_id:
            logger.warning("Google Drive에 'assets' 폴더가 아직 없습니다.")
            return {"indexed_count": 0, "status": "no_assets_folder"}

        logger.info("Google Drive 원격 assets 디렉터리 목록 조회 중...")
        doc_folders = self._list_remote_files_all(service, parent_id=assets_folder_id, mime_type=folder_mime)
        logger.info(f"원격 문서 에셋 폴더 {len(doc_folders)}개 발견. 이미지 파일 인덱싱 시작...")

        assets_map = {}
        total_images = 0
        for idx, doc_f in enumerate(doc_folders, 1):
            doc_id = doc_f["name"]
            img_files = self._list_remote_files_all(service, parent_id=doc_f["id"])
            for img in img_files:
                if img.get("mimeType") != folder_mime:
                    assets_map[f"{doc_id}/{img['name']}"] = img["id"]
                    total_images += 1
            if idx % 25 == 0 or idx == len(doc_folders):
                logger.info(f"인덱싱 진행: [{idx}/{len(doc_folders)}] 폴더 완료 (누적 이미지: {total_images}개)")

        map_path = target_db / ASSETS_MAP_FILENAME
        map_path.write_text(json.dumps(assets_map, ensure_ascii=False, indent=2), encoding="utf-8")
        self._assets_map_cache = assets_map

        # assets_map.json이 포함된 새 번들 생성
        bundle_info = self.create_text_bundle(target_db)
        logger.info(f"✅ 원격 에셋 인덱싱 완료: 총 {total_images}개 이미지 매핑 저장 및 번들 갱신 완료")
        return {
            "indexed_count": total_images,
            "doc_folders_count": len(doc_folders),
            "bundle_size_bytes": bundle_info["bundle_size_bytes"],
            "map_file": str(map_path),
        }

    def _list_remote_files(self, service, parent_id: str) -> list[dict]:
        q = f"'{parent_id}' in parents and trashed = false"
        res = service.files().list(q=q, spaces="drive", fields="files(id, name, modifiedTime)", pageSize=200).execute()
        return res.get("files", [])

    def _ensure_remote_folder(self, service, name: str, parent_id: str) -> str:
        folder_mime = "application/vnd.google-apps.folder"
        existing_id = self._find_remote_file_id(service, name=name, parent_id=parent_id, mime_type=folder_mime)
        if existing_id:
            return existing_id
        metadata = {"name": name, "mimeType": folder_mime, "parents": [parent_id]}
        created = service.files().create(body=metadata, fields="id").execute()
        return created["id"]

    def _search_remote_asset_id(self, service, doc_id: str, filename: str) -> Optional[str]:
        try:
            assets_folder_id = self._find_remote_file_id(
                service,
                name="assets",
                parent_id=self.settings.gdrive_folder_id,
                mime_type="application/vnd.google-apps.folder",
            )
            if not assets_folder_id:
                return None
            doc_folder_id = self._find_remote_file_id(
                service,
                name=doc_id,
                parent_id=assets_folder_id,
                mime_type="application/vnd.google-apps.folder",
            )
            if not doc_folder_id:
                return None
            return self._find_remote_file_id(service, name=filename, parent_id=doc_folder_id)
        except Exception:
            return None

    def _download_file_bytes(self, service, file_id: str) -> Optional[bytes]:
        request = service.files().get_media(fileId=file_id)
        if hasattr(request, "execute"):
            # googleapiclient MediaIoBaseDownload 또는 직접 execute 지원
            try:
                from googleapiclient.http import MediaIoBaseDownload

                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return buf.getvalue()
            except Exception:
                data = request.execute()
                return data if isinstance(data, bytes) else None
        return None

    def _upload_or_update_file(
        self,
        service,
        local_path: Path,
        parent_id: str,
        mime_type: str = "application/octet-stream",
    ) -> Optional[str]:
        size = local_path.stat().st_size if local_path.exists() else 0
        use_resumable = size > 1024 * 512
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=use_resumable, chunksize=1024 * 1024)
        except Exception:
            media = None

        existing_id = self._find_remote_file_id(service, name=local_path.name, parent_id=parent_id)
        if existing_id:
            req = service.files().update(fileId=existing_id, media_body=media, fields="id")
        else:
            metadata = {"name": local_path.name, "parents": [parent_id]}
            req = service.files().create(body=metadata, media_body=media, fields="id")

        if use_resumable and media is not None:
            response = None
            while response is None:
                _, response = req.next_chunk()
            return response.get("id", existing_id)
        else:
            res = req.execute()
            return res.get("id", existing_id)


_gdrive_instance: Optional[GDriveStorageManager] = None


def get_gdrive_storage(settings: Optional[Settings] = None) -> GDriveStorageManager:
    """전역 GDriveStorageManager 인스턴스를 반환한다."""
    global _gdrive_instance
    target_settings = settings or get_settings()
    if _gdrive_instance is None or _gdrive_instance.settings is not target_settings:
        _gdrive_instance = GDriveStorageManager(settings=target_settings)
    return _gdrive_instance
