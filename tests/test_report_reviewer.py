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
칩렛은 개별 다이를 연결하는 첨단 패키징 기술이다. <출처: [칩렛 기술 문서](/api/documents/chiplet)>

## 2. 기술동향
UCIe 표준을 적용하며 3nm 공정과 연계된다. <출처: [칩렛 기술 문서](/api/documents/chiplet)>

| 기술 방식 | 대역폭 | 장점 |
|---|---|---|
| 2.5D | 1Tbps | 고밀도 연결 |
| 3D | 2Tbps | 수직 적층 |

![다이어그램](/api/assets/doc/img.png)
*(도표: 패키징 구조)*

## 3. 시장동향 (국내/세계시장 규모 데이터)
2025년 50억 달러에서 2030년 400억 달러로 CAGR 40% 고성장이 전망된다. <출처: [칩렛 시장 전망](/api/documents/chiplet)>

| 연도 | 시장규모(억 달러) |
|---|---|
| 2025 | 50 |
| 2030 | 400 |

## 4. 주요업체
인텔, TSMC, 삼성전자가 주도하고 있다. <출처: [칩렛 기업 동향](/api/documents/chiplet)>

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
    assert res["checklist"]["citations_valid"] is False  # 본문 출처 태그 누락
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
    assert res["checklist"]["citations_valid"] is True
    assert res["checklist"]["tone_valid"] is True
    assert res["passed_all"] is True
    assert len(res["defects"]) == 0


def test_reviewer_detects_fresh_docs():
    """WikiDB에 신규 등재 문서가 있는 경우 fresh_knowledge_synced 실패 및 defects 검출 확인."""
    reviewer = ReportReviewAgent(api_key="dummy_key")
    fresh_docs = [
        {"doc_id": "new_doc_1", "title": "2026 차세대 패키징 로드맵"},
        {"doc_id": "new_doc_2", "title": "최신 칩렛 시장 조사"}
    ]
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", fresh_docs=fresh_docs)

    assert res["checklist"]["fresh_knowledge_synced"] is False
    assert res["passed_all"] is False
    assert any("신규 등재된 관련 문서 2건" in d for d in res["defects"])
    assert len(res["fresh_docs"]) == 2


def test_reviewer_passes_when_no_fresh_docs():
    """신규 등재 문서가 없는 경우(fresh_docs=[]) fresh_knowledge_synced 통과 확인."""
    reviewer = ReportReviewAgent(api_key="dummy_key")
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", fresh_docs=[])

    assert res["checklist"]["fresh_knowledge_synced"] is True
    assert res["passed_all"] is True
    assert len(res["defects"]) == 0
    assert res["fresh_docs"] == []


def test_reviewer_detects_malformed_tables():
    """표 헤더 앞에 줄바꿈이 누락된 파손 표(Malformed Table)를 정확히 결함으로 감지하는지 확인."""
    reviewer = ReportReviewAgent(api_key="dummy_key")
    # PERFECT_MD에서 표 헤더 앞에 텍스트를 줄바꿈 없이 붙인 마크다운
    malformed_md = PERFECT_MD.replace(
        "\n| 기술 방식 | 대역폭 | 장점 |",
        "*(자료: 협회)* <출처: [문서](/api/doc)>| 기술 방식 | 대역폭 | 장점 |"
    )

    res = reviewer.review_report(malformed_md, topic="칩렛")
    assert res["checklist"]["tables_valid"] is False
    assert res["passed_all"] is False
    assert any("표 문법 파손 감지" in d for d in res["defects"])


def test_reviewer_validates_section_specific_tables():
    """2장(기술 비교), 3장(시장 전망), 4장(기업 비교) 표가 각 섹션에 위치하는지 검증."""
    reviewer = ReportReviewAgent(api_key="dummy_key")

    # 1. 2장 기술 비교표만 누락된 경우
    no_tech_table_md = PERFECT_MD.replace(
        "| 기술 방식 | 대역폭 | 장점 |\n|---|---|---|\n| 2.5D | 1Tbps | 고밀도 연결 |\n| 3D | 2Tbps | 수직 적층 |",
        "2장에는 표가 없습니다."
    )
    res1 = reviewer.review_report(no_tech_table_md, topic="칩렛")
    assert res1["checklist"]["tables_valid"] is False
    assert any("2장" in d and "기술" in d for d in res1["defects"])

    # 2. 3장 시장 전망표만 누락된 경우
    no_market_table_md = PERFECT_MD.replace(
        "| 연도 | 시장규모(억 달러) |\n|---|---|\n| 2025 | 50 |\n| 2030 | 400 |",
        "3장에는 표가 없습니다."
    )
    res2 = reviewer.review_report(no_market_table_md, topic="칩렛")
    assert res2["checklist"]["tables_valid"] is False
    assert any("3장" in d and "시장" in d for d in res2["defects"])

    # 3. 4장 기업 비교표만 누락된 경우
    no_company_table_md = PERFECT_MD.replace(
        "| 기업명 | 주요 제품 | 전략 포지셔닝 |\n|---|---|---|\n| TSMC | CoWoS | 파운드리 주도 |",
        "4장에는 표가 없습니다."
    )
    res3 = reviewer.review_report(no_company_table_md, topic="칩렛")
    assert res3["checklist"]["tables_valid"] is False
    assert any("4장" in d and "기업" in d for d in res3["defects"])


def test_reviewer_validates_image_whitelist():
    """valid_image_urls가 전달되었을 때 화이트리스트에 없는 외부/허위 URL을 결함으로 탐지."""
    reviewer = ReportReviewAgent(api_key="dummy_key")

    # 1. 화이트리스트에 정확한 이미지가 포함되어 있는 경우 통과
    res_valid = reviewer.review_report(
        PERFECT_MD,
        topic="칩렛",
        valid_image_urls=["/api/assets/doc/img.png"]
    )
    assert res_valid["checklist"]["images_valid"] is True
    assert not any("승인되지 않은" in d or "허위" in d for d in res_valid["defects"])

    # 2. 화이트리스트에 없는 URL이 사용된 경우 실패
    res_invalid = reviewer.review_report(
        PERFECT_MD,
        topic="칩렛",
        valid_image_urls=["/api/assets/doc/other_valid.png"]
    )
    assert res_invalid["checklist"]["images_valid"] is False
    assert any("승인되지 않은" in d or "허위" in d for d in res_invalid["defects"])

    # 3. valid_image_urls가 None인 경우 기존처럼 이미지가 존재하면 통과
    res_none = reviewer.review_report(PERFECT_MD, topic="칩렛", valid_image_urls=None)
    assert res_none["checklist"]["images_valid"] is True


def test_reviewer_validates_citations_integrity():
    """5장 데이터 출처 목록 및 본문 문단 종결부 <출처: [...]> 태그 무결성 검증."""
    reviewer = ReportReviewAgent(api_key="dummy_key")

    # 1. 본문 내 <출처: [...]> 태그가 누락된 경우
    no_inline_cite_md = PERFECT_MD.replace("<출처: [칩렛 기술 문서](/api/documents/chiplet)>", "")\
                                  .replace("<출처: [칩렛 시장 전망](/api/documents/chiplet)>", "")\
                                  .replace("<출처: [칩렛 기업 동향](/api/documents/chiplet)>", "")
    res1 = reviewer.review_report(no_inline_cite_md, topic="칩렛")
    assert res1["checklist"]["citations_valid"] is False
    assert any("본문" in d and "출처" in d for d in res1["defects"])

    # 2. 5장 데이터 출처 섹션에 문서 링크가 누락된 경우
    no_sec5_links_md = PERFECT_MD.replace("- [칩렛 문서](/api/documents/chiplet)", "출처 링크 없음")
    res2 = reviewer.review_report(no_sec5_links_md, topic="칩렛")
    assert res2["checklist"]["citations_valid"] is False
    assert any("5장" in d and "출처" in d for d in res2["defects"])


def test_deep_audit_detects_factuality_flaw():
    """deep_audit=True 시 원본 컨텍스트 대조 사실 왜곡(날조)을 감지하고 결함을 반환하는지 확인."""
    from unittest.mock import MagicMock
    import json

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "factuality_valid": False,
        "causality_valid": True,
        "defects": ["컨텍스트에 전혀 없는 날조된 시장 수치 100조 원 감지"],
        "suggestions": ["컨텍스트에 명시된 시장 전망치만 인용하십시오."]
    })
    mock_client.models.generate_content.return_value = mock_response
    reviewer.client = mock_client

    context = "칩렛 시장은 2025년 50억 달러 규모로 추정된다."
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=context, deep_audit=True)

    assert res["checklist"]["factuality_valid"] is False
    assert res["checklist"]["causality_valid"] is True
    assert res["passed_all"] is False
    assert any("날조된 시장 수치" in d for d in res["defects"])
    assert any("명시된 시장 전망치" in s for s in res["actionable_suggestions"])


def test_deep_audit_detects_causality_flaw():
    """deep_audit=True 시 기술-시장 3단계 인과 논리 부재를 감지하고 결함을 반환하는지 확인."""
    from unittest.mock import MagicMock
    import json

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "factuality_valid": True,
        "causality_valid": False,
        "defects": ["2장 패키징 기술 혁신과 3장 시장 성장의 3단계 인과 논리 부재"],
        "suggestions": ["기술 혁신이 어떻게 병목을 해결하고 시장을 창출하는지 논리적 연결을 강화하십시오."]
    })
    mock_client.models.generate_content.return_value = mock_response
    reviewer.client = mock_client

    context = "칩렛 기술은 인터커넥트 병목을 해소하여 고성능 AI 반도체 시장을 견인한다."
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=context, deep_audit=True)

    assert res["checklist"]["factuality_valid"] is True
    assert res["checklist"]["causality_valid"] is False
    assert res["passed_all"] is False
    assert any("3단계 인과 논리 부재" in d for d in res["defects"])


def test_deep_audit_graceful_fallback_on_llm_exception():
    """LLM 호출 중 예외(네트워크/API 오류) 발생 시 크래시 없이 안전하게 폴백(Graceful fallback)하는지 확인."""
    from unittest.mock import MagicMock

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API 네트워크 연결 시간 초과")
    reviewer.client = mock_client

    context = "유효한 컨텍스트 데이터"
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=context, deep_audit=True)

    assert res["checklist"]["factuality_valid"] is True
    assert res["checklist"]["causality_valid"] is True
    assert res["passed_all"] is True
    assert len(res["defects"]) == 0


def test_deep_audit_skipped_when_flag_false():
    """deep_audit=False인 경우 LLM을 호출하지 않고 룰베이스 결과만 고속 반환하는지 확인."""
    from unittest.mock import MagicMock

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    reviewer.client = mock_client

    context = "유효한 컨텍스트 데이터"
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=context, deep_audit=False)

    mock_client.models.generate_content.assert_not_called()
    assert "factuality_valid" not in res["checklist"]
    assert "causality_valid" not in res["checklist"]
    assert res["passed_all"] is True


def test_deep_audit_passes_valid_report():
    """deep_audit=True 시 정합성과 인과 논리가 모두 유효하면 전수 통과하는지 확인."""
    from unittest.mock import MagicMock
    import json

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "factuality_valid": True,
        "causality_valid": True,
        "defects": [],
        "suggestions": []
    })
    mock_client.models.generate_content.return_value = mock_response
    reviewer.client = mock_client

    context = "정상적인 칩렛 컨텍스트"
    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=context, deep_audit=True)

    assert res["checklist"]["factuality_valid"] is True
    assert res["checklist"]["causality_valid"] is True
    assert res["passed_all"] is True
    assert len(res["defects"]) == 0


def test_llm_semantic_audit_missing_client_or_context():
    """클라이언트가 없거나 컨텍스트가 비어있을 때 안전하게 (True, True, [], [])를 반환하는지 확인."""
    reviewer_no_key = ReportReviewAgent(api_key=None)
    reviewer_no_key.client = None

    f_valid, c_valid, defects, suggestions = reviewer_no_key._llm_semantic_audit(
        report_markdown=PERFECT_MD, topic="칩렛", context="컨텍스트"
    )
    assert (f_valid, c_valid, defects, suggestions) == (True, True, [], [])

    reviewer_with_key = ReportReviewAgent(api_key="mock_key")
    f_valid2, c_valid2, defects2, suggestions2 = reviewer_with_key._llm_semantic_audit(
        report_markdown=PERFECT_MD, topic="칩렛", context=""
    )
    assert (f_valid2, c_valid2, defects2, suggestions2) == (True, True, [], [])


def test_llm_semantic_audit_parses_markdown_json_block():
    """LLM이 마크다운 코드블록(```json ... ```)으로 응답한 경우에도 정상적으로 파싱되는지 확인."""
    from unittest.mock import MagicMock

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """```json
{
  "factuality_valid": false,
  "causality_valid": false,
  "factuality_defects": ["허위 수치 감지"],
  "causality_defects": ["인과관계 결여"],
  "suggestions": ["수치와 인과관계를 보정하십시오."]
}
```"""
    mock_client.models.generate_content.return_value = mock_response
    reviewer.client = mock_client

    f_valid, c_valid, defects, suggestions = reviewer._llm_semantic_audit(
        report_markdown=PERFECT_MD, topic="칩렛", context="컨텍스트"
    )
    assert f_valid is False
    assert c_valid is False
    assert "허위 수치 감지" in defects
    assert "인과관계 결여" in defects
    assert "수치와 인과관계를 보정하십시오." in suggestions


def test_deep_audit_skipped_when_context_is_empty_or_none():
    """deep_audit=True이나 context가 None 또는 빈 문자열인 경우 LLM을 호출하지 않는지 확인."""
    from unittest.mock import MagicMock

    reviewer = ReportReviewAgent(api_key="mock_key")
    mock_client = MagicMock()
    reviewer.client = mock_client

    res = reviewer.review_report(PERFECT_MD, topic="칩렛", context=None, deep_audit=True)
    mock_client.models.generate_content.assert_not_called()
    assert "factuality_valid" not in res["checklist"]
    assert res["passed_all"] is True


def test_table_boundary_defect():
    """표 내부 이미지 침투 또는 종결 개행 누락으로 파손된 표가 있을 때 tables_valid=False 및 결함이 지적되는지 검증."""
    reviewer = ReportReviewAgent(api_key="mock_key")

    # 1. 표 내부 셀에 이미지가 들어간 파손 마크다운
    table_leakage_md = PERFECT_MD.replace(
        "| 2.5D | 1Tbps | 고밀도 연결 |",
        "| 2.5D | 1Tbps | 고밀도 연결 |\n"
        "| *(단위: 억 달러)* ![도표](/api/assets/doc/img.png) | | |"
    )

    res = reviewer.review_report(table_leakage_md, topic="칩렛")
    assert res["checklist"]["tables_valid"] is False
    assert any("표 문법 파손" in d or "침투" in d for d in res["defects"])



