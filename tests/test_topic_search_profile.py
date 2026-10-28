"""AI 생성 보고서 업데이트 시 다차원 지식 프로필 및 LLM 키워드 확장 기반 검색 단위 테스트."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.topic_search import (
    ReportSearchProfile,
    extract_search_profile_rules,
    expand_search_profile_with_llm,
    search_relevant_sections_with_profile,
    search_relevant_sections_for_report,
)


SAMPLE_REPORT_MD = """# HBM 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
> - **주제어**: HBM
> - **생성일시**: 2026-09-14 07:34:23 UTC

## 1. 기술개요
HBM(High Bandwidth Memory)은 인공지능 시대의 고대역폭 메모리 아키텍처입니다.
TSV(Through Silicon Via)[^1] 공정을 통해 D램 다이를 수직 적층하여 대역폭을 극대화합니다.
로직 다이와 베이스 다이를 통해 병렬 제어를 수행합니다. <출처: [HBF 산업분석보고서](/api/documents/doc_hbf_001)>

## 2. 기술동향
HBM 기술은 HBM3, HBM3E, HBM4로 빠르게 진화하고 있습니다.
첨단 패키징 및 CoWoS 인터커넥트 기술이 핵심입니다.

## 3. 시장동향
글로벌 AI 가속기 및 GPU 수요 급증으로 시장 규모가 폭발적으로 성장하고 있습니다.

## 4. 주요업체
SK하이닉스와 삼성전자, 마이크론이 시장을 주도하고 있으며, TSMC 및 엔비디아와 긴밀한 생태계를 형성하고 있습니다.

## 5. 데이터 출처
- [HBF 산업분석보고서](/api/documents/doc_hbf_001)
- [반도체 패키징 기술동향](/api/documents/doc_pkg_002)

[^1]: **TSV**: 실리콘 관통 전극 기술
"""


def test_rule_based_search_profile_extraction():
    """보고서 마크다운 본문으로부터 규칙 기반 프로필이 정확히 추출되는지 검증."""
    profile = extract_search_profile_rules(SAMPLE_REPORT_MD, "HBM")

    assert profile.primary_topic.lower() == "hbm"
    # 동의어에 고대역폭 메모리 또는 영문 풀네임이 포함되어야 함
    assert any("high bandwidth memory" in s.lower() or "고대역폭" in s for s in profile.synonyms)
    # 기술 용어에 TSV, HBM3E, HBM4, 패키징 등이 수집되어야 함
    terms_joined = " ".join(profile.technical_terms).lower()
    assert "tsv" in terms_joined or "hbm4" in terms_joined or "패키징" in terms_joined
    # 주요 업체에 SK하이닉스 또는 삼성전자가 수집되어야 함
    companies_joined = " ".join(profile.companies)
    assert "SK하이닉스" in companies_joined or "삼성전자" in companies_joined
    # 기존 5장 출처 ID 수집 검증
    assert "doc_hbf_001" in profile.existing_source_ids
    assert "doc_pkg_002" in profile.existing_source_ids


def test_llm_search_profile_expansion_success():
    """Mock LLM 호출 성공 시 확장 키워드 및 시맨틱 쿼리문이 프로필에 정상 병합되는지 검증."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "synonyms": ["High Bandwidth Memory", "고대역폭 메모리"],
        "technical_terms": ["TSV", "MR-MUF", "하이브리드 본딩", "HBM3E", "HBM4"],
        "companies": ["SK하이닉스", "삼성전자", "TSMC", "NVIDIA"],
        "semantic_query": "HBM 고대역폭 메모리 아키텍처 및 TSV 적층 패키징 공정 기술과 글로벌 AI 반도체 시장 동향"
    }"""
    mock_client.models.generate_content.return_value = mock_response

    base_profile = extract_search_profile_rules(SAMPLE_REPORT_MD, "HBM")
    expanded = expand_search_profile_with_llm(
        report_markdown=SAMPLE_REPORT_MD,
        profile=base_profile,
        client=mock_client,
    )

    assert "MR-MUF" in expanded.technical_terms or "하이브리드 본딩" in expanded.technical_terms
    assert "NVIDIA" in expanded.companies or "TSMC" in expanded.companies
    assert "시맨틱" in expanded.semantic_query or "HBM" in expanded.semantic_query


def test_llm_search_profile_expansion_fallback_on_error():
    """LLM 호출 실패(402, 429, 예외 등) 시 중단 없이 1단계 규칙 기반 프로필로 안전하게 폴백되는지 검증."""
    mock_client_fail = MagicMock()
    mock_client_fail.models.generate_content.side_effect = RuntimeError("402 Payment Required: Credit depleted")

    base_profile = extract_search_profile_rules(SAMPLE_REPORT_MD, "HBM")
    expanded = expand_search_profile_with_llm(
        report_markdown=SAMPLE_REPORT_MD,
        profile=base_profile,
        client=mock_client_fail,
    )

    # 예외 없이 기본 프로필을 안전하게 유지 반환
    assert expanded.primary_topic == "HBM"
    assert len(expanded.technical_terms) > 0
    assert "doc_hbf_001" in expanded.existing_source_ids


def test_nonlinear_scoring_eliminates_40_flat(tmp_path: Path):
    """비선형 포화 스코어링 및 복합 일치 시너지로 40점 플랫 현상이 해결되고 관련도별 점수 차이가 발생하는지 검증."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    # 문서 1: HBM 단어만 30번 나오는 일반 문서 (요소기술 없음)
    doc1 = docs_dir / "general_hbm.md"
    doc1.write_text("# 일반 IT 시장 보고서\n\n" + "HBM 관련 시장이 활성화되고 있다. " * 30, encoding="utf-8")

    # 문서 2: HBM 핵심 기술 문서 (HBM + TSV + 패키징 + SK하이닉스 복합 등장)
    doc2 = docs_dir / "core_hbm_tech.md"
    doc2.write_text(
        "# 차세대 HBM3E 및 HBM4 적층 패키징 기술동향\n\n"
        "HBM 메모리는 TSV 실리콘 관통 전극과 첨단 패키징 공정으로 제조됩니다. "
        "SK하이닉스와 삼성전자가 HBM4 양산을 주도하고 있습니다. " * 15,
        encoding="utf-8"
    )

    # 문서 3: 무관한 일반 배터리 문서 (배터리 단어만 많음)
    doc3 = docs_dir / "battery.md"
    doc3.write_text("# 전기차 배터리 시장 보고서\n\n" + "이차전지 배터리 시장이 성장 중이다. " * 50, encoding="utf-8")

    profile = ReportSearchProfile(
        primary_topic="HBM",
        synonyms=["High Bandwidth Memory", "고대역폭 메모리"],
        technical_terms=["TSV", "패키징", "HBM4", "HBM3E", "적층"],
        companies=["SK하이닉스", "삼성전자"],
        existing_source_ids=[],
        semantic_query="HBM 고대역폭 메모리 TSV 패키징 기술동향"
    )

    results = search_relevant_sections_with_profile(profile, docs_dir, top_k=5)

    # 1. 문서 2가 압도적으로 1위여야 함 (복합 일치 시너지)
    assert len(results) >= 2
    assert results[0]["doc_id"] == "core_hbm_tech"
    # 2. 문서 2와 문서 1의 점수가 동일하지 않고 확연한 차이를 보여야 함 (40.0 플랫 해결)
    score_doc2 = results[0]["score"]
    score_doc1 = next(r["score"] for r in results if r["doc_id"] == "general_hbm")
    assert score_doc2 > score_doc1 + 30.0, f"score_doc2({score_doc2})가 score_doc1({score_doc1})보다 30점 이상 높아야 합니다."
    # 3. 무관한 배터리 문서는 결과에 포함되지 않아야 함
    doc_ids = [r["doc_id"] for r in results]
    assert "battery" not in doc_ids


def test_recency_boosting_in_report_search(tmp_path: Path):
    """보고서 작성 시점(report_mtime) 이후 유입된 최신 문서에 우선순위 가산점(Recency Boosting)이 적용되는지 검증."""
    import time

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    base_time = 1700000000.0

    # 구 문서 (report_mtime 이전)
    old_doc = docs_dir / "old_hbm_doc.md"
    old_doc.write_text("# 과거 HBM2 동향\n\nHBM2 메모리 기술과 시장 개요입니다.", encoding="utf-8")

    # 신규 최신 문서 (report_mtime 이후)
    new_doc = docs_dir / "new_hbm_doc.md"
    new_doc.write_text("# 최신 HBM4 양산 출하\n\n최신 HBM4 메모리 규격 및 출하 현황입니다.", encoding="utf-8")

    # 파일 mtime 인위적 설정
    import os
    os.utime(old_doc, (base_time - 1000, base_time - 1000))
    os.utime(new_doc, (base_time + 1000, base_time + 1000))

    profile = ReportSearchProfile(
        primary_topic="HBM",
        synonyms=["고대역폭 메모리"],
        technical_terms=["HBM4", "양산"],
        companies=[],
        existing_source_ids=[],
        semantic_query="HBM 메모리 최신 동향"
    )

    results = search_relevant_sections_with_profile(
        profile=profile,
        docs_dir=docs_dir,
        report_mtime=base_time,
        top_k=2
    )

    assert len(results) == 2
    # 최신 문서가 최상위에 랭크되어야 함
    assert results[0]["doc_id"] == "new_hbm_doc"
