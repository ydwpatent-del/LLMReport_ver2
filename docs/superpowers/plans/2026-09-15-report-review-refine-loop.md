# AI 보고서 품질 검수 에이전트 및 온디맨드 보정 루프 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 생성 보고서의 품질과 신뢰성을 보장하기 위해 `ReportReviewAgent`를 통한 5대 기준 온디맨드 감수 및 피드백 반영 덮어쓰기 보정(Refinement Loop)을 구현한다.

**Architecture:** 사용자가 보고서 열람 중 [AI 품질 검증]을 요청하면 `ReportReviewAgent`가 5대 기준(목차, 3대 표, 정량 데이터, 이미지, 전문 어조)을 감수하여 결함 및 제안을 반환하고, 사용자가 [피드백 반영 보완]을 승인하면 `TopicReportGenerator.refine_report`가 동일 마크다운 파일에 In-place 덮어쓰기 갱신(점수 메타데이터 제외)을 수행한다.

**Tech Stack:** Python 3.14, FastAPI, Google GenAI SDK (Gemini 2.5 Flash), Tailwind CSS, Vanilla JavaScript, Pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-report-review-refine-loop-design.md`

## Global Constraints
- 모든 응답 및 코드 주석, docstring은 한국어로 작성하며 식별자(변수/함수명)는 표준 영문을 사용한다.
- 기존의 5대 표준 목차, 출처 인용 형식(`<출처: [...]>`), 인라인 이미지 단독 행 배치 규칙을 100% 엄격히 유지한다.
- 보정(Refine) 시 점수(Score: XX점) 메타데이터는 일절 포함하지 않고 단일 파일 In-place 덮어쓰기를 유지한다.
- 모든 기능 구현은 TDD(Test-Driven Development) 원칙에 따라 실패하는 단위 테스트를 먼저 작성하고 최소 코드로 통과시킨다.

---

### Task 1: `ReportReviewAgent` 모듈 및 5대 기준 감수 단위 테스트 구현

**Files:**
- Create: `app/report_reviewer.py`
- Test: `tests/test_report_reviewer.py`

**Interfaces:**
- Produces: `ReportReviewAgent.review_report(report_markdown: str, topic: str, context: Optional[str] = None) -> dict`
- 반환 스키마:
  ```python
  {
      "passed_all": bool,
      "checklist": {
          "structure_valid": bool,
          "tables_valid": bool,
          "quantitative_data_valid": bool,
          "images_valid": bool,
          "tone_valid": bool
      },
      "defects": list[str],
      "actionable_suggestions": list[str]
  }
  ```

- [ ] **Step 1: 실패하는 단위 테스트 작성**

`tests/test_report_reviewer.py` 생성:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

실행: `.venv\Scripts\pytest tests/test_report_reviewer.py -v`  
예상: FAIL with `ModuleNotFoundError: No module named 'app.report_reviewer'`

- [ ] **Step 3: `app/report_reviewer.py` 구현**

```python
"""AI 생성 보고서 품질 검수 및 사실 정합성 평가 에이전트 모듈."""

import json
import logging
import os
import re
from typing import Optional
from google import genai

logger = logging.getLogger("ReportReviewAgent")

class ReportReviewAgent:
    """5대 핵심 기준(목차, 3대 표, 정량 데이터, 이미지, 전문 어조)을 감수하는 평가 에이전트."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _rule_based_audit(self, md: str) -> tuple[dict, list[str], list[str]]:
        """정규식 및 휴리스틱 기반 초고속 룰베이스 품질 검수."""
        checklist = {
            "structure_valid": False,
            "tables_valid": False,
            "quantitative_data_valid": False,
            "images_valid": False,
            "tone_valid": True
        }
        defects = []
        suggestions = []

        # 1. 5대 목차 준수도 점검
        required_headers = [
            r'##\s*1\.\s*기술\s*개요',
            r'##\s*2\.\s*기술\s*동향',
            r'##\s*3\.\s*시장\s*동향',
            r'##\s*4\.\s*주요\s*업체',
            r'##\s*5\.\s*데이터\s*출처'
        ]
        missing_headers = []
        for pat in required_headers:
            if not re.search(pat, md):
                missing_headers.append(pat.replace(r'\s*', ' ').replace(r'##', '## '))
        
        if not missing_headers:
            checklist["structure_valid"] = True
        else:
            defects.append(f"5대 표준 목차 중 누락된 섹션이 있습니다: {', '.join(missing_headers)}")
            suggestions.append("5대 표준 목차(1.기술개요~5.데이터출처)를 빠짐없이 구성하십시오.")

        # 2. 3대 필수 표 구비 점검
        table_matches = re.findall(r'\|[^\n]+\|\s*\n\s*\|[\s\-:|]+\|', md)
        if len(table_matches) >= 3:
            checklist["tables_valid"] = True
        else:
            defects.append(f"필수 비교 표(기술 비교표, 시장 전망표, 기업 비교표) 중 일부가 누락되었습니다 (현재 {len(table_matches)}개 발견, 최소 3개 필요).")
            suggestions.append("2장(기술 비교 요약 표), 3장(시장 규모 및 전망 표), 4장(주요 기업 비교 표)을 마크다운 표로 작성하십시오.")

        # 3. 정량 데이터 충실도 점검
        has_numbers = re.search(r'\b(202[0-9]|203[0-9])년', md) and re.search(r'(\d+(?:\.\d+)?\s*(?:억\s*원|억\s*달러|조\s*원|%|CAGR|nm|Gbps|W))', md, re.IGNORECASE)
        if has_numbers:
            checklist["quantitative_data_valid"] = True
        else:
            defects.append("시장 규모, 연도별 추이 수치 또는 핵심 기술 규격 데이터가 부족합니다.")
            suggestions.append("구체적인 연도, 금액 단위(억 원/달러), CAGR %, 규격 수치를 본문과 표에 명시하십시오.")

        # 4. 시각 자산 결합 점검
        has_images = bool(re.search(r'!\[.*?\]\(.*?\)', md))
        if has_images:
            checklist["images_valid"] = True
        else:
            defects.append("인라인 도표 또는 아키텍처 다이어그램 이미지가 배치되지 않았습니다.")
            suggestions.append("컨텍스트에서 제공된 유의미한 차트 및 구조도 이미지를 단독 행으로 결합하십시오.")

        # 5. 전문 어조 및 AI 상투어 배제 점검
        greetings = ["안녕하세요", "작성해 드립니다", "보고서를 작성합니다", "도움이 되길", "이상으로 보고서를"]
        found_greetings = [g for g in greetings if g in md]
        if found_greetings:
            checklist["tone_valid"] = False
            defects.append(f"보고서에 불필요한 AI 인사말 또는 안내 문구가 포함되어 있습니다: {', '.join(found_greetings)}")
            suggestions.append("서두/말미의 인사말과 메타 발언을 모두 삭제하고 순수한 보고서 본문만 기술하십시오.")

        return checklist, defects, suggestions

    def review_report(self, report_markdown: str, topic: str, context: Optional[str] = None) -> dict:
        """보고서 본문을 검수하여 체크리스트, 결함 목록, 개선 제안을 반환한다."""
        checklist, defects, suggestions = self._rule_based_audit(report_markdown)
        passed_all = all(checklist.values()) and len(defects) == 0

        return {
            "passed_all": passed_all,
            "checklist": checklist,
            "defects": defects,
            "actionable_suggestions": suggestions
        }
```

- [ ] **Step 4: 테스트 통과 확인**

실행: `.venv\Scripts\pytest tests/test_report_reviewer.py -v`  
예상: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add app/report_reviewer.py tests/test_report_reviewer.py
git commit -m "feat: add ReportReviewAgent and unit tests for 5-criteria quality audit"
```

---

### Task 2: `TopicReportGenerator.refine_report` 메서드 구현 및 단위 테스트

**Files:**
- Modify: `app/topic_generator.py`
- Test: `tests/test_topic_system.py`

**Interfaces:**
- Produces: `TopicReportGenerator.refine_report(report_id: str, feedback: dict) -> dict`
- 기존 `{report_id}.md` 파일에 In-place 덮어쓰기 저장 (점수 표기 메타데이터 제외).

- [ ] **Step 1: 실패하는 단위 테스트 추가**

`tests/test_topic_system.py` 하단에 `test_refine_report_in_place` 추가:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

실행: `.venv\Scripts\pytest tests/test_topic_system.py::test_refine_report_in_place -v`  
예상: FAIL with `AttributeError: 'TopicReportGenerator' object has no attribute 'refine_report'`

- [ ] **Step 3: `TopicReportGenerator.refine_report` 구현**

`app/topic_generator.py`에 메서드 추가:
```python
    def _build_refine_prompt(self, current_markdown: str, topic: str, feedback: dict) -> str:
        """기존 보고서 내용과 리뷰어 피드백을 결합한 보정 전용 프롬프트를 구성한다."""
        defects_str = "\n".join(f"- {d}" for d in feedback.get("defects", []))
        suggestions_str = "\n".join(f"- {s}" for s in feedback.get("actionable_suggestions", []))

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 감수위원입니다.
아래에 제공된 기존 보고서를 정밀 검토하고, 독립 품질 감사 에이전트가 지적한 결함(Defects)과 개선 권고사항을 완벽히 보강하여 최상급의 완성본 마크다운 보고서로 재작성해 주십시오.

[기존 작성 보고서 원본]
{current_markdown}

[감수 에이전트 지적 결함 목록]
{defects_str}

[구체적 개선 요구사항]
{suggestions_str}

[보정 절대 준수 규칙]
1. 기존 보고서에서 이미 충실하게 작성된 문단과 구조, 정상적인 표 및 이미지는 훼손하지 말고 최대한 보존하십시오.
2. [지적 결함] 및 [개선 요구사항]에 명시된 누락 항목(예: 2장 기술 비교표, 3장 시장 전망표, 4장 기업 비교표, 정량 수치 보강 등)을 해당 섹션 내에 자연스럽고 정밀하게 추가/보완하십시오.
3. 머리말 헤더 메타데이터 영역에 `> - **검수 상태**: ✨ AI 리뷰어 피드백 반영 보정 완료` 항목을 추가하십시오. 단, 점수(XX점 등) 관련 문구는 일절 기재하지 마십시오.
4. 첫 행은 반드시 `# {topic} 종합 기술 및 시장 분석 보고서`로 시작하며, 불필요한 AI 인사말이나 서두/말미의 안내 문구("수정본을 작성했습니다" 등)는 일절 작성하지 마십시오.
"""
        return prompt

    def refine_report(self, report_id: str, feedback: dict) -> dict:
        """기존 보고서와 리뷰 피드백을 기반으로 LLM 보정을 수행하고 In-place 덮어쓰기 저장한다."""
        detail = self.get_report_detail(report_id)
        if not detail:
            raise RuntimeError(f"보정할 보고서 '{report_id}'를 찾을 수 없습니다.")

        topic = detail.get("topic") or report_id
        current_md = detail["content"]

        prompt = self._build_refine_prompt(current_md, topic, feedback)

        # Gemini LLM 호출
        model_names = ["gemini-2.5-flash", "gemini-2.0-flash"]
        response_text = None
        last_error = None

        for model_name in model_names:
            try:
                logger.info(f"Gemini 모델 '{model_name}'으로 보고서 보정(Refine) 시도 중: {report_id}")
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    response_text = response.text
                    break
            except Exception as e:
                logger.warning(f"보정 호출 중 오류 ({model_name}): {e}")
                last_error = e

        if not response_text:
            raise RuntimeError(f"보고서 보정 LLM 호출 실패: {last_error}")

        # In-place 덮어쓰기 저장
        cleaned_markdown = self.deduplicate_citations(response_text)
        target_file = self.reports_dir / f"{Path(report_id).stem}.md"
        target_file.write_text(cleaned_markdown, encoding="utf-8")
        logger.info(f"보고서 보정 In-place 덮어쓰기 완료: {target_file}")

        first_heading = re.search(r'^#\s+(.+)$', cleaned_markdown, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else detail["title"]

        return {
            "id": report_id,
            "title": title,
            "topic": topic,
            "markdown": cleaned_markdown,
            "file_name": target_file.name,
            "file_path": str(target_file),
            "file_size": target_file.stat().st_size,
            "created_at": detail.get("ingested_at"),
            "modified_time": target_file.stat().st_mtime,
            "is_synthesized": True
        }
```

- [ ] **Step 4: 테스트 통과 확인**

실행: `.venv\Scripts\pytest tests/test_topic_system.py::test_refine_report_in_place -v`  
예상: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/topic_generator.py tests/test_topic_system.py
git commit -m "feat: implement TopicReportGenerator.refine_report with in-place overwrite"
```

---

### Task 3: FastAPI 라우터 엔드포인트 구현 및 통합 테스트

**Files:**
- Modify: `app/topic_router.py`
- Test: `tests/test_topic_system.py`

**Interfaces:**
- `POST /api/topic/reports/{report_id}/review` -> `{"report_id": str, "review": dict}`
- `POST /api/topic/reports/{report_id}/refine` -> `TopicReportItemResponse`

- [ ] **Step 1: 실패하는 엔드포인트 통합 테스트 작성**

`tests/test_topic_system.py`에 `test_review_and_refine_api_endpoints` 추가:
```python
def test_review_and_refine_api_endpoints(tmp_path):
    """FastAPI review 및 refine 엔드포인트 동작 검증."""
    from fastapi.testclient import TestClient
    from app.server import create_app
    from app.config import Settings

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generator = TopicReportGenerator(reports_dir=reports_dir, api_key="dummy_key")

    report_info = generator.save_report(
        topic="양자컴퓨팅",
        markdown="# 양자컴퓨팅 보고서\n\n## 1. 기술개요\n초안입니다.",
        sources=[]
    )
    report_id = report_info["id"]

    custom_settings = Settings(
        source_dir=tmp_path / "Source",
        wiki_db_dir=tmp_path,
        docs_dir=tmp_path / "docs",
        assets_dir=tmp_path / "assets",
        manifest_path=tmp_path / "manifest.json"
    )
    app = create_app(settings=custom_settings)
    client = TestClient(app)

    # 1. POST /api/topic/reports/{report_id}/review 호출
    res_review = client.post(f"/api/topic/reports/{report_id}/review")
    assert res_review.status_code == 200
    review_data = res_review.json()
    assert "review" in review_data
    assert "checklist" in review_data["review"]
    assert "defects" in review_data["review"]

    # 2. POST /api/topic/reports/{report_id}/refine 호출 (Mock)
    with patch.object(TopicReportGenerator, "refine_report") as mock_refine:
        mock_refine.return_value = {
            "id": report_id,
            "title": "보정된 양자컴퓨팅 보고서",
            "topic": "양자컴퓨팅",
            "original_filename": f"{report_id}.md",
            "file_size": 1024,
            "modified_time": 1700000000.0,
            "status": "completed",
            "ingested_at": "2026-09-15",
            "is_synthesized": True
        }
        res_refine = client.post(
            f"/api/topic/reports/{report_id}/refine",
            json={"feedback": review_data["review"]}
        )
        assert res_refine.status_code == 200
        refine_json = res_refine.json()
        assert refine_json["id"] == report_id
        assert refine_json["title"] == "보정된 양자컴퓨팅 보고서"
```

- [ ] **Step 2: 테스트 실패 확인**

실행: `.venv\Scripts\pytest tests/test_topic_system.py::test_review_and_refine_api_endpoints -v`  
예상: FAIL with `404 Not Found` (엔드포인트 미구현)

- [ ] **Step 3: `app/topic_router.py` 엔드포인트 구현**

```python
from app.report_reviewer import ReportReviewAgent

class TopicRefineRequest(BaseModel):
    """보고서 보정 요청 DTO."""
    feedback: dict

_reviewer_instance: Optional[ReportReviewAgent] = None

def get_reviewer() -> ReportReviewAgent:
    """ReportReviewAgent 의존성 프로바이더."""
    global _reviewer_instance
    if _reviewer_instance is None:
        _reviewer_instance = ReportReviewAgent()
    return _reviewer_instance

@topic_router.post("/reports/{report_id}/review")
async def review_topic_report(
    report_id: str,
    generator: TopicReportGenerator = Depends(get_generator),
    reviewer: ReportReviewAgent = Depends(get_reviewer)
):
    """지정된 보고서 본문을 5대 기준으로 정밀 검수하고 결과를 반환한다."""
    detail = generator.get_report_detail(report_id)
    if not detail:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")

    review_res = reviewer.review_report(
        report_markdown=detail["content"],
        topic=detail.get("topic", detail["title"])
    )
    return {"report_id": report_id, "review": review_res}

@topic_router.post("/reports/{report_id}/refine")
async def refine_topic_report(
    report_id: str,
    req: TopicRefineRequest,
    generator: TopicReportGenerator = Depends(get_generator)
):
    """리뷰 피드백을 반영하여 보고서를 In-place 덮어쓰기 보정한다."""
    try:
        updated = generator.refine_report(report_id=report_id, feedback=req.feedback)
        return updated
    except Exception as e:
        logger.exception(f"보고서 보정 오류 ({report_id}): {e}")
        raise HTTPException(status_code=500, detail=f"보고서 보정 실패: {str(e)}")
```

- [ ] **Step 4: 테스트 통과 확인**

실행: `.venv\Scripts\pytest tests/test_topic_system.py::test_review_and_refine_api_endpoints -v`  
예상: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/topic_router.py tests/test_topic_system.py
git commit -m "feat: add review and refine API endpoints to topic_router"
```

---

### Task 4: 프론트엔드 검증 버튼 및 피드백 반영 모달 UI/UX 구현

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`

**Interfaces:**
- HTML 요소: `#btnReviewReport`, `#reportReviewModal`, `#btnApplyRefine`, `#btnCloseReviewModal`
- JS 핸들러: `handleReviewReport()`, `handleApplyRefine()`, `renderReviewModal(reviewData)`

- [ ] **Step 1: `app/static/index.html`에 검증 버튼 및 모달 마크업 추가**

1. 상단 툴바 `topicReportViewer` 헤더 영역에 버튼 추가:
```html
<button id="btnReviewReport" class="px-2.5 py-1.5 text-xs rounded-lg bg-amber-600/80 hover:bg-amber-600 text-white transition flex items-center gap-1.5 shadow-md cursor-pointer active:scale-95">
  <i class="fa-solid fa-magnifying-glass-chart" id="reviewIcon"></i>
  <span id="reviewBtnText">AI 품질 검증</span>
</button>
```

2. 바디 하단에 검수 결과 모달 마크업 추가:
```html
<!-- AI 보고서 품질 검증 모달 -->
<div id="reportReviewModal" class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm hidden flex items-center justify-center p-4">
  <div class="bg-slate-800 border border-slate-700 rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
    <!-- 모달 헤더 -->
    <div class="p-4 border-b border-slate-700/80 flex items-center justify-between bg-slate-800/90 shrink-0">
      <h3 class="text-sm font-bold text-white flex items-center gap-2">
        <i class="fa-solid fa-magnifying-glass-chart text-amber-400"></i>
        <span>AI 보고서 품질 및 사실 검증 결과</span>
      </h3>
      <button id="btnCloseReviewModal" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-700/60 transition">
        <i class="fa-solid fa-xmark text-base"></i>
      </button>
    </div>

    <!-- 모달 본문 (스크롤) -->
    <div class="p-5 overflow-y-auto space-y-4 text-xs">
      <!-- 5대 항목 체크리스트 -->
      <div class="bg-slate-900/70 rounded-xl p-3 border border-slate-700/60 space-y-2">
        <h4 class="font-bold text-slate-300 mb-2">📋 5대 표준 품질 체크리스트</h4>
        <div id="reviewChecklistContainer" class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <!-- JS 동적 생성 -->
        </div>
      </div>

      <!-- 지적 결함 및 개선 제안 -->
      <div class="space-y-3">
        <div>
          <h4 class="font-bold text-red-300 mb-1.5 flex items-center gap-1.5">
            <i class="fa-solid fa-triangle-exclamation text-red-400"></i> 발견된 보완 항목
          </h4>
          <ul id="reviewDefectsList" class="list-disc list-inside space-y-1 text-slate-300 bg-red-950/20 p-3 rounded-xl border border-red-900/30">
            <!-- JS 동적 생성 -->
          </ul>
        </div>
        <div>
          <h4 class="font-bold text-brand-300 mb-1.5 flex items-center gap-1.5">
            <i class="fa-solid fa-wand-magic-sparkles text-brand-400"></i> 개선 권고사항
          </h4>
          <ul id="reviewSuggestionsList" class="list-disc list-inside space-y-1 text-slate-300 bg-brand-950/20 p-3 rounded-xl border border-brand-900/30">
            <!-- JS 동적 생성 -->
          </ul>
        </div>
      </div>
    </div>

    <!-- 모달 푸터 액션 -->
    <div class="p-4 border-t border-slate-700/80 flex items-center justify-end gap-2 bg-slate-800/90 shrink-0">
      <button id="btnCloseReviewModal2" class="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 transition font-medium">
        닫기
      </button>
      <button id="btnApplyRefine" class="px-4 py-2 rounded-xl bg-gradient-to-r from-amber-600 to-brand-600 hover:from-amber-500 hover:to-brand-500 text-white font-semibold transition flex items-center gap-1.5 shadow-lg shadow-amber-600/20 active:scale-95 cursor-pointer">
        <i class="fa-solid fa-wand-magic-sparkles"></i>
        <span id="refineBtnText">✨ 피드백 반영하여 보고서 개선</span>
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: `app/static/app.js`에 검증 및 보정 이벤트 핸들러 구현**

`app/static/app.js` 내에:
1. `currentActiveReportId` 및 `lastReviewData` 상태 변수 연동
2. `btnReviewReport.addEventListener('click', ...)`:
   - `POST /api/topic/reports/${currentActiveReportId}/review` 호출
   - 로딩 스피너 및 모달 팝업 표출
3. `btnApplyRefine.addEventListener('click', ...)`:
   - `POST /api/topic/reports/${currentActiveReportId}/refine` 호출 (페이로드에 `lastReviewData` 전달)
   - 보정 완료 후 모달 닫기
   - 마크다운 본문 `topicRenderedContent` 즉시 갱신 및 토스트 알림

- [ ] **Step 3: 브라우저 및 통합 회귀 테스트**

실행: `.venv\Scripts\pytest`  
예상: 전체 테스트 스위트 정상 통과

- [ ] **Step 4: 커밋**

```bash
git add app/static/index.html app/static/app.js
git commit -m "feat: add UI modal and interaction for report quality review and refinement"
```
