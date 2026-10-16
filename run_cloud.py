"""스마트폰/외부 접속용 클라우드 서버 전용 실행 엔트리포인트.

로컬 PC용 run.py와 완전히 분리되어 작동하며:
1. watchdog 로컬 파일 감시기를 기동하지 않아 컨테이너 리소스를 절약한다.
2. 서버 시작 시 Google Drive(또는 내장된 wiki_text_bundle.zip)에서 24MB 텍스트 데이터를
   즉시 복원하여 0.1초 내 초고속 검색 및 AI 보고서 생성을 지원한다.
3. 1.42GB 규모의 도표 이미지(assets/)는 문서 열람 및 HTML/PDF 내보내기 시점에
   Google Drive에서 온디맨드로 스트리밍 및 캐싱한다.
"""

import logging
import os
import uvicorn

# 클라우드 엔트리포인트에서는 기본 STORAGE_MODE를 gdrive로 설정
os.environ.setdefault("STORAGE_MODE", "gdrive")

from app.config import get_settings
from app.gdrive_storage import get_gdrive_storage
from app.manifest import ManifestManager
from app.server import create_app

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("LLMWikiCloudRunner")


def build_cloud_app():
    """클라우드 환경용 FastAPI 앱을 부트스트랩하여 반환한다."""
    settings = get_settings()
    storage = get_gdrive_storage(settings)

    logger.info("=" * 60)
    logger.info("☁️ LLM Wiki 모바일/클라우드 서버 기동 중...")
    logger.info(f"   - 스토리지 모드: {settings.storage_mode}")
    logger.info(f"   - Google Drive 연동 설정 여부: {storage.is_configured}")
    logger.info(f"   - 모바일 PIN 잠금 활성화 여부: {bool(settings.wiki_access_pin)}")

    # 1. Google Drive 또는 내장 번들에서 텍스트 데이터(manifest, docs, reports) 부트스트랩
    boot_res = storage.bootstrap_from_remote(settings.wiki_db_dir)
    logger.info(f"   - 초기 번들 동기화 결과: {boot_res}")

    # 2. ManifestManager 초기화 및 디스크 상태 자가 치유(경로 동기화 및 누락 문서 복구)
    manifest_mgr = ManifestManager(settings.manifest_path)
    heal_res = manifest_mgr.reconcile_with_disk(settings.docs_dir, settings.assets_dir)
    logger.info(f"   - 디스크 정합성 자가 치유 결과: {heal_res}")
    logger.info(f"   - 최종 유효 등록 문서 수: {len(manifest_mgr.get_all_documents())}건")
    logger.info("=" * 60)

    return create_app(
        settings=settings,
        manifest_mgr=manifest_mgr,
        agent=None,
        gdrive_storage=storage,
    )


app = build_cloud_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
