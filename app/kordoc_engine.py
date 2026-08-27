"""kordoc CLI를 호출하여 문서를 100% 무삭제 마크다운으로 변환하고 이미지를 인라인 보정하는 엔진."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.ai_refiner import AIRefiner

logger = logging.getLogger("KordocEngine")

# 지원 이미지 확장자
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".gif", ".tiff"}

class KordocEngine:
    """kordoc CLI 기반 문서 파싱 및 AI 위키 지식 정돈 엔진."""

    def __init__(self, docs_dir: Path, assets_dir: Path, refiner: Optional[AIRefiner] = None):
        self.docs_dir = docs_dir
        self.assets_dir = assets_dir
        self.refiner = refiner or AIRefiner()
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _generate_metadata_header(self, title: str, original_name: str, file_hash: str, ext: str) -> str:
        """LLM Wiki 및 RAG용 표준 kordoc-wiki-ingest 메타데이터 헤더를 생성한다."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        format_name = ext.lstrip('.').upper() or "문서"
        return (
            f"# {title}\n\n"
            f"> - **원본 파일명**: `{original_name}`\n"
            f"> - **원본형식**: `{format_name}`\n"
            f"> - **인제스트 일시**: `{now}`\n"
            f"> - **파일 무결성 해시 (SHA-256)**: `{file_hash}`\n"
            f"> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)\n"
            f"> - **문서 분류**: LLM Wiki Ground Truth Source\n\n"
            f"---\n\n"
        )

    def _run_kordoc_lint(self, md_path: Path) -> None:
        """kordoc-wiki-ingest Phase 6: 생성된 마크다운에 대해 kordoc lint 자가 검증을 수행한다."""
        try:
            cmd = f'cmd /c npx -y kordoc@^4 lint "{md_path.resolve()}"'
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
            if res.returncode == 0:
                logger.info(f"kordoc lint 자가 검증 통과: {md_path.name}")
            else:
                logger.warning(f"kordoc lint 검증 경고 ({md_path.name}): {res.stdout or res.stderr}")
        except Exception as e:
            logger.warning(f"kordoc lint 실행 중 오류 (무시됨): {e}")

    def _process_and_inline_images(
        self,
        raw_md: str,
        doc_id: str,
        doc_asset_dir: Path,
        search_dirs: list[Path]
    ) -> tuple[str, list[Path]]:
        """마크다운 본문 내의 모든 이미지 참조를 탐색하여 에셋을 복사하고 웹 인라인 경로로 치환한다."""
        extracted_images: list[Path] = []
        doc_asset_dir.mkdir(parents=True, exist_ok=True)

        # 1. 탐색 디렉토리 내의 모든 이미지 파일 인덱싱 (파일명 -> 실제 경로)
        available_images: dict[str, Path] = {}
        for search_dir in search_dirs:
            if search_dir and search_dir.exists():
                for img_path in search_dir.rglob("*"):
                    if img_path.is_file() and img_path.suffix.lower() in IMAGE_EXTENSIONS:
                        available_images[img_path.name.lower()] = img_path
                        # 디렉토리 포함 상대 경로도 등록
                        try:
                            rel = img_path.relative_to(search_dir)
                            available_images[str(rel).replace("\\", "/").lower()] = img_path
                        except ValueError:
                            pass

        def resolve_and_copy_image(ref_path: str) -> Optional[str]:
            """참조된 이미지 경로를 찾아 doc_asset_dir로 복사하고 웹 경로를 반환한다."""
            clean_ref = ref_path.strip().strip("'\"").replace("\\", "/")
            if clean_ref.startswith(("http://", "https://", "data:", "/api/assets/")):
                return clean_ref

            filename = Path(clean_ref).name
            matched_src: Optional[Path] = None

            # 1) 상대경로 직접 매칭 시도
            for search_dir in search_dirs:
                direct_path = (search_dir / clean_ref).resolve()
                if direct_path.exists() and direct_path.is_file():
                    matched_src = direct_path
                    break

            # 2) 파일명 기반 인덱스 매칭 시도
            if not matched_src:
                matched_src = available_images.get(clean_ref.lower()) or available_images.get(filename.lower())

            if matched_src and matched_src.exists():
                target_file = doc_asset_dir / matched_src.name
                shutil.copy2(matched_src, target_file)
                if target_file not in extracted_images:
                    extracted_images.append(target_file)
                return f"/api/assets/{doc_id}/{matched_src.name}"

            # 파일을 디스크에서 찾지 못했더라도 웹 API 규격 경로로 안전하게 매핑
            return f"/api/assets/{doc_id}/{filename}"

        # 2. 마크다운 문법 치환: ![alt](url "title")
        def replace_md_img(match):
            alt = match.group(1)
            raw_url = match.group(2).strip()
            # title 속성 분리 (e.g. url "title")
            url_parts = raw_url.split(maxsplit=1)
            url = url_parts[0]
            title_part = f' {url_parts[1]}' if len(url_parts) > 1 else ''
            
            new_url = resolve_and_copy_image(url)
            return f'![{alt}]({new_url}{title_part})'

        adjusted_md = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_md_img, raw_md)

        # 3. HTML img 태그 치환: <img ... src="url" ...>
        def replace_html_img(match):
            before = match.group(1)
            src = match.group(2)
            after = match.group(3)
            new_src = resolve_and_copy_image(src)
            return f'<img {before}src="{new_src}"{after}>'

        adjusted_md = re.sub(
            r'<img\s+([^>]*?)src=["\'](.*?)["\']([^>]*?)>',
            replace_html_img,
            adjusted_md,
            flags=re.IGNORECASE
        )

        return adjusted_md, extracted_images

    def convert(
        self,
        source_path: Path,
        doc_id: str,
        file_hash: str,
        enable_ocr: bool = False,
        page_range: Optional[str] = None
    ) -> tuple[Path, list[Path], str]:
        """원본 파일을 마크다운 및 이미지 에셋으로 변환하여 저장한다."""
        title = source_path.stem
        target_md_path = self.docs_dir / f"{doc_id}.md"
        doc_asset_dir = self.assets_dir / doc_id
        doc_asset_dir.mkdir(parents=True, exist_ok=True)

        ext = source_path.suffix.lower()
        source_parent = source_path.parent

        # 1. 텍스트 또는 마크다운 파일 직접 처리
        if ext in {".txt", ".md"}:
            raw_content = source_path.read_text(encoding="utf-8", errors="replace")
            search_dirs = [
                source_parent,
                source_parent / "images",
                source_parent / f"{source_path.stem}_images",
                self.assets_dir / doc_id
            ]
            adjusted_md, extracted_images = self._process_and_inline_images(
                raw_content, doc_id, doc_asset_dir, search_dirs
            )

            # AI 위키 지식 리파이닝 적용
            final_md, meta = self.refiner.refine_text(
                raw_md=adjusted_md,
                doc_id=doc_id,
                original_filename=source_path.name,
                file_hash=file_hash
            )
            target_md_path.write_text(final_md, encoding="utf-8")
            return target_md_path, extracted_images, meta["title"]

        # 2. HWP, HWPX, PDF, DOCX, XLSX 등 복합 문서는 kordoc CLI 호출
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_out_md = Path(temp_dir) / "output_raw.md"
            
            flags = []
            if enable_ocr:
                flags.append("--ocr --formula-ocr")
            if page_range:
                flags.append(f"-p {page_range}")

            flag_str = " " + " ".join(flags) if flags else ""
            cmd = f'cmd /c npx -y kordoc@^4 "{source_path.resolve()}" -o "{temp_out_md.resolve()}"{flag_str}'
            
            logger.info(f"kordoc 파싱 시작: {cmd}")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            if not temp_out_md.exists():
                error_detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"kordoc 변환 실패 (코드: {result.returncode}): {error_detail}")

            raw_md = temp_out_md.read_text(encoding="utf-8", errors="replace")

            # 임시 폴더 내의 추출 이미지 인라인 보정 및 복사
            search_dirs = [
                Path(temp_dir),
                Path(temp_dir) / "images",
                source_parent,
                source_parent / "images"
            ]
            adjusted_md, extracted_images = self._process_and_inline_images(
                raw_md, doc_id, doc_asset_dir, search_dirs
            )

            # AI 위키 지식 리파이닝 적용
            final_md, meta = self.refiner.refine_text(
                raw_md=adjusted_md,
                doc_id=doc_id,
                original_filename=source_path.name,
                file_hash=file_hash
            )
            target_md_path.write_text(final_md, encoding="utf-8")

            # kordoc lint 자가 검증 실행
            self._run_kordoc_lint(target_md_path)

        return target_md_path, extracted_images, meta["title"]
