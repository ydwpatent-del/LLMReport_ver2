"""주제 기반 지식 보고서 생성 시스템 단위 및 통합 테스트."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.topic_search import (
    parse_markdown_sections,
    search_relevant_sections,
    SectionChunk,
    cosine_similarity,
    EmbeddingCacheManager,
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

    # 5. 심화 분석 및 최신 시장자료 우선/기술-시장 논리 연계 규칙 확인
    assert "품질 극대화 및 심층 분석 심화 규칙" in prompt
    assert "최신 시장 규모 자료 최우선 반영 강제" in prompt
    assert "기술동향-시장동향 간 논리적 연계성 및 감수 검증성 강제" in prompt
    assert "복수 문헌 간 다각적 교차 종합" in prompt
    assert "산업 밸류체인(Value Chain) 연계 분석" in prompt
    assert "표준 GFM 각주(Footnotes) 격리 수록" in prompt


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


def test_cosine_similarity_math():
    """코사인 유사도 연산의 수학적 정합성 및 예외 케이스 검증."""
    # 1. 동일 벡터 (유사도 1.0)
    v1 = [1.0, 2.0, 3.0]
    assert pytest.approx(cosine_similarity(v1, v1), 0.0001) == 1.0

    # 2. 직교 벡터 (유사도 0.0)
    v_a = [1.0, 0.0]
    v_b = [0.0, 1.0]
    assert pytest.approx(cosine_similarity(v_a, v_b), 0.0001) == 0.0

    # 3. 반대 벡터 (유사도 -1.0)
    v_c = [1.0, 0.0]
    v_d = [-1.0, 0.0]
    assert pytest.approx(cosine_similarity(v_c, v_d), 0.0001) == -1.0

    # 4. 빈 벡터 또는 길이 불일치 (0.0 반환)
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_embedding_cache_manager(tmp_path):
    """임베딩 디스크 캐싱 및 원자적 영속화 검증."""
    cache_file = tmp_path / ".embedding_cache.json"
    cache = EmbeddingCacheManager(cache_file)

    # 초기 상태
    assert cache.get("테스트 텍스트") is None

    # 저장 및 캐시 히트
    test_vec = [0.1, 0.2, 0.3, 0.4]
    cache.set("테스트 텍스트", test_vec)
    assert cache.get("테스트 텍스트") == test_vec

    # 디스크 저장 후 신규 인스턴스에서 로드 검증
    cache.save()
    assert cache_file.exists()

    new_cache = EmbeddingCacheManager(cache_file)
    assert new_cache.get("테스트 텍스트") == test_vec


def test_hybrid_semantic_search_synonym(tmp_path):
    """어휘 불일치(동의어: '이종 집적' vs '칩렛') 상황에서 시맨틱 임베딩으로 문서를 구출하는지 검증."""
    chiplet_content = """# 첨단 패키징 솔루션
> - **문서분류**: 리서치 보고서
> - **원본 파일명**: packaging_report.pdf

## 차세대 반도체 다이 인터커넥트
개별 반도체 칩을 결합하여 고성능을 구현하는 칩렛 방식이 차세대 표준으로 부상하고 있습니다.
실리콘 브릿지와 인터포저를 활용하여 고밀도 배선을 구현합니다.

## 시장 전망
패키징 시장은 연평균 30% 이상 성장합니다.
"""
    bio_content = """# 바이오 헬스케어 동향
> - **문서분류**: 산업 보고서
> - **원본 파일명**: bio_health.pdf

## 신약 개발 임상시험
항암제 파이프라인의 임상 3상 결과가 발표되었습니다.
"""
    (tmp_path / "chiplet_doc.md").write_text(chiplet_content, encoding="utf-8")
    (tmp_path / "bio_doc.md").write_text(bio_content, encoding="utf-8")

    # 가상 임베딩 벡터 생성 (이종 집적 쿼리와 chiplet_doc은 높은 유사도, bio_doc은 낮은 유사도)
    query_vec = [1.0, 0.0, 0.0]
    chiplet_vec = [0.95, 0.05, 0.0]   # cos_sim ≈ 0.99
    bio_vec = [0.0, 1.0, 0.0]          # cos_sim = 0.0

    mock_client = MagicMock()

    def mock_embed(model, contents):
        res = MagicMock()
        emb = MagicMock()
        text = contents.lower()
        if "이종 집적" in text:
            emb.values = query_vec
        elif "칩렛" in text or "인터커넥트" in text or "패키징" in text:
            emb.values = chiplet_vec
        else:
            emb.values = bio_vec
        res.embeddings = [emb]
        return res

    mock_client.models.embed_content.side_effect = mock_embed

    with patch("os.getenv", return_value="fake_api_key"), \
         patch("google.genai.Client", return_value=mock_client):
        # '이종 집적'은 chiplet_doc 본문에 단 한 글자도 없으나 시맨틱 유사도로 chiplet_doc이 최상위로 랭킹되어야 함
        results = search_relevant_sections("이종 집적", docs_dir=tmp_path, top_k=2)

        assert len(results) > 0
        top_doc = results[0]
        assert top_doc["doc_id"] == "chiplet_doc"
        # 섹션도 성공적으로 랭킹되었는지 확인
        assert len(top_doc["sections"]) > 0
        assert "인터커넥트" in top_doc["sections"][0].heading or "패키징" in top_doc["sections"][0].text


def test_hybrid_semantic_search_fallback_on_error(tmp_path):
    """임베딩 API 오류 발생 시 아무런 예외 없이 기존 룰베이스 키워드 검색으로 안전 폴백되는지 검증."""
    doc_file = tmp_path / "chiplet_doc.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")

    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = RuntimeError("네트워크 통신 타임아웃")

    with patch("os.getenv", return_value="fake_api_key"), \
         patch("google.genai.Client", return_value=mock_client):
        # API 오류가 나더라도 룰베이스 키워드 매칭으로 정상 결과 반환
        results = search_relevant_sections("칩렛 시장", docs_dir=tmp_path, top_k=1)
        assert len(results) == 1
        assert "chiplet" in results[0]["doc_id"].lower()


def test_build_prompt_enhanced_guidelines():
    """신규 보고서 생성 프롬프트에 강화된 5대 보완 규칙(Key Insight, 5열 표, 화이트리스트, 날조 차단)이 포함되어 있는지 검증."""
    generator = TopicReportGenerator(api_key="dummy_key")
    prompt = generator._build_prompt(topic="전고체 배터리", matched_docs=[])

    # 1. Key Insight 블록 지침 검증
    assert "Key Insight" in prompt
    # 2. 3대 표 5열 스키마 가이드 검증
    assert "핵심 기술 방식 비교 요약 표" in prompt
    assert "시장 규모 및 전망 데이터 표" in prompt
    assert "주요 기업별 기술 및 개발 현황 비교 표" in prompt
    # 3. 수치 날조 차단 지침 검증
    assert "날조" in prompt or "원천 데이터" in prompt
    # 4. 이미지 화이트리스트 및 중복 도배 방지 검증
    assert "화이트리스트" in prompt
    assert "중복 도배 금지" in prompt
    # 5. 최신 데이터 우선권 및 논리 충돌 검토 검증
    assert "실제 데이터 자체의 기준 연도 및 조사·발행 시점을 반드시 비교 확인" in prompt
    assert "논리적 충돌을 방치하지 말고" in prompt


def test_refine_report_integrates_fresh_docs(tmp_path):
    """보고서 생성 이후 신규 등재된 최신 문서가 보정 프롬프트에 정상 주입되는지 검증."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    # 1. 기존 보고서 작성 및 저장
    initial_md = """# 칩렛 반도체 종합 보고서
> - **주제어**: 칩렛

## 1. 기술개요
기존 칩렛 개요입니다.
"""
    saved_info = generator.save_report(topic="칩렛", markdown=initial_md, sources=[])
    report_id = saved_info["id"]

    # 2. 보고서 생성 이후 신규 최신 문서 등재 (WikiDB/docs)
    new_doc_content = """# 2026 차세대 칩렛 표준 백서
> - **문서분류**: 기술 백서
> - **원본 파일명**: chiplet_next_2026.pdf

## 신규 UCIe 2.0 표준 발표
2026년 발표된 UCIe 2.0 표준은 대역폭을 2배 향상시킵니다.
새롭게 인텔과 엔비디아 컨소시엄이 합류하였습니다.

| 연도 | 대역폭 | 표준 |
| --- | --- | --- |
| 2026 | 32Gbps | UCIe 2.0 |
"""
    new_doc_file = docs_dir / "chiplet_next_2026.md"
    new_doc_file.write_text(new_doc_content, encoding="utf-8")

    # LLM 모킹 설정 (전달된 프롬프트 캡처)
    captured_prompts = []
    mock_client = MagicMock()

    def mock_generate(model, contents):
        captured_prompts.append(contents)
        res = MagicMock()
        res.text = """# 칩렛 종합 기술 및 시장 분석 보고서
> - **주제어**: 칩렛
> - **검수 상태**: ✨ AI 리뷰어 피드백 및 최신 지식DB 동기화 완료

## 1. 기술개요
신규 UCIe 2.0 표준을 반영한 칩렛 개요입니다.
"""
        return res

    mock_client.models.generate_content.side_effect = mock_generate
    generator.client = mock_client

    feedback = {
        "defects": ["표 누락"],
        "actionable_suggestions": ["비교 표 추가"]
    }

    # 보정 실행 (docs_dir 전달)
    generator.refine_report(report_id=report_id, feedback=feedback, docs_dir=docs_dir)

    # 3. LLM에게 전달된 프롬프트에 신규 등재 문서 내용이 정상 융합되었는지 검증
    assert len(captured_prompts) > 0
    refine_prompt = captured_prompts[0]

    assert "신규 등재 문서: 2026 차세대 칩렛 표준 백서" in refine_prompt
    assert "UCIe 2.0" in refine_prompt
    assert "신규 등재 데이터 반영 절대 규칙" in refine_prompt
    assert "최신 데이터 우선권 및 기술-시장 논리 정합성 집중 보정" in refine_prompt
    assert "기술 사양 혁신과 시장 수요 창출 간의 인과관계" in refine_prompt
    assert "통계 및 시장규모 데이터의 실제 최신성 검증 의무화" in refine_prompt
    assert "기술동향의 기존 논리 체계와의 충돌 검토 의무화" in refine_prompt


def test_review_endpoint_detects_fresh_documents(tmp_path):
    """보고서 생성 이후 WikiDB에 신규 문서가 추가되었을 때 review 엔드포인트가 이를 감지하는지 검증."""
    import os
    import time
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.topic_router import get_generator
    from app.config import Settings, get_settings

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir()
    docs_dir.mkdir()

    custom_settings = Settings(
        source_dir=tmp_path / "source",
        wiki_db_dir=tmp_path,
        docs_dir=docs_dir,
        reports_dir=reports_dir
    )

    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy-key")

    # 1. 과거 시점 보고서 저장
    initial_md = """# AI 반도체 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: AI 반도체

## 1. 기술개요
AI 반도체 개요

## 2. 기술동향
| 기술 | 특징 | 장점 | 단점 | 적용처 |
|---|---|---|---|---|
| NPU | 가속기 | 고효율 | 범용성 | 로봇 |

![도표](/api/assets/doc/img.png)

## 3. 시장동향 (국내/세계시장 규모 데이터)
2024년 500억 달러에서 2030년 1000억 달러 CAGR 12%

| 연도 | 규모 | 비고 | 성장률 | 동인 |
|---|---|---|---|---|
| 2024 | 500 | 실적 | 12% | 수요 |

## 4. 주요업체
| 기업 | 제품 | 양산 | 경쟁력 | 파트너 |
|---|---|---|---|---|
| 엔비디아 | H100 | 양산 | 플랫폼 | 빅테크 |

## 5. 데이터 출처
- [출처1](/api/documents/doc1)
"""
    saved = generator.save_report(topic="AI 반도체", markdown=initial_md, sources=[])
    report_id = saved["id"]

    # 과거 시간으로 mtime 강제 설정 (100초 전)
    report_file = reports_dir / f"{report_id}.md"
    past_time = time.time() - 100
    os.utime(str(report_file), (past_time, past_time))

    # 2. 이후 시점에 docs_dir에 신규 문서 추가
    new_doc_path = docs_dir / "신규_AI_반도체_2026_전망.md"
    new_doc_content = """# 신규 AI 반도체 2026 전망
> - **원본 파일명**: AI_Semiconductor_2026.pdf

## 최신 시장 전망
2026년 AI 반도체 시장은 초고속 성장을 기록할 것입니다.
"""
    new_doc_path.write_text(new_doc_content, encoding="utf-8")

    app = create_app(settings=custom_settings)
    app.dependency_overrides[get_settings] = lambda: custom_settings
    app.dependency_overrides[get_generator] = lambda: generator
    client = TestClient(app)

    # 3. review 엔드포인트 호출
    res = client.post(f"/api/topic/reports/{report_id}/review")
    assert res.status_code == 200
    data = res.json()

    assert data["fresh_docs_count"] >= 1
    assert len(data["fresh_docs"]) >= 1
    assert data["fresh_docs"][0]["title"] == "신규 AI 반도체 2026 전망"
    assert data["review"]["checklist"]["fresh_knowledge_synced"] is False
    assert data["review"]["passed_all"] is False
    assert any("신규 등재된 관련 문서" in d for d in data["review"]["defects"])


def test_extract_smart_section_text_preserves_quant_data():
    """긴 섹션 텍스트가 제한 길이를 초과할 때 단순 절단 대신 후반부의 핵심 정량 데이터 문단이 보존되는지 검증."""
    # 총 4,500자 이상의 긴 텍스트 구성 (앞부분은 장황한 서술, 뒷부분은 핵심 규격 및 시장 전망)
    intro_para = "반도체 패키징 산업은 무어의 법칙 한계를 극복하기 위해 첨단 이종 집적 기술을 빠르게 도입하고 있습니다. " * 3
    verbose_para_1 = "기존의 모놀리식 단일 칩 아키텍처는 수율 저하와 다이 크기 증가에 따른 비용 문제에 직면해 있습니다. " * 35
    verbose_para_2 = "따라서 개별 기능 블록을 분리하여 최적 공정에서 제조한 후 초정밀 인터커넥트로 결합하는 패키징 공법이 대안으로 부상했습니다. " * 35
    
    # 후반부 핵심 정량 데이터 및 소제목 문단 (단순 [:2000] 슬라이싱 시 완전히 유실되는 위치)
    tech_spec_para = "### 핵심 인터커넥트 사양\n차세대 인터커넥트는 3nm 공정 노드를 적용하며 UCIe 규격을 통해 단일 레인당 32Gbps 대역폭을 제공합니다."
    market_quant_para = "### 글로벌 시장 전망\n세계 칩렛 시장은 2025년 80억 달러 규모에서 2030년 500억 달러로 확대되며 연평균 35% CAGR 고성장을 기록할 전망입니다."

    long_sec_text = f"{intro_para}\n\n{verbose_para_1}\n\n{verbose_para_2}\n\n{tech_spec_para}\n\n{market_quant_para}"
    assert len(long_sec_text) > 4000

    # max_chars=2000으로 스마트 추출 실행
    smart_text = TopicReportGenerator._extract_smart_section_text(long_sec_text, max_chars=2000)

    # 1. 길이 제한 준수 검증
    assert len(smart_text) <= 2000

    # 2. 후반부 핵심 정량 데이터 및 소제목 문단이 누락되지 않고 보존되었는지 검증
    assert "### 핵심 인터커넥트 사양" in smart_text
    assert "3nm" in smart_text
    assert "32Gbps" in smart_text
    assert "### 글로벌 시장 전망" in smart_text
    assert "2030년" in smart_text
    assert "500억 달러" in smart_text
    assert "CAGR" in smart_text

    # 3. 문단 분할 경계(\n\n) 유지 확인
    assert "\n\n" in smart_text


def test_build_prompt_modular_structure():
    """_build_prompt가 6대 핵심 모듈 블록과 3대 필수 표 5열 스펙 및 스마트 컨텍스트를 정상 구성하는지 검증."""
    generator = TopicReportGenerator(api_key="dummy_key")

    long_text = (
        "개요 서술 내용입니다.\n\n"
        + ("장황한 일반 배경 서술입니다. " * 50) + "\n\n"
        + "### 세부 시장 전망\n2030년까지 글로벌 시장 규모는 700억 달러로 연평균 40% CAGR 성장이 확실시됩니다."
    )

    matched_docs = [
        {
            "doc_id": "doc_chiplet_2026",
            "title": "2026 차세대 칩렛 기술 분석",
            "score": 10.0,
            "sections": [
                SectionChunk(
                    doc_id="doc_chiplet_2026",
                    doc_title="2026 차세대 칩렛 기술 분석",
                    heading="시장 규모 및 전망",
                    level=2,
                    text=long_text,
                    images=[{"alt": "시장 차트", "url": "/api/assets/doc/img1.png", "caption": "연도별 전망"}],
                    tables=["| 연도 | 규모 |\n|---|---|\n| 2030 | 700억 달러 |"],
                    category="market"
                )
            ]
        }
    ]

    prompt = generator._build_prompt("차세대 칩렛", matched_docs)

    # 1. 6대 모듈 헤더 구조 검증
    assert "[1. 분석가 역할 및 보고서 개요]" in prompt
    assert "[2. 5대 표준 목차 및 필수 섹션 스펙]" in prompt
    assert "[3. 3대 필수 표 5열 표준 구조 정의]" in prompt
    assert "[4. 원천 데이터 보존 및 이미지 화이트리스트 규칙]" in prompt
    assert "[5. 기술-시장 3단계 인과 논리 및 최신성 우선 원칙" in prompt
    assert "[6. 전문 어조 및 서식 무결성 규칙" in prompt
    assert "[참고 컨텍스트 데이터]" in prompt

    # 2. 3대 필수 표 5열 스키마 규격 검증
    assert "| 세부 기술/방식 | 핵심 아키텍처/원리 | 주요 장점 및 효익 | 기술적 과제 및 난제 | 대표 적용처/분야 |" in prompt
    assert "| 시장 구분 (국내/글로벌) | 기준 연도 실적 | 전망 연도 규모 | 연평균 성장률(CAGR) | 핵심 성장 동인 |" in prompt
    assert "| 기업명 | 주력 제품/기술 | 양산 및 상용화 단계 | 핵심 경쟁력/차별화 포인트 | 생태계 협력 파트너 |" in prompt

    # 3. 스마트 컨텍스트를 통해 후반부 핵심 정량 데이터가 프롬프트 컨텍스트에 유입되었는지 검증
    assert "700억 달러" in prompt
    assert "CAGR" in prompt
    assert "doc_chiplet_2026" in prompt
    assert "/api/assets/doc/img1.png" in prompt

def test_build_refine_prompt_surgical_principles():
    """외과적 타겟 보정 및 정상 섹션 불변 보존 4대 원칙이 프롬프트에 포함되는지 검증."""
    generator = TopicReportGenerator(api_key="dummy_key")
    sample_md = """# 초안 보고서
## 1. 기술개요
초안 내용
"""
    feedback = {
        "defects": ["2장 기술 비교표 누락"],
        "actionable_suggestions": ["기술 비교표를 추가하십시오."]
    }
    prompt = generator._build_refine_prompt(
        current_markdown=sample_md,
        topic="차세대 패키징",
        feedback=feedback,
        fresh_context_str=""
    )

    # 1. 외과적 타겟 보정 4대 불변 원칙 명시 검증
    assert "외과적 타겟 보정 및 무손실 보존 4대 불변 원칙" in prompt
    assert "Surgical Non-regression Principles" in prompt

    # 2. 4대 세부 원칙 명시 검증
    assert "정상 섹션 불변 보존 (Zero Drift)" in prompt
    assert "결함 섹션 국소 집중 보강 (Surgical Targeting)" in prompt
    assert "신규 데이터 보완적 통합" in prompt
    assert "형식 및 메타데이터 무결성" in prompt

    # 3. 보정 요청 톤 명확화 검증
    assert "기존의 충실한 분석을 온전히 보존하면서 지적된 결함 섹션만을 정밀 보정하십시오" in prompt


def test_refine_report_safety_guardrail_on_truncated_response(tmp_path):
    """보정된 응답의 길이가 기존 본문 대비 60% 미만으로 급감했을 때 원본이 보호되고 예외가 발생하는지 검증."""
    reports_dir = tmp_path / "reports"
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    initial_md = """# 고성능 인공지능 가속기 종합 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: AI 가속기

## 1. 기술개요
AI 연산 처리를 위한 전용 프로세서 아키텍처 기술입니다.

## 2. 기술동향
NPU와 GPU 기술이 융합되고 있으며 HBM 인터페이스 표준화가 진행 중입니다.

## 3. 시장동향 (국내/세계시장 규모 데이터)
2026년 세계 시장 규모는 500억 달러로 성장할 전망입니다.

## 4. 주요업체
엔비디아, AMD, 인텔이 시장을 주도하고 있습니다.

## 5. 데이터 출처
- [출처1](/api/documents/doc1)
"""
    saved_info = generator.save_report(topic="AI 가속기", markdown=initial_md, sources=[])
    report_id = saved_info["id"]
    report_file = Path(saved_info["file_path"])

    # LLM이 기존 길이(약 500자)의 60% 미만인 극단적으로 축소된 텍스트(50자)를 반환하도록 모킹
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "# AI 가속기\n내용이 비정상적으로 절단된 짧은 요약문입니다."
    mock_client.models.generate_content.return_value = mock_response
    generator.client = mock_client

    feedback = {
        "defects": ["정량 데이터 미흡"],
        "actionable_suggestions": ["수치 보강"]
    }

    # 퇴행 방어 안전장치 작동으로 RuntimeError 발생 검증
    with pytest.raises(RuntimeError) as exc_info:
        generator.refine_report(report_id=report_id, feedback=feedback)

    assert "비정상적으로 축소" in str(exc_info.value) or "보존" in str(exc_info.value)

    # 디스크의 원본 파일이 덮어쓰이지 않고 안전하게 보존되었는지 검증
    preserved_content = report_file.read_text(encoding="utf-8")
    assert "고성능 인공지능 가속기 종합 분석 보고서" in preserved_content
    assert "## 2. 기술동향" in preserved_content
    assert "내용이 비정상적으로 절단된 짧은 요약문" not in preserved_content


def test_refine_report_safety_guardrail_on_missing_headers(tmp_path):
    """기존 보고서에 5대 목차가 온전히 존재하는데 보정본에서 필수 헤더가 누락된 경우 원본이 보호되는지 검증."""
    reports_dir = tmp_path / "reports"
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    initial_md = """# 차세대 뉴로모픽 반도체 종합 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 뉴로모픽

## 1. 기술개요
인간 뇌신경망 구조를 모방한 스파이킹 뉴럴 네트워크 기반 반도체입니다.

## 2. 기술동향
아날로그 시냅스 소자와 초저전력 구동 회로 기술이 발전하고 있습니다.

## 3. 시장동향 (국내/세계시장 규모 데이터)
2030년 세계 시장은 80억 달러 규모로 추정됩니다.

## 4. 주요업체
IBM, 인텔 등이 연구 개발을 선도하고 있습니다.

## 5. 데이터 출처
- [뉴로모픽 기술보고서](/api/documents/doc_neuro)
"""
    saved_info = generator.save_report(topic="뉴로모픽", markdown=initial_md, sources=[])
    report_id = saved_info["id"]
    report_file = Path(saved_info["file_path"])

    # LLM이 길이는 충분하지만 필수 목차(3장 시장동향, 4장 주요업체)를 누락하고 반환한 경우 모킹
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """# 차세대 뉴로모픽 반도체 종합 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서
> - **주제어**: 뉴로모픽
> - **검수 상태**: ✨ AI 리뷰어 피드백 완료

## 1. 기술개요
충분히 긴 내용으로 작성된 기술 개요 본문입니다. 아주 긴 서술을 포함하여 글자 수 기준은 넘겼습니다.

## 2. 기술동향
충분히 긴 내용으로 작성된 기술 동향 본문입니다. 아주 긴 서술을 포함하여 글자 수 기준은 넘겼습니다.

## 5. 데이터 출처
- [뉴로모픽 기술보고서](/api/documents/doc_neuro)
"""
    mock_client.models.generate_content.return_value = mock_response
    generator.client = mock_client

    feedback = {
        "defects": ["표 보완 필요"],
        "actionable_suggestions": ["표를 추가하십시오."]
    }

    # 필수 목차 누락에 따른 퇴행 방어 안전장치 작동으로 RuntimeError 발생 검증
    with pytest.raises(RuntimeError) as exc_info:
        generator.refine_report(report_id=report_id, feedback=feedback)

    assert "필수 목차" in str(exc_info.value) or "누락" in str(exc_info.value) or "보존" in str(exc_info.value)

    # 원본 파일이 온전히 보존되었는지 검증
    preserved_content = report_file.read_text(encoding="utf-8")
    assert "## 3. 시장동향 (국내/세계시장 규모 데이터)" in preserved_content
    assert "## 4. 주요업체" in preserved_content


def test_review_endpoint_passes_context_and_valid_images(tmp_path):
    """리뷰 엔드포인트 호출 시 WikiDB 검색 결과의 컨텍스트 및 이미지 화이트리스트가 reviewer에 전달되는지 검증."""
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.topic_router import get_generator, get_reviewer
    from app.config import Settings, get_settings
    from app.report_reviewer import ReportReviewAgent

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir()
    docs_dir.mkdir()

    custom_settings = Settings(
        source_dir=tmp_path / "source",
        wiki_db_dir=tmp_path,
        docs_dir=docs_dir,
        reports_dir=reports_dir
    )

    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy-key")
    initial_md = """# 실리콘 포토닉스 분석 보고서
> - **주제어**: 실리콘 포토닉스

## 1. 기술개요
개요 본문

## 2. 기술동향
기술 본문

## 3. 시장동향
시장 본문

## 4. 주요업체
기업 본문

## 5. 데이터 출처
- [문서1](/api/documents/doc1)
"""
    saved = generator.save_report(topic="실리콘 포토닉스", markdown=initial_md, sources=[])
    report_id = saved["id"]

    mock_matched_docs = [
        {
            "doc_id": "silicon_photonics_doc",
            "title": "실리콘 포토닉스 기술 동향",
            "file_path": str(docs_dir / "doc1.md"),
            "score": 85.0,
            "sections": [
                SectionChunk(
                    doc_id="silicon_photonics_doc",
                    doc_title="실리콘 포토닉스 기술 동향",
                    heading="광 인터커넥트 아키텍처",
                    level=2,
                    text="실리콘 포토닉스는 빛을 매개로 초고속 데이터를 전송합니다.",
                    images=[
                        {"url": "/api/assets/doc1/optics_arch.png", "alt": "광 구조도", "caption": "구조도"}
                    ]
                )
            ]
        }
    ]

    mock_reviewer = MagicMock(spec=ReportReviewAgent)
    mock_reviewer.review_report.return_value = {
        "passed_all": True,
        "checklist": {},
        "defects": [],
        "actionable_suggestions": [],
        "fresh_docs": []
    }

    app = create_app(settings=custom_settings)
    app.dependency_overrides[get_settings] = lambda: custom_settings
    app.dependency_overrides[get_generator] = lambda: generator
    app.dependency_overrides[get_reviewer] = lambda: mock_reviewer
    client = TestClient(app)

    with patch("app.topic_router.search_relevant_sections", return_value=mock_matched_docs):
        res = client.post(f"/api/topic/reports/{report_id}/review")
        assert res.status_code == 200
        data = res.json()
        assert data["deep_audit"] is False

        # reviewer.review_report가 전달받은 인자 검증
        mock_reviewer.review_report.assert_called_once()
        _, kwargs = mock_reviewer.review_report.call_args
        assert kwargs["report_markdown"].strip() == initial_md.strip()
        assert kwargs["topic"] == "실리콘 포토닉스"
        assert kwargs["context"] is not None
        assert "실리콘 포토닉스 기술 동향" in kwargs["context"]
        assert "광 인터커넥트 아키텍처" in kwargs["context"]
        assert kwargs["valid_image_urls"] == ["/api/assets/doc1/optics_arch.png"]
        assert kwargs["deep_audit"] is False


def test_review_endpoint_deep_audit_query_parameter(tmp_path):
    """deep_audit=true 쿼리 파라미터 전달 시 reviewer에 deep_audit=True가 전달되고 응답에 반영되는지 검증."""
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.topic_router import get_generator, get_reviewer
    from app.config import Settings, get_settings
    from app.report_reviewer import ReportReviewAgent

    reports_dir = tmp_path / "reports"
    docs_dir = tmp_path / "docs"
    reports_dir.mkdir()
    docs_dir.mkdir()

    custom_settings = Settings(
        source_dir=tmp_path / "source",
        wiki_db_dir=tmp_path,
        docs_dir=docs_dir,
        reports_dir=reports_dir
    )

    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy-key")
    initial_md = """# 양자 컴퓨팅 분석 보고서
> - **주제어**: 양자 컴퓨팅

## 1. 기술개요
개요
"""
    saved = generator.save_report(topic="양자 컴퓨팅", markdown=initial_md, sources=[])
    report_id = saved["id"]

    mock_reviewer = MagicMock(spec=ReportReviewAgent)
    mock_reviewer.review_report.return_value = {
        "passed_all": True,
        "checklist": {},
        "defects": [],
        "actionable_suggestions": [],
        "fresh_docs": []
    }

    app = create_app(settings=custom_settings)
    app.dependency_overrides[get_settings] = lambda: custom_settings
    app.dependency_overrides[get_generator] = lambda: generator
    app.dependency_overrides[get_reviewer] = lambda: mock_reviewer
    client = TestClient(app)

    with patch("app.topic_router.search_relevant_sections", return_value=[]):
        res = client.post(f"/api/topic/reports/{report_id}/review?deep_audit=true")
        assert res.status_code == 200
        data = res.json()
        assert data["deep_audit"] is True

        mock_reviewer.review_report.assert_called_once()
        _, kwargs = mock_reviewer.review_report.call_args
        assert kwargs["deep_audit"] is True


def test_save_report_inplace_and_debounce_guard(tmp_path):
    """동일 주제어 저장 시 기존 파일 덮어쓰기(In-place) 및 60초 이내 디바운스 가드 검증."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy-key")

    md_v1 = "# 이차전지 양극재 분석 보고서\n## 1. 개요\nv1 내용"
    md_v2 = "# 이차전지 양극재 분석 보고서\n## 1. 개요\nv2 내용 업데이트"

    # 1. 공백이 섞인 주제어로 첫 저장
    saved1 = generator.save_report(topic="이차전지 양극재 ", markdown=md_v1, sources=["출처1"])
    files = list(reports_dir.glob("*.md"))
    assert len(files) == 1
    assert "이차전지_양극재" in files[0].name
    assert "__" not in files[0].name  # 이중 언더스코어 방지 확인

    # 2. 동일 주제어(공백 정규화된 형태)로 두 번째 저장 시 파일이 2개로 늘어나지 않고 In-place 갱신
    saved2 = generator.save_report(topic="이차전지 양극재", markdown=md_v2, sources=["출처2"])
    files = list(reports_dir.glob("*.md"))
    assert len(files) == 1  # 여전히 1개 파일 유지
    assert files[0].name == saved1["file_name"]
    assert "v2 내용 업데이트" in files[0].read_text(encoding="utf-8")

    # 3. 60초 이내 동일 주제어 generate_report 호출 시 API 재호출 없이 기존 보고서 즉시 반환(디바운스 가드)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    mock_client = MagicMock()
    generator._client = mock_client
    debounced_result = generator.generate_report(topic="이차전지 양극재", docs_dir=docs_dir)
    assert debounced_result["id"] == saved1["id"]
    mock_client.models.generate_content.assert_not_called()  # LLM API 호출되지 않음


def test_embedding_402_fallback_to_secondary_key():
    """유료 키가 402 소진 상태일 때 2번째 모델을 헛돌지 않고 즉시 보조 키로 폴백되는지 검증."""
    from app.topic_search import get_embedding

    # 402 오류를 발생시키는 주 클라이언트 (유료 키 소진 상태)
    mock_client_402 = MagicMock()
    mock_client_402.models.embed_content.side_effect = RuntimeError("402 Payment Required: Credit depleted")

    # 정상 작동하는 보조 클라이언트
    mock_client_ok = MagicMock()
    mock_res = MagicMock()
    mock_emb = MagicMock()
    mock_emb.values = [0.1, 0.2, 0.3]
    mock_res.embeddings = [mock_emb]
    mock_client_ok.models.embed_content.return_value = mock_res

    # 1회차 호출: 유료 키에서 402 발생 -> gemini-embedding-2를 찌르지 않고 즉시 보조 키로 폴백하여 성공
    vec1 = get_embedding("첫 번째 쿼리", client=mock_client_402, fallback_clients=[mock_client_ok])
    assert vec1 == [0.1, 0.2, 0.3]
    assert mock_client_402.models.embed_content.call_count == 1
    assert mock_client_ok.models.embed_content.call_count == 1

    # 동일 검색 내 2회차 호출: 이미 소진 확인된 유료 키를 다시 찌르지 않고 보조 키로 바로 처리
    vec2 = get_embedding("두 번째 쿼리", client=mock_client_402, fallback_clients=[mock_client_ok])
    assert vec2 == [0.1, 0.2, 0.3]
    assert mock_client_402.models.embed_content.call_count == 1
    assert mock_client_ok.models.embed_content.call_count == 2




