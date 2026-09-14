"""주제 기반 지식 보고서 생성 시스템 단위 및 통합 테스트."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.topic_search import (
    parse_markdown_sections,
    search_relevant_sections,
    SectionChunk
)
from app.topic_generator import TopicReportGenerator

SAMPLE_MD = """# 칩렛(Chiplet) 반도체
> - **문서분류**: 리서치 보고서
> - **원본형식**: PDF

## 산업 개요
![문서 표지](/api/assets/sample_chiplet/image_001.png)
반도체 미세 공정 한계로 칩렛이 주목받고 있습니다.

## 기술 동향
칩렛은 개별 다이를 연결하는 고밀도 패키징 기술입니다.
초고속 인터커넥트 UCIe 표준을 적용합니다.

![칩렛 패키징 아키텍처 다이어그램](/api/assets/sample_chiplet/image_005.png)
*(도표 5: 칩렛 인터커넥트 구조)*

## 시장 현황
세계 칩렛 시장은 연평균 40% 이상 고성장할 전망입니다.
2025년 50억 달러에서 2030년 400억 달러 규모로 확대됩니다.

![글로벌 시장 규모 추이 차트](/api/assets/sample_chiplet/image_008.png)
*(그림 8: 세계 칩렛 시장 전망)*

## 주요 업체
인텔, AMD, TSMC, 삼성전자 등이 시장을 주도하고 있습니다.
"""

def test_parse_markdown_sections():
    """마크다운 헤딩 분할 및 유의미한 이미지 매핑 테스트 (표지성 이미지 배제 확인)."""
    sections = parse_markdown_sections(
        md_text=SAMPLE_MD,
        doc_id="sample_chiplet",
        title="칩렛(Chiplet) 반도체"
    )
    
    assert len(sections) >= 4
    section_titles = [s.heading for s in sections]
    assert "기술 동향" in section_titles
    assert "시장 현황" in section_titles
    assert "주요 업체" in section_titles

    tech_section = next(s for s in sections if s.heading == "기술 동향")
    assert "고밀도 패키징" in tech_section.text
    assert len(tech_section.images) == 1
    assert "image_005.png" in tech_section.images[0]["url"]

    # 표지성 첫 번째 이미지(image_001.png)는 산업 개요에서 걸러지거나 제외되는지 확인
    overview_section = next(s for s in sections if s.heading == "산업 개요")
    # image_001.png는 표지성이므로 images 리스트에서 배제되었는지 검증
    for img in overview_section.images:
        assert "image_001.png" not in img["url"]

def test_search_relevant_sections(tmp_path):
    """주제 키워드 기반 연관 섹션 검색 테스트."""
    doc_file = tmp_path / "chiplet_doc.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")

    results = search_relevant_sections("칩렛 시장 규모", docs_dir=tmp_path, top_k=2)
    assert len(results) > 0
    top_res = results[0]
    assert "chiplet" in top_res["doc_id"].lower()
    assert len(top_res["sections"]) > 0

def test_saved_report_distinction(tmp_path):
    """생성 보고서 저장 시 디렉토리 격리 및 메타데이터 식별성 검증."""
    reports_dir = tmp_path / "reports"
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    mock_llm_markdown = """# 차세대 칩렛 기술 및 시장 종합 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
> - **주제어**: 칩렛
> - **생성일시**: 2026-09-14

## 1. 기술개요
칩렛은 소형 반도체 다이를 결합하는 기술입니다. [출처: 칩렛 반도체](/api/documents/sample_chiplet)

## 2. 기술동향
UCIe 기반 초고속 인터커넥트가 핵심입니다. [출처: 칩렛 반도체](/api/documents/sample_chiplet)
![칩렛 패키징 아키텍처 다이어그램](/api/assets/sample_chiplet/image_005.png)
*(도표 5: 칩렛 인터커넥트 구조)*

## 3. 시장동향 (국내/세계시장 규모 데이터)
2030년 400억 달러에 달할 전망입니다. [출처: 칩렛 반도체](/api/documents/sample_chiplet)
![글로벌 시장 규모 추이 차트](/api/assets/sample_chiplet/image_008.png)
*(그림 8: 세계 칩렛 시장 전망)*

## 4. 주요업체
TSMC와 삼성전자가 주도합니다. [출처: 칩렛 반도체](/api/documents/sample_chiplet)

## 5. 데이터 출처
- [칩렛 반도체](/api/documents/sample_chiplet)
"""

    report_info = generator.save_report(
        topic="칩렛",
        markdown=mock_llm_markdown,
        sources=[{"doc_id": "sample_chiplet", "title": "칩렛(Chiplet) 반도체"}]
    )

    saved_path = Path(report_info["file_path"])
    assert saved_path.exists()
    assert saved_path.parent == reports_dir
    content = saved_path.read_text(encoding="utf-8")
    assert "🤖 AI 생성 주제 보고서" in content
    assert report_info["topic"] == "칩렛"
    assert report_info["is_synthesized"] is True

def test_topic_router_endpoints():
    """FastAPI topic_router 엔드포인트 동작 테스트."""
    from fastapi.testclient import TestClient
    from app.server import create_app

    app = create_app()
    client = TestClient(app)

    # 1. 추천 키워드 엔드포인트
    res = client.get("/api/topic/suggestions")
    assert res.status_code == 200
    data = res.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) > 0
    assert "칩렛" in data["suggestions"]

    # 2. 보고서 목록 엔드포인트
    res_reports = client.get("/api/topic/reports")
    assert res_reports.status_code == 200
    assert isinstance(res_reports.json(), list)


def test_generate_report_uses_only_valid_model_names():
    """보고서 생성 모델 목록에 존재하지 않는 gemini-3.6-flash가 없어야 한다."""
    import inspect
    from app.topic_generator import TopicReportGenerator

    source = inspect.getsource(TopicReportGenerator.generate_report)
    assert "gemini-3.6-flash" not in source, \
        "gemini-3.6-flash는 존재하지 않는 모델명입니다. 유효한 모델명으로 교체하세요."

