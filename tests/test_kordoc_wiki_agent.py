"""kordoc-wiki-ingest 전용 에이전트 단위 테스트."""

import pytest
from pathlib import Path
from app.kordoc_wiki_agent import KordocWikiAgent

def test_kordoc_wiki_agent_rule_based_pipeline(tmp_path: Path):
    """KordocWikiAgent가 kordoc-wiki-ingest 5대 원칙에 따라 무삭제 마크다운을 산출하는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)

    source_file = tmp_path / "LS증권_반도체_2026.md"
    source_file.write_text(
        "# 산업 분석\n\n"
        "2026.06.30\n\n"
        "I. 개요\n"
        "HBM 및 DRAM 공급 부족이 심화되고 있습니다.\n\n"
        "1. 세부 전망\n"
        "소부장 밸류체인의 실적 개선이 기대됩니다.\n",
        encoding="utf-8"
    )

    target_md, images, title = agent.execute_ingest(
        source_path=source_file,
        doc_id="test_ingest_001",
        file_hash="hash987654321"
    )

    assert target_md.exists()
    assert target_md.parent == docs_dir
    content = target_md.read_text(encoding="utf-8")

    # 1. 메타데이터 헤더 검증
    assert "# LS증권_반도체_2026" in content
    assert "**발행기관**" in content
    assert "**데이터 보존 원칙**" in content
    assert "100% 무삭제 완본" in content

    # 2. 헤딩 위계 정돈 검증
    assert "## I. 개요" in content or "# I. 개요" in content or "### 1. 세부 전망" in content
