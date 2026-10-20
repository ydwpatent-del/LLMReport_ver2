"""FastAPI 웹 서버 및 REST API 라우터."""

import hashlib
import hmac
import shutil
import logging
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.manifest import ManifestManager, DocumentEntry
from app.ingest_agent import IngestAgent
from app.utils import safe_remove_file, safe_remove_dir
from app.topic_router import topic_router
from app.audit_agent import AuditAgent
from app.gdrive_storage import GDriveStorageManager, get_gdrive_storage

logger = logging.getLogger(__name__)

AUTH_COOKIE_NAME = "wiki_auth_token"
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 900  # 15분 차단


def _compute_pin_token(pin: str, salt_suffix: str = "") -> str:
    """설정된 PIN 번호에 대한 HMAC-SHA256 서명 토큰을 생성한다."""
    salt = f"llmwiki_pin_auth_v1:{salt_suffix}".encode("utf-8")
    return hmac.new(pin.encode("utf-8"), salt, hashlib.sha256).hexdigest()


def _render_pin_login_html() -> str:
    """모바일 및 PC 브라우저용 간편 PIN 잠금 해제 HTML 화면을 반환한다."""
    return """<!DOCTYPE html>
<html lang="ko" class="h-full bg-slate-900 text-slate-100">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>LLM Wiki 접속 인증</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full flex items-center justify-center p-4">
  <div class="w-full max-w-sm bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5">
    <div class="text-center space-y-1.5">
      <div class="w-12 h-12 rounded-xl bg-indigo-600/20 border border-indigo-500/40 text-indigo-400 mx-auto flex items-center justify-center text-xl font-bold">🔒</div>
      <h1 class="text-lg font-bold text-white">LLM Wiki 보안 잠금</h1>
      <p class="text-xs text-slate-400">스마트폰/외부 접속 보호를 위해 설정된 PIN을 입력해 주세요.<br>(인증 후 30일간 자동 유지됩니다)</p>
    </div>
    <form id="pinForm" class="space-y-4">
      <input id="pinInput" type="password" inputmode="text" autocomplete="current-password" placeholder="접속 PIN 또는 비밀번호 입력" required
        class="w-full px-4 py-3 rounded-xl bg-slate-900 border border-slate-600 text-white text-center text-base tracking-widest focus:outline-none focus:border-indigo-500">
      <p id="errMsg" class="text-xs text-rose-400 text-center hidden">PIN 번호가 일치하지 않습니다.</p>
      <button type="submit" class="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm transition">
        잠금 해제
      </button>
    </form>
  </div>
  <script>
    document.getElementById('pinForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pin = document.getElementById('pinInput').value;
      const err = document.getElementById('errMsg');
      err.classList.add('hidden');
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pin})
      });
      if (res.ok) {
        window.location.href = '/';
      } else {
        err.classList.remove('hidden');
      }
    });
  </script>
</body>
</html>"""


class PinLoginRequest(BaseModel):
    """모바일/외부 접속 PIN 로그인 요청 DTO."""
    pin: str


class DocumentResponse(BaseModel):
    """문서 목록 반환용 DTO."""
    id: str
    original_filename: str
    file_hash: Optional[str] = None
    file_size: int
    modified_time: float
    status: str
    ingested_at: str
    title: str
    error_message: Optional[str] = None

class DocumentDetailResponse(DocumentResponse):
    """문서 상세 및 본문 내용 반환용 DTO."""
    content: str

def _find_document_entry(doc_id_or_title: str, manifest_mgr: ManifestManager) -> Optional[DocumentEntry]:
    """URL 디코딩 및 정규화, 부분 일치를 고려하여 문서를 안전하게 조회한다.
    
    구버전 ID 호환: 클라이언트가 구버전 ID를 요청하더라도 자가 치유된 최신 문서를 원본 파일명 및 접두사로 탐색한다.
    """
    clean_id = urllib.parse.unquote(doc_id_or_title).strip()
    # 1. 정확한 ID 일치
    doc = manifest_mgr.get_document(clean_id) or manifest_mgr.get_document(doc_id_or_title)
    if doc:
        return doc

    # 2. 제목, 원본 파일명 일치 검색
    all_docs = manifest_mgr.get_all_documents()
    for d in all_docs:
        if d.id == clean_id or d.id == doc_id_or_title or d.title == clean_id:
            return d
        if d.original_filename == clean_id or Path(d.original_filename).stem == clean_id:
            return d

    # 3. 파일명 stem 기반 유사 매칭 (해시/타임스탬프 suffix 변동 대응 안전망)
    # 예: '20260616_AI_Bottleneck_Issue_...' 또는 'broken_doc_id'
    clean_stem = re.sub(r'_\d+_[a-fA-F0-9]+$', '', clean_id)
    
    for d in all_docs:
        d_stem = re.sub(r'_\d+_[a-fA-F0-9]+$', '', d.id)
        if clean_stem and (clean_stem.lower() == d_stem.lower() or clean_stem.lower() in d.id.lower()):
            return d
        if d.original_filename and clean_stem.lower() in Path(d.original_filename).stem.lower():
            return d

    return None

def create_app(
    settings: Optional[Settings] = None,
    manifest_mgr: Optional[ManifestManager] = None,
    agent: Optional[IngestAgent] = None,
    gdrive_storage: Optional[GDriveStorageManager] = None,
) -> FastAPI:
    """FastAPI 애플리케이션 인스턴스를 팩토리 패턴으로 생성한다."""
    if settings is None:
        settings = get_settings()
    if manifest_mgr is None:
        manifest_mgr = ManifestManager(settings.manifest_path)
    if gdrive_storage is None:
        gdrive_storage = get_gdrive_storage(settings)

    # 서버 기동 시 디스크 파일과 매니페스트 간 정합성 자동 검사 및 자가 치유(Self-Healing)
    try:
        heal_res = manifest_mgr.reconcile_with_disk(settings.docs_dir, settings.assets_dir)
        if heal_res.get("reconciled", 0) > 0 or heal_res.get("new_registered", 0) > 0:
            logger.info(f"WikiDB 자가 치유 완료: 복구 {heal_res['reconciled']}건, 신규 등록 {heal_res['new_registered']}건")
    except Exception as e:
        logger.warning(f"WikiDB 자가 치유 검사 중 오류: {e}")

    app = FastAPI(
        title="LLM Wiki Knowledge Ingestion Server",
        description="무삭제 문서 변환 및 지식 데이터베이스 서빙 API",
        version="1.0.0"
    )

    # CORS 스펙 준수: 와일드카드(*) 사용 시 credentials=False 로 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(topic_router)

    # IP별 로그인/인증 실패 횟수 및 잠금 시각 기록용 테이블
    failed_login_attempts: dict[str, tuple[int, float]] = {}

    def _get_client_ip(req: Request) -> str:
        """프록시(Cloud Run 등) 환경을 고려하여 실제 클라이언트 IP를 추출한다."""
        xff = req.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return req.client.host if req.client else "127.0.0.1"

    def _apply_security_headers(resp):
        """표준 웹 보안 헤더(MIME 스니핑 방지, 클릭재킹 방지, 리퍼러 보호)를 응답에 강제 부착한다."""
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return resp

    @app.middleware("http")
    async def pin_auth_and_security_headers_middleware(request: Request, call_next):
        """선택적 외부 접속 PIN 인증, 브루트포스 잠금 및 표준 웹 보안 헤더를 처리한다."""
        active_pin = (settings.wiki_access_pin or "").strip()
        path = request.url.path
        client_ip = _get_client_ip(request)

        # 1. IP 잠금 상태 확인 (5회 실패 시 15분간 차단)
        now = time.time()
        if client_ip in failed_login_attempts:
            fail_count, lock_time = failed_login_attempts[client_ip]
            if fail_count >= LOGIN_MAX_FAILURES:
                if now - lock_time < LOGIN_LOCKOUT_SECONDS:
                    remaining = int(LOGIN_LOCKOUT_SECONDS - (now - lock_time))
                    return _apply_security_headers(JSONResponse(
                        status_code=429,
                        content={"detail": f"PIN 입력 실패 횟수({LOGIN_MAX_FAILURES}회)를 초과하여 접근이 잠겼습니다. {remaining}초 후 다시 시도해 주세요."},
                        headers={"Retry-After": str(remaining)}
                    ))
                else:
                    failed_login_attempts.pop(client_ip, None)

        if active_pin:
            exempt_paths = {
                "/login",
                "/api/auth/login",
                "/api/auth/logout",
                "/manifest.webmanifest",
                "/service-worker.js",
                "/favicon.ico"
            }
            is_exempt = path in exempt_paths or path.startswith("/static/")
            if not is_exempt:
                salt_suffix = settings.gdrive_folder_id or ""
                expected_token = _compute_pin_token(active_pin, salt_suffix)
                cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
                header_pin = request.headers.get("X-Wiki-Pin", "")
                is_authenticated = hmac.compare_digest(cookie_token, expected_token) or (
                    bool(header_pin) and hmac.compare_digest(header_pin, active_pin)
                )

                if not is_authenticated:
                    # 잘못된 X-Wiki-Pin 헤더가 전송된 경우 실패 카운트 누적
                    if header_pin:
                        prev_cnt, _ = failed_login_attempts.get(client_ip, (0, 0.0))
                        failed_login_attempts[client_ip] = (prev_cnt + 1, now)

                    if path.startswith("/api/"):
                        return _apply_security_headers(JSONResponse(status_code=401, content={"detail": "PIN 인증이 필요합니다."}))
                    return _apply_security_headers(HTMLResponse(_render_pin_login_html(), status_code=401))
                else:
                    # 유효한 인증 요청이 확인되면 실패 카운트 초기화
                    failed_login_attempts.pop(client_ip, None)

        response = await call_next(request)

        # 2. 표준 웹 보안 헤더 부착
        _apply_security_headers(response)

        # 3. 민감 API 및 정적 자산 캐시 제어
        if path.startswith("/static") or path.startswith("/api") or path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/login", response_class=HTMLResponse)
    async def serve_login_page():
        """모바일/외부 접속 PIN 입력 페이지를 반환한다."""
        return HTMLResponse(_render_pin_login_html())

    @app.post("/api/auth/login")
    async def login_with_pin(req: PinLoginRequest, request: Request):
        """입력된 PIN 번호를 검증하고 실패 누적 시 잠금을 적용하며 30일간 유지되는 HttpOnly 인증 쿠키를 발급한다."""
        active_pin = (settings.wiki_access_pin or "").strip()
        client_ip = _get_client_ip(request)
        now = time.time()

        # 브루트포스 잠금 상태 검사
        if client_ip in failed_login_attempts:
            fail_count, lock_time = failed_login_attempts[client_ip]
            if fail_count >= LOGIN_MAX_FAILURES:
                if now - lock_time < LOGIN_LOCKOUT_SECONDS:
                    remaining = int(LOGIN_LOCKOUT_SECONDS - (now - lock_time))
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"PIN 입력 실패 횟수({LOGIN_MAX_FAILURES}회)를 초과하여 접근이 잠겼습니다. {remaining}초 후 다시 시도해 주세요."},
                        headers={"Retry-After": str(remaining)}
                    )
                else:
                    failed_login_attempts.pop(client_ip, None)

        if not active_pin:
            return {"authenticated": True, "message": "PIN 잠금이 비활성화되어 있습니다."}

        if not hmac.compare_digest(req.pin.strip(), active_pin):
            prev_cnt, _ = failed_login_attempts.get(client_ip, (0, 0.0))
            new_cnt = prev_cnt + 1
            failed_login_attempts[client_ip] = (new_cnt, now)
            rem = max(0, LOGIN_MAX_FAILURES - new_cnt)
            msg = f"PIN 번호가 일치하지 않습니다. (남은 기회: {rem}회)" if rem > 0 else f"PIN 입력 실패 횟수를 초과하여 {LOGIN_LOCKOUT_SECONDS // 60}분간 접속이 차단됩니다."
            raise HTTPException(status_code=401, detail=msg)

        # 로그인 성공 시 실패 기록 제거
        failed_login_attempts.pop(client_ip, None)

        salt_suffix = settings.gdrive_folder_id or ""
        token = _compute_pin_token(active_pin, salt_suffix)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"

        res = JSONResponse(content={"authenticated": True, "message": "인증 성공"})
        res.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=is_https,
        )
        return res

    @app.post("/api/auth/logout")
    async def logout_pin():
        """인증 쿠키를 제거한다."""
        res = JSONResponse(content={"authenticated": False, "message": "로그아웃 완료"})
        res.delete_cookie(key=AUTH_COOKIE_NAME)
        return res


    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        """대시보드 메인 HTML을 반환한다."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>LLM Wiki Server is Running</h1>")

    @app.get("/manifest.webmanifest")
    async def serve_manifest():
        """PWA 웹앱 매니페스트를 반환한다."""
        manifest_file = static_dir / "manifest.webmanifest"
        if manifest_file.exists():
            return FileResponse(manifest_file, media_type="application/manifest+json")
        raise HTTPException(status_code=404, detail="Manifest not found")

    @app.get("/service-worker.js")
    async def serve_service_worker():
        """PWA 서비스 워커 스크립트를 반환한다."""
        sw_file = static_dir / "service-worker.js"
        if sw_file.exists():
            return FileResponse(
                sw_file,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Service-Worker-Allowed": "/"
                }
            )
        raise HTTPException(status_code=404, detail="Service worker not found")

    @app.get("/favicon.ico")
    async def serve_favicon():
        """기본 파비콘 및 웹앱 아이콘을 반환한다."""
        icon_file = static_dir / "icons" / "icon-192.png"
        if icon_file.exists():
            return FileResponse(icon_file, media_type="image/png")
        raise HTTPException(status_code=404, detail="Favicon not found")

    @app.get("/api/documents", response_model=list[DocumentResponse])
    async def list_documents():
        """인제스트된 모든 문서 목록을 반환한다.
        
        중복 방지: 동일 파일에 대해 completed 상태가 존재하면 과거의 processing 좀비 항목은 제외하고 최신 1건만 노출한다.
        """
        raw_docs = manifest_mgr.get_all_documents()
        completed_hashes = {d.file_hash for d in raw_docs if d.status == "completed"}

        valid_docs = []
        for d in raw_docs:
            # 이미 완료된 파일의 잔여 처리중(processing) 고아 항목 배제
            if d.status == "processing" and d.file_hash in completed_hashes:
                continue
            valid_docs.append(d)

        # 동일 파일 해시당 최신 1건만 유지 (중복 방지)
        unique_by_hash = {}
        for d in sorted(valid_docs, key=lambda x: x.ingested_at):
            unique_by_hash[d.file_hash] = d

        result = list(unique_by_hash.values())
        return sorted(result, key=lambda d: d.ingested_at, reverse=True)

    @app.get("/api/documents/{doc_id:path}", response_model=DocumentDetailResponse)
    async def get_document_detail(doc_id: str):
        """특정 문서의 메타데이터와 마크다운 본문을 반환한다.
        
        자가 치유(Self-Healing): target_md_path 경로가 누락되었거나 불일치할 경우 디스크에서 실존 완본을 즉시 탐색하여 복구한다.
        """
        doc = _find_document_entry(doc_id, manifest_mgr)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        md_path = Path(doc.target_md_path) if doc.target_md_path else None
        content = ""

        # 1. 명시된 target_md_path가 유효한 경우
        if md_path and md_path.exists() and md_path.is_file():
            content = md_path.read_text(encoding="utf-8", errors="replace")
        else:
            # 2. 경로 불일치 시 docs_dir에서 자가 치유 실시간 탐색
            candidate_files = []
            if settings.docs_dir.exists():
                orig_stem = Path(doc.original_filename).stem if doc.original_filename else doc.title
                clean_stem = re.sub(r'[^a-zA-Z0-9_\uac00-\ud7a3-]', '_', orig_stem)
                for f in settings.docs_dir.glob("*.md"):
                    if clean_stem.lower() in f.name.lower() or f.stem.startswith(clean_stem) or doc.id in f.name:
                        candidate_files.append(f)

            if candidate_files:
                best_md = max(candidate_files, key=lambda p: (p.stat().st_size, p.stat().st_mtime))
                content = best_md.read_text(encoding="utf-8", errors="replace")
                # manifest 정보 즉시 동기화
                doc.target_md_path = str(best_md.resolve())
                doc.status = "completed"
                doc.error_message = None
                manifest_mgr.add_or_update_document(doc)
                logger.info(f"문서 상세 조회 중 자가 치유 성공: {doc.title} -> {best_md.name}")

        return DocumentDetailResponse(
            id=doc.id,
            original_filename=doc.original_filename,
            file_hash=doc.file_hash,
            file_size=doc.file_size,
            modified_time=doc.modified_time,
            status=doc.status,
            ingested_at=doc.ingested_at,
            title=doc.title,
            error_message=doc.error_message,
            content=content
        )

    @app.delete("/api/documents/{doc_id}")
    async def delete_document(doc_id: str):
        """특정 문서를 삭제하고, WikiDB 내의 마크다운 파일 및 에셋 이미지들을 전면 삭제한다."""
        doc = _find_document_entry(doc_id, manifest_mgr)
        target_id = doc.id if doc else urllib.parse.unquote(doc_id).strip()

        # 클라우드 모드(Google Drive 원격 스토리지)에서는 모바일 오터치 및 침해로 인한 원본 문서 삭제 차단
        is_report = target_id.startswith("REPORT_") or doc_id.startswith("REPORT_")
        if settings.storage_mode == "gdrive" and not is_report:
            raise HTTPException(
                status_code=403,
                detail="클라우드(웹) 모드에서는 원본 지식 DB 문서를 삭제할 수 없습니다. 원본 관리는 로컬 PC에서 수행해 주세요."
            )

        # 1. 마크다운 파일 안전 삭제
        deleted_files = []
        if doc and doc.target_md_path:
            md_path = Path(doc.target_md_path)
            if md_path.exists():
                safe_remove_file(md_path)
                deleted_files.append(str(md_path))

        # 기본 docs_dir 내 md 파일도 안전 삭제
        for candidate_name in [f"{target_id}.md", f"{doc_id}.md"]:
            cand_path = settings.docs_dir / candidate_name
            if cand_path.exists():
                safe_remove_file(cand_path)
                deleted_files.append(str(cand_path))

        # AI 생성 보고서 디렉터리(reports_dir) 내 md 파일도 안전 삭제
        reports_dir = settings.wiki_db_dir / "reports"
        if reports_dir.exists():
            for cand_report in [f"{target_id}.md", f"{doc_id}.md"]:
                cand_report_path = reports_dir / cand_report
                if cand_report_path.exists():
                    safe_remove_file(cand_report_path)
                    deleted_files.append(str(cand_report_path))
            if target_id.startswith("REPORT_") or doc_id.startswith("REPORT_"):
                for f in reports_dir.glob("*.md"):
                    if f.stem == target_id or f.stem == doc_id or target_id in f.stem or doc_id in f.stem:
                        safe_remove_file(f)
                        deleted_files.append(str(f))

        # 2. 에셋 디렉터리 및 내부 이미지 전면 안전 삭제
        deleted_asset_dirs = []
        for candidate_dir_name in [target_id, doc_id]:
            asset_path = settings.assets_dir / candidate_dir_name
            if asset_path.exists() and asset_path.is_dir():
                safe_remove_dir(asset_path)
                deleted_asset_dirs.append(str(asset_path))

        # 3. manifest에서 제거
        manifest_mgr.delete_document(target_id)
        if doc_id != target_id:
            manifest_mgr.delete_document(doc_id)

        logger.info(f"문서 삭제 완료: ID={target_id}, 마크다운={deleted_files}, 에셋={deleted_asset_dirs}")
        return {
            "message": "문서와 관련 에셋이 성공적으로 삭제되었습니다.",
            "deleted_id": target_id,
            "deleted_files_count": len(deleted_files),
            "deleted_assets_dirs": deleted_asset_dirs
        }

    @app.post("/api/documents/{doc_id}/audit")
    async def audit_document_endpoint(doc_id: str):
        """특정 문서의 무결성 및 품질 검사를 단독 실행한다 (Dry-Run)."""
        doc = _find_document_entry(doc_id, manifest_mgr)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        md_path = Path(doc.target_md_path) if doc.target_md_path else settings.docs_dir / f"{doc.id}.md"
        if not md_path.exists():
            raise HTTPException(status_code=404, detail="마크다운 파일이 존재하지 않습니다.")

        source_path = Path(doc.source_path)
        if not source_path.exists():
            alt_source = settings.source_dir / doc.original_filename
            if alt_source.exists():
                source_path = alt_source

        doc_asset_dir = settings.assets_dir / doc.id
        auditor = AuditAgent(docs_dir=settings.docs_dir)
        report = auditor.audit_document(
            doc_id=doc.id,
            source_path=source_path,
            md_path=md_path,
            assets_dir=doc_asset_dir if doc_asset_dir.exists() else None,
        )
        return report.to_dict()

    @app.post("/api/documents/{doc_id}/heal")
    async def heal_document_endpoint(doc_id: str):
        """특정 문서의 품질 결함에 대해 자율 치유(Tier 1 서식 정돈 / Tier 2 완본 재인제스트)를 실행한다."""
        doc = _find_document_entry(doc_id, manifest_mgr)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        engine = getattr(agent, "engine", None)
        if not engine:
            from app.kordoc_wiki_agent import KordocWikiAgent
            engine = KordocWikiAgent(docs_dir=settings.docs_dir, assets_dir=settings.assets_dir)

        auditor = AuditAgent(docs_dir=settings.docs_dir)
        success, message, report = auditor.audit_and_heal_single(
            doc_id=doc.id,
            manifest_mgr=manifest_mgr,
            engine=engine,
            source_dir=settings.source_dir,
            docs_dir=settings.docs_dir,
            assets_dir=settings.assets_dir,
        )

        # 치유 후 최신 본문 로드
        updated_doc = _find_document_entry(doc.id, manifest_mgr)
        md_path = Path(updated_doc.target_md_path) if updated_doc.target_md_path else settings.docs_dir / f"{updated_doc.id}.md"
        content = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""

        return {
            "success": success,
            "message": message,
            "report": report.to_dict() if report else None,
            "document": DocumentDetailResponse(
                id=updated_doc.id,
                original_filename=updated_doc.original_filename,
                file_hash=updated_doc.file_hash,
                file_size=updated_doc.file_size,
                modified_time=updated_doc.modified_time,
                status=updated_doc.status,
                ingested_at=updated_doc.ingested_at,
                title=updated_doc.title,
                error_message=updated_doc.error_message,
                content=content
            )
        }

    @app.get("/api/assets/{doc_id}/{filename:path}")
    async def serve_asset(doc_id: str, filename: str):
        """추출된 이미지 및 도표 에셋 파일을 반환한다.
        로컬 캐시에 파일이 없을 경우 Google Drive 온디맨드 스트리밍/캐싱으로 자동 복구한다.
        """
        clean_doc_id = urllib.parse.unquote(doc_id)
        clean_filename = urllib.parse.unquote(filename)
        safe_filename = Path(clean_filename).name

        target_dir = settings.assets_dir / clean_doc_id
        if not target_dir.exists():
            target_dir = settings.assets_dir / doc_id

        if not target_dir.exists() and settings.assets_dir.exists():
            for d in settings.assets_dir.iterdir():
                if d.is_dir() and (d.name == clean_doc_id or d.name == doc_id or clean_doc_id in d.name):
                    target_dir = d
                    break

        file_path = target_dir / safe_filename
        if not file_path.exists() or not file_path.is_file():
            if target_dir.exists() and target_dir.is_dir():
                for f in target_dir.iterdir():
                    if f.is_file() and (f.name.lower() == safe_filename.lower() or f.name.lower() == clean_filename.lower()):
                        file_path = f
                        break

        # 로컬에 없을 경우 Google Drive / 미러 스토리지에서 온디맨드 페치 및 로컬 캐싱
        if (not file_path.exists() or not file_path.is_file()) and gdrive_storage is not None:
            fetched_path = gdrive_storage.ensure_asset_file(
                doc_id=clean_doc_id,
                filename=safe_filename,
                assets_dir=settings.assets_dir,
            )
            if fetched_path and fetched_path.exists() and fetched_path.is_file():
                file_path = fetched_path

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"이미지 파일을 찾을 수 없습니다: {filename}")

        # 에셋 디렉터리 경로 이탈(Path Traversal) 검증
        try:
            file_path.resolve().relative_to(settings.assets_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="허용되지 않은 파일 경로입니다.")

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
        """웹 화면에서 Source 폴더로 직접 파일을 업로드한다.
        
        보안: 경로 순회 방지, 클라우드 모드 제한, 확장자 화이트리스트 및 파일 크기(최대 50MB) 검증을 수행한다.
        """
        # 1. 클라우드 모드에서는 임시 디스크 고갈 및 원본 불일치 방지를 위해 직접 업로드 차단
        if settings.storage_mode == "gdrive":
            raise HTTPException(
                status_code=403,
                detail="클라우드(웹) 모드에서는 직접 파일 업로드가 비활성화되어 있습니다. 로컬 PC의 Source 폴더에 문서를 투입하면 자동 동기화됩니다."
            )

        raw_name = file.filename or ""
        safe_name = Path(raw_name).name.strip()
        if not safe_name or safe_name.startswith("."):
            raise HTTPException(status_code=400, detail="유효하지 않은 파일명입니다.")

        # 2. 확장자 화이트리스트 검사
        ext = Path(safe_name).suffix.lower()
        if ext not in settings.supported_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"지원되지 않는 파일 형식입니다 ({ext}). 지원 형식: {', '.join(sorted(settings.supported_extensions))}"
            )

        # 3. 최대 50MB 용량 제한 검증
        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="파일 크기가 너무 큽니다. 최대 50MB까지 업로드 가능합니다.")

        target_path = settings.source_dir / safe_name
        with open(target_path, "wb") as buffer:
            buffer.write(file_content)
        
        # 에이전트가 존재하면 즉시 변환 처리
        if agent is not None:
            agent.process_file(target_path)

        return {"filename": safe_name, "message": "파일 업로드 및 처리 완료"}


    @app.post("/api/reconcile")
    async def trigger_reconcile():
        """디스크의 마크다운 및 에셋과 Manifest 간의 동기화 및 자가 치유를 즉시 수행한다."""
        result = manifest_mgr.reconcile_with_disk(settings.docs_dir, settings.assets_dir)
        return {
            "message": "WikiDB 자가 치유 및 동기화 완료",
            **result
        }

    @app.post("/api/cloud/sync")
    async def trigger_cloud_sync():
        """클라우드/스마트폰 화면에서 Google Drive 원격 번들 및 신규 보고서를 수동 동기화한다."""
        sync_res = gdrive_storage.bootstrap_from_remote(settings.wiki_db_dir) if gdrive_storage else {}
        heal_res = manifest_mgr.reconcile_with_disk(settings.docs_dir, settings.assets_dir)
        return {
            "message": "Google Drive 동기화 및 WikiDB 갱신 완료",
            "sync": sync_res,
            "reconcile": heal_res,
        }

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
            "wiki_db_dir": str(settings.wiki_db_dir),
            "storage_mode": settings.storage_mode,
            "gdrive_configured": gdrive_storage.is_configured if gdrive_storage else False,
        }

    return app
