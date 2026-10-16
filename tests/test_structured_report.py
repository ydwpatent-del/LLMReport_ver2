"""구조화된 보고서 Pydantic 모델 및 결정론적 마크다운 조립기 단위 테스트."""

import pytest
import markdown
from app.topic_models import (
    StructuredTopicReport,
    SectionBlock,
    TableBlock,
    ImageAssetBlock,
    FootnoteItem,
    assemble_markdown_from_structured_report,
)
from app.utils import heal_markdown_table_boundaries


def test_assemble_markdown_from_structured_report_deterministic():
    """구조화된 Pydantic 보고서 모델이 100% 무결성을 갖춘 표준 GFM 마크다운으로 조립되는지 검증."""
    report = StructuredTopicReport(
        title="양자 컴퓨팅 종합 기술 및 시장 분석 보고서",
        topic="양자 컴퓨팅",
        sections=[
            SectionBlock(
                section_number=1,
                title="기술개요",
                insight="양자 역학 원리를 바탕으로 초고속 연산을 수행합니다.",
                paragraphs=[
                    "양자 컴퓨팅은 큐비트를 기본 단위로 활용합니다 <출처: [통합문서](/api/documents/doc1)>.",
                ],
            ),
            SectionBlock(
                section_number=2,
                title="기술동향",
                paragraphs=[
                    "초전도 및 이온 트랩 방식이 치열하게 경쟁하고 있습니다 <출처: [통합문서](/api/documents/doc1)>.",
                ],
                tables=[
                    TableBlock(
                        title="핵심 기술 방식 비교 요약 표",
                        headers=["기술 방식", "핵심 원리", "장점", "단점", "대표 기업"],
                        rows=[
                            ["초전도", "조셉슨 접합", "빠른 연산", "극저온 필요", "IBM"],
                            ["이온트랩", "전자기장 포획", "긴 결맞음", "느린 게이트", "IonQ"],
                        ],
                        caption="출처: 조사기관",
                    )
                ],
            ),
            SectionBlock(
                section_number=3,
                title="시장동향",
                paragraphs=[
                    "세계 시장은 연평균 38% 성장하고 있습니다 <출처: [통합문서](/api/documents/doc1)>.",
                ],
                tables=[
                    TableBlock(
                        title="시장 규모 및 전망 표",
                        headers=["구분", "2024년", "2029년(E)", "CAGR"],
                        rows=[
                            ["국내", "1,363억 원", "8,393억 원", "43.9%"],
                            ["글로벌", "27억 달러", "138억 달러", "38.6%"],
                        ],
                        caption="단위: 억 원/달러",
                    )
                ],
                images=[
                    ImageAssetBlock(
                        url="/api/assets/doc1/image_001.png",
                        alt="세계 양자 컴퓨팅 시장 규모",
                        caption="도표: 세계 양자 시장 전망",
                    )
                ],
            ),
            SectionBlock(
                section_number=4,
                title="주요업체",
                paragraphs=[
                    "글로벌 빅테크가 상용화를 주도하고 있습니다.",
                ],
                tables=[
                    TableBlock(
                        title="주요 기업별 현황 비교 표",
                        headers=["기업명", "주력 제품", "상용화 단계", "핵심 경쟁력", "협력 파트너"],
                        rows=[
                            ["IBM", "Qiskit", "상용화", "초전도 생태계", "오픈소스"],
                        ],
                    )
                ],
            ),
        ],
        sources=[
            "[통합_양자 컴퓨팅](/api/documents/doc1)",
        ],
        footnotes=[
            FootnoteItem(index=1, term="큐비트", definition="양자 정보의 기본 단위"),
        ],
    )

    assembled_md = assemble_markdown_from_structured_report(report)

    # 1. 5대 표준 목차 존재 검증
    for n in range(1, 6):
        assert f"## {n}." in assembled_md

    # 2. 표 헤더와 구분선 사이 무개행 검증
    assert "| 기술 방식 | 핵심 원리 | 장점 | 단점 | 대표 기업 |\n|:---|:---|:---|:---|:---|" in assembled_md
    assert "| 구분 | 2024년 | 2029년(E) | CAGR |\n|:---|:---|:---|:---|" in assembled_md

    # 3. 표 직후 빈 줄 및 캡션 독립 행 검증
    assert "| IonQ |\n\n*(출처: 조사기관)*" in assembled_md

    # 4. 이미지 및 캡션 단독 행 검증
    assert "![세계 양자 컴퓨팅 시장 규모](/api/assets/doc1/image_001.png)\n*(도표: 세계 양자 시장 전망)*" in assembled_md

    # 5. 각주 최하단 분리 수록 검증
    assert "### 📌 각주 (Footnotes)\n\n[^1]: **큐비트**: 양자 정보의 기본 단위" in assembled_md

    # 6. markdown 파서 렌더링 무결성 검증 (<table> 태그 정상 생성 확인)
    html = markdown.markdown(assembled_md, extensions=["tables"])
    table_count = html.count("<table>")
    assert table_count == 3, f"3개의 표가 모두 정상 <table>로 렌더링되어야 함: {table_count}개 생성됨"
