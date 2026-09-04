"""kordoc-wiki-ingest 스킬 규격 공통 유틸리티 모듈.

PDF 규모 진단, 유효 이미지 선별 검증, 표준 메타데이터 헤더 생성,
자동 목차(TOC) 구성, Red Flag 자가 검증, kordoc lint 실행기를 제공한다.
"""

import logging
import os
import re
import shutil
import stat
import struct
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KordocUtils")

# 지원 이미지 확장자
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".gif", ".tiff"}


def get_pdf_page_count(pdf_path: Path) -> int:
    """PDF 파일의 전체 페이지 수를 바이너리 구조에서 고속으로 추출한다.
    
    실패 시 기본값 1을 반환한다.
    """
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return 1

    try:
        content = pdf_path.read_bytes()
        # /Type /Pages /Count N 정규식 검색
        matches = re.findall(rb'/Type\s*/Pages.*?/Count\s+(\d+)', content, re.DOTALL)
        if matches:
            counts = [int(m) for m in matches]
            return max(counts)

        # /Type /Page (개별 페이지 개수) 카운팅
        page_objs = re.findall(rb'/Type\s*/Page\b', content)
        if page_objs:
            return len(page_objs)
    except Exception as e:
        logger.warning(f"PDF 페이지 수 진단 실패 ({pdf_path.name}): {e}")

    return 1


def is_valid_content_image(img_path: Path, has_caption: bool = False) -> bool:
    """kordoc 스킬 기준에 부합하는 유효 콘텐츠 이미지(도표/차트/직인/인증서)인지 판별한다.
    
    [엄격 제외 기준]
    1. 파일 부재, 0바이트, 1,500바이트 미만의 초소형 파일 제외
    2. 종횡비(가로:세로) 12:1 초과 극단적 라인/구분선 노이즈 제외
    3. 면적 6,000px² 미만 초소형 블릿/아이콘 제외 (단, 공식 캡션 수반 시 4,000px² 적용)
    """
    if not img_path.exists() or not img_path.is_file():
        return False

    try:
        size = img_path.stat().st_size
        if size < 1500:
            return False

        with open(img_path, "rb") as f:
            head = f.read(64)

        width = 0
        height = 0

        # PNG 헤더 파싱
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">LL", head[16:24])

        # JPEG 헤더 파싱 (기본 프레임 마커 탐색)
        elif len(head) >= 2 and head[:2] == b"\xff\xd8":
            try:
                with open(img_path, "rb") as f:
                    f.seek(2)
                    while True:
                        b = f.read(1)
                        if not b:
                            break
                        if b != b"\xff":
                            continue
                        marker = f.read(1)
                        while marker == b"\xff":
                            marker = f.read(1)
                        if not marker:
                            break
                        marker_val = ord(marker)
                        # SOF0 ~ SOF3, SOF5 ~ SOF7, SOF9 ~ SOF11, SOF13 ~ SOF15 (이미지 크기 프레임)
                        if marker_val in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                            f.seek(3, 1)  # 길이(2) + 정밀도(1) 건너뜀
                            h_bytes = f.read(2)
                            w_bytes = f.read(2)
                            height, width = struct.unpack(">HH", h_bytes + w_bytes)
                            break
                        else:
                            length_bytes = f.read(2)
                            if len(length_bytes) < 2:
                                break
                            length = struct.unpack(">H", length_bytes)[0]
                            f.seek(length - 2, 1)
            except Exception:
                pass

        # GIF 헤더 파싱
        elif len(head) >= 10 and head[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", head[6:10])

        # 해상도 파싱에 성공한 경우 엄격 판정
        if width > 0 and height > 0:
            # 1. 얇은 구분선 노이즈 배제: 종횡비가 12배를 초과하는 극단적 선형 그래픽
            aspect_ratio = max(width / height, height / width)
            if aspect_ratio > 12.0:
                logger.debug(f"구분선 노이즈 제외: {img_path.name} ({width}x{height}, 종횡비 {aspect_ratio:.1f})")
                return False

            # 2. 초소형 블릿/아이콘 배제: 면적 기준
            area = width * height
            min_area = 4000 if has_caption else 6000
            min_side = 30 if has_caption else 45

            if area < min_area or width < min_side or height < min_side:
                logger.debug(f"초소형 아이콘 제외: {img_path.name} ({width}x{height}, 면적 {area}px²)")
                return False

            return True

        # 헤더에서 해상도를 판별하기 어려운 경우(SVG, BMP 등)는 파일 크기 기준으로 유효성 인정
        return size >= 2500

    except Exception as e:
        logger.warning(f"이미지 유효성 검사 중 오류 ({img_path.name}): {e}")
        return True


def generate_standard_metadata_header(
    title: str,
    original_filename: str,
    file_hash: str,
    ext: str,
    publisher: str = "미상 (원문 기재)",
    date_str: Optional[str] = None,
    category: str = "리서치 보고서 / 기술 문서",
    entity_tags: str = "#지식베이스 #전수복원",
    page_info: Optional[str] = None
) -> str:
    """kordoc-wiki-ingest 스킬 Phase 5 규격의 표준 메타데이터 헤더 블록을 생성한다."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ext_upper = ext.lstrip(".").upper() or "문서"
    date_formatted = date_str or datetime.now(timezone.utc).strftime("%Y년 %m월 %d일")
    format_detail = f"{ext_upper} ({page_info})" if page_info else f"{ext_upper} (100% 무삭제 전수 인제스트)"

    return (
        f"# {title}\n\n"
        f"> - **원본 파일명**: `{original_filename}`\n"
        f"> - **발행기관**: {publisher}\n"
        f"> - **발행일자**: {date_formatted}\n"
        f"> - **문서분류**: {category}\n"
        f"> - **핵심 엔티티**: {entity_tags}\n"
        f"> - **원본형식**: `{format_detail}`\n"
        f"> - **인제스트 일시**: `{now_str}`\n"
        f"> - **무결성 해시 (SHA-256)**: `{file_hash}`\n"
        f"> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)\n\n"
        f"---\n\n"
    )


def generate_toc_and_anchors(markdown_text: str) -> str:
    """마크다운 본문의 헤딩(#, ##, ###)을 파싱하여 전체 목차(TOC)와 앵커 링크를 구축한다.
    
    이미 [목차]가 존재하는 경우 덮어쓰지 않고 반환한다.
    """
    if "## 📑 전체 목차 (Table of Contents)" in markdown_text or "## 목차" in markdown_text:
        return markdown_text

    heading_regex = re.compile(r'^(#{2,4})\s+(.+)$', re.MULTILINE)
    matches = heading_regex.findall(markdown_text)

    if not matches or len(matches) < 2:
        return markdown_text

    toc_lines = ["## 📑 전체 목차 (Table of Contents)\n"]
    for hashes, h_text in matches:
        level = len(hashes) - 2  # ## -> 0, ### -> 1, #### -> 2
        indent = "  " * max(0, level)
        clean_text = h_text.strip()
        # 앵커 슬러그 생성 (특수문자 제거, 공백은 하이픈으로)
        slug = re.sub(r'[^\w\uac00-\ud7a3\s-]', '', clean_text).strip().replace(" ", "-").lower()
        toc_lines.append(f"{indent}- [{clean_text}](#{slug})")

    toc_block = "\n".join(toc_lines) + "\n\n---\n\n"

    # 메타데이터 헤더의 '---' 뒤에 TOC 삽입
    header_delimiter = "---\n\n"
    first_delim_pos = markdown_text.find(header_delimiter)
    if first_delim_pos != -1:
        insert_pos = first_delim_pos + len(header_delimiter)
        return markdown_text[:insert_pos] + toc_block + markdown_text[insert_pos:]

    return toc_block + markdown_text


def validate_red_flags(markdown_text: str) -> list[str]:
    """kordoc-wiki-ingest 스킬 규격의 Red Flags 결함을 자가 검증하여 위반 목록을 반환한다."""
    flags = []

    # 1. 무삭제 원칙 위반 표현 탐지
    loss_patterns = [
        (r'(?:~|등|외)\s*생략', "생략 표현 ('~외 생략') 발견"),
        (r'\.{3,}\s*\(?\s*중략\s*\)?\s*\.{3,}', "중략 표현 ('...(중략)...') 발견"),
        (r'주요\s*항목만\s*발췌', "임의 발췌 표현 발견"),
    ]
    for pat, desc in loss_patterns:
        if re.search(pat, markdown_text):
            flags.append(f"무삭제 원칙 위반: {desc}")

    # 2. 메타데이터 블록 누락 검사
    required_meta = ["**원본 파일명**", "**발행기관**", "**무결성 해시", "**데이터 보존 원칙**"]
    for req in required_meta:
        if req not in markdown_text:
            flags.append(f"표준 메타데이터 누락: '{req}' 항목 부재")

    # 3. 차트 이미지 삽입 후 수치 표 누락 검사
    # 본문에 이미지가 있는데 마크다운 표가 전혀 없는 경우
    has_image = bool(re.search(r'!\[.*?\]\(/api/assets/.*?\)', markdown_text))
    has_table = bool(re.search(r'\|(?:\s*---+\s*\|)+', markdown_text))
    if has_image and not has_table:
        flags.append("Dual-Mode 원칙 위반: 도표/차트 이미지가 존재하나 원본 수치 표(|---|)가 누락됨")

    return flags


def run_kordoc_lint(md_path: Path) -> tuple[bool, str]:
    """kordoc CLI lint 검증을 수행하고 (통과여부, 출력메시지)를 반환한다.
    
    로컬 시스템에 kordoc 명령어가 설치되어 있으면 직접 실행하고, 없으면 npx를 통해 호출한다.
    """
    try:
        kordoc_cmd = "kordoc" if shutil.which("kordoc") else "npx -y kordoc@^4"
        cmd = f'cmd /c {kordoc_cmd} lint "{md_path.resolve()}"'
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15
        )
        passed = (res.returncode == 0)
        output = (res.stdout or res.stderr or "").strip()
        if passed:
            logger.info(f"kordoc lint 자가 검증 통과: {md_path.name}")
        else:
            logger.warning(f"kordoc lint 검증 경고 ({md_path.name}): {output}")
        return passed, output
    except Exception as e:
        logger.warning(f"kordoc lint 실행 오류 (무시됨): {e}")
        return False, str(e)


def safe_remove_file(file_path: Path, max_retries: int = 3, delay: float = 0.1) -> bool:
    """Windows 파일 잠김 및 읽기 전용 속성을 고려하여 안전하게 파일을 삭제한다."""
    if not file_path.exists():
        return True
    for _ in range(max_retries):
        try:
            try:
                os.chmod(file_path, stat.S_IWRITE)
            except Exception:
                pass
            file_path.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception as e:
            logger.warning(f"파일 안전 삭제 실패 ({file_path.name}): {e}")
            break
    return not file_path.exists()


def safe_remove_dir(dir_path: Path, max_retries: int = 3, delay: float = 0.1) -> bool:
    """Windows 디렉터리 잠김을 고려하여 안전하게 디렉터리와 하위 파일을 재귀 삭제한다."""
    if not dir_path.exists():
        return True
    for _ in range(max_retries):
        try:
            shutil.rmtree(dir_path, ignore_errors=True)
            if not dir_path.exists():
                return True
            time.sleep(delay)
        except Exception as e:
            logger.warning(f"디렉터리 안전 삭제 실패 ({dir_path.name}): {e}")
            break
    return not dir_path.exists()


def render_vector_diagram_pages(
    pdf_path: Path,
    markdown_text: str,
    doc_id: str,
    doc_asset_dir: Path,
    dpi: int = 150
) -> tuple[str, list[dict]]:
    """PDF 내에서 단일 완성형 래스터 이미지로 삽입되지 않고, 벡터 그래픽(선, 도형, 화살표)과
    텍스트 상자가 결합되어 직접 그려진 복합 그림(Composite Figure) 페이지를 순수 구조적으로 판별하여
    고해상도 이미지(150 DPI)로 렌더링하고 마크다운 본문의 해당 위치에 인라인 주입한다. (추가 API 비용 $0)
    """
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return markdown_text, []

    rendered_diagrams = []
    updated_md = markdown_text

    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        doc_asset_dir.mkdir(parents=True, exist_ok=True)

        for p_idx, page in enumerate(doc):
            page_num = p_idx + 1
            p_text = page.get_text()

            # 1. 벡터 그래픽 복잡도 판별 (단순 구분선이나 테두리가 아닌 복합 벡터 드로잉 객체 여부)
            drawings = page.get_drawings()
            if len(drawings) < 120:
                continue

            # 2. 텍스트 상자와 벡터 그래픽의 공간적 결합도 검사 (텍스트가 존재하는 복합 그래픽인지 확인)
            text_lines = [l.strip() for l in p_text.split('\n') if l.strip()]
            if len(text_lines) < 2:
                continue

            # 3. 단일 래스터 캔버스 이미지 부재 검사 (페이지 전면을 덮는 대형 비트맵 사진/차트가 없는지 확인)
            imgs = page.get_images()
            has_dominant_raster = False
            for img in imgs:
                if len(img) >= 4:
                    w, h = img[2], img[3]
                    if w >= 500 and h >= 350 and max(w / h, h / w) <= 3.0:
                        has_dominant_raster = True
                        break

            if has_dominant_raster:
                continue

            # 4. 정형 데이터 표(Table) 기파싱 여부 검증 (진짜 데이터 표가 마크다운 본문에 이미 파싱되어 있다면 스냅샷 중복 방지)
            tables = page.find_tables()
            if tables and tables.tables:
                table_already_in_md = False
                for tab in tables.tables:
                    try:
                        rows = tab.extract()
                        if rows and len(rows) >= 3 and len(rows[0]) >= 3:
                            sample_words = []
                            for row in rows[:3]:
                                for cell in row:
                                    cell_text = str(cell or "").strip()
                                    if len(cell_text) >= 3 and not cell_text.isdigit():
                                        sample_words.append(cell_text.lower())
                            if sample_words:
                                match_count = sum(1 for w in sample_words if w in updated_md.lower())
                                if match_count >= 3:
                                    table_already_in_md = True
                                    break
                    except Exception:
                        pass

                if table_already_in_md:
                    logger.info(f"⏭️ 페이지 {page_num}: 이미 마크다운 표로 파싱 완료되어 중복 스냅샷 제외")
                    continue

            # 5. 그림 식별성 검증: 캡션, 출처 문구, 또는 순서/단계/라벨 표기가 수반되는지 확인
            caption_indicators = ["자료:", "자료 :", "source:", "출처:", "도표", "그림", "figure", "chart", "table"]
            has_source_or_caption = any(k in p_text.lower() for k in caption_indicators)
            has_step_labels = any(marker in p_text for marker in ["1.", "2.", "Step", "step", "공정", "구조", "flow", "단계"])
            if not (has_source_or_caption or has_step_labels):
                continue

            # 6. 표적 복합 그림 페이지 렌더링
            filename = f"page_{page_num:03d}_diagram.png"
            target_img_path = doc_asset_dir / filename
            pix = page.get_pixmap(dpi=dpi)
            pix.save(target_img_path)
            rendered_diagrams.append({"filename": filename, "path": target_img_path})
            logger.info(f"📸 복합 벡터 그림 고해상도 스냅샷 생성: {pdf_path.name} (페이지 {page_num} -> {filename}, 드로잉 {len(drawings)}개)")

            # 7. 마크다운 본문의 해당 위치에 인라인 주입
            img_tag = f"\n\n![도표 (페이지 {page_num} 공정 다이어그램)](/api/assets/{doc_id}/{filename})\n"

            inserted = False
            # 패턴 1: 해당 페이지 번호가 명시된 바닥글/출처 바로 위 삽입
            page_patterns = [
                rf'(\b(?:LS Securities Research|Research)\s+{page_num}\b)',
                rf'(\bPage\s+{page_num}\b)',
            ]
            for pat in page_patterns:
                match = re.search(pat, updated_md)
                if match:
                    pos = match.start()
                    nearby = updated_md[max(0, pos - 200):pos]
                    if filename not in nearby and "/api/assets/" not in nearby:
                        updated_md = updated_md[:pos] + img_tag + updated_md[pos:]
                        inserted = True
                        break

            # 패턴 2: 페이지 상단 핵심 소제목/대제목 라인과 본문 매칭 (공백/마크다운 서식 무관 정규식)
            if not inserted:
                page_lines = [l.strip() for l in p_text.split('\n') if l.strip()]
                # 페이지 상단 2~6번째 라인 중 소제목 후보 추출
                candidate_lines = []
                for cl in page_lines[1:7]:
                    clean_l = cl.lstrip('●■ \t')
                    if len(clean_l) >= 4 and not any(k in clean_l.lower() for k in ['securities', 'research', '자료', '출처']):
                        candidate_lines.append(clean_l)

                # 전체 라인에서도 소제목 형태 탐색
                candidate_lines.sort(key=lambda l: (0 if 6 <= len(l) <= 30 else 1, -len(l)))
                search_start = min(2500, len(updated_md) // 3)

                for pline in candidate_lines:
                    clean_chars = [re.escape(c) for c in pline if not c.isspace() and re.match(r'[\w가-힣]', c)]
                    if len(clean_chars) >= 4:
                        pat = r'[\s\*_\-]*'.join(clean_chars)
                        match = re.search(pat, updated_md[search_start:], re.IGNORECASE)
                        if match:
                            pos = search_start + match.end()
                            nl_pos = updated_md.find('\n', pos)
                            if nl_pos != -1:
                                updated_md = updated_md[:nl_pos] + img_tag + updated_md[nl_pos:]
                                inserted = True
                                break

            # 패턴 3: 출처 문구 바로 위 삽입
            if not inserted:
                for match in re.finditer(r'(\*\(자료:.*?\)\*|\b자료\s*:\s*.*?\b)', updated_md):
                    pos = match.start()
                    if filename not in updated_md:
                        updated_md = updated_md[:pos] + img_tag + updated_md[pos:]
                        inserted = True
                        break

            # 폴백: 본문 맨 끝 추가
            if not inserted:
                updated_md += img_tag

        doc.close()

    except Exception as e:
        logger.warning(f"복합 그림 스냅샷 렌더링 중 오류 (무시됨): {e}")

    return updated_md, rendered_diagrams

