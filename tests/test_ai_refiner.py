"""AI 위키 리파이너 및 구조화 정돈 단위 테스트."""

import pytest
from pathlib import Path
from app.ai_refiner import AIRefiner

def test_rule_based_refine_headings_and_metadata():
    """룰베이스 리파이너가 헤딩 위계, 엔티티 태그, 메타데이터를 올바르게 정돈하는지 검증한다."""
    refiner = AIRefiner()
    
    raw_md = (
        "LS증권 반도체 산업 전망 보고서\n"
        "2025.06.02 발행\n\n"
        "I. 산업 개황\n"
        "DRAM 및 NAND 시장의 반등세가 뚜렷하게 나타나고 있습니다.\n\n"
        "1. HBM 시장 동향\n"
        "HBM3E 양산 본격화에 따라 관련 소부장 기업들의 수혜가 예상됩니다.\n\n"
        "![image](/api/assets/doc1/image_001.png)\n"
        "<도표 1> 분기별 HBM 수요 전망 (자료: LS증권, 단위: 억달러)\n"
    )

    refined_md, meta = refiner.refine_text(
        raw_md=raw_md,
        doc_id="doc1",
        original_filename="LS증권_반도체_20250602.pdf",
        file_hash="hash123456"
    )

    # 1. 메타데이터 헤더 검증
    assert "# LS" in refined_md
    assert "**발행기관**" in refined_md
    assert "**핵심 엔티티**" in refined_md
    assert "DRAM" in refined_md or "HBM" in refined_md

    # 2. 헤딩 위계 검증
    assert "## I. 산업 개황" in refined_md or "## 1. HBM" in refined_md or "### 1. HBM" in refined_md

    # 3. 도표 캡션 및 인라인 이미지 결합 검증
    assert "/api/assets/doc1/image_001.png" in refined_md
    assert "*(자료:" in refined_md or "도표 1" in refined_md or "HBM 수요 전망" in refined_md


def test_publisher_list_uses_shared_constant():
    """ai_refiner와 kordoc_wiki_agent 모두 utils.KNOWN_PUBLISHERS를 사용해야 한다."""
    import inspect
    from app import ai_refiner, kordoc_wiki_agent
    from app.utils import KNOWN_PUBLISHERS

    assert isinstance(KNOWN_PUBLISHERS, list) and len(KNOWN_PUBLISHERS) > 0
    assert "KNOWN_PUBLISHERS" in inspect.getsource(ai_refiner), \
        "ai_refiner가 KNOWN_PUBLISHERS를 임포트하지 않음"
    assert "KNOWN_PUBLISHERS" in inspect.getsource(kordoc_wiki_agent), \
        "kordoc_wiki_agent가 KNOWN_PUBLISHERS를 임포트하지 않음"

