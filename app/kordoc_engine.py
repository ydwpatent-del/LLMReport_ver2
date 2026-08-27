"""kordoc CLI를 호출하여 문서를 100% 무삭제 마크다운으로 변환하는 엔진."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("KordocEngine")

class KordocEngine:
    """kordoc CLI 기반 문서 파싱 및 이미지 추출 엔진."""

    def __init__(self, docs_dir: Path, assets_dir: Path):
        self.docs_dir = docs_dir
        self.assets_dir = assets_dir
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
                logger.warning(f"kordoc lint 자가 검증 경고 ({md_path.name}): {res.stdout or res.stderr}")
        except Exception as e:
            logger.warning(f"kordoc lint 실행 중 오류 (무시됨): {e}")

    def convert(
        self,
        source_path: Path,
        doc_id: str,
        file_hash: str,
        enable_ocr: bool = False,
        page_range: Optional[str] = None
    ) -> tuple[Path, list[Path], str]:
        """원본 파일을 마크다운 및 이미지 에셋으로 변환하여 저장한다.

        반환값: (생성된 마크다운 파일 경로, 추출된 이미지 파일 목록, 문서 제목)
        """
        title = source_path.stem
        target_md_path = self.docs_dir / f"{doc_id}.md"
        doc_asset_dir = self.assets_dir / doc_id
        doc_asset_dir.mkdir(parents=True, exist_ok=True)
        extracted_images: list[Path] = []

        ext = source_path.suffix.lower()

        # 1. 텍스트 또는 마크다운 파일 직접 처리
        if ext in {".txt", ".md"}:
            raw_content = source_path.read_text(encoding="utf-8", errors="replace")
            header = self._generate_metadata_header(title, source_path.name, file_hash, ext)
            final_content = header + raw_content
            target_md_path.write_text(final_content, encoding="utf-8")
            return target_md_path, extracted_images, title

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

            # 임시 디렉토리의 images/ 폴더 에셋 복사
            temp_images_dir = Path(temp_dir) / "images"
            if temp_images_dir.exists():
                for img_file in temp_images_dir.glob("*.*"):
                    target_img = doc_asset_dir / img_file.name
                    shutil.copy2(img_file, target_img)
                    extracted_images.append(target_img)

            # 마크다운 내 이미지 링크를 웹 서빙 경로로 변환: images/xyz.png -> /api/assets/<doc_id>/xyz.png
            adjusted_md = re.sub(
                r'!\[(.*?)\]\((?:\.{1,2}[/\\])?images[/\\](.*?)\)',
                rf'![\1](/api/assets/{doc_id}/\2)',
                raw_md
            )

            header = self._generate_metadata_header(title, source_path.name, file_hash, ext)
            final_content = header + adjusted_md
            target_md_path.write_text(final_content, encoding="utf-8")

            # kordoc lint 자가 검증 실행
            self._run_kordoc_lint(target_md_path)

        return target_md_path, extracted_images, title
