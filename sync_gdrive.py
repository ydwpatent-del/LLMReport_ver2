"""로컬 PC의 WikiDB 데이터를 텍스트 번들(wiki_text_bundle.zip)로 패키징하거나
Google Drive(데스크톱 마운트 폴더 또는 REST API)와 동기화하는 CLI 스크립트.

사용 예시:
1. 인증 없이 텍스트 번들(manifest + docs + reports) 압축만 생성:
   python sync_gdrive.py --pack-only

2. PC에 설치된 구글 드라이브 데스크톱 폴더로 동기화 (API 키 불필요):
   python sync_gdrive.py --target-dir "G:\\내 드라이브\\LLMwiki_DB"

3. Google Drive API 설정 후 원격 업로드/동기화:
   python sync_gdrive.py push
   python sync_gdrive.py pull
"""

import argparse
import logging
import sys
from pathlib import Path

from app.config import get_settings
from app.gdrive_storage import GDriveStorageManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SyncGDriveCLI")


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki Google Drive 하이브리드 동기화 도구")
    parser.add_argument(
        "action",
        nargs="?",
        default="pack",
        choices=["pack", "push", "pull", "index"],
        help="수행할 작업: pack(번들 생성), push(업로드), pull(가져오기), index(원격 이미지 매핑 인덱싱)",
    )
    parser.add_argument(
        "--pack-only",
        action="store_true",
        help="Google Drive 인증 없이 로컬 WikiDB/wiki_text_bundle.zip 파일만 즉시 생성합니다.",
    )
    parser.add_argument(
        "--target-dir",
        type=str,
        default=None,
        help="구글 드라이브 데스크톱(로컬 마운트) 경로 지정 시 API 인증 없이 해당 폴더와 동기화합니다.",
    )
    parser.add_argument(
        "--skip-assets",
        action="store_true",
        help="이미지(assets/) 복사를 건너뛰고 텍스트 번들 및 보고서만 빠르게 동기화합니다.",
    )

    args = parser.parse_args()
    settings = get_settings()
    storage = GDriveStorageManager(settings=settings)

    # 1. --pack-only 또는 기본 pack 모드
    if args.pack_only or (args.action == "pack" and not args.target_dir):
        info = storage.create_text_bundle(settings.wiki_db_dir)
        size_mb = info["bundle_size_bytes"] / (1024 * 1024)
        logger.info("=" * 60)
        logger.info("📦 텍스트 번들 패키징 완료 (Google Drive 인증 불필요)")
        logger.info(f"   - 파일 경로: {info['bundle_path']}")
        logger.info(f"   - 포함 문서: {info['docs_count']}건 (docs/*.md)")
        logger.info(f"   - 포함 보고서: {info['reports_count']}건 (reports/*.md)")
        logger.info(f"   - 압축 용량: {size_mb:.2f} MB")
        logger.info("=" * 60)
        return 0

    # 2. 로컬 구글 드라이브 마운트 폴더(--target-dir 또는 GDRIVE_LOCAL_MIRROR_DIR) 동기화
    target_mirror = Path(args.target_dir) if args.target_dir else settings.gdrive_local_mirror_dir
    if target_mirror:
        logger.info(f"📂 로컬 Google Drive 폴더 동기화 시작: {target_mirror}")
        res = storage.sync_with_mirror_dir(
            wiki_db_dir=settings.wiki_db_dir,
            mirror_dir=target_mirror,
            include_assets=not args.skip_assets,
        )
        logger.info("=" * 60)
        logger.info("✅ 로컬 Google Drive 폴더 동기화 완료")
        logger.info(f"   - 번들 크기: {res['bundle_size_bytes'] / (1024 * 1024):.2f} MB (문서 {res['docs_count']}건)")
        logger.info(f"   - 보고서 동기화: 가져오기(Pull) {res['pulled_reports']}건 / 내보내기(Push) {res['pushed_reports']}건")
        logger.info(f"   - 에셋 이미지: 신규 복사 {res['copied_assets']}건 / 기존 유지 {res['skipped_assets']}건")
        logger.info("=" * 60)
        return 0

    # 3. Google Drive API 기반 push / pull
    if args.action == "push":
        if not storage.is_api_configured:
            logger.warning(
                "⚠️ Google Drive API 인증이 아직 설정되지 않았습니다. "
                "대신 로컬 텍스트 번들(wiki_text_bundle.zip)만 생성합니다."
            )
            storage.create_text_bundle(settings.wiki_db_dir)
            return 0

        res = storage.push_all_to_gdrive_api(
            wiki_db_dir=settings.wiki_db_dir,
            upload_assets=not args.skip_assets,
        )
        logger.info(f"✅ Google Drive API 업로드 완료: {res}")
        return 0

    if args.action == "pull":
        res = storage.bootstrap_from_remote(settings.wiki_db_dir)
        logger.info(f"✅ Google Drive 원격 동기화(Pull) 완료: {res}")
        return 0

    if args.action == "index":
        logger.info("🔍 Google Drive에 업로드된 에셋 이미지 인덱싱 및 assets_map.json 생성 중...")
        res = storage.build_remote_assets_index(settings.wiki_db_dir)
        logger.info("=" * 60)
        logger.info(f"✅ 인덱싱 완료: 총 {res.get('indexed_count', 0)}개 이미지 파일 매핑 완료")
        logger.info(f"   - 번들 파일 크기: {res.get('bundle_size_bytes', 0) / (1024 * 1024):.2f} MB")
        logger.info("=" * 60)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
