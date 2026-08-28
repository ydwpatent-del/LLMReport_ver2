"""FastAPI 웹 서버 및 REST API 라우터."""

import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.manifest import ManifestManager, DocumentEntry
from app.ingest_agent import IngestAgent

class DocumentResponse(BaseModel):
    """문서 목록 반환용 DTO."""
    id: str
    original_filename: str
    file_size: int
    modified_time: float
    status: str
    ingested_at: str
    title: str
    error_message: Optional[str] = None

class DocumentDetailResponse(DocumentResponse):
    """문서 상세 및 본문 내용 반환용 DTO."""
    content: str

def create_app(
    settings: Optional[Settings] = None,
    manifest_mgr: Optional[ManifestManager] = None,
    agent: Optional[IngestAgent] = None
) -> FastAPI:
    """FastAPI 애플리케이션 인스턴스를 팩토리 패턴으로 생성한다."""
    if settings is None:
        settings = get_settings()
    if manifest_mgr is None:
        manifest_mgr = ManifestManager(settings.manifest_path)

    app = FastAPI(
        title="LLM Wiki Knowledge Ingestion Server",
        description="무삭제 문서 변환 및 지식 데이터베이스 서빙 API",
        version="1.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_no_cache_header(request, call_next):
        """개발 및 실시간 업데이트 중 브라우저 캐시로 인한 구버전 실행을 방지한다."""
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path.startswith("/api") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        """대시보드 메인 HTML을 반환한다."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>LLM Wiki Server is Running</h1>")

    @app.get("/api/documents", response_model=list[DocumentResponse])
    async def list_documents():
        """인제스트된 모든 문서 목록을 반환한다."""
        docs = manifest_mgr.get_all_documents()
        return sorted(docs, key=lambda d: d.ingested_at, reverse=True)

    @app.get("/api/documents/{doc_id:path}", response_model=DocumentDetailResponse)
    async def get_document_detail(doc_id: str):
        """특정 문서의 메타데이터와 마크다운 본문을 반환한다."""
        import urllib.parse
        clean_id = urllib.parse.unquote(doc_id)
        doc = manifest_mgr.get_document(clean_id) or manifest_mgr.get_document(doc_id)
        if not doc:
            # 부분 일치 검색 시도 (안전망)
            for d in manifest_mgr.get_all_documents():
                if d.id == clean_id or d.id == doc_id or d.title == clean_id:
                    doc = d
                    break
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        md_path = Path(doc.target_md_path)
        content = ""
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8", errors="replace")

        return DocumentDetailResponse(
            id=doc.id,
            original_filename=doc.original_filename,
            file_size=doc.file_size,
            modified_time=doc.modified_time,
            status=doc.status,
            ingested_at=doc.ingested_at,
            title=doc.title,
            error_message=doc.error_message,
            content=content
        )

    @app.get("/api/assets/{doc_id}/{filename:path}")
    async def serve_asset(doc_id: str, filename: str):
        """추출된 이미지 및 도표 에셋 파일을 반환한다."""
        import urllib.parse
        clean_doc_id = urllib.parse.unquote(doc_id)
        clean_filename = urllib.parse.unquote(filename)
        safe_filename = Path(clean_filename).name

        target_dir = settings.assets_dir / clean_doc_id
        if not target_dir.exists():
            # 인코딩되지 않은 doc_id로도 시도
            target_dir = settings.assets_dir / doc_id

        if not target_dir.exists():
            # 부분 일치 검색 (안전망)
            for d in settings.assets_dir.iterdir():
                if d.is_dir() and (d.name == clean_doc_id or d.name == doc_id or clean_doc_id in d.name):
                    target_dir = d
                    break

        file_path = target_dir / safe_filename
        if not file_path.exists() or not file_path.is_file():
            # 디렉토리 내 대소문자 무시 검색
            if target_dir.exists() and target_dir.is_dir():
                for f in target_dir.iterdir():
                    if f.is_file() and (f.name.lower() == safe_filename.lower() or f.name.lower() == clean_filename.lower()):
                        file_path = f
                        break

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"이미지 파일을 찾을 수 없습니다: {filename}")

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
        """웹 화면에서 Source 폴더로 직접 파일을 업로드한다."""
        target_path = settings.source_dir / file.filename
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 에이전트가 존재하면 즉시 변환 처리
        if agent is not None:
            agent.process_file(target_path)

        return {"filename": file.filename, "message": "파일 업로드 및 처리 완료"}

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
            "wiki_db_dir": str(settings.wiki_db_dir)
        }

    return app
