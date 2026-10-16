"""LLM의 자의적 이미지 태그 누락 방지 및 사후 외과적 재주입(Reconciliation) 단위 테스트 모듈."""

import pytest
from pathlib import Path
from app.kordoc_wiki_agent import KordocWikiAgent

def test_extract_and_inline_images_enriches_semantic_alt_and_context(tmp_path: Path):
    """사전 단계에서 캡션이 없는 유효 이미지에 인접 헤딩 기반 의미 태그를 부여하고 문맥을 보관하는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)

    # 1. 테스트용 대형 이미지 파일 생성 (유효 콘텐츠 조건: 다채로운 픽셀 패턴으로 단색 박스 및 공백률 필터 통과)
    source_img_dir = tmp_path / "kordoc_images"
    source_img_dir.mkdir(parents=True, exist_ok=True)
    test_img = source_img_dir / "image_004.png"
    
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 250, 250), False)
    # 복합 그래픽 시뮬레이션 (스트라이프 및 색상 변동)
    samples = bytearray(pix.samples)
    for y in range(250):
        for x in range(250):
            idx = (y * 250 + x) * 3
            samples[idx] = (x * 7) % 255
            samples[idx + 1] = (y * 11) % 255
            samples[idx + 2] = ((x + y) * 13) % 255
    pix = pymupdf.Pixmap(pymupdf.csRGB, 250, 250, bytes(samples), False)
    pix.save(str(test_img))

    raw_md = (
        "### 업종 분류 및 산업기술코드\n\n"
        "기타 발전기 및 전기변환장치 제조업(C28119)\n\n"
        "전력변환기기(200302)\n\n"
        "![image](image_004.png)\n\n"
        "### 산업 구조\n\n"
        "후방 산업은 전력 반도체 부품 산업임.\n"
    )

    doc_asset_dir = assets_dir / "test_doc"
    adjusted_md, images_info = agent._extract_and_inline_images(
        raw_md=raw_md,
        doc_id="test_doc",
        doc_asset_dir=doc_asset_dir,
        search_dirs=[source_img_dir]
    )

    # 1) 에셋 디렉터리에 복사되었는지 확인
    assert (doc_asset_dir / "image_004.png").exists()
    assert len(images_info) == 1
    assert images_info[0]["filename"] == "image_004.png"

    # 2) images_info에 문맥 정보(context_before, nearest_heading)가 수집되었는지 확인
    assert "context_before" in images_info[0]
    assert "전력변환기기" in images_info[0]["context_before"]
    assert "업종 분류" in images_info[0].get("nearest_heading", "")

    # 3) alt 태그가 인접 헤딩을 바탕으로 승격되었는지 확인
    assert "업종 분류" in adjusted_md


def test_validate_and_fix_image_links_reinjects_missing_image(tmp_path: Path):
    """사후 단계에서 LLM이 이미지 태그를 지워버렸을 때, 에셋에 실존하는 유효 이미지를 문맥 위치에 외과적으로 재주입하는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)

    doc_asset_dir = assets_dir / "test_doc"
    doc_asset_dir.mkdir(parents=True, exist_ok=True)
    test_img = doc_asset_dir / "image_004.png"
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 200, 200), False)
    samples = bytearray(pix.samples)
    for y in range(200):
        for x in range(200):
            idx = (y * 200 + x) * 3
            samples[idx] = (x * 7) % 255
            samples[idx + 1] = (y * 11) % 255
            samples[idx + 2] = ((x + y) * 13) % 255
    pix = pymupdf.Pixmap(pymupdf.csRGB, 200, 200, bytes(samples), False)
    pix.save(str(test_img))

    # LLM이 image_004 태그를 완전히 빠뜨리고 생성한 마크다운 결과물
    llm_output_missing_image = (
        "# 전기차 충전기\n\n"
        "### 업종 분류 및 산업기술코드\n\n"
        "기타 발전기 및 전기변환장치 제조업(C28119)\n\n"
        "전력변환기기(200302)\n\n"
        "### 산업 구조\n\n"
        "후방 산업은 전력 반도체 부품 산업임.\n"
    )

    images_info = [{
        "filename": "image_004.png",
        "path": test_img,
        "context_before": "전력변환기기(200302)",
        "context_after": "### 산업 구조",
        "nearest_heading": "업종 분류 및 산업기술코드"
    }]

    fixed_md = agent._validate_and_fix_image_links(
        final_md=llm_output_missing_image,
        doc_id="test_doc",
        doc_asset_dir=doc_asset_dir,
        images_info=images_info
    )

    # image_004.png 태그가 복원되었는지 검증
    assert "/api/assets/test_doc/image_004.png" in fixed_md

    # 복원 위치가 '전력변환기기(200302)' 뒤, '### 산업 구조' 앞인지 검증
    pos_before = fixed_md.find("전력변환기기(200302)")
    pos_img = fixed_md.find("image_004.png")
    pos_after = fixed_md.find("### 산업 구조")

    assert pos_before != -1
    assert pos_img != -1
    assert pos_after != -1
    assert pos_before < pos_img < pos_after
