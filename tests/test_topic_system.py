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


def test_delete_topic_report(tmp_path):
    """AI 보고서 삭제(delete_report) 및 DELETE API 엔드포인트 검증."""
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.config import Settings

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    reports_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")
    report_info = generator.save_report(
        topic="테스트주제",
        markdown="# 테스트 보고서\n본문 내용",
        sources=[]
    )
    report_id = report_info["id"]
    report_file = reports_dir / f"{report_id}.md"
    assert report_file.exists()

    # 1. TopicReportGenerator.delete_report 검증
    del_res = generator.delete_report(report_id)
    assert del_res is True
    assert not report_file.exists()

    # 다시 삭제 시 False 반환
    assert generator.delete_report(report_id) is False

    # 2. FastAPI DELETE 엔드포인트 검증 (/api/topic/reports/{report_id} 및 /api/documents/{report_id})
    report_info2 = generator.save_report(
        topic="테스트주제2",
        markdown="# 테스트 보고서 2\n본문 내용",
        sources=[]
    )
    report_id2 = report_info2["id"]
    report_file2 = reports_dir / f"{report_id2}.md"
    assert report_file2.exists()

    custom_settings = Settings(
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path,
        docs_dir=docs_dir,
        assets_dir=assets_dir,
        manifest_path=tmp_path / "manifest.json"
    )
    app = create_app(settings=custom_settings)
    client = TestClient(app)

    # 2-1. DELETE /api/topic/reports/{report_id}
    res = client.delete(f"/api/topic/reports/{report_id2}")
    assert res.status_code == 200
    assert not report_file2.exists()

    # 2-2. DELETE /api/documents/{report_id} 에서도 AI 보고서 삭제 지원 검증
    report_info3 = generator.save_report(
        topic="테스트주제3",
        markdown="# 테스트 보고서 3\n본문 내용",
        sources=[]
    )
    report_id3 = report_info3["id"]
    report_file3 = reports_dir / f"{report_id3}.md"
    assert report_file3.exists()

    res3 = client.delete(f"/api/documents/{report_id3}")
    assert res3.status_code == 200
    assert not report_file3.exists()


def test_build_prompt_quality_guidelines(tmp_path):
    """보고서 생성 프롬프트의 5대 목차, 필수 비교 표, 정량 데이터 원칙 검증."""
    generator = TopicReportGenerator(reports_dir=tmp_path / "reports", api_key="dummy_key")
    matched_docs = [
        {
            "doc_id": "test_doc_1",
            "title": "차세대 반도체 패키징",
            "score": 10.0,
            "sections": [
                SectionChunk(
                    doc_id="test_doc_1",
                    doc_title="차세대 반도체 패키징",
                    heading="기술 개요",
                    level=2,
                    text="반도체 미세화의 물리적 한계를 극복하기 위한 패키징 기술입니다.",
                    images=[],
                    tables=[],
                    category="overview"
                ),
                SectionChunk(
                    doc_id="test_doc_1",
                    doc_title="차세대 반도체 패키징",
                    heading="시장 규모",
                    level=2,
                    text="2025년 시장 규모는 100억 달러에서 2030년 300억 달러로 CAGR 24% 성장이 예상됩니다.",
                    images=[],
                    tables=["| 연도 | 시장규모(억 달러) |\n|---|---|\n| 2025 | 100 |\n| 2030 | 300 |"],
                    category="market"
                )
            ]
        }
    ]

    prompt = generator._build_prompt("차세대 패키징", matched_docs)

    # 1. 5대 목차 존재 확인
    assert "## 1. 기술개요" in prompt
    assert "## 2. 기술동향" in prompt
    assert "## 3. 시장동향 (국내/세계시장 규모 데이터)" in prompt
    assert "## 4. 주요업체" in prompt
    assert "## 5. 데이터 출처" in prompt

    # 2. 필수 표(Markdown Table) 작성 지침 포함 확인
    assert "핵심 기술 방식 비교 요약 표(Markdown Table)" in prompt
    assert "시장 규모 및 전망 데이터 표(Markdown Table)" in prompt
    assert "주요 기업별 기술 및 개발 현황 비교 표(Markdown Table)" in prompt

    # 3. 정량 데이터 및 AI 상투어 차단 규칙 확인
    assert "정량적 팩트 중심 서술" in prompt
    assert "인공지능 상투어 차단" in prompt
    assert "일관된 전문 보고서 문체" in prompt

    # 4. 출처 링크 및 이미지 인용 형식 포함 확인
    assert "<출처: [{문서제목}](/api/documents/{문서ID})>" in prompt
    assert "![" in prompt


def test_deduplicate_citations_in_report():
    """보고서 본문 및 5번 데이터 출처 섹션에서 괄호/공백 차이의 동일 문헌 출처가 단일화되는지 검증한다."""
    from app.topic_generator import TopicReportGenerator

    sample_md = """# HBF 종합 기술 보고서

한미반도체는 차세대 TC 본더를 개발 중입니다 <출처: [HBF 산업분석보고서 (Growth Research)](/api/documents/doc_1)>, <출처: [HBF 산업분석보고서 Growth Research](/api/documents/doc_2)>.

SK하이닉스는 HBF 공정을 선도합니다 <출처: [HBF 산업분석보고서 (Growth Research)](/api/documents/doc_1)>, <출처: [LS증권_피지컬AI](/api/documents/doc_3)>.

## 5. 데이터 출처

- [HBF 산업분석보고서 (Growth Research)](/api/documents/doc_1)
- [HBF 산업분석보고서 Growth Research](/api/documents/doc_2)
- [LS증권_피지컬AI](/api/documents/doc_3)
"""

    cleaned = TopicReportGenerator.deduplicate_citations(sample_md)

    # 본문 연속 중복 출처 단일화 검증
    assert "<출처: [HBF 산업분석보고서 (Growth Research)](/api/documents/doc_1)>." in cleaned
    assert "<출처: [HBF 산업분석보고서 Growth Research](/api/documents/doc_2)>" not in cleaned

    # 서로 다른 문헌은 정상 유지
    assert "<출처: [HBF 산업분석보고서 (Growth Research)](/api/documents/doc_1)>, <출처: [LS증권_피지컬AI](/api/documents/doc_3)>" in cleaned

    # 5번 데이터 출처 섹션 내 중복 bullet 제거 검증
    assert cleaned.count("[HBF 산업분석보고서 (Growth Research)]") == 3  # 본문 2 + 5번 섹션 1
    assert cleaned.count("[HBF 산업분석보고서 Growth Research]") == 0
    assert "- [LS증권_피지컬AI](/api/documents/doc_3)" in cleaned


def test_search_relevant_sections_deduplication(tmp_path):
    """동일한 해시(SHA-256)를 가진 마크다운 파일이 여러 개 존재해도 검색 결과에는 1개만 포함되어야 한다."""
    from app.topic_search import search_relevant_sections

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    header_template = """# HBF 산업분석보고서
> - **원본 파일명**: HBF_보고서.pdf
> - **무결성 해시 (SHA-256)**: `463e1da9a82e296f412a2f5a5a0e169b983126c1b664759d8703992928cd0c9b`

## 기술 개요
HBF는 차세대 고대역폭 플래시 메모리 기술입니다.
"""

    # 동일 파일 해시를 가진 서로 다른 두 파일 생성
    (docs_dir / "HBF_doc_old_1788000000_aaaa1111.md").write_text(header_template, encoding="utf-8")
    (docs_dir / "HBF_doc_new_1789000000_bbbb2222.md").write_text(header_template + "\n추가 본문 내용", encoding="utf-8")

    matched = search_relevant_sections("HBF", docs_dir, top_k=5)

    # 2개 파일이 아닌 1개 문서만 매칭되어야 함
    assert len(matched) == 1
    assert matched[0]["doc_id"] in ["HBF_doc_old_1788000000_aaaa1111", "HBF_doc_new_1789000000_bbbb2222"]


def test_refine_report_in_place(tmp_path):
    """피드백 반영 보정 시 In-place 덮어쓰기 저장 및 점수 메타데이터 제외 검증."""
    reports_dir = tmp_path / "reports"
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    initial_md = """# 테스트 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 전고체 배터리

## 1. 기술개요
초안 내용입니다.
"""
    report_info = generator.save_report(topic="전고체 배터리", markdown=initial_md, sources=[])
    report_id = report_info["id"]
    file_path = Path(report_info["file_path"])
    assert file_path.exists()

    # 모의 LLM 보정 응답 주입 테스트를 위해 generator.client mock 처리
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """# 전고체 배터리 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
> - **주제어**: 전고체 배터리
> - **검수 상태**: ✨ AI 리뷰어 피드백 반영 보정 완료

---

## 1. 기술개요
보정된 완성도 높은 개요입니다.

## 2. 기술동향
| 방식 | 특징 |
|---|---|
| 황화물계 | 고이온전도도 |

## 3. 시장동향 (국내/세계시장 규모 데이터)
2030년 100억 달러 CAGR 30% 성장.

| 연도 | 규모 |
|---|---|
| 2030 | 100억 달러 |

## 4. 주요업체
삼성SDI, 도요타

## 5. 데이터 출처
- [출처1](/api/documents/doc1)
"""
    mock_client.models.generate_content.return_value = mock_response
    generator.client = mock_client

    feedback = {
        "defects": ["표 누락", "시장 수치 부족"],
        "actionable_suggestions": ["비교 표 추가", "2030년 100억 달러 수치 추가"]
    }

    refined_info = generator.refine_report(report_id=report_id, feedback=feedback)

    # 1. In-place 덮어쓰기 검증: 동일한 ID 및 동일 파일 경로
    assert refined_info["id"] == report_id
    assert Path(refined_info["file_path"]) == file_path
    updated_content = file_path.read_text(encoding="utf-8")
    assert "✨ AI 리뷰어 피드백 반영 보정 완료" in updated_content
    # 2. 점수(XX점) 메타데이터 배제 검증
    assert "점수" not in updated_content
    assert "Score" not in updated_content


def test_review_and_refine_api_endpoints(tmp_path):
    """보고서 리뷰 및 보정(refine) API 엔드포인트 통합 테스트."""
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.config import Settings
    from app.topic_router import get_generator

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    custom_settings = Settings(
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path,
        docs_dir=docs_dir,
        assets_dir=tmp_path / "assets",
        manifest_path=tmp_path / "manifest.json"
    )

    # 1. 초기 임의 테스트 보고서 저장
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")
    initial_md = """# 인공지능 반도체 기술 분석
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 인공지능 반도체

## 1. 기술개요
AI 연산 가속을 위한 NPU 기술입니다.
"""
    saved_info = generator.save_report(
        topic="인공지능 반도체",
        markdown=initial_md,
        sources=[]
    )
    report_id = saved_info["id"]

    # LLM 모킹 설정 (보정 시 호출 대응)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """# 인공지능 반도체 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 인공지능 반도체
> - **검수 상태**: ✨ AI 리뷰어 피드백 반영 보정 완료

---

## 1. 기술개요
보정된 AI 반도체 개요입니다.

## 2. 기술동향
| 기술 | 특징 |
|---|---|
| NPU | 가속기 |

## 3. 시장동향 (국내/세계시장 규모 데이터)
2030년 1000억 달러 전망.

| 연도 | 규모 |
|---|---|
| 2030 | 1000억 달러 |

## 4. 주요업체
엔비디아

| 업체 | 제품 |
|---|---|
| 엔비디아 | H100 |

## 5. 데이터 출처
- [출처1](/api/documents/doc1)
"""
    mock_client.models.generate_content.return_value = mock_response
    generator.client = mock_client

    app = create_app(settings=custom_settings)
    app.dependency_overrides[get_generator] = lambda: generator
    client = TestClient(app)

    # 2. POST /api/topic/reports/{report_id}/review 호출 검증
    res_review = client.post(f"/api/topic/reports/{report_id}/review")
    assert res_review.status_code == 200
    review_data = res_review.json()
    assert review_data["report_id"] == report_id
    assert "review" in review_data
    review = review_data["review"]
    assert "passed_all" in review
    assert "checklist" in review
    assert "defects" in review
    assert "actionable_suggestions" in review
    assert review["checklist"]["structure_valid"] is False  # 5대 목차 중 일부 누락 상태
    assert len(review["defects"]) > 0

    # 3. POST /api/topic/reports/{report_id}/refine 호출 검증
    refine_payload = {
        "feedback": {
            "defects": review["defects"],
            "actionable_suggestions": review["actionable_suggestions"]
        }
    }
    res_refine = client.post(f"/api/topic/reports/{report_id}/refine", json=refine_payload)
    assert res_refine.status_code == 200
    refine_data = res_refine.json()
    assert refine_data["id"] == report_id
    assert refine_data["status"] == "completed"

    # In-place 갱신 디스크 파일 확인
    report_file = reports_dir / f"{report_id}.md"
    assert report_file.exists()
    file_content = report_file.read_text(encoding="utf-8")
    assert "✨ AI 리뷰어 피드백 반영 보정 완료" in file_content
    assert "보정된 AI 반도체 개요입니다." in file_content
