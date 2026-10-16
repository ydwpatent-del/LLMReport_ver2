"""배경 그래픽 위에 텍스트가 오버레이된 복합 인포그래픽의 통 이미지 추출 및 중복 표 배제 단위 테스트 모듈."""

import pymupdf
from pathlib import Path
from app.utils import enrich_composite_overlay_images


def test_enrich_composite_overlay_images(tmp_path: Path):
    """배경 비트맵 위에 텍스트가 오버레이된 인포그래픽이 감지되어 완성형 통 이미지로 추출되고 중복 표가 배제되는지 검증."""
    pdf_path = tmp_path / "test_overlay_doc.pdf"
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    # 1. 테스트용 PDF 생성: 400x300 크기의 배경 비트맵 위에 텍스트 12단어 오버레이
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # 400x300 픽스맵 (배경 비트맵)
    pix_bg = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 300), False)
    pix_bg.set_rect((0, 0, 400, 300), (220, 240, 255))  # 연파랑 배경
    r_img = pymupdf.Rect(100, 200, 500, 500)
    page.insert_image(r_img, pixmap=pix_bg)

    # 배경 이미지 위에 텍스트 12단어 오버레이 (PyMuPDF 기본 폰트 호환 영문/숫자 키워드)
    overlay_text = (
        "Technology Importance Level 3 High\n"
        "Industry Cycle Level 4 Mature\n"
        "Market Forecast 2024 Year 4111B Growth 6.3%"
    )
    page.insert_text((120, 250), overlay_text, fontsize=12)

    doc.save(str(pdf_path))
    doc.close()

    # 2. 추출 디렉터리에 텍스트가 빠진 껍데기 이미지 파일 준비 (kordoc 시뮬레이션)
    shell_img_file = img_dir / "image_004.png"
    pix_bg.save(str(shell_img_file))
    orig_shell_bytes = shell_img_file.read_bytes()

    # 3. 마크다운 본문: 껍데기 이미지 태그 아래에 텍스트가 억지 표로 분해되어 있는 상황
    raw_md = (
        "# Analysis Report\n\n"
        "## Chapter 1 Market Status\n\n"
        "![Figure 1: Industry Overview](images/image_004.png)\n"
        "*(Source: Research Center)*\n\n"
        "| Category | Content |\n"
        "|:---|:---|\n"
        "| Technology Importance | Level 3 High |\n"
        "| Industry Cycle | Level 4 Mature |\n"
        "| Market Forecast | 2024 Year 4111B Growth 6.3% |\n\n"
        "### Detail Analysis\n\n"
        "| Supply Chain | Target | Demand |\n"
        "|:---|:---|:---|\n"
        "| Upstream Materials | Core Industry | Downstream Products |\n\n"
        "Following body text."
    )

    # 4. 복합 오버레이 인포그래픽 보강 엔진 실행
    updated_md = enrich_composite_overlay_images(pdf_path, raw_md, [img_dir])

    # 5. 검증:
    # 1) shell_img_file에 텍스트가 렌더링된 완성형 통 이미지가 덮어쓰여졌는지 확인
    assert shell_img_file.exists()
    assert shell_img_file.read_bytes() != orig_shell_bytes
    # 2) 마크다운 본문에서 억지로 분해되었던 중복 표가 깨끗하게 배제되었는지 확인
    assert "| Technology Importance | Level 3 High |" not in updated_md
    assert "| Industry Cycle | Level 4 Mature |" not in updated_md
    # 3) 인포그래픽 통 이미지 태그와 캡션 및 다음 섹션의 정당한 표는 온전히 보존되었는지 확인
    assert "image_004.png" in updated_md
    assert "*(Source: Research Center)*" in updated_md
    assert "### Detail Analysis" in updated_md
    assert "| Supply Chain | Target | Demand |" in updated_md
    assert "Following body text." in updated_md


def test_sub_icons_inside_composite_overlay_excluded(tmp_path: Path):
    """복합 인포그래픽 통 이미지 영역 내부에 포함된 부속 레벨 아이콘/클립아트가 자동 배제되는지 검증."""
    pdf_path = tmp_path / "test_sub_icon_doc.pdf"
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # 1. 400x300 대형 복합 인포그래픽 영역
    pix_bg = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 400, 300), False)
    pix_bg.set_rect((0, 0, 400, 300), (220, 240, 255))
    r_img = pymupdf.Rect(100, 200, 500, 500)
    page.insert_image(r_img, pixmap=pix_bg)

    # 2. 인포그래픽 영역 내부에 위치한 40x40 부속 아이콘 (예: 와이파이 레벨 아이콘)
    pix_icon = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 40, 40), False)
    pix_icon.set_rect((0, 0, 40, 40), (0, 100, 255))
    r_icon = pymupdf.Rect(150, 220, 190, 260)  # r_img 내부에 완전히 포함됨
    page.insert_image(r_icon, pixmap=pix_icon)

    # 텍스트 오버레이
    overlay_text = "Technology Importance Level 3 High\nIndustry Cycle Level 4 Mature\nMarket Forecast 2024 Year 4111B"
    page.insert_text((120, 280), overlay_text, fontsize=12)

    doc.save(str(pdf_path))
    doc.close()

    # 이미지 파일 준비
    f_composite = img_dir / "image_004.png"
    f_sub_icon = img_dir / "image_005.png"
    pix_bg.save(str(f_composite))
    pix_icon.save(str(f_sub_icon))

    raw_md = (
        "# Analysis Report\n\n"
        "## Table of Contents\n"
        "1. [Industry Overview](#industry-overview)\n\n"
        "## Chapter 1 Industry Overview\n\n"
        "![Figure 1: Overview](images/image_004.png)\n\n"
        "![Icon](images/image_005.png)\n\n"
        "Following body text."
    )

    # 복합 오버레이 인포그래픽 보강 엔진 실행
    updated_md = enrich_composite_overlay_images(pdf_path, raw_md, [img_dir])

    # 검증:
    # 1) 통 이미지(image_004.png)는 유지됨
    assert f_composite.exists()
    assert "image_004.png" in updated_md
    # 2) 부속 서브 아이콘(image_005.png)은 안전하게 파일 삭제 및 마크다운 태그 제거됨
    assert not f_sub_icon.exists()
    assert "image_005.png" not in updated_md

