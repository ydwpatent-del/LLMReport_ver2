"""위키 문서 기반 AI 보고서 작성 및 증분 업데이트 프롬프트 고도화 검증 테스트."""

import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.topic_generator import TopicReportGenerator
from app.topic_search import SectionChunk


@pytest.fixture
def sample_matched_docs():
    """가상의 매칭된 위키 문서 데이터 픽스처."""
    return [
        {
            "doc_id": "doc_chiplet_overview",
            "title": "칩렛 패키징 아키텍처 개요",
            "score": 0.85,
            "mtime": 1000.0,
            "sections": [
                SectionChunk(
                    doc_id="doc_chiplet_overview",
                    doc_title="칩렛 패키징 아키텍처 개요",
                    heading="기술 정의 및 등장 배경",
                    level=2,
                    text="칩렛은 단일 모놀리식 다이의 면적 한계를 극복하기 위해 기능별 다이를 분할하여 이종 집적하는 패키징 기술입니다.",
                    images=[{"url": "/api/assets/doc_chiplet_overview/arch.png", "alt": "칩렛 구조도", "caption": "아키텍처"}],
                    tables=["| 구분 | 모놀리식 | 칩렛 방식 |\n| :--- | :--- | :--- |\n| 수율 | 낮음 | 높음 |"],
                    category="tech"
                ),
                SectionChunk(
                    doc_id="doc_chiplet_overview",
                    doc_title="칩렛 패키징 아키텍처 개요",
                    heading="시장 규모 및 성장 전망",
                    level=2,
                    text="가트너(Gartner)에 따르면 세계 칩렛 시장은 2024년 65억 달러에서 2028년 500억 달러로 연평균 45% 성장할 전망입니다.",
                    images=[],
                    tables=["| 연도 | 시장규모(억달러) |\n| :--- | :--- |\n| 2024 | 65 |\n| 2028 | 500 |"],
                    category="market"
                )
            ]
        }
    ]


def test_build_prompt_includes_wiki_grounding_directives(sample_matched_docs):
    """최초 생성 프롬프트(_build_prompt)에 위키 팩트 그라운딩 및 다차원 합성 지침이 엄격히 포함되는지 검증."""
    generator = TopicReportGenerator()
    prompt = generator._build_prompt("칩렛 반도체", sample_matched_docs)

    # 1. 팩트 그라운딩 및 환각 방지 지침 검증
    assert "Strict Wiki Grounding" in prompt
    assert "가상의 기술 스펙이나 미확인 통계치를 임의로 보충하거나 날조" in prompt
    assert "자료상 세부 내용 미제시" in prompt

    # 2. 1차 출처 및 2차 링크 분리 표기 지침 검증
    assert "1차 조사기관 출처와 2차 위키DB 링크 구분 명시" in prompt
    assert "가트너(Gartner)" in prompt

    # 3. 다중 위키 교차 융합 지침 검증
    assert "Cross-Wiki Multi-Perspective Synthesis" in prompt
    assert "유기적 전주기 밸류체인 관점" in prompt


def test_build_incremental_update_prompt_directives(sample_matched_docs):
    """증분 업데이트 전용 프롬프트(_build_incremental_update_prompt)의 기존 근거 대조, 3단계 사전 리뷰 프로토콜 및 5대 불변 원칙 검증."""
    generator = TopicReportGenerator()
    current_md = "# 칩렛 종합 기술 및 시장 분석 보고서\n\n## 1. 기술개요\n기존 분석 내용입니다."
    existing_docs = [
        {
            "doc_id": "doc_old_chiplet_2023",
            "title": "2023년 초기 칩렛 시장 조사",
            "score": 0.80,
            "mtime": 500.0,
            "sections": [
                SectionChunk(
                    doc_id="doc_old_chiplet_2023",
                    doc_title="2023년 초기 칩렛 시장 조사",
                    heading="초기 시장 전망",
                    level=2,
                    text="2023년 기준 초기 조사에서는 2028년 시장 규모를 300억 달러로 추산하였습니다.",
                    images=[],
                    tables=[],
                    category="market",
                )
            ],
        }
    ]

    prompt = generator._build_incremental_update_prompt(
        current_markdown=current_md,
        topic="칩렛",
        new_docs=sample_matched_docs,
        existing_docs=existing_docs,
    )

    # 1. 기존 작성분 근거 데이터(Existing Basis Data)와 신규 후보 데이터(New Candidate Data) 동시 포함 검증
    assert "기존 작성분의 근거가 되는 위키 문서 데이터 (Existing Basis Data)" in prompt
    assert "2023년 초기 칩렛 시장 조사" in prompt
    assert "새롭게 반영 검토할 최신 위키 문서 데이터 (New Candidate Data)" in prompt
    assert "칩렛 패키징 아키텍처 개요" in prompt

    # 2. 본문 작성 전 3단계 사전 리뷰 프로토콜(최신성 대조 + 논리적 정합성 리뷰 + 자체 검수) 포함 검증
    assert "Pre-Update Review Protocol" in prompt
    assert "Recency & Base-Year Verification" in prompt
    assert "역행 갱신 절대 금지" in prompt
    assert "Logical Consistency & Causality Review" in prompt
    assert "Self-Review Before Finalizing" in prompt

    # 3. 5대 불변 원칙 키워드 및 출처 갱신 규칙 검증
    assert "외과적 증분 개정" in prompt or "Surgical Incremental Revision" in prompt
    assert "기존 내용 불변 보존" in prompt or "Non-destructive Update" in prompt
    assert "검증된 델타 지식" in prompt or "Delta Knowledge" in prompt
    assert "궤적" in prompt or "Trajectory" in prompt
    assert "위키 지식 개정본" in prompt
    assert "반영된 신규 위키 지식" in prompt
    assert "5장 데이터 출처" in prompt


def test_update_report_with_wiki_docs_incremental_flow(tmp_path):
    """update_report_with_wiki_docs 메서드가 기존 근거 문서와 신규 위키 문서를 분리 대조하고,
    초안 작성 후 논리적 정합성 및 최신 데이터 리뷰를 거쳐 In-place 증분 업데이트를 수행하는지 검증."""
    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    # 1. 기존 근거 위키 문서 생성 (과거 mtime)
    import os
    old_doc_file = docs_dir / "old_doc.md"
    old_doc_file.write_text("# 기존 칩렛 UCIe 1.0 표준\n## 기술 개요\nUCIe 1.0 기본 사양입니다.", encoding="utf-8")
    os.utime(old_doc_file, (900.0, 900.0))

    # 2. 기존 보고서 파일 생성 (중간 시각 mtime 설정)
    existing_file = reports_dir / "REPORT_칩렛_1000000000.md"
    existing_content = """# 칩렛 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 칩렛

## 1. 기술개요
기존 칩렛 분석 본문입니다. <출처: [기존 칩렛 UCIe 1.0 표준](/api/documents/old_doc)>

## 5. 데이터 출처
- [기존 칩렛 UCIe 1.0 표준](/api/documents/old_doc)
"""
    existing_file.write_text(existing_content, encoding="utf-8")
    os.utime(existing_file, (1000.0, 1000.0))

    # 3. 최신 위키 문서 생성 (보고서보다 최신 mtime)
    new_doc_file = docs_dir / "new_chiplet_spec.md"
    new_doc_content = """# 차세대 칩렛 UCIe 2.0 표준
## 기술 동향
UCIe 2.0 표준은 3D 패키징 인터커넥트 대역폭을 2배 향상시킵니다.
"""
    new_doc_file.write_text(new_doc_content, encoding="utf-8")
    os.utime(new_doc_file, (2000.0, 2000.0))

    generator = TopicReportGenerator(reports_dir=reports_dir)

    # 4. 리뷰 통과 시나리오 검증 (Mock Reviewer가 논리·사실 정합성 이상 없음 반환)
    mock_reviewer = MagicMock()
    mock_reviewer.review_report.return_value = {
        "quality_score": 96,
        "defects": [],
        "checklist": {"factuality_valid": True, "causality_valid": True},
    }

    mock_llm_response = """# 칩렛 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서 (위키 지식 개정본)
> - **주제어**: 칩렛
> - **반영된 신규 위키 지식**: 차세대 칩렛 UCIe 2.0 표준

## 1. 기술개요
기존 칩렛 분석 본문입니다. 최신 UCIe 2.0 표준이 추가 통합되었습니다.

## 5. 데이터 출처
- [기존 칩렛 UCIe 1.0 표준](/api/documents/old_doc)
- [차세대 칩렛 UCIe 2.0 표준](/api/documents/new_chiplet_spec)
"""
    with patch.object(generator, "_sync_report_to_remote"), patch.object(
        generator, "_call_gemini_api", return_value=mock_llm_response
    ) as mock_api:
        result = generator.update_report_with_wiki_docs(
            report_id="REPORT_칩렛_1000000000",
            docs_dir=docs_dir,
            force_all_matched=False,
            reviewer=mock_reviewer,
        )

        assert mock_api.call_count == 1
        assert mock_reviewer.review_report.called
        assert result["updated"] is True
        assert result["existing_basis_docs_count"] >= 1
        assert result["merged_docs_count"] >= 1
        assert result["review_score"] == 96

        updated_disk_content = existing_file.read_text(encoding="utf-8")
        assert "위키 지식 개정본" in updated_disk_content
        assert "차세대 칩렛 UCIe 2.0 표준" in updated_disk_content


def test_update_report_reviews_and_refines_when_logic_or_recency_flaw_detected(tmp_path):
    """1차 증분 작성 후 리뷰에서 논리적 정합성 또는 최신 데이터 반영 결함이 감지되면 즉시 2차 보정 본문을 작성하는지 검증."""
    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    existing_file = reports_dir / "REPORT_칩렛_1000000000.md"
    existing_file.write_text("# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n기존 2024년 분석 본문입니다.", encoding="utf-8")

    new_doc_file = docs_dir / "new_chiplet_2025.md"
    new_doc_file.write_text("# 2025 칩렛 시장 동향\n## 시장 전망\n2025년 최신 조사 결과 600억 달러 전망.", encoding="utf-8")

    generator = TopicReportGenerator(reports_dir=reports_dir)

    draft_flawed_md = "# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n1차 초안: 구형 수치와 신규 수치가 논리 없이 혼재된 본문입니다."
    refined_valid_md = "# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n2차 보정 완료: 2024년 대비 2025년 최신 데이터(600억 달러)와 인과 논리가 정합하게 검증된 최종 본문입니다."

    mock_reviewer = MagicMock()
    # 1차 리뷰: 논리/사실 정합성 결함 감지 -> 2차 리뷰: 정합성 통과
    mock_reviewer.review_report.side_effect = [
        {
            "quality_score": 68,
            "defects": ["신규 2025년 데이터와 기존 2024년 데이터 간 인과 설명 누락"],
            "improvement_orders": ["2024년 전망 대비 2025년 최신 수치 상향 근거를 명확히 서술할 것"],
            "checklist": {"factuality_valid": False, "causality_valid": False},
        },
        {
            "quality_score": 95,
            "defects": [],
            "checklist": {"factuality_valid": True, "causality_valid": True},
        },
    ]

    with patch.object(generator, "_sync_report_to_remote"), patch.object(
        generator, "_call_gemini_api", side_effect=[draft_flawed_md, refined_valid_md]
    ) as mock_api:
        result = generator.update_report_with_wiki_docs(
            report_id="REPORT_칩렛_1000000000",
            docs_dir=docs_dir,
            force_all_matched=True,
            reviewer=mock_reviewer,
        )

        # 1차 초안 생성 + 리뷰 결함에 따른 2차 정밀 보정 호출까지 총 2회 LLM 호출 검증
        assert mock_api.call_count == 2
        assert mock_reviewer.review_report.call_count == 2
        assert result["updated"] is True
        assert result["review_score"] == 95
        assert "2차 보정 완료" in existing_file.read_text(encoding="utf-8")


def test_generate_report_applies_plan_a_incremental_update(tmp_path):
    """generate_report 호출 시 기존 보고서가 존재하면 [방안 A]에 따라 update_report_with_wiki_docs로 분기하는지 검증."""
    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    # 1. 100초 전에 생성된 기존 보고서 준비 (60초 디바운스 초과)
    existing_file = reports_dir / "REPORT_자율주행차_1000000000.md"
    existing_file.write_text("# 자율주행차 종합 보고서\n\n## 1. 개요\n본문", encoding="utf-8")
    past_time = time.time() - 100
    import os
    os.utime(existing_file, (past_time, past_time))

    generator = TopicReportGenerator(reports_dir=reports_dir)

    # 2. update_report_with_wiki_docs 호출 감시
    with patch.object(generator, "update_report_with_wiki_docs", return_value={"id": "REPORT_자율주행차_1000000000", "updated": True}) as mock_update:
        res = generator.generate_report(topic="자율주행차", docs_dir=docs_dir, update_if_exists=True, force=False)
        assert mock_update.called
        assert res["id"] == "REPORT_자율주행차_1000000000"


def test_update_report_with_wiki_api_endpoint(tmp_path):
    """POST /api/topic/reports/{report_id}/update-wiki 엔드포인트 정상 동작 검증."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.topic_router import topic_router, get_generator
    from app.config import Settings, get_settings

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    # 보고서 파일 생성
    rep_file = reports_dir / "REPORT_양자컴퓨팅_1000.md"
    rep_file.write_text("# 양자컴퓨팅 보고서\n\n## 1. 개요\n본문", encoding="utf-8")

    generator = TopicReportGenerator(reports_dir=reports_dir)
    app = FastAPI()
    app.include_router(topic_router)

    custom_settings = Settings(wiki_db_dir=tmp_path)
    app.dependency_overrides[get_settings] = lambda: custom_settings
    app.dependency_overrides[get_generator] = lambda: generator

    client = TestClient(app)

    with patch.object(generator, "update_report_with_wiki_docs", return_value={"id": "REPORT_양자컴퓨팅_1000", "updated": True}) as mock_fn:
        resp = client.post("/api/topic/reports/REPORT_양자컴퓨팅_1000/update-wiki?force_all_matched=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] is True
        assert mock_fn.called


def test_quality_review_and_refine_prompt_includes_basis_data_and_pre_review_protocol(tmp_path):
    """품질검수 보정(refine_report 및 _build_refine_prompt) 시 기존 근거 문서 데이터와 신규 문서 데이터를 함께 주입하고
    3단계 사전 리뷰 프로토콜(Pre-Refine Review Protocol)을 포함하는지 검증."""
    import os

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    # 1. 기존 작성분 근거 위키 문서 (과거 mtime)
    old_doc = docs_dir / "old_basis_doc.md"
    old_doc.write_text("# 2024 칩렛 시장 기초 보고서\n## 시장 전망\n2024년 기준 칩렛 시장 규모는 50억 달러입니다.", encoding="utf-8")
    os.utime(old_doc, (900.0, 900.0))

    # 2. 기존 작성된 AI 보고서 (중간 mtime)
    rep_file = reports_dir / "REPORT_칩렛_1000.md"
    rep_file.write_text(
        "# 칩렛 종합 기술 및 시장 분석 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n기존 본문 <출처: [2024 칩렛 시장 기초 보고서](/api/documents/old_basis_doc)>",
        encoding="utf-8",
    )
    os.utime(rep_file, (1000.0, 1000.0))

    # 3. 신규 등재 위키 문서 (최신 mtime)
    new_doc = docs_dir / "new_candidate_doc.md"
    new_doc.write_text("# 2025 차세대 칩렛 전망\n## 시장 동향\n2025년 최신 조사 기준 칩렛 시장은 85억 달러입니다.", encoding="utf-8")
    os.utime(new_doc, (2000.0, 2000.0))

    generator = TopicReportGenerator(reports_dir=reports_dir)
    captured_prompts = []

    def fake_call_gemini(prompt, log_subject=""):
        captured_prompts.append(prompt)
        return "# 칩렛 종합 기술 및 시장 분석 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n보정 완료된 본문입니다. 충분한 길이를 확보합니다."

    with patch.object(generator, "_sync_report_to_remote"), patch.object(
        generator, "_call_gemini_api", side_effect=fake_call_gemini
    ):
        generator.refine_report(
            report_id="REPORT_칩렛_1000",
            feedback={"defects": ["최신 데이터 동기화 필요"], "actionable_suggestions": ["최신성 대조 후 보정"]},
            docs_dir=docs_dir,
        )

    assert len(captured_prompts) == 1
    refine_prompt = captured_prompts[0]
    # 기존 작성분 근거 데이터와 신규 등재 데이터가 모두 포함되었는지 검증
    assert "기존 작성분의 근거가 되는 위키 문서 데이터 (Existing Basis Data)" in refine_prompt
    assert "2024 칩렛 시장 기초 보고서" in refine_prompt
    assert "보고서 생성 이후 WikiDB에 신규 등재된 최신 원본 데이터" in refine_prompt
    assert "2025 차세대 칩렛 전망" in refine_prompt
    # 3단계 사전 리뷰 프로토콜 포함 검증
    assert "Pre-Refine Review Protocol" in refine_prompt
    assert "Recency & Base-Year Verification" in refine_prompt
    assert "Logical Consistency & Causality Review" in refine_prompt


def test_refine_report_with_loop_verifies_recency_and_logical_consistency(tmp_path):
    """자율 반추 품질검수 루프(refine_report_with_loop)가 매 턴마다 원천 근거 컨텍스트를 전달하여
    최신성(factuality_valid) 및 논리적 정합성(causality_valid) 통과 시까지 보정을 수행하는지 검증."""
    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    (docs_dir / "chiplet_doc.md").write_text("# 칩렛 표준 문서\n## 기술 동향\nUCIe 2.0 대역폭 32Gbps.", encoding="utf-8")
    rep_file = reports_dir / "REPORT_칩렛_1000.md"
    rep_file.write_text("# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n초기 본문입니다.", encoding="utf-8")

    generator = TopicReportGenerator(reports_dir=reports_dir)

    mock_reviewer = MagicMock()
    # 1차 보정 후 리뷰: 점수는 92점이나 논리적 정합성(causality_valid=False) 미통과 -> 2차 보정 후 리뷰: 모두 통과
    mock_reviewer.review_report.side_effect = [
        {
            "quality_score": 92,
            "defects": [],
            "actionable_suggestions": ["기술-시장 간 인과 논리 충돌 해소 필요"],
            "checklist": {"factuality_valid": True, "causality_valid": False},
        },
        {
            "quality_score": 96,
            "defects": [],
            "actionable_suggestions": [],
            "checklist": {"factuality_valid": True, "causality_valid": True},
        },
    ]

    turn1_md = "# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n1차 보정 본문이나 인과 논리가 미흡합니다."
    turn2_md = "# 칩렛 보고서\n> - **주제어**: 칩렛\n\n## 1. 기술개요\n2차 보정 본문: 최신 데이터와 기술-시장 인과 논리가 완벽히 정합합니다."

    with patch.object(generator, "_sync_report_to_remote"), patch.object(
        generator, "_call_gemini_api", side_effect=[turn1_md, turn2_md]
    ) as mock_api:
        res = generator.refine_report_with_loop(
            report_id="REPORT_칩렛_1000",
            initial_feedback={"defects": ["초기 결함"], "actionable_suggestions": ["보완"]},
            reviewer=mock_reviewer,
            max_iterations=3,
            target_score=90,
            docs_dir=docs_dir,
        )

        # 1차 턴에서 점수가 92점이었지만 causality_valid=False였으므로 종료하지 않고 2차 턴까지 수행했는지 검증
        assert mock_api.call_count == 2
        assert mock_reviewer.review_report.call_count == 2
        _, review_kwargs = mock_reviewer.review_report.call_args
        assert review_kwargs["deep_audit"] is True
        assert "칩렛 표준 문서" in review_kwargs["context"]
        assert "2차 보정 본문" in res["markdown"]


def test_reviewer_llm_semantic_audit_prompt_checks_recency_and_contradiction():
    """ReportReviewAgent._llm_semantic_audit가 데이터 최신성(기준 연도 역행 여부)과
    기존 작성분-신규 데이터 간 논리적 충돌을 감사 프롬프트에 포함하는지 검증."""
    from app.report_reviewer import ReportReviewAgent
    import json

    reviewer = ReportReviewAgent(api_key="dummy_key")
    mock_client = MagicMock()
    captured_audit_prompts = []

    def fake_generate(model, contents, config=None):
        captured_audit_prompts.append(contents)
        resp = MagicMock()
        resp.text = json.dumps({
            "factuality_valid": True,
            "causality_valid": True,
            "defects": [],
            "suggestions": [],
        })
        return resp

    mock_client.models.generate_content.side_effect = fake_generate
    reviewer.client = mock_client

    reviewer._llm_semantic_audit(
        report_markdown="# 칩렛 보고서\n본문",
        topic="칩렛",
        context="## [기존 작성분 근거 문서] 2024 보고서\n...\n---\n## [신규/미반영 후보 문서] 2025 보고서\n...",
    )

    assert len(captured_audit_prompts) == 1
    audit_prompt = captured_audit_prompts[0]
    assert "Data Recency Verification" in audit_prompt
    assert "역행 갱신" in audit_prompt
    assert "Logical Consistency & Causality Review" in audit_prompt
    assert "기존 작성분과 신규 데이터 간 논리적 충돌 감사" in audit_prompt

