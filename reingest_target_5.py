"""오늘 생성된 5개 문서에 대해 수정된 범용 필터를 적용하여 재인제스트를 수행하는 스크립트."""

import sys
import logging
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

from app.config import get_settings
from app.manifest import ManifestManager
from app.kordoc_wiki_agent import KordocWikiAgent
from app.ingest_agent import IngestAgent
from app.utils import safe_remove_file, safe_remove_dir

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TargetedReingest")

TARGET_FILES = [
    "통합_C20499_퀀텀닷_20260609_R.pdf",
    "통합_C26294101_스마트폰용 센서_20260616_N.pdf",
    "통합_C26310800_양자 컴퓨팅_20260529_R.pdf",
    "통합_C26429204_저궤도 위성_20260528_N.pdf",
    "통합_J58222_기업자산관리(EAM) 소프트웨어_20260529_R.pdf",
]

def reingest_targeted_files():
    settings = get_settings()
    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocWikiAgent(docs_dir=settings.docs_dir, assets_dir=settings.assets_dir)
    agent = IngestAgent(
        source_dir=settings.source_dir,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts=settings.supported_extensions
    )

    all_docs = manifest_mgr.get_all_documents()

    for filename in TARGET_FILES:
        source_path = settings.source_dir / filename
        if not source_path.exists():
            logger.warning(f"파일이 존재하지 않습니다: {filename}")
            continue

        logger.info(f"\n==================================================")
        logger.info(f"🔄 재인제스트 시작: {filename}")
        
        # 1. 기존 매니페스트 및 파일 정리
        matched_docs = [
            d for d in all_docs
            if d.original_filename == filename or filename in d.original_filename
        ]
        for d in matched_docs:
            if d.target_md_path and Path(d.target_md_path).exists():
                safe_remove_file(Path(d.target_md_path))
                logger.info(f"  기존 마크다운 삭제: {Path(d.target_md_path).name}")
            if d.assets_dir and Path(d.assets_dir).exists():
                safe_remove_dir(Path(d.assets_dir))
                logger.info(f"  기존 에셋 폴더 삭제: {Path(d.assets_dir).name}")
            manifest_mgr.delete_document(d.id)
            logger.info(f"  기존 매니페스트 삭제: {d.id}")

        # 2. 재변환 실행
        ok = agent.process_file(source_path, debounce=0.0)
        if ok:
            logger.info(f"✅ 재변환 성공: {filename}")
        else:
            logger.error(f"❌ 재변환 실패: {filename}")

    logger.info(f"\n==================================================")
    logger.info("🏁 5개 대상 문서 재인제스트 완료. 결과 검증 중...")

    # 검증: 각 문서의 마크다운 내 이미지 태그 확인
    manifest_mgr = ManifestManager(settings.manifest_path)
    updated_docs = manifest_mgr.get_all_documents()
    import re

    for filename in TARGET_FILES:
        doc = next((d for d in updated_docs if d.original_filename == filename), None)
        if doc and doc.target_md_path and Path(doc.target_md_path).exists():
            content = Path(doc.target_md_path).read_text(encoding="utf-8")
            tags = re.findall(r'!\[.*?\]\([^\)]+\)', content)
            print(f"\n📄 {filename} (ID: {doc.id}):")
            print(f"   마크다운 경로: {Path(doc.target_md_path).name}")
            print(f"   추출된 이미지 태그 수: {len(tags)}개")
            for t in tags:
                print(f"     {t}")
        else:
            print(f"\n❌ {filename}: 마크다운 파일 없음!")

if __name__ == "__main__":
    reingest_targeted_files()
