"""kordoc CLI를 호출하여 문서를 100% 무삭제 마크다운으로 변환하고 이미지를 인라인 보정하는 엔진."""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from app.ai_refiner import AIRefiner
from app.utils import run_kordoc_lint, generate_standard_metadata_header

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
        return generate_standard_metadata_header(
            title=title,
            original_filename=original_name,
            file_hash=file_hash,
            ext=ext,
            category="LLM Wiki Ground Truth Source"
        )

    def _run_kordoc_lint(self, md_path: Path) -> None:
        """kordoc-wiki-ingest Phase 6: 생성된 마크다운에 대해 kordoc lint 자가 검증을 수행한다."""
        run_kordoc_lint(md_path)

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

        available_images: dict[str, Path] = {}
        for search_dir in search_dirs:
            if search_dir and search_dir.exists():
                for img_path in search_dir.rglob("*"):
                    if img_path.is_file() and img_path.suffix.lower() in IMAGE_EXTENSIONS:
                        available_images[img_path.name.lower()] = img_path
                        try:
                            rel = img_path.relative_to(search_dir)
                            available_images[str(rel).replace("\\", "/").lower()] = img_path
                        except ValueError:
                            pass

        def resolve_and_copy_image(ref_path: str) -> Optional[str]:
            clean_ref = ref_path.strip().strip("'\"").replace("\\", "/")
            if clean_ref.startswith(("http://", "https://", "data:", "/api/assets/")):
                return clean_ref

            filename = Path(clean_ref).name
            matched_src: Optional[Path] = None

            for search_dir in search_dirs:
                direct_path = (search_dir / clean_ref).resolve()
                if direct_path.exists() and direct_path.is_file():
                    matched_src = direct_path
                    break

            if not matched_src:
                matched_src = available_images.get(clean_ref.lower()) or available_images.get(filename.lower())

            if matched_src and matched_src.exists():
                target_file = doc_asset_dir / matched_src.name
                shutil.copy2(matched_src, target_file)
                if target_file not in extracted_images:
                    extracted_images.append(target_file)
                return f"/api/assets/{doc_id}/{matched_src.name}"

            return f"/api/assets/{doc_id}/{filename}"

        def replace_md_img(match):
            alt = match.group(1)
            raw_url = match.group(2).strip()
            url_parts = raw_url.split(maxsplit=1)
            url = url_parts[0]
            title_part = f' {url_parts[1]}' if len(url_parts) > 1 else ''
            
            new_url = resolve_and_copy_image(url)
            return f'![{alt}]({new_url}{title_part})'

        adjusted_md = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_md_img, raw_md)

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
        page_range: Optional[str] = None,
        skip_lint: bool = False
    ) -> tuple[Path, list[Path], str]:
        """원본 파일을 마크다운 및 이미지 에셋으로 변환하여 저장한다."""
        title = source_path.stem
        target_md_path = self.docs_dir / f"{doc_id}.md"
        doc_asset_dir = self.assets_dir / doc_id
        doc_asset_dir.mkdir(parents=True, exist_ok=True)

        ext = source_path.suffix.lower()
        source_parent = source_path.parent

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

            final_md, meta = self.refiner.refine_text(
                raw_md=adjusted_md,
                doc_id=doc_id,
                original_filename=source_path.name,
                file_hash=file_hash
            )
            target_md_path.write_text(final_md, encoding="utf-8")
            return target_md_path, extracted_images, meta["title"]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_out_md = Path(temp_dir) / "output_raw.md"
            
            # shell=False + 리스트 인자 방식으로 명령어 인젝션 방지
            npx_path = shutil.which("npx") or "npx"
            if sys.platform == "win32":
                # Windows: .cmd 래퍼는 cmd를 통해 실행해야 한다
                base_args = ["cmd", "/c", npx_path, "-y", "kordoc@^4",
                             str(source_path.resolve()),
                             "-o", str(temp_out_md.resolve())]
            else:
                base_args = [npx_path, "-y", "kordoc@^4",
                             str(source_path.resolve()),
                             "-o", str(temp_out_md.resolve())]

            if enable_ocr:
                base_args += ["--ocr", "--formula-ocr"]
            if page_range:
                base_args += ["-p", page_range]

            logger.info(f"kordoc 파싱 시작: {' '.join(base_args)}")
            result = subprocess.run(
                base_args,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            if not temp_out_md.exists():
                error_detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"kordoc 변환 실패 (코드: {result.returncode}): {error_detail}")

            raw_md = temp_out_md.read_text(encoding="utf-8", errors="replace")

            search_dirs = [
                Path(temp_dir),
                Path(temp_dir) / "images",
                source_parent,
                source_parent / "images"
            ]
            adjusted_md, extracted_images = self._process_and_inline_images(
                raw_md, doc_id, doc_asset_dir, search_dirs
            )

            final_md, meta = self.refiner.refine_text(
                raw_md=adjusted_md,
                doc_id=doc_id,
                original_filename=source_path.name,
                file_hash=file_hash
            )
            target_md_path.write_text(final_md, encoding="utf-8")

            if not skip_lint:
                self._run_kordoc_lint(target_md_path)

        return target_md_path, extracted_images, meta["title"]
