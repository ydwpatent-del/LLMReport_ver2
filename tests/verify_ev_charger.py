"""전기차 충전기 문서 재인제스트 및 image_004 누락 방지 실증 검증 스크립트."""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VerifyEVCharger")

from app.config import get_settings
from app.manifest import ManifestManager
from app.kordoc_wiki_agent import KordocWikiAgent
from app.ingest_agent import IngestAgent
from app.utils import safe_remove_file, safe_remove_dir

def verify_ev_charger():
    settings = get_settings()
    manifest_mgr = ManifestManager(settings.manifest_path)
    engine = KordocWikiAgent(docs_dir=settings.docs_dir, assets_dir=settings.assets_dir)
    agent = IngestAgent(
        source_dir=settings.source_dir,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts=settings.supported_extensions
    )

    filename = "통합_C28119106_전기차 충전기_20250327_R.pdf"
    source_path = settings.source_dir / filename

    if not source_path.exists():
        logger.error(f"원본 파일 없음: {source_path}")
        return

    # 1. 기존 문서 정리
    for d in manifest_mgr.get_all_documents():
        if "전기차" in d.original_filename or "C28119106" in d.original_filename:
            if d.target_md_path and Path(d.target_md_path).exists():
                safe_remove_file(Path(d.target_md_path))
            if d.assets_dir and Path(d.assets_dir).exists():
                safe_remove_dir(Path(d.assets_dir))
            manifest_mgr.delete_document(d.id)
            logger.info(f"기존 매니페스트 및 파일 삭제: {d.id}")

    # docs 및 assets 내 잔여 전기차 파일들도 안전 정리
    for f in settings.docs_dir.glob("*전기차*.md"):
        safe_remove_file(f)
    for f in settings.docs_dir.glob("*C28119106*.md"):
        safe_remove_file(f)

    logger.info(f"🚀 '{filename}' 재인제스트 시작...")
    ok = agent.process_file(source_path, debounce=0.0)

    if not ok:
        logger.error("❌ 재인제스트 실패!")
        return

    logger.info("✅ 재인제스트 완료! 결과 검증 진행 중...")
    docs = [d for d in manifest_mgr.get_all_documents() if "전기차" in d.original_filename or "C28119106" in d.original_filename]
    if not docs:
        logger.error("매니페스트에 등록된 문서 없음!")
        return

    doc = docs[0]
    md_file = Path(doc.target_md_path)
    asset_dir = Path(doc.assets_dir)

    print(f"\n==========================================")
    print(f"문서 ID: {doc.id}")
    print(f"마크다운 파일: {md_file.name}")
    print(f"에셋 디렉터리: {asset_dir.name}")

    # 에셋 폴더 내 image_004 존재 검증
    img_004_path = asset_dir / "image_004.png"
    print(f"에셋 내 image_004.png 존재 여부: {img_004_path.exists()}")
    if img_004_path.exists():
        print(f"  image_004.png 크기: {img_004_path.stat().st_size} bytes")

    # 마크다운 본문 내 image_004 태그 검증
    md_text = md_file.read_text(encoding="utf-8")
    import re
    tags = re.findall(r'!\[.*?\]\([^\)]+\)', md_text)
    print(f"\n마크다운 본문 내 총 이미지 태그 수: {len(tags)}개")
    tags_004 = [t for t in tags if "image_004.png" in t]
    print(f"image_004.png 태그 개수: {len(tags_004)}개")
    for t in tags_004:
        print(f"  -> {t}")

    # 전후 문맥 위치 확인
    pos = md_text.find("image_004.png")
    if pos != -1:
        start_ctx = max(0, pos - 150)
        end_ctx = min(len(md_text), pos + 150)
        print(f"\n[image_004.png 주변 본문 문맥]:")
        print(md_text[start_ctx:end_ctx])
    print(f"==========================================\n")

if __name__ == "__main__":
    verify_ev_charger()
