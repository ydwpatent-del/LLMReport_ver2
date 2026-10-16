"""LLM Wiki 지식 인제스트 에이전트 및 웹 대시보드 메인 실행기."""

import logging
import signal
import sys
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import get_settings
from app.manifest import ManifestManager
from app.kordoc_wiki_agent import KordocWikiAgent
from app.ingest_agent import IngestAgent
from app.audit_agent import AuditAgent
from app.server import create_app

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("LLMWikiRunner")

def main():
    """시스템 초기화 및 서버/에이전트 통합 기동 함수."""
    settings = get_settings()
    logger.info("=" * 60)
    logger.info("🚀 kordoc-wiki-ingest 기반 LLM 지능형 인제스트 시스템 기동 중...")
    logger.info(f"📂 원본 문서 투입 폴더 (Source): {settings.source_dir.resolve()}")
    logger.info(f"📚 위키 DB 저장 폴더 (WikiDB):  {settings.wiki_db_dir.resolve()}")
    logger.info("=" * 60)

    # 1. kordoc-wiki-ingest 전용 에이전트 및 매니페스트 초기화
    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocWikiAgent(docs_dir=settings.docs_dir, assets_dir=settings.assets_dir)
    agent = IngestAgent(
        source_dir=settings.source_dir,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts=settings.supported_extensions
    )

    # 2. 실시간 파일 감시 에이전트 백그라운드 시작
    agent.start()

    # 3. 초기 스캔 및 기존 마크다운 무결성 검사/자율 치유를 백그라운드 스레드로 비동기 실행
    def async_initial_scan():
        logger.info("🔍 Source 폴더 초기 동기화 스캔 실행 중 (백그라운드)...")
        proc_cnt, skip_cnt = agent.scan_now()
        logger.info(f"✅ 초기 스캔 완료: {proc_cnt}건 신규 변환 완료, {skip_cnt}건 기존 파일 유지")

    import threading
    threading.Thread(target=async_initial_scan, daemon=True).start()

    # 4. FastAPI 앱 생성
    app = create_app(settings=settings, manifest_mgr=manifest_mgr, agent=agent)

    # 5. 안전 종료 시그널 핸들러 등록
    def handle_exit(sig, frame):
        logger.info("\n🛑 시스템 종료 신호 수신. 리소스를 정리합니다...")
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # 6. Uvicorn 웹 서버 실행
    logger.info(f"🌐 로컬 및 네트워크 대시보드 웹 서버 시작:")
    logger.info(f"   👉 로컬 접속:   http://localhost:{settings.port}")
    logger.info(f"   👉 네트워크(모바일): http://0.0.0.0:{settings.port}")
    logger.info("=" * 60)

    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    finally:
        agent.stop()

if __name__ == "__main__":
    main()
