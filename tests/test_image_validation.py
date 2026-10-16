"""이미지 유효성 판별 및 비유효 이미지 제외 단위 테스트."""

import pytest
import struct
from pathlib import Path
from app.utils import is_valid_content_image

def test_divider_line_noise_excluded(tmp_path: Path):
    """800x4px 등의 극단적 종횡비를 가진 구분선 노이즈는 제외되는지 검증한다."""
    line_png = tmp_path / "divider_line.png"
    # 800x4 크기 PNG 헤더 생성
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 800, 4)
    line_png.write_bytes(ihdr + b"\x00" * 3000)

    # 800/4 = 200:1 로 종횡비 12:1을 초과하므로 비유효 이미지로 판정되어야 함
    assert is_valid_content_image(line_png) is False


def test_tiny_bullet_icon_excluded(tmp_path: Path):
    """면적 6,000px² 미만(예: 30x30px)의 초소형 글머리 기호 아이콘은 제외되는지 검증한다."""
    bullet_png = tmp_path / "bullet.png"
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 30, 30)
    bullet_png.write_bytes(ihdr + b"\x00" * 2000)

    assert is_valid_content_image(bullet_png) is False


def test_valid_chart_image_accepted(tmp_path: Path):
    """600x400px 크기의 정상적인 차트/도표 이미지는 유효 이미지로 판정되는지 검증한다."""
    chart_png = tmp_path / "chart.png"
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 600, 400)
    chart_png.write_bytes(ihdr + b"\x00" * 5000)

    # 종횡비 1.5:1, 면적 240,000px²
    assert is_valid_content_image(chart_png) is True


def test_caption_associated_image_relaxed(tmp_path: Path):
    """약간 작은 크기(70x70, 4,900px²)라도 공식 캡션이 수반되면 유효 이미지로 인정되는지 검증한다."""
    small_chart_png = tmp_path / "small_chart.png"
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 70, 70)
    small_chart_png.write_bytes(ihdr + b"\x00" * 2500)

    # 캡션이 없을 때는 6,000px² 미만이라 제외
    assert is_valid_content_image(small_chart_png, has_caption=False) is False
    # 캡션이 수반될 때는 4,000px² 이상이므로 승인
    assert is_valid_content_image(small_chart_png, has_caption=True) is True


def test_corrupt_or_tiny_file_excluded(tmp_path: Path):
    """1.5KB 미만의 극소형 파일 또는 깨진 파일은 제외되는지 검증한다."""
    tiny_file = tmp_path / "corrupt.png"
    tiny_file.write_bytes(b"\x00" * 500)

    assert is_valid_content_image(tiny_file) is False


def test_80x80_uncaptioned_icon_excluded(tmp_path: Path):
    """캡션이 없는 80x80px(6,400px²) 크기의 장식용 미니 아이콘은 제외되는지 검증한다."""
    icon_png = tmp_path / "icon_80.png"
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 80, 80)
    icon_png.write_bytes(ihdr + b"\x00" * 2500)

    assert is_valid_content_image(icon_png, has_caption=False) is False


def test_blank_box_fill_excluded(tmp_path: Path):
    """해상도는 크지만(1819x373) 바이트 밀도가 극단적으로 낮은 대형 단색 배경/박스는 제외되는지 검증한다."""
    box_png = tmp_path / "blank_box.png"
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 1819, 373)
    # 면적 678,487px²에 비해 3.5KB 수준의 극단적 저밀도 단색 데이터
    box_png.write_bytes(ihdr + b"\x00" * 3500)

    assert is_valid_content_image(box_png) is False


def test_blank_slide_canvas_excluded(tmp_path: Path):
    """1122x793 크기의 대형 캔버스 중 70% 이상이 백지인 슬라이드 배경 템플릿은 배제되는지 검증한다."""
    import pymupdf
    template_png = tmp_path / "slide_template.png"
    w, h = 1122, 793
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, w, h), False)
    # 70% 영역을 흰색(#FFFFFF), 30% 영역을 검은색(#000000)으로 채움
    pix.set_rect((0, 0, w, h), (255, 255, 255))
    pix.set_rect((0, 0, int(w * 0.3), h), (10, 10, 10))
    pix.save(str(template_png))

    # 공식 캡션이 없는 경우 65% 이상 백지이므로 제외되어야 함
    assert is_valid_content_image(template_png, has_caption=False) is False


def test_stitch_adjacent_pdf_images(tmp_path: Path):
    """수직으로 맞닿아 쪼개진 스트립 이미지들이 온전한 1장의 이미지로 자동 병합되는지 검증한다."""
    import pymupdf
    from app.utils import stitch_adjacent_pdf_images

    # 1. 테스트용 PDF 생성: 동일 가로폭(w=400)에 위아래로 딱 맞닿은(y1=100, y0=100) 2개 이미지 배치
    pdf_path = tmp_path / "split_test.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # 2개의 스트립 픽스맵 생성 (400x150)
    pix1 = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 150), False)
    pix1.set_rect((0, 0, 400, 150), (200, 50, 50))  # 빨간색 상단
    pix2 = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 150), False)
    pix2.set_rect((0, 0, 400, 150), (50, 200, 50))  # 초록색 하단

    # 페이지에 수직으로 연속 배치 (r1: y=50~200, r2: y=200~350)
    r1 = pymupdf.Rect(100, 50, 500, 200)
    r2 = pymupdf.Rect(100, 200, 500, 350)
    page.insert_image(r1, pixmap=pix1)
    page.insert_image(r2, pixmap=pix2)
    doc.save(str(pdf_path))
    doc.close()

    # 2. 추출 디렉터리에 2개 파일 준비
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    f1 = img_dir / "image_001.png"
    f2 = img_dir / "image_002.png"
    pix1.save(str(f1))
    pix2.save(str(f2))

    raw_md = (
        "# 테스트 문서\n\n"
        "![그림 1: 상단부](images/image_001.png)\n"
        "![그림 1: 하단부](images/image_002.png)\n\n"
        "본문 설명입니다."
    )

    # 3. 수직 병합 실행
    updated_md = stitch_adjacent_pdf_images(pdf_path, raw_md, [img_dir])

    # 4. 검증:
    # - f1(상단) 파일이 병합되어 높이가 300px로 증가
    merged_pix = pymupdf.Pixmap(str(f1))
    assert merged_pix.width == 400
    assert merged_pix.height == 300
    # - f2(잉여 하단) 파일은 안전 삭제됨
    assert not f2.exists()
    # - 마크다운 본문에서 image_002 태그가 제거되고 단일 태그로 통합됨
    assert "image_001.png" in updated_md
    assert "image_002.png" not in updated_md


def test_text_glyph_fragment_excluded(tmp_path: Path):
    """높이가 150px 이하이고 종횡비가 1.8 이상인 텍스트 단어 조각 비트맵(3KB 미만)은 배제된다."""
    glyph_png = tmp_path / "glyph_fragment.png"
    # 316x119 해상도, 약 2KB 크기 생성
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">LL", 316, 119)
    glyph_png.write_bytes(ihdr + b"\x00" * 2000)

    # 캡션 유무와 무관하게 텍스트 조각 노이즈로 분류되어 배제되어야 함
    assert is_valid_content_image(glyph_png, has_caption=True) is False
    assert is_valid_content_image(glyph_png, has_caption=False) is False


def test_clean_pdf_decorative_images(tmp_path: Path):
    """1페이지 표지 장식 일러스트 및 상하단 헤더/푸터 영역 기관 로고가 일반화된 기하학적 규칙으로 자동 배제되는지 검증."""
    import pymupdf
    from app.utils import clean_pdf_decorative_images

    # 1. 테스트용 PDF 생성
    pdf_path = tmp_path / "test_doc_with_logo.pdf"
    doc = pymupdf.open()

    # Page 1: 표지 (글자수 50자 미만) + 표지 그래픽
    p1 = doc.new_page(width=600, height=800)
    p1.insert_text((50, 100), "산업 분석 리포트\n2026. 5. 27.\n작성자: 리서치팀", fontsize=16)
    pix_cover = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 300), 0)
    p1.insert_image(pymupdf.Rect(100, 200, 500, 500), pixmap=pix_cover)

    # Page 2: 본문 + 상단 헤더 로고 (y=30~60) + 본문 중앙 차트 (y=200~450)
    p2 = doc.new_page(width=600, height=800)
    p2.insert_text((50, 120), "제1장 시장 현황\n본문 텍스트 내용입니다.", fontsize=12)
    pix_logo = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 150, 40), 0)
    pix_chart = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 250), 0)
    p2.insert_image(pymupdf.Rect(420, 30, 570, 70), pixmap=pix_logo)       # 헤더 로고 (y < 90)
    p2.insert_image(pymupdf.Rect(100, 200, 500, 450), pixmap=pix_chart)     # 본문 차트 (중앙)

    doc.save(str(pdf_path))
    doc.close()

    # 2. 이미지 디렉터리 준비
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    f_cover = img_dir / "image_001.png"
    f_logo = img_dir / "image_002.png"
    f_chart = img_dir / "image_003.png"
    pix_cover.save(str(f_cover))
    pix_logo.save(str(f_logo))
    pix_chart.save(str(f_chart))

    raw_md = (
        "# 산업 분석 리포트\n\n"
        "![표지 이미지](images/image_001.png)\n\n"
        "## 제1장 시장 현황\n\n"
        "![기관 로고](images/image_002.png)\n\n"
        "본문 설명입니다.\n\n"
        "![도표 1: 시장 점유율](images/image_003.png)\n"
    )

    # 3. 장식 이미지 정돈 실행
    cleaned_md = clean_pdf_decorative_images(pdf_path, raw_md, [img_dir])

    # 4. 검증:
    # - 표지 그래픽 (image_001.png) 삭제 및 마크다운에서 제거
    assert not f_cover.exists()
    assert "image_001.png" not in cleaned_md
    # - 헤더 로고 (image_002.png) 삭제 및 마크다운에서 제거
    assert not f_logo.exists()
    assert "image_002.png" not in cleaned_md
    # - 본문 차트 (image_003.png) 유지 및 마크다운에 보존
    assert f_chart.exists()
    assert "image_003.png" in cleaned_md


def test_flat_pictogram_icon_excluded(tmp_path: Path):
    """단색/이색으로 구성된 120x120px 크기의 단순 레벨 아이콘/픽토그램(캡션 없음)은 배제되는지 검증."""
    import pymupdf
    icon_png = tmp_path / "level_icon.png"
    w, h = 120, 120
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, w, h), False)
    # 배경 흰색, 전경 파란색 (단 2가지 색상만 사용하는 단순 심볼 아이콘)
    pix.set_rect((0, 0, w, h), (255, 255, 255))
    pix.set_rect((30, 30, 90, 90), (0, 80, 220))
    pix.save(str(icon_png))

    # 캡션이 없는 경우 단순 픽토그램으로 판정되어 배제되어야 함
    assert is_valid_content_image(icon_png, has_caption=False) is False





