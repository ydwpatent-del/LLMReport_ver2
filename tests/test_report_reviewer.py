"""ReportReviewAgent 품질 검수 단위 테스트."""

import pytest
from app.report_reviewer import ReportReviewAgent

FLAWED_MD = """# 테스트 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서

## 1. 기술개요
기술의 개요입니다. 안녕하세요, 보고서를 작성해 드립니다.

## 2. 기술동향
기술 동향 내용입니다. 표는 없습니다.

## 3. 시장동향 (국내/세계시장 규모 데이터)
시장이 크게 성장하고 있습니다. 수치나 표는 없습니다.

## 4. 주요업체
주요 기업들이 경쟁하고 있습니다.

## 5. 데이터 출처
- [참고문서](/api/documents/doc1)
"""

PERFECT_MD = """# 칩렛 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 칩렛

## 1. 기술개요
### 1.1 기술 개념 및 등장 배경
칩렛은 개별 다이를 연결하는 첨단 패키징 기술이다.

## 2. 기술동향
UCIe 표준을 적용하며 3nm 공정과 연계된다.

| 기술 방식 | 대역폭 | 장점 |
|---|---|---|
| 2.5D | 1Tbps | 고밀도 연결 |
| 3D | 2Tbps | 수직 적층 |

![다이어그램](/api/assets/doc/img.png)
*(도표: 패키징 구조)*

## 3. 시장동향 (국내/세계시장 규모 데이터)
2025년 50억 달러에서 2030년 400억 달러로 CAGR 40% 고성장이 전망된다.

| 연도 | 시장규모(억 달러) |
|---|---|
| 2025 | 50 |
| 2030 | 400 |

## 4. 주요업체
인텔, TSMC, 삼성전자가 주도하고 있다.

| 기업명 | 주요 제품 | 전략 포지셔닝 |
|---|---|---|
| TSMC | CoWoS | 파운드리 주도 |

## 5. 데이터 출처
- [칩렛 문서](/api/documents/chiplet)
"""

def test_reviewer_detects_flaws():
    """결함이 있는 보고서에 대해 checklist 항목 실패 및 defects 검출 확인."""
    reviewer = ReportReviewAgent(api_key="dummy_key")
    res = reviewer.review_report(FLAWED_MD, topic="테스트")

    assert res["passed_all"] is False
    assert res["checklist"]["tables_valid"] is False  # 3대 표 누락
    assert res["checklist"]["quantitative_data_valid"] is False  # 수치 부재
    assert res["checklist"]["tone_valid"] is False  # 인사말 포함
    assert len(res["defects"]) > 0
    assert len(res["actionable_suggestions"]) > 0

def test_reviewer_passes_perfect_report():
    """완벽한 보고서에 대해 5대 체크리스트 전수 통과 확인."""
    reviewer = ReportReviewAgent(api_key="dummy_key")
    res = reviewer.review_report(PERFECT_MD, topic="칩렛")

    assert res["checklist"]["structure_valid"] is True
    assert res["checklist"]["tables_valid"] is True
    assert res["checklist"]["quantitative_data_valid"] is True
    assert res["checklist"]["images_valid"] is True
    assert res["checklist"]["tone_valid"] is True
    assert res["passed_all"] is True
    assert len(res["defects"]) == 0
