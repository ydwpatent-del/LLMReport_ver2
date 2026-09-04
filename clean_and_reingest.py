"""기존 산출물 정리 및 Source 문서 전체 재인제스트 실행 스크립트."""

import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone

from app.config import get_settings
from app.manifest import ManifestManager, ManifestData
from app.kordoc_wiki_agent import KordocWikiAgent
from app.ingest_agent import IngestAgent
from app.utils import safe_remove_file, safe_remove_dir

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ReingestRunner")

def clean_wikidb():
    """WikiDB 내의 기존 마크다운, 에셋 이미지, 매니페스트를 완전 초기화한다."""
    settings = get_settings()
    logger.info("🧹 기존 WikiDB 산출물 정리 시작...")

    # 1. docs 디렉터리 내 md 파일 안전 삭제
    if settings.docs_dir.exists():
        for md_file in settings.docs_dir.glob("*.md"):
            safe_remove_file(md_file)
            logger.info(f"   - 마크다운 삭제: {md_file.name}")

    # 2. assets 디렉터리 내 에셋 폴더 안전 삭제
    if settings.assets_dir.exists():
        for asset_item in settings.assets_dir.iterdir():
            if asset_item.is_dir():
                safe_remove_dir(asset_item)
                logger.info(f"   - 에셋 폴더 삭제: {asset_item.name}")
            elif asset_item.is_file():
                safe_remove_file(asset_item)

    # 3. manifest.json 초기화
    empty_manifest = ManifestData(
        version="1.0.0",
        last_updated=datetime.now(timezone.utc).isoformat(),
        documents={}
    )
    with open(settings.manifest_path, "w", encoding="utf-8") as f:
        f.write(empty_manifest.model_dump_json(indent=2))
    logger.info("✅ manifest.json 초기화 완료")
    logger.info("=" * 60)

def run_reingestion():
    """Source 폴더 내 문서를 현재 개선된 코드로 순차 재인제스트한다."""
    settings = get_settings()
    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocWikiAgent(docs_dir=settings.docs_dir, assets_dir=settings.assets_dir)
    agent = IngestAgent(
        source_dir=settings.source_dir,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts=settings.supported_extensions
    )

    source_files = sorted([
        f for f in settings.source_dir.glob("*.*")
        if f.suffix.lower() in settings.supported_extensions
    ])

    logger.info(f"🚀 총 {len(source_files)}개 문서 재인제스트 시작 (Source 폴더):")
    for f in source_files:
        logger.info(f"   📄 {f.name} ({f.stat().st_size / 1024:.1f} KB)")
    logger.info("=" * 60)

    success_count = 0
    fail_count = 0

    for idx, file_path in enumerate(source_files, 1):
        logger.info(f"\n[{idx}/{len(source_files)}] 처리 중: {file_path.name}")
        try:
            ok = agent.process_file(file_path, debounce=0.0)
            if ok:
                success_count += 1
                logger.info(f"[{idx}/{len(source_files)}] ✅ 성공: {file_path.name}")
            else:
                fail_count += 1
                logger.warning(f"[{idx}/{len(source_files)}] ⚠️ 건너뜀/실패: {file_path.name}")
        except Exception as e:
            fail_count += 1
            logger.error(f"[{idx}/{len(source_files)}] ❌ 예외 발생: {file_path.name} - {e}")

    logger.info("\n" + "=" * 60)
    logger.info(f"🏁 전체 재인제스트 완료! (성공: {success_count}건, 실패/스킵: {fail_count}건)")
    
    docs = manifest_mgr.get_all_documents()
    logger.info(f"📚 WikiDB 최종 등록 문서: {len(docs)}건")
    for d in docs:
        logger.info(f"   - [{d.status}] {d.title} (ID: {d.id}) -> {Path(d.target_md_path).name}")
    logger.info("=" * 60)

if __name__ == "__main__":
    clean_wikidb()
    run_reingestion()
