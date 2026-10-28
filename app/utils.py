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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KordocUtils")

# 지원 이미지 확장자
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".gif", ".tiff"}

# 발행기관 탐지 기준 목록 — ai_refiner, kordoc_wiki_agent 공용 단일 진실원
KNOWN_PUBLISHERS = [
    "LS증권", "미래에셋증권", "삼성증권", "KB증권", "NH투자증권", "신한투자증권",
    "하나증권", "한국투자증권", "메리츠증권", "다올투자증권", "키움증권", "대신증권",
    "한국은행", "산업통상자원부", "과학기술정보통신부", "금융감독원", "기획재정부",
    "KDI", "한국개발연구원", "ETRI", "정보통신산업진흥원",
]



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
            head = f.read(512)

        width = 0
        height = 0

        # PNG 헤더 파싱
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">LL", head[16:24])

        # JPEG 헤더 파싱 (기본 프레임 마커 탐색 - 메모리 버퍼 재사용)
        elif len(head) >= 2 and head[:2] == b"\xff\xd8":
            try:
                from io import BytesIO
                buf = BytesIO(head)
                buf.seek(2)
                while True:
                    b = buf.read(1)
                    if not b:
                        break
                    if b != b"\xff":
                        continue
                    marker = buf.read(1)
                    while marker == b"\xff":
                        marker = buf.read(1)
                    if not marker:
                        break
                    marker_val = ord(marker)
                    # SOF0 ~ SOF3, SOF5 ~ SOF7, SOF9 ~ SOF11, SOF13 ~ SOF15 (이미지 크기 프레임)
                    if marker_val in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        buf.seek(3, 1)  # 길이(2) + 정밀도(1) 건너뜀
                        h_bytes = buf.read(2)
                        w_bytes = buf.read(2)
                        if len(h_bytes) == 2 and len(w_bytes) == 2:
                            height, width = struct.unpack(">HH", h_bytes + w_bytes)
                        break
                    else:
                        length_bytes = buf.read(2)
                        if len(length_bytes) < 2:
                            break
                        length = struct.unpack(">H", length_bytes)[0]
                        buf.seek(length - 2, 1)
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

            area = width * height

            # 2. 대형 단색 박스/배경 테두리 배제: 면적 대비 바이트 밀도가 극단적으로 낮은 더미 그래픽
            # (예: 1819x373 해상도인데 파일 크기가 3~5KB에 불과한 단색 채우기 상자)
            if area >= 80000 and (size / area) < 0.02:
                logger.debug(f"단색 박스 노이즈 제외: {img_path.name} ({width}x{height}, {size}B, 밀도 {size/area:.4f})")
                return False

            # 3. 초소형 블릿/아이콘 배제: 면적 및 최소 변 기준 (공식 캡션 부재 시 80x80 등 장식용 픽토그램 차단)
            min_area = 4000 if has_caption else 10000
            min_side = 30 if has_caption else 85

            if area < min_area or width < min_side or height < min_side:
                logger.debug(f"초소형 아이콘 제외: {img_path.name} ({width}x{height}, 면적 {area}px²)")
                return False

            # 4. 대형 캔버스 빈 슬라이드/배경 템플릿 배제 (Blank Canvas & Decorative Template Filter)
            # 테두리 선이나 로고만 있고 본문 콘텐츠가 없는 순수 백지 템플릿을 정밀하게 감지하여 배제한다.
            # 중심부 집약형 인포그래픽/다이어그램은 배경 여백이 70~85%에 달하더라도
            # 유효 그래픽 픽셀 수(content_pixels)와 풍부한 비트맵 디테일(파일 크기)을 보유하므로 정상 보존한다.
            if area >= 200000:
                try:
                    import pymupdf
                    pix = pymupdf.Pixmap(str(img_path))
                    n = pix.n
                    samples = pix.samples
                    tot_sampled = 0
                    white_cnt = 0
                    for y in range(0, height, 4):
                        row_offset = y * width * n
                        for x in range(0, width, 8):
                            idx = row_offset + x * n
                            # n 값에 따른 채널 안전 처리 (1=Gray, 2=GA, 3=RGB, 4=RGBA)
                            if n == 1:
                                r = g = b = samples[idx]
                                a = 255
                            elif n == 2:
                                r = g = b = samples[idx]
                                a = samples[idx + 1]
                            elif n >= 3:
                                r, g, b = samples[idx], samples[idx + 1], samples[idx + 2]
                                a = samples[idx + 3] if n == 4 else 255
                            else:
                                continue
                            tot_sampled += 1
                            # 흰색/극미색(#F0F0F0 이상) 또는 투명
                            if a < 15 or (r > 240 and g > 240 and b > 240):
                                white_cnt += 1

                    if tot_sampled > 0:
                        overall_blank_ratio = white_cnt / tot_sampled
                        non_blank_cnt = tot_sampled - white_cnt
                        limit = 0.96 if has_caption else 0.90

                        # 내용물이 풍부한 그래픽 볼륨 예외:
                        # 샘플링된 유효 콘텐츠 픽셀이 1,500개 이상이거나 파일 크기가 45KB 이상인 경우,
                        # 중심부 집약형 인포그래픽(다이어그램, 차트, 방사형 그래프 등)이므로 공백률 완화(96%까지 허용)
                        is_rich_content = (non_blank_cnt >= 1500 or size >= 45000)
                        effective_limit = 0.96 if is_rich_content else limit

                        if overall_blank_ratio >= effective_limit:
                            logger.debug(f"빈 캔버스 템플릿 제외: {img_path.name} ({width}x{height}, 공백률 {overall_blank_ratio:.1%}, 유효픽셀 {non_blank_cnt}개)")
                            return False
                except Exception as pix_err:
                    logger.debug(f"픽셀 공백률 분석 건너뜀 ({img_path.name}): {pix_err}")

            # 5. 텍스트 단어 조각/글리프 비트맵 배제 (Text Glyph & Label Fragment Filter)
            # PDF 렌더러가 폰트 대신 단어/라벨을 가로로 긴 형태(종횡비 1.8 이상, 높이 150px 이하)의 소용량(<3.5KB) 비트맵으로 임베딩한 조각 노이즈 차단
            if aspect_ratio >= 1.8 and height <= 150 and size < 3500:
                logger.debug(f"텍스트 글리프 조각 노이즈 제외: {img_path.name} ({width}x{height}, {size}B)")
                return False

            # 6. 단순 픽토그램/클립아트/장식 인디케이터 배제 (Decorative Icon & Pictogram Filter)
            # 공식 도표/차트 캡션이 없고, 가로/세로 300px 이하의 중소형 그래픽이면서
            # 고유 색상 수(Unique Colors)가 24색 이하인 단순 단색/이색 심볼(레벨 아이콘, 불릿, 체크박스 등) 차단
            if not has_caption and max(width, height) <= 300 and min(width, height) >= 40:
                try:
                    import pymupdf
                    pix = pymupdf.Pixmap(str(img_path))
                    n = pix.n
                    samples = pix.samples
                    colors = set()
                    # 최대 2,000개 픽셀을 균일 샘플링하여 고유 색상 수 집계
                    step_y = max(1, pix.height // 40)
                    step_x = max(1, pix.width // 40)
                    for y in range(0, pix.height, step_y):
                        row_offset = y * pix.width * n
                        for x in range(0, pix.width, step_x):
                            idx = row_offset + x * n
                            r_val, g_val, b_val = samples[idx], samples[idx + 1], samples[idx + 2]
                            colors.add((r_val, g_val, b_val))
                            if len(colors) > 24:
                                break
                        if len(colors) > 24:
                            break

                    if len(colors) <= 24:
                        logger.debug(f"단순 장식 픽토그램/아이콘 제외: {img_path.name} ({width}x{height}, 고유색상 {len(colors)}개)")
                        return False
                except Exception as color_err:
                    logger.debug(f"픽토그램 색상 분석 건너뜀 ({img_path.name}): {color_err}")

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


def generate_toc_and_anchors(markdown_text: str, force_update: bool = False) -> str:
    """마크다운 본문의 헤딩(#, ##, ###, ####)을 파싱하여 전체 목차(TOC)와 앵커 링크를 구축한다.
    
    이미 [목차]가 존재하는 경우 기본적으로 보존하되, force_update가 True이거나
    기존 목차 항목 수가 2개 이하로 극단적으로 불완전한 경우 전체 헤딩 기준으로 갱신한다.
    """
    heading_regex = re.compile(r'^(#{2,4})\s+(.+)$', re.MULTILINE)
    matches = [
        (hashes, text.strip()) for hashes, text in heading_regex.findall(markdown_text)
        if "목차" not in text
    ]

    if not matches or len(matches) < 2:
        return markdown_text

    has_existing_toc = ("## 📑 전체 목차 (Table of Contents)" in markdown_text or "## 목차" in markdown_text)

    # 기존 목차가 존재하는 경우 불완전성 검사
    if has_existing_toc and not force_update:
        toc_match = re.search(r'##\s+(?:📑\s+전체\s+)?목차[^\n]*\n([\s\S]*?)(?=\n---\n|\n##\s+)', markdown_text)
        if toc_match:
            toc_content = toc_match.group(1)
            existing_items = re.findall(r'(?:[-*]|\d+\.)\s+\[.*?\]\(#.*?\)', toc_content)
            has_corrupted_toc = bool(re.search(r'!\[.*?\]\(.*?\)', toc_content))
            # 본문 헤딩은 4개 이상인데 목차 항목이 2개 이하이거나, 목차 내에 이미지 태그 오염이 있는 경우 자동 갱신
            if has_corrupted_toc or (len(matches) >= 4 and len(existing_items) <= 2):
                force_update = True
            else:
                return markdown_text
        else:
            return markdown_text

    toc_title = "## 목차" if ("## 목차" in markdown_text and "📑" not in markdown_text) else "## 📑 전체 목차 (Table of Contents)"
    toc_lines = [f"{toc_title}\n"]
    for hashes, h_text in matches:
        level = len(hashes) - 2  # ## -> 0, ### -> 1, #### -> 2
        indent = "  " * max(0, level)
        clean_text = h_text.strip()
        # 앵커 슬러그 생성 (특수문자 제거, 공백은 하이픈으로)
        slug = re.sub(r'[^\w\uac00-\ud7a3\s-]', '', clean_text).strip().replace(" ", "-").lower()
        toc_lines.append(f"{indent}- [{clean_text}](#{slug})")

    toc_block = "\n".join(toc_lines) + "\n\n---\n\n"

    # 기존 불완전 목차가 존재하여 갱신하는 경우 기존 목차 블록을 치환
    if has_existing_toc:
        old_toc_pat = re.compile(r'##\s+(?:📑\s+전체\s+)?목차[^\n]*\n[\s\S]*?(?=\n---\n|\n##\s+)(?:\n---\n\n)?')
        if old_toc_pat.search(markdown_text):
            return old_toc_pat.sub(toc_block, markdown_text, count=1)

    # 메타데이터 헤더의 '---' 뒤에 TOC 삽입
    header_delimiter = "---\n\n"
    first_delim_pos = markdown_text.find(header_delimiter)
    if first_delim_pos != -1:
        insert_pos = first_delim_pos + len(header_delimiter)
        return markdown_text[:insert_pos] + toc_block + markdown_text[insert_pos:]

    return toc_block + markdown_text


def deduplicate_inlined_images(markdown_text: str, doc_id: Optional[str] = None) -> str:
    """마크다운 본문 내 중복 삽입된 동일 에셋 이미지 태그 및 서두 일괄 덤프 블록을 안전하게 외과적으로 정돈한다."""
    if doc_id:
        img_tag_pattern = re.compile(
            rf'(!\[(.*?)\]\(/api/assets/{re.escape(doc_id)}/([^\)\s]+)\)(?:\s*\n\s*\*\([^\n]+\)\*)?)',
            re.MULTILINE
        )
    else:
        img_tag_pattern = re.compile(
            r'(!\[(.*?)\]\((?:/api/assets/[^/]+/|[^\)\s/]+/)?([^\)\s]+)\)(?:\s*\n\s*\*\([^\n]+\)\*)?)',
            re.MULTILINE
        )

    matches = list(img_tag_pattern.finditer(markdown_text))
    if not matches:
        return markdown_text

    fn_counts = Counter(m.group(3) for m in matches)
    duplicate_fns = {fn for fn, c in fn_counts.items() if c > 1}
    if not duplicate_fns:
        return markdown_text

    logger.info(f"중복 에셋 이미지 {len(duplicate_fns)}종 감지: {', '.join(sorted(duplicate_fns))}")

    # 1. 서두 일괄 덤프 블록 감지 및 정돈
    # 패턴: 상단 섹션(## 바로 다음)에 2개 이상의 중복 이미지가 실질적인 본문 단락 없이 연속 배치된 경우
    top_sec_match = re.search(r'(##\s+[^\n]+\n)([\s\S]*?)(\n###\s+)', markdown_text)
    if top_sec_match:
        top_start = top_sec_match.start(2)
        top_end = top_sec_match.end(2)
        top_content = top_sec_match.group(2)

        top_img_matches = list(img_tag_pattern.finditer(top_content))
        top_dup_imgs = [m.group(3) for m in top_img_matches if m.group(3) in duplicate_fns]

        # 상단 구역의 이미지가 본문 다른 곳에도 존재하는 중복 이미지인 경우
        if len(top_dup_imgs) >= 2 and len(top_dup_imgs) >= len(top_img_matches) * 0.7:
            lines = [l.strip() for l in top_content.split('\n') if l.strip()]
            non_media_lines = [
                l for l in lines
                if not (l.startswith(('![', '*(', '|', ':-', '-:')) or l in ('', '---'))
            ]
            if len(non_media_lines) <= 2:
                logger.info(f"서두 일괄 덤프 블록 감지 ({len(top_dup_imgs)}개 이미지) -> 제거")
                markdown_text = markdown_text[:top_start] + '\n\n' + markdown_text[top_end:]

    # 2. 개별 잔여 중복 이미지 태그 정돈
    for _ in range(15):
        cur_matches = list(img_tag_pattern.finditer(markdown_text))
        cur_counts = Counter(m.group(3) for m in cur_matches)
        cur_dups = {fn for fn, c in cur_counts.items() if c > 1}
        if not cur_dups:
            break

        for dup_fn in cur_dups:
            fn_matches = [m for m in img_tag_pattern.finditer(markdown_text) if m.group(3) == dup_fn]
            if len(fn_matches) > 1:
                # 앞선 중복 태그를 제거하여 본문 상세 위치의 태그 보존
                target_m = fn_matches[0]
                end_pos = target_m.end()
                while end_pos < len(markdown_text) and markdown_text[end_pos] in ('\n', '\r', ' '):
                    end_pos += 1
                markdown_text = markdown_text[:target_m.start()] + markdown_text[end_pos:]
                break

    # 3. 이미지 레이블 순서 번호 정상화 (이미지 5 -> 이미지 1 등)
    img_counter = 1
    def repl_img(m):
        nonlocal img_counter
        prefix = m.group(1)
        title = m.group(2)
        rest = m.group(3)
        new_tag = f"{prefix}이미지 {img_counter}: {title}{rest}"
        img_counter += 1
        return new_tag

    markdown_text = re.sub(
        r'(!\[\s*)이미지\s*\d+\s*:\s*([^\]]+)(\]\((?:/api/assets/[^/]+/|[^\)\s/]+/))',
        repl_img,
        markdown_text
    )

    # 4. 불필요한 연속 개행 정돈
    markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)

    return markdown_text


def validate_red_flags(markdown_text: str, check_metadata: bool = True) -> list[str]:
    """kordoc-wiki-ingest 스킬 규격의 Red Flags 결함을 자가 검증하여 위반 목록을 반환한다.
    
    check_metadata=False 로 호출하면 메타데이터 헤더 누락 검사를 건너뛴다.
    AI 보정 산출물의 본문 조각 단위 검증 시 사용한다.
    """
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
    if check_metadata:
        required_meta = ["**원본 파일명**", "**발행기관**", "**무결성 해시", "**데이터 보존 원칙**"]
        for req in required_meta:
            if req not in markdown_text:
                flags.append(f"표준 메타데이터 누락: '{req}' 항목 부재")

    # 3. 통계 차트 이미지 삽입 후 수치 표 누락 검사
    # 캡션에 수치성 키워드가 있을 때만 통계 차트로 판별 (개념도/인포그래픽 오탐 제외)
    _STAT_KEYWORDS = r"단위|cagr|억원|억\s*달러|성장률|추이|실적|%"
    has_stat_chart = bool(re.search(
        r'!\[.*?\]\(/api/assets/.*?\)\s*\n\s*\*\([^)]*(?:' + _STAT_KEYWORDS + r')[^)]*\)\*',
        markdown_text,
        re.IGNORECASE
    ))
    has_table = bool(re.search(r'\|(?:\s*:?-+:?\s*\|)+', markdown_text))
    if has_stat_chart and not has_table:
        flags.append("Dual-Mode 원칙 위반: 통계 차트 이미지가 존재하나 원본 수치 표(|---|)가 누락됨")

    # 4. 깨진 마크다운 표 감지 (구분선(|---|)이 전혀 없는 고립된 표 블록)
    lines = markdown_text.splitlines()
    table_block = []
    table_separator_pattern = re.compile(r'^\|(?:\s*:?-+:?\s*\|)+\s*$')

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|'):
            table_block.append(stripped)
        else:
            if table_block:
                has_separator = any(table_separator_pattern.match(l) for l in table_block)
                if not has_separator:
                    flags.append(f"표 문법 파손: 구분선(|---|) 없는 고립된 표 블록 감지 ('{table_block[0][:30]}')")
                    break
                table_block = []

    if table_block:
        has_separator = any(table_separator_pattern.match(l) for l in table_block)
        if not has_separator:
            flags.append(f"표 문법 파손: 구분선(|---|) 없는 고립된 표 블록 감지 ('{table_block[0][:30]}')")

    # 4-1. 개행 누락으로 본문/출처와 결합되어 파손된 표 헤더 감지 (중첩 수량자 제거로 ReDoS 방지)
    malformed_table_headers = re.findall(
        r'(?:^|\n)(?!\s*\|)([^\n|]+)(\|[^\n]*\n[ \t]*\|(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*(?=\n|$))',
        markdown_text
    )
    if malformed_table_headers:
        flags.append(f"표 문법 파손: 개행 누락으로 본문/출처와 결합된 파손 표 헤더 감지 ({len(malformed_table_headers)}건)")

    # 5. 무맥락 이미지 연속 덤프(Dump) 감지 (설명 없이 연속된 이미지 태그)
    if re.search(r'!\[.*?\]\([^\)]+\)\s*\n+\s*!\[.*?\]\([^\)]+\)', markdown_text):
        flags.append("Visual Context Inlining 위반: 설명 문맥 없는 이미지 연속 덤프 감지")

    # 6. 불릿 이중 기호 및 들여쓰기 위반 감지
    if re.search(r'^\s*[-*+]\s*[○◦●■□◇◆▶▷]', markdown_text, re.MULTILINE):
        flags.append("불릿 서식 위반: 이중 불릿 기호('- ○') 잔존")
    if re.search(r'^\s*[-*+]\s*[-*+]\s+', markdown_text, re.MULTILINE):
        flags.append("불릿 서식 위반: 중복 하이픈('- -') 잔존")
    if re.search(r'^[○◦●◇◆▶▷]\s+', markdown_text, re.MULTILINE):
        flags.append("불릿 들여쓰기 위반: 2단계 불릿('○')의 들여쓰기(2칸) 누락")

    # 7. 각주 인라인 미분리 및 중복 감지
    body_part = re.split(r'^\s*#{2,4}\s*(?:📌\s*)?(?:각주|Footnotes?)\b', markdown_text, flags=re.IGNORECASE | re.MULTILINE)[0]
    if re.search(r'^\s*[-*+]?\s*\d+\)\s*[^:\n]{2,20}:\s*.+', body_part, re.MULTILINE):
        flags.append("각주 서식 위반: 본문 내 인라인 각주 미분리 잔존")
    if re.search(r'^\s*\[\^(\d+)\]:\s*.+', body_part, re.MULTILINE):
        flags.append("각주 서식 위반: 본문 내 각주 정의 미분리 잔존")

    # 전체 문서에서 각주 번호 중복 정의 검사
    all_fn_defs = re.findall(r'^\s*\[\^(\d+)\]:\s*', markdown_text, re.MULTILINE)
    if len(all_fn_defs) != len(set(all_fn_defs)):
        flags.append(f"각주 서식 위반: 각주 정의 중복 삽입 ({len(all_fn_defs) - len(set(all_fn_defs))}건 중복)")

    return flags


def heal_markdown_table_boundaries(markdown_text: str) -> str:
    """마크다운 표(Table)의 시작 전과 종결 후 빈 줄(\n\n)을 보장하고,
    표 직후에 붙은 캡션/출처 및 인라인 도표 이미지를 독립된 문단으로 안전하게 분리한다.

    1. 코드 블록(```) 내부의 텍스트는 온전히 보존.
    2. 인라인 복합 태그 분리:
       `<출처:...>![이미지](url)` 또는 `*(캡션)*![이미지](url)` 와 같이 한 줄에 붙은
       이미지 태그를 `\n\n![이미지](url)` 로 분리하여 독립 이미지 문단으로 격리.
    3. 닫는 파이프 없이 줄바꿈되어 두 동강 난 표 행(| 셀1\n\n| 셀2 |...) 자동 봉합.
    4. 개행 누락으로 앞 일반 텍스트/캡션에 붙어버린 표 헤더만 표준 줄바꿈(\n\n)으로 분리 복원.
    5. 표 종결 경계 분리 (Table Terminator Healing):
       표 데이터 행(| ... |) 직후 빈 줄 없이 이어지는 일반 텍스트/캡션/출처/이미지 행 사이에
       반드시 빈 줄(\n\n)을 삽입하여 GFM 파서가 표 밖의 요소를 표 내부 셀(<td>)로
       오인 흡수하는 결함을 완벽히 차단.
    """
    if not markdown_text:
        return markdown_text

    # 1. 코드 블록 보호 및 플레이스홀더 치환
    code_blocks = []
    def save_code_block(m):
        code_blocks.append(m.group(0))
        return f"<!--CODE_BLOCK_PLACEHOLDER_{len(code_blocks)-1}-->"

    text = re.sub(r'```[\s\S]*?```', save_code_block, markdown_text)

    # 2. 인라인 복합 태그 및 개행 누락 문단/헤딩 분리:
    # 2-0) 중첩된 <출처: [A](urlA), <출처: [B](urlB)>> 비정상 태그 단일 <출처: [A](urlA), [B](urlB)>로 평탄화
    def flatten_nested_citation(m):
        full = m.group(0)
        items = re.findall(r'\[((?:\[[^\]]*\]|[^\]])+)\]\(([^)]+)\)', full)
        if items:
            return "<출처: " + ", ".join(f"[{t}]({l})" for t, l in items) + ">"
        return full

    text = re.sub(
        r'<출처\s*:\s*\[(?:\[[^\]]*\]|[^\]])+\]\([^)]+\)(?:,\s*<출처\s*:\s*\[(?:\[[^\]]*\]|[^\]])+\]\([^)]+\))+>',
        flatten_nested_citation,
        text
    )

    # 2-1) <출처:...> 또는 *(...)* 직후에 공백 없이 바로 붙은 ![...](...) 이미지 태그 분리
    text = re.sub(r'([>)]|\*(?:[^*]+)\*)\s*(!\[[^\n\]]*\]\([^\n\)]+\))', r'\1\n\n\2', text)
    # 2-2) 도표 캡션(*(도표:...)*) 앞의 불필요한 공백/들여쓰기 제거
    text = re.sub(r'(!\[.*?\]\([^\)]+\)\s*\n)[ \t]+(\*\([^\n]+\)\*)', r'\1\2', text)
    # 2-3) 출처 태그 직후 표 헤더, 헤딩(###), 목록(*, -, +), 볼드 소제목이 바로 붙은 경우 빈 줄(\n\n)로 격리
    # 일반 문단 끝(비-표 행)에 달라붙은 표 헤더는 빈 줄(\n\n)로 확실히 분리하고, 표 내부 셀의 닫는 파이프(>|)는 온전히 보존
    text = re.sub(r'((?:^|\n)(?!\s*\|)[^\n]+?<출처\s*:[^>]+>)[ \t]*(\|[^\n]+\|)', r'\1\n\n\2', text)
    text = re.sub(r'(<출처\s*:[^>]+>)[ \t]*(#{1,6}\s+)', r'\1\n\n\2', text)
    text = re.sub(r'(<출처\s*:[^>]+>)[ \t]*([*+-]\s+)', r'\1\n\n\2', text)
    text = re.sub(r'(<출처\s*:[^>]+>)[ \t]*(\*\*[^\n*]+\*\*)', r'\1\n\n\2', text)
    text = re.sub(r'(<출처\s*:[^>]+>\.?)[ \t]*(#{1,6}\s+|[*+-]\s+|\|[^\n]+\|)', r'\1\n\n\2', text)
    # 2-4) 캡션 닫는 ')*' 직후 공백/개행 없이 헤딩(###)이 이어지는 경우 빈 줄(\n\n)로 분리
    text = re.sub(r'(\*\([^\n]+\)\*)[ \t]*(#{1,6}\s+)', r'\1\n\n\2', text)
    # 2-5) 출처 태그, 마침표, 일반 본문 직후에 개행 없이 인라인으로 붙어버린 모든 헤딩(#{1,6} ) 앞에 빈 줄(\n\n) 강제 분리
    text = re.sub(r'([^\n#])[ \t]*(#{1,6}\s+[^\n]+)', r'\1\n\n\2', text)

    # 3. 닫는 파이프 없이 줄바꿈되어 두 동강 난 표 행(| 셀1\n\n| 셀2 |...) 자동 봉합
    text = re.sub(
        r'(^|\n)[ \t]*\|([^|\n]*)\n+[ \t]*(\|(?:[^|\n]*\|)+)',
        r'\1|\2 \3',
        text
    )

    # 4-1. 표 헤더 행과 구분 행 사이에 빈 줄(\n\n)이 끼어 깨진 표 봉합
    text = re.sub(
        r'((?:^|\n)[ \t]*\|[^\n]+\|[ \t]*)\n+[ \t]*(\|(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*(?=\n|$))',
        r'\1\n\2',
        text
    )

    # 4-2. 개행 누락 또는 단일 개행으로 앞 일반 텍스트나 출처/캡션에 붙어버린 표 헤더만 표준 빈 줄(\n\n)로 분리 복원
    text = re.sub(
        r'((?:^|\n)(?!\s*\|)[^\n|]+?)[ \t]*\n?((?:\|[^|\n]+)+\|[ \t]*\n[ \t]*\|(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*(?=\n|$))',
        r'\1\n\n\2',
        text
    )

    # 5. 표 종결 경계 분리:
    # 표 데이터 행(| ... |) 직후 빈 줄 없이 비-표 행(파이프로 시작하지 않는 줄)이 올 때 빈 줄(\n\n) 삽입
    lines = text.split('\n')
    healed_lines = []
    in_table = False

    def is_table_row(line_str: str) -> bool:
        s = line_str.strip()
        return s.startswith('|') and s.endswith('|') and len(s) >= 2

    for line in lines:
        stripped = line.strip()
        if is_table_row(line):
            in_table = True
            healed_lines.append(line)
        else:
            if in_table:
                in_table = False
                if stripped != '':
                    # 표가 끝난 직후 행이 빈 줄이 아니면 빈 줄 삽입하여 표 종결
                    healed_lines.append('')
            healed_lines.append(line)

    healed_text = '\n'.join(healed_lines)

    # 6. 코드 블록 복원
    for idx, block in enumerate(code_blocks):
        healed_text = healed_text.replace(f"<!--CODE_BLOCK_PLACEHOLDER_{idx}-->", block)

    return healed_text


def clean_markdown_typography(markdown_text: str) -> str:
    """마크다운 본문의 불릿 기호를 네모(□) - 동그라미(○) - 하이픈(-) 체계로 통일하고,
    본문 중간에 혼입되거나 중복 삽입된 각주 설명을 전수 수거하여 문서 최하단 표준 GFM 각주([^1])로 일원화한다.
    
    1. 불릿 기호 체계 통일 (이중 기호 제거):
       - 1단계(대항목): □ (네모)
       - 2단계(중항목): ○ (동그라미) — '- ○' 이중기호에서 앞선 '- '를 제거하여 순수 '○ '로 복원
       - 3단계(소항목): - (하이픈) — '- -' 중복 하이픈을 단일 '- '로 정돈
    
    2. 각주 표준 분리 및 중복 제거 (Option A - GFM 각주 문법):
       - 본문 단락 또는 표 사이에 끼어있는 각주 정의('- 1) 용어: 설명' 및 '[^1]: **용어**: 설명' 등)를 전수 감지 및 수거
       - 본문 중간 및 말단에 중복 기재된 동일 번호 각주를 최고 품질의 설명으로 단일 통합(Deduplication)
       - 본문 텍스트 내의 '단어1)' 인용부를 표준 '단어[^1]'로 치환 (기존 '[^1]' 인용부는 온전히 보존)
       - 분리 및 통합된 모든 각주를 문서 최하단에 번호 오름차순의 [^1]: **용어**: 설명 단일 블록으로 일원화
       - Zero Information Loss 원칙: 원본 텍스트 및 각주 내용을 100% 무손실 보존
    """
    if not markdown_text:
        return markdown_text

    # 0. 마크다운 표 시작 및 종결 경계 자율 치유 (두 동강 난 표 행 봉합 및 헤더/종결 분리 통합)
    markdown_text = heal_markdown_table_boundaries(markdown_text)

    # 0-3. 본문 내 설명 문맥 없이 연속으로 나열된 이미지 태그들에 대해
    # 각 이미지의 alt 텍스트를 기반으로 시각적 캡션(*(도표: {설명})*)을 부여하여
    # Visual Context Inlining 완성 및 무맥락 연속 덤프 결함 자율 치유
    consecutive_pat = re.compile(
        r'(!\[(.*?)\]\(([^\)]+)\))(?:\s*\n)+\s*(?=!\[.*?\]\([^\)]+\))'
    )
    if consecutive_pat.search(markdown_text):
        def repl_img_block(match):
            tag = match.group(1)
            alt = match.group(2).strip()
            desc = alt
            desc_match = re.search(r'\((.*?)\)', alt)
            if desc_match:
                desc = desc_match.group(1).strip()
            caption = f"*(도표: {desc})*" if desc else "*(도표/인포그래픽)*"
            return f"{tag}\n{caption}\n\n"

        for _ in range(10):
            if not consecutive_pat.search(markdown_text):
                break
            markdown_text = consecutive_pat.sub(repl_img_block, markdown_text)

        # 연속 블록의 마지막 이미지 태그 뒤에도 캡션이 없는 경우 보완
        last_in_chain_pat = re.compile(
            r'(\*\([^\n]+\)\*\s*\n+)(!\[(.*?)\]\(([^\)]+)\))(?!\s*\n\s*\*\(|\s*\n\s*!\[)'
        )
        def repl_last_img(m):
            prev_caption = m.group(1)
            tag = m.group(2)
            alt = m.group(3).strip()
            desc = alt
            desc_match = re.search(r'\((.*?)\)', alt)
            if desc_match:
                desc = desc_match.group(1).strip()
            caption = f"*(도표: {desc})*" if desc else "*(도표/인포그래픽)*"
            return f"{prev_caption}{tag}\n{caption}"

        markdown_text = last_in_chain_pat.sub(repl_last_img, markdown_text)

    # 0-2. 과거 버그로 인해 발생한 동일 위계 목록의 들여쓰기 왜곡(첫 항목 0~2칸, 후속 항목 4칸) 사전 치유
    # 직전에 ○(중항목) 부모가 없는데 첫 항목이 0~2칸 대시이고 후속 항목들이 4칸 대시로 이어진 경우 동일 위계로 평탄화
    raw_lines = markdown_text.split('\n')
    healed_raw_lines = []
    in_dash_block = False
    first_dash_indent = ''
    has_circle_parent = False

    for r_line in raw_lines:
        m_dash_chk = re.match(r'^(\s*)-\s+(.*)$', r_line)
        if re.match(r'^\s*(?:[-*+]\s*)?[○◦●◇◆▶▷]', r_line):
            has_circle_parent = True
            in_dash_block = False
            first_dash_indent = ''
            healed_raw_lines.append(r_line)
            continue
        if re.match(r'^\s*#{1,6}\s', r_line) or re.match(r'^\s*□', r_line):
            has_circle_parent = False
            in_dash_block = False
            first_dash_indent = ''
            healed_raw_lines.append(r_line)
            continue

        if m_dash_chk:
            cur_indent = m_dash_chk.group(1)
            cur_content = m_dash_chk.group(2)
            if not in_dash_block:
                in_dash_block = True
                first_dash_indent = cur_indent
                healed_raw_lines.append(r_line)
            else:
                # 직전 부모가 circle이 아닌데 첫 항목이 0~2칸이고 후속 항목이 4칸 이상으로 튀어버린 경우
                if not has_circle_parent and len(first_dash_indent) <= 2 and len(cur_indent) >= 4:
                    healed_raw_lines.append(f"{first_dash_indent}- {cur_content}")
                else:
                    healed_raw_lines.append(r_line)
        else:
            if r_line.strip() != '':
                in_dash_block = False
                first_dash_indent = ''
            healed_raw_lines.append(r_line)

    lines = healed_raw_lines
    cleaned_lines = []
    footnotes = {}  # num -> (term, desc)

    # 1) 일반 텍스트 각주 정의 행 매칭 패턴:
    # 예: '- 1) Transformer: 설명...' 또는 '1) Transformer: 설명...' 또는 '- 1) 설명...'
    footnote_def_pat = re.compile(r'^\s*[-*+]?\s*(\d+)\)\s*(?:([^:\n]+):)?\s*(.+)$')

    # 2) GFM 표준 각주 정의 행 매칭 패턴:
    # 예: '[^5]: **비즈니스 규칙(Heuristics)**: 설명...' 또는 '[^1]: 용어: 설명...' 또는 '[^1]: 설명...'
    gfm_footnote_def_pat = re.compile(r'^\s*\[\^(\d+)\]:\s*(?:(?:\*\*([^\*\n]+)\*\*|([^\:\n]+)):\s*)?(.+)$')

    # 3) 기존 각주 섹션 헤더 행 매칭 패턴:
    footnote_header_pat = re.compile(r'^\s*#{2,4}\s*(?:📌\s*)?(?:각주|Footnotes?)\b.*$', re.IGNORECASE)

    # 불릿 정규화 패턴
    empty_square_pat = re.compile(r'^\s*□\s*$')
    square_bullet_pat = re.compile(r'^\s*(?:[-*+]\s*)?([■□])\s*(.*)$')
    circle_bullet_pat = re.compile(r'^\s*(?:[-*+]\s*)?([○◦●◇◆▶▷])\s*(.*)$')
    dash_bullet_pat = re.compile(r'^(\s*)(?:[-*+]\s*[-*+]|[-*+])\s+(.*)$')

    def register_footnote(n: int, t: str, d: str) -> None:
        """각주 정의를 딕셔너리에 등록하며, 중복 시 더 상세하고 완전한 내용을 보존한다."""
        t_clean = t.strip().strip('*').strip()
        d_clean = d.strip()
        if n in footnotes:
            prev_t, prev_d = footnotes[n]
            # 새 term이 더 유효하고 구체적인 경우 채택
            best_t = t_clean if (t_clean and (not prev_t or len(t_clean) > len(prev_t))) else prev_t
            # 더 길고 상세한 설명을 채택
            best_d = d_clean if len(d_clean) >= len(prev_d) else prev_d
            footnotes[n] = (best_t, best_d)
        else:
            footnotes[n] = (t_clean, d_clean)

    current_bullet_level = 0
    current_dash_indent = ""

    for line in lines:
        # 기존 각주 섹션 헤더는 본문 흐름에서 제거 (문서 최하단에 단일 표준 헤더로 재생성)
        if footnote_header_pat.match(line):
            continue

        # 마크다운 수평선(---, ***, ___ 등 구분선)은 일단 보존 (후속 단계에서 고립/중복 정리)
        if re.match(r'^\s*([-*_])(?:\s*\1){2,}\s*$', line):
            cleaned_lines.append(line)
            continue

        # 빈 더미 네모 기호 줄은 제외
        if empty_square_pat.match(line):
            continue

        # 1-1. GFM 표준 각주 정의 라인 감지 및 수거
        m_gfm = gfm_footnote_def_pat.match(line)
        if m_gfm:
            try:
                num = int(m_gfm.group(1))
                term = m_gfm.group(2) or m_gfm.group(3) or ""
                desc = m_gfm.group(4)
                register_footnote(num, term, desc)
                continue  # 본문 흐름에서 제거
            except ValueError:
                pass

        # 1-2. 일반 텍스트 인라인 각주 정의 라인 감지 및 수거
        m_fn = footnote_def_pat.match(line)
        if m_fn:
            num_str = m_fn.group(1)
            try:
                num = int(num_str)
                term = m_fn.group(2).strip() if m_fn.group(2) else ""
                desc = m_fn.group(3).strip()
                register_footnote(num, term, desc)
                continue  # 본문 흐름에서 제거
            except ValueError:
                pass

        # 2. 불릿 기호 체계 통일 및 계층형 들여쓰기 반영:
        #    - 1단계(대항목): □ (들여쓰기 0칸)
        #    - 2단계(중항목):   ○ (들여쓰기 2칸, 이중 기호 '- ○' 금지)
        #    - 3단계(소항목):     - (들여쓰기 4칸, 2단계 하위)
        #    - 일반 마크다운 목록: 동일 위계의 대시(-) 불릿은 첫 항목과 동일한 들여쓰기를 일관되게 유지
        m_sq = square_bullet_pat.match(line)
        if m_sq:
            rest = m_sq.group(2).strip()
            line = f"□ {rest}  "
            current_bullet_level = 1
            current_dash_indent = ""
        else:
            m_cir = circle_bullet_pat.match(line)
            if m_cir:
                rest = m_cir.group(2).strip()
                line = f"  ○ {rest}  "
                current_bullet_level = 2
                current_dash_indent = ""
            else:
                m_dash = dash_bullet_pat.match(line)
                if m_dash:
                    orig_indent = m_dash.group(1)
                    rest = m_dash.group(2).strip()
                    # 직전 불릿이 중항목(○, level 2)인 경우 그 하위 소항목으로 4칸 들여쓰기
                    if current_bullet_level == 2:
                        line = f"    - {rest}  "
                        current_bullet_level = 3
                        current_dash_indent = "    "
                    # 이미 소항목(level 3)으로 진행 중인 경우 동일 레벨(4칸) 유지
                    elif current_bullet_level == 3:
                        line = f"    - {rest}  "
                    # 직전 불릿이 대항목(□, level 1)인 경우 직속 하위로 2칸 들여쓰기
                    elif current_bullet_level == 1:
                        line = f"  - {rest}  "
                        current_dash_indent = "  "
                    # 대항목이나 중항목이 없는 독립 일반 마크다운 목록인 경우:
                    # 동일 위계 항목들이 첫 항목 이후 강제 들여쓰기되지 않도록 첫 항목의 들여쓰기로 일관 통일
                    else:
                        if not current_dash_indent:
                            if len(orig_indent) >= 4:
                                current_dash_indent = "    "
                            elif len(orig_indent) >= 2:
                                current_dash_indent = "  "
                            else:
                                current_dash_indent = "- "
                        if current_dash_indent == "- ":
                            line = f"- {rest}  "
                        else:
                            line = f"{current_dash_indent}- {rest}  "
                else:
                    if line.strip().startswith('#'):
                        current_bullet_level = 0
                        current_dash_indent = ""

        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)

    # 본문 중간 각주 수거로 인해 발생할 수 있는 중복/고립 수평선(---) 정리
    # 1) 연속된 수평선 정리
    text = re.sub(r'(\n\s*[-*_]{3,}\s*){2,}', r'\n\n---', text)
    # 2) 표 직전/직후의 고립된 수평선 정리 (표의 연속성 보장)
    text = re.sub(r'(\|\s*\n)\s*[-*_]{3,}\s*\n+(\s*\|)', r'\1\2', text)
    # 3) 3개 이상의 과도한 연속 빈 줄 정리
    text = re.sub(r'\n{4,}', r'\n\n\n', text)

    # 3. 본문 인용부 치환 (예: 'Transformer1)' -> 'Transformer[^1]')
    # 과거 정규식 오작동으로 파손된 출처 링크 URL 말미(예: _69fd4fd[^8])를 우선 복원
    text = re.sub(r'(/api/documents/[^\s)>\]]+?)\[\^(\d+)\](?=[,>\s\)]|$)', r'\1\2)', text)

    if footnotes:
        # 마크다운 링크 URL 내부가 각주 치환에 의해 훼손되지 않도록 임시 보호
        protected_urls: list[str] = []
        def _mask_url(m: re.Match) -> str:
            protected_urls.append(m.group(0))
            return f"__MD_URL_PROTECT_{len(protected_urls) - 1}__"

        text = re.sub(r'\]\([^)\n]+\)', _mask_url, text)

        for num in sorted(footnotes.keys()):
            term, desc = footnotes[num]
            if term:
                # 용어명 바로 뒤에 붙은 각주 번호 우선 치환 (예: Transformer1) -> Transformer[^1])
                text = re.sub(rf'({re.escape(term)})\s*{num}\)', rf'\1[^{num}]', text)
            # 일반적인 문자 뒤의 각주 번호 치환 (예: 모달리티4) -> 모달리티[^4], 구조)3) -> 구조)[^3])
            # 단, 연도 표현(예: 2023, 2024 등)의 숫자나 대문자 약어(예: FP4, GPT4 등), 해시 문자열이 오인 치환되지 않도록 가드 적용
            text = re.sub(rf'(?<!\d)(?<![A-Z0-9_])([가-힣A-Za-z\)])\s*{num}\)', rf'\1[^{num}]', text)

        for idx, orig_url in enumerate(protected_urls):
            text = text.replace(f"__MD_URL_PROTECT_{idx}__", orig_url)

        # 4. 수집된 모든 각주를 문서 최하단에 단일 표준 GFM 각주 섹션으로 배치
        fn_section = "\n\n---\n\n### 📌 각주 (Footnotes)\n\n"
        for num in sorted(footnotes.keys()):
            term, desc = footnotes[num]
            if term:
                fn_section += f"[^{num}]: **{term}**: {desc}\n"
            else:
                fn_section += f"[^{num}]: {desc}\n"

        # 본문 말미의 구분선 잔재 정리 후 각주 섹션 부착
        text = text.rstrip()
        if text.endswith('---'):
            text = text[:-3].rstrip()

        text = text + fn_section

    return text


def resolve_citation_links(markdown_text: str, docs_dir: Optional[Path] = None) -> str:
    """본문 내 인용된 위키문서 출처 표기(<출처: ...>) 중 링크가 누락되었거나 파손된 대상을
    지식 DB(WikiDB/docs) 및 5번 데이터 출처 섹션을 바탕으로 자동 매핑하여
    올바른 마크다운 링크 <출처: [문서제목](/api/documents/{doc_id})> 로 자동 복원(Auto-linkify)한다.
    """
    if not markdown_text:
        return markdown_text

    # 1. 문서 카탈로그 색인 구축
    doc_catalog: dict[str, tuple[str, str]] = {}
    doc_id_to_title: dict[str, str] = {}

    def normalize_key(s: str) -> str:
        return re.sub(r'[\s_()\[\]\-\.:]+', '', s).lower()

    # 1-1. 5번 데이터 출처 섹션 우선 수집
    sec5_match = re.search(r'##\s*5\.\s*데이터\s*출처.*?(?=\n##|\Z)', markdown_text, re.DOTALL)
    if sec5_match:
        sec5_text = sec5_match.group(0)
        for line in sec5_text.splitlines():
            link_match = re.search(r'\[(.*?)\]\((?:/api/documents/)?([^)]+)\)', line)
            if link_match:
                t = link_match.group(1).strip()
                did = link_match.group(2).strip().replace('/api/documents/', '')
                if did:
                    doc_id_to_title[did] = t
                    nk = normalize_key(t)
                    if nk:
                        doc_catalog[nk] = (did, t)
                    ndid = normalize_key(did)
                    if ndid:
                        doc_catalog[ndid] = (did, t)

    # 1-2. WikiDB/docs 디렉토리 색인 보강
    if docs_dir is None:
        docs_dir = Path(__file__).resolve().parent.parent / "WikiDB" / "docs"

    if docs_dir.exists():
        for md_path in docs_dir.glob("*.md"):
            did = md_path.stem
            if did.startswith("."):
                continue
            title = did
            try:
                head = md_path.read_text(encoding="utf-8", errors="replace")[:1200]
                t_m = re.search(r'^#\s+(.+)$', head, re.MULTILINE)
                if t_m:
                    title = t_m.group(1).strip()
                else:
                    orig_f_m = re.search(r'\*\*원본\s*파일명\*\*:\s*`?([^`\n]+)`?', head)
                    if orig_f_m:
                        title = Path(orig_f_m.group(1).strip()).stem
            except Exception:
                title = did

            if did not in doc_id_to_title:
                doc_id_to_title[did] = title

            nk = normalize_key(title)
            if nk and nk not in doc_catalog:
                doc_catalog[nk] = (did, title)

            ndid = normalize_key(did)
            if ndid and ndid not in doc_catalog:
                doc_catalog[ndid] = (did, title)

            clean_stem = re.sub(r'_\d+_[a-f0-9]+$', '', did)
            n_clean = normalize_key(clean_stem)
            if n_clean and n_clean not in doc_catalog:
                doc_catalog[n_clean] = (did, title)

    # 2. 단일 출처 항목 리졸브
    def resolve_single_source(raw_item: str) -> Optional[tuple[str, str]]:
        s = raw_item.strip()
        if not s:
            return None

        # 2-1. 이미 올바른 마크다운 링크인 경우: [title](/api/documents/{doc_id})
        already_link = re.match(r'^\[(.*)\]\((?:/api/documents/)?([^)]+)\)$', s)
        if already_link:
            title = already_link.group(1).strip()
            did = already_link.group(2).strip().replace('/api/documents/', '')
            did = re.sub(r'\[\^(\d+)\]$', r'\1', did).rstrip('],>.)')
            return (title, did)

        # 2-2. 텍스트 정제
        cleaned = s.strip('<>[]()\'"').strip()
        if not cleaned:
            return None

        # doc_id 정확 일치
        if cleaned in doc_id_to_title:
            return (doc_id_to_title[cleaned], cleaned)

        # 정규화 키 일치
        nk = normalize_key(cleaned)
        if nk in doc_catalog:
            did, title = doc_catalog[nk]
            chosen_title = title if title and not title.endswith(('a0339d78', 'cfa62149', 'bb494629')) else cleaned
            return (chosen_title, did)

        # 부분 매칭 탐색
        best_match = None
        best_len = 0
        for k, (did, t) in doc_catalog.items():
            if len(k) >= 3 and (k in nk or nk in k):
                common_len = min(len(k), len(nk))
                if common_len > best_len:
                    best_len = common_len
                    best_match = (t, did)

        if best_match and best_len >= 4:
            return best_match

        return (cleaned, "")

    # 3. 본문 내 <출처: ...> 치환
    def replace_citation_tag(match: re.Match) -> str:
        body = match.group(1).strip()
        if re.match(r'^\[.*?\]\(/api/documents/[^)]+\)$', body):
            return f"<출처: {body}>"

        parts = []
        buf = []
        in_bracket = 0
        for char in body:
            if char in ('[', '('):
                in_bracket += 1
                buf.append(char)
            elif char in (']', ')'):
                if in_bracket > 0:
                    in_bracket -= 1
                buf.append(char)
            elif char == ',' and in_bracket == 0:
                parts.append(''.join(buf).strip())
                buf = []
            else:
                buf.append(char)
        if buf:
            parts.append(''.join(buf).strip())

        resolved_items = []
        for p in parts:
            if not p:
                continue
            res = resolve_single_source(p)
            if res:
                t, did = res
                if did:
                    resolved_items.append(f"[{t}](/api/documents/{did})")
                else:
                    resolved_items.append(t)

        if not resolved_items:
            return match.group(0)

        return ", ".join(f"<출처: {item}>" for item in resolved_items)

    # 백틱으로 둘러싸인 출처 태그 및 링크의 백틱 벗기기 + 파손된 각주 URL 복원
    markdown_text = re.sub(r'(/api/documents/[^\s)>\]]+?)\[\^(\d+)\](?=[,>\s\)]|$)', r'\1\2)', markdown_text)
    markdown_text = re.sub(r'`\s*(<출처\s*:[^>]+>)\s*`', r'\1', markdown_text)
    markdown_text = re.sub(r'`\s*(\[[^\]\n]+\]\((?:/api/documents/)?[^)\n]+\))\s*`', r'\1', markdown_text)

    resolved_md = re.sub(r'<출처\s*:\s*([^>]+)>', replace_citation_tag, markdown_text)

    # 4. 이미지 캡션 내 출처 치환: *(... - 출처: ...)*
    def replace_caption_source(match: re.Match) -> str:
        full_caption = match.group(0)
        prefix = match.group(1)
        desc = match.group(2)
        source_raw = match.group(3).strip()
        suffix = match.group(4)

        if '/api/documents/' in source_raw:
            return full_caption

        res = resolve_single_source(source_raw)
        if res and res[1]:
            t, did = res
            return f"{prefix}{desc}[{t}](/api/documents/{did}){suffix}"
        return full_caption

    resolved_md = re.sub(
        r'(\*\()([^\n*]*?출처\s*:\s*)([^\n*()]+)(\)\*)',
        replace_caption_source,
        resolved_md
    )

    return resolved_md


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
    """마크다운 본문에 이미 텍스트로 추출된 페이지는 전면 통 이미지 스냅샷 중복 삽입을 배제한다.
    
    (호환성을 유지하며 빈 목록을 반환함)
    """
    return markdown_text, []


def stitch_adjacent_pdf_images(
    pdf_path: Path,
    raw_md: str,
    search_dirs: list[Path]
) -> str:
    """PDF 내에서 수직으로 타일링/분할된 이미지 스트립을 자동 감지하여 단일 이미지로 결합하고 마크다운을 보정한다."""
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return raw_md

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        logger.warning(f"수직 분할 이미지 병합을 위한 PDF 열기 실패 ({pdf_path.name}): {e}")
        return raw_md

    updated_md = raw_md

    # search_dirs 내의 모든 이미지 파일 인덱싱 (경로, 너비, 높이)
    available_img_files: list[tuple[Path, int, int]] = []
    for s_dir in search_dirs:
        if s_dir and s_dir.exists():
            for f in s_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        pix = pymupdf.Pixmap(str(f))
                        available_img_files.append((f, pix.width, pix.height))
                    except Exception:
                        pass

    try:
        for p_no in range(len(doc)):
            page = doc[p_no]
            images = page.get_images()
            if len(images) < 2:
                continue

            img_rects = []
            for info in images:
                xref = info[0]
                rects = page.get_image_rects(xref)
                for r in rects:
                    if r.width > 80 and r.height > 30 and r.x0 >= 0:
                        img_rects.append((xref, r))

            if len(img_rects) < 2:
                continue

            # x0 기준 정렬 후 y0 기준 정렬
            img_rects.sort(key=lambda item: (round(item[1].x0, 1), round(item[1].y0, 1)))

            # 인접 수직 스트립 체인 탐색
            chains: list[list[tuple[int, pymupdf.Rect]]] = []
            used_indices = set()

            for i in range(len(img_rects)):
                if i in used_indices:
                    continue
                current_chain = [img_rects[i]]

                for j in range(i + 1, len(img_rects)):
                    if j in used_indices:
                        continue
                    last_xref, last_r = current_chain[-1]
                    next_xref, next_r = img_rects[j]

                    same_x = abs(last_r.x0 - next_r.x0) <= 3.0 and abs(last_r.x1 - next_r.x1) <= 3.0
                    touching_y = abs(last_r.y1 - next_r.y0) <= 3.0

                    if same_x and touching_y:
                        current_chain.append((next_xref, next_r))
                        used_indices.add(j)

                if len(current_chain) >= 2:
                    chains.append(current_chain)
                    used_indices.add(i)

            # 체인별 병합 수행
            for chain in chains:
                try:
                    pixmaps = [pymupdf.Pixmap(doc, xref) for xref, _ in chain]
                    base_w = pixmaps[0].width
                    if not all(abs(p.width - base_w) <= 4 for p in pixmaps):
                        continue

                    # 수직 결합 Pixmap 생성
                    total_h = sum(p.height for p in pixmaps)
                    first_p = pixmaps[0]
                    stitched_pix = pymupdf.Pixmap(first_p.colorspace, (0, 0, base_w, total_h), first_p.alpha)

                    curr_y = 0
                    for p in pixmaps:
                        stitched_pix.copy(p, (0, curr_y, base_w, curr_y + p.height))
                        curr_y += p.height

                    # search_dirs에서 각 체인 조각의 디스크 파일 매핑
                    matched_files: list[Path] = []
                    for p in pixmaps:
                        cand = next((f for f, w, h in available_img_files if abs(w - p.width) <= 2 and abs(h - p.height) <= 2 and f not in matched_files), None)
                        if cand:
                            matched_files.append(cand)

                    if len(matched_files) == len(chain):
                        top_file = matched_files[0]
                        rest_files = matched_files[1:]

                        # 상단 파일에 병합 이미지 덮어쓰기 저장
                        stitched_pix.save(str(top_file))
                        logger.info(f"수직 분할 이미지 {len(chain)}개 병합 완료: {top_file.name} ({base_w}x{total_h})")

                        # 잉여 하단 파일들 안전 삭제
                        for rf in rest_files:
                            safe_remove_file(rf)

                        # 마크다운 텍스트에서 분할 이미지 태그 병합 치환
                        top_name_esc = re.escape(top_file.name)
                        for rf in rest_files:
                            rf_name_esc = re.escape(rf.name)
                            comb_pat = rf'(!\[.*?\]\([^\)]*{top_name_esc}[^\)]*\))\s*\n+!\[.*?\]\([^\)]*{rf_name_esc}[^\)]*\)'
                            if re.search(comb_pat, updated_md):
                                updated_md = re.sub(comb_pat, r'\1', updated_md)
                            else:
                                solo_pat = rf'!\[.*?\]\([^\)]*{rf_name_esc}[^\)]*\)\n*'
                                updated_md = re.sub(solo_pat, '', updated_md)

                except Exception as chain_err:
                    logger.debug(f"인접 이미지 체인 병합 실패 (무시됨): {chain_err}")

        doc.close()
    except Exception as e:
        logger.warning(f"수직 분할 이미지 병합 처리 중 오류: {e}")

    return updated_md


def clean_pdf_decorative_images(
    pdf_path: Path,
    raw_md: str,
    search_dirs: list[Path]
) -> str:
    """PDF 내의 표지 일러스트, 상하단 헤더/푸터 기관 로고 등 무의미한 장식 그래픽을 기하학적 규칙으로 감지하여 배제한다."""
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return raw_md

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        logger.warning(f"장식 이미지 배제를 위한 PDF 열기 실패 ({pdf_path.name}): {e}")
        return raw_md

    updated_md = raw_md

    # search_dirs 내의 모든 이미지 파일 인덱싱 (경로, 너비, 높이)
    available_img_files: list[tuple[Path, int, int]] = []
    for s_dir in search_dirs:
        if s_dir and s_dir.exists():
            for f in s_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        pix = pymupdf.Pixmap(str(f))
                        available_img_files.append((f, pix.width, pix.height))
                    except Exception:
                        pass

    decorative_items: list[tuple[int, int, int, str]] = []  # (xref, width, height, reason)
    seen_xrefs = set()

    try:
        for p_no in range(len(doc)):
            page = doc[p_no]
            page_text = page.get_text().strip()
            text_len = len(page_text)
            page_h = page.rect.height

            images = page.get_images()
            for info in images:
                xref = info[0]
                if xref in seen_xrefs:
                    continue

                rects = page.get_image_rects(xref)
                for r in rects:
                    is_decorative = False
                    reason = ""

                    # 1. 다페이지 문서의 1페이지 표지 일러스트 (단일 페이지 문서는 본문이므로 제외, 도표 캡션 존재 시 보존)
                    has_chart_caption = bool(re.search(r'(?:도표|차트|그림|Figure|Chart|Table)\s*\d*', page_text, re.IGNORECASE))
                    if len(doc) > 1 and p_no == 0 and text_len < 400 and not has_chart_caption:
                        is_decorative = True
                        reason = "1페이지 표지 장식 일러스트"
                    # 2. 상단 헤더 영역 로고 (상단 95pt 이내, 높이 70pt 이하)
                    elif r.y1 <= 95.0 and r.height <= 70.0:
                        is_decorative = True
                        reason = "상단 헤더 영역 기관 로고"
                    # 3. 하단 푸터 영역 로고/장식 (하단 80pt 이내, 높이 70pt 이하)
                    elif r.y0 >= page_h - 80.0 and r.height <= 70.0:
                        is_decorative = True
                        reason = "하단 푸터 영역 기관 로고/장식"
                    # 4. 페이지 내 표시 크기가 50pt 이하인 초소형 인디케이터/불릿/아이콘 그래픽
                    elif r.width <= 50.0 and r.height <= 50.0:
                        is_decorative = True
                        reason = f"초소형 인디케이터/아이콘 그래픽 ({r.width:.1f}x{r.height:.1f}pt)"

                    if is_decorative:
                        try:
                            pix = pymupdf.Pixmap(doc, xref)
                            decorative_items.append((xref, pix.width, pix.height, reason))
                            seen_xrefs.add(xref)
                        except Exception:
                            pass
                        break

        # 식별된 장식 이미지 파일 매칭 및 삭제, 마크다운 태그 제거
        removed_files: set[Path] = set()
        for xref, dw, dh, reason in decorative_items:
            cand = next(
                (f for f, w, h in available_img_files if abs(w - dw) <= 2 and abs(h - dh) <= 2 and f not in removed_files),
                None
            )
            if cand:
                removed_files.add(cand)
                file_name = cand.name
                safe_remove_file(cand)
                # 마크다운 태그 및 줄바꿈 제거
                tag_pat = rf'!\[.*?\]\([^\)]*{re.escape(file_name)}[^\)]*\)\s*\n*'
                updated_md = re.sub(tag_pat, '', updated_md)
                logger.info(f"무의미한 장식 이미지 배제 완료: {file_name} ({reason})")

        doc.close()
    except Exception as e:
        logger.warning(f"장식 이미지 배제 처리 중 오류 발생: {e}")

    return updated_md


# Dual-Mode 규정 보호: 표 내부 정량 통계 수치 및 단위 패턴 (숫자 + %, 억원, 원, 달러 등)
_NUMERIC_UNIT_RE = re.compile(r'[\d,]+(?:\.\d+)?\s*(?:%|억원|만원|원|달러|위안|엔|건|개|명|배|pt|bp|천|조|백만|십억)')


def enrich_composite_overlay_images(
    pdf_path: Path,
    raw_md: str,
    search_dirs: list[Path],
    dpi: int = 180
) -> str:
    """PDF 내에서 배경 비트맵 위에 텍스트/라벨이 오버레이된 복합 인포그래픽을 기하학적으로 감지하여,
    텍스트가 포함된 완성형 통 이미지로 고해상도 렌더링하고 마크다운 본문의 억지 분해 중복 표를 배제한다."""
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return raw_md

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        logger.warning(f"복합 오버레이 이미지 보강을 위한 PDF 열기 실패 ({pdf_path.name}): {e}")
        return raw_md

    updated_md = raw_md

    # search_dirs 내의 이미지 파일 인덱싱 (경로, 너비, 높이)
    available_img_files: list[tuple[Path, int, int]] = []
    for s_dir in search_dirs:
        if s_dir and s_dir.exists():
            for f in s_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        pix = pymupdf.Pixmap(str(f))
                        available_img_files.append((f, pix.width, pix.height))
                    except Exception:
                        pass

    try:
        for p_no in range(len(doc)):
            page = doc[p_no]
            images = page.get_images()
            if not images:
                continue

            # 페이지 내 모든 단어 좌표 수집
            all_words = page.get_text("words")  # (x0, y0, x1, y1, word, block_no, line_no, word_no)
            if not all_words:
                continue

            for info in images:
                xref = info[0]
                rects = page.get_image_rects(xref)
                for r in rects:
                    # 1. 크기 조건: 충분한 크기의 인포그래픽/도표 영역 (width >= 200, height >= 150)
                    if r.width < 200 or r.height < 150:
                        continue
                    # 슬라이드 전체를 덮는 배경 캔버스(페이지 너비/높이의 85% 이상)는 레이아웃 배경이므로 제외
                    if r.width >= page.rect.width * 0.85 and r.height >= page.rect.height * 0.85:
                        continue

                    # 2. 텍스트 오버레이 조건: 해당 이미지 Rect와 겹치는 단어 수 조사
                    intersecting_words = [
                        w[4] for w in all_words
                        if pymupdf.Rect(w[:4]).intersects(r)
                    ]

                    # 3. 10단어 이상의 텍스트가 얹어져 있는 복합 인포그래픽인지 판별
                    if len(intersecting_words) < 10:
                        continue

                    logger.info(
                        f"🎨 복합 오버레이 인포그래픽 감지: 페이지 {p_no + 1}, xref {xref}, "
                        f"영역 {r}, 오버레이 단어수 {len(intersecting_words)}개"
                    )

                    # 4. 해당 영역을 텍스트 및 그래픽 포함 완성형 통 이미지로 고해상도 클리핑 렌더링
                    enriched_pix = page.get_pixmap(clip=r, dpi=dpi)

                    # 5. search_dirs에서 원본 껍데기 이미지 파일 매칭
                    raw_pix = pymupdf.Pixmap(doc, xref)
                    matched_file = next(
                        (f for f, w, h in available_img_files if abs(w - raw_pix.width) <= 2 and abs(h - raw_pix.height) <= 2),
                        None
                    )

                    if matched_file and matched_file.exists():
                        # 완성형 통 이미지로 덮어쓰기 저장
                        enriched_pix.save(str(matched_file))
                        logger.info(f"✅ 완성형 통 이미지로 교체 저장: {matched_file.name} ({enriched_pix.width}x{enriched_pix.height})")
                    else:
                        # 신규 파일 저장
                        if search_dirs and search_dirs[0].exists():
                            new_file = search_dirs[0] / f"composite_p{p_no + 1:03d}_{xref}.png"
                            enriched_pix.save(str(new_file))
                            logger.info(f"✅ 신규 완성형 통 이미지 저장: {new_file.name}")

                    # 6. 마크다운 본문에서 해당 인포그래픽 영역 내부 텍스트로 분해된 억지 중복 표 배제
                    # 단, 문서 전체를 대상으로 하지 않고 해당 이미지 태그 바로 뒤부터 다음 헤딩(#) 이전까지의
                    # 인접 블록으로 범위를 엄격히 한정하여 다른 섹션의 정당한 표가 오인 삭제되지 않도록 보장한다.
                    target_filename = matched_file.name if matched_file else f"composite_p{p_no + 1:03d}_{xref}.png"
                    sample_check_words = [w.strip() for w in intersecting_words if len(w.strip()) >= 2]

                    tag_match = re.search(rf'!\[.*?\]\([^\)]*{re.escape(target_filename)}[^\)]*\)', updated_md)
                    if tag_match:
                        start_pos = tag_match.end()
                        # 다음 헤딩(#, ##, ### 등) 직전까지를 검사 범위로 한정
                        next_heading_match = re.search(r'\n#{1,4}\s+', updated_md[start_pos:])
                        if next_heading_match:
                            end_pos = start_pos + next_heading_match.start()
                        else:
                            end_pos = len(updated_md)

                        scope_text = updated_md[start_pos:end_pos]
                        table_pattern = r'(\|.+?\|\r?\n\|[-:\s|]+?\|\r?\n(?:\|.+?\|(?:\r?\n|$))+)'
                        modified_scope = scope_text
                        for t_match in list(re.finditer(table_pattern, scope_text)):
                            table_str = t_match.group(1)
                            overlap_count = sum(1 for sw in sample_check_words if sw in table_str)
                            if overlap_count >= 2:
                                # Dual-Mode 원칙 보호: 표 내부에 수치/단위가 3개 이상이면
                                # 정당한 통계 수치 표이므로 삭제하지 않는다.
                                numeric_matches = _NUMERIC_UNIT_RE.findall(table_str)
                                if len(numeric_matches) >= 3:
                                    logger.debug(f"Dual-Mode 수치 표 보호 (수치 {len(numeric_matches)}개 감지)")
                                    continue
                                logger.info(f"🗑️ 복합 인포그래픽 인접 영역 내 억지 분해 표 배제 ({overlap_count}단어 일치)")
                                modified_scope = modified_scope.replace(table_str, "")

                        updated_md = updated_md[:start_pos] + modified_scope + updated_md[end_pos:]

                    # 7. 완성형 통 이미지 영역(r) 내부에 완전히 포함되거나 대다수가 겹치는 부속 서브 이미지(아이콘, 클립아트, 레벨 바 등) 배제
                    removed_sub_files: set[Path] = set()
                    for sub_info in images:
                        sub_xref = sub_info[0]
                        if sub_xref == xref:
                            continue
                        sub_rects = page.get_image_rects(sub_xref)
                        for sub_r in sub_rects:
                            # 서브 이미지가 통 이미지 영역 r 내부에 포함되거나 70% 이상 겹치는지 판정
                            overlap_area = r.intersect(sub_r).get_area()
                            sub_area = sub_r.get_area()
                            if sub_area > 0 and (overlap_area / sub_area) >= 0.7:
                                try:
                                    sub_pix = pymupdf.Pixmap(doc, sub_xref)
                                    sub_matched = next(
                                        (f for f, w, h in available_img_files if abs(w - sub_pix.width) <= 2 and abs(h - sub_pix.height) <= 2 and f not in removed_sub_files),
                                        None
                                    )
                                    if sub_matched and sub_matched.exists():
                                        removed_sub_files.add(sub_matched)
                                        sub_fname = sub_matched.name
                                        safe_remove_file(sub_matched)
                                        # 마크다운 본문 태그 제거
                                        tag_pat = rf'!\[.*?\]\([^\)]*{re.escape(sub_fname)}[^\)]*\)\s*\n*'
                                        updated_md = re.sub(tag_pat, '', updated_md)
                                        logger.info(f"🗑️ 복합 인포그래픽 내부 부속 서브 이미지 배제: {sub_fname} (통 이미지 {target_filename}에 병합됨)")
                                        break
                                except Exception as sub_err:
                                    logger.debug(f"부속 이미지 제거 중 오류: {sub_err}")

        doc.close()
    except Exception as e:
        logger.warning(f"복합 오버레이 이미지 보강 처리 중 오류 발생: {e}")

    # 연속된 불필요 빈 줄 정리
    updated_md = re.sub(r'\n{3,}', '\n\n', updated_md)
    return updated_md


def get_gemini_api_keys_list() -> list[str]:
    """환경변수에서 주 API 키와 대체(Fallback) 무료 키 목록을 순서대로 수집한다."""
    keys: list[str] = []
    for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_FALLBACK", "GEMINI_API_KEYS"):
        raw_val = os.getenv(env_var)
        if raw_val:
            for k in re.split(r"[,;]+", raw_val):
                clean_k = k.strip().strip("'\"")
                if clean_k and clean_k not in keys:
                    keys.append(clean_k)
    return keys


def is_gemini_key_permanently_exhausted(error: Exception) -> bool:
    """API 키 자체의 크레딧 고갈(402), 만료 또는 인증 실패(401/403)인지 판별한다 (다음 키로 넘어가야 함)."""
    err_str = str(error).upper()
    return any(code in err_str for code in ("402", "DEPLETED", "PREPAYMENT", "401", "403", "PERMISSION_DENIED", "API_KEY_INVALID"))


def is_gemini_rate_limited(error: Exception) -> bool:
    """특정 모델의 일시적 요청량 또는 분당/일일 할당량 초과(429)인지 판별한다 (다음 모델로 넘어가야 함)."""
    err_str = str(error).upper()
    # 402 선불 크레딧 소진은 키 영구 소진이므로 단순 rate limit에서 제외
    if any(code in err_str for code in ("402", "DEPLETED", "PREPAYMENT")):
        return False
    return any(code in err_str for code in ("429", "RESOURCE_EXHAUSTED", "RATE_LIMIT", "QUOTA"))


def is_gemini_key_exhausted_or_invalid(error: Exception) -> bool:
    """발생한 오류가 API 키 크레딧 소진(402), 인증 실패(401/403), 혹은 일시적 할당량 초과(429)인지 종합 판별한다."""
    return is_gemini_key_permanently_exhausted(error) or is_gemini_rate_limited(error)




