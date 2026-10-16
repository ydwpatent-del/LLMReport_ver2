# AI 지식DB 보고서 품질검수 및 프롬프트 개선 구현 계획서 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 생성 보고서의 품질 검수 체계(`ReportReviewAgent`)를 정규식 중심에서 사실 정합성·표 구조·이미지 화이트리스트·인과 논리까지 정밀 검증하는 2단계 하이브리드 감사 엔진으로 고도화하고, 생성 및 보정 프롬프트(`TopicReportGenerator`)의 모놀리식 결함과 퇴행적 재작성(Regressive Drift) 문제를 외과적 타겟 보정 방식으로 근본 개선한다.

**Architecture:** 
1. **ReportReviewAgent 고도화**: 초고속 결정론적 룰베이스(5대 목차, 3대 표 컬럼 스펙, 정량 밀도, 화이트리스트 이미지, 출처 무결성)와 온디맨드 LLM 사실 정합성/논리 감사(할루시네이션 및 기술-시장 3단계 인과성 검증)를 결합한 2단계 하이브리드 아키텍처.
2. **외과적 타겟 보정(Surgical Refinement)**: 전체 재작성으로 인한 양질의 기존 텍스트 변형·유실을 방지하기 위해 결함 섹션 중심 보정 프롬프트 구조화 및 맥락 보존 메커니즘 도입.
3. **스마트 컨텍스트 압축 및 프롬프트 모듈화**: `sec.text[:3000]` 기계적 절단 탈피, 핵심 표·수치 중심 스마트 컨텍스트 구성 및 지시 과부하 완화.

**Tech Stack:** Python 3.14+, FastAPI, Google GenAI SDK (Gemini 2.5 Flash / Pro), Pytest, Regex

**Spec:** `docs/superpowers/specs/2026-09-15-report-review-refine-loop-design.md` 및 본 계획서

## Global Constraints
- Python 표준 및 프로젝트 기존 의존성(`google-genai`, `fastapi`, `pymupdf` 등) 준수, 불필요한 신규 패키지 추가 지양.
- 기존 단위 테스트 23건의 하위 호환성 100% 유지.
- 코드 주석 및 커밋/문서는 한국어 표준 규칙 준수.

---

### Task 1: ReportReviewAgent 룰베이스 검수 정밀화 (3대 표 규격, 이미지 화이트리스트, 출처 무결성)

**Files:**
- Modify: `app/report_reviewer.py:25-143`
- Test: `tests/test_report_reviewer.py`

**Interfaces:**
- Consumes: `report_markdown: str`, `context: Optional[str]`, `fresh_docs: Optional[list]`, `valid_image_urls: Optional[list[str]]`
- Produces: `checklist: dict`, `defects: list[str]`, `actionable_suggestions: list[str]`
  - `checklist` 확장 키: `tables_valid`, `images_valid`, `citations_valid`, `quantitative_data_valid`

- [ ] **Step 1: 실패하는 단위 테스트 작성**
  `tests/test_report_reviewer.py`에 다음 테스트 케이스 추가:
  - 3대 표 중 2장 기술표/3장 시장표/4장 기업표의 특정 열이 누락되었거나 엉뚱한 헤더인 경우 감지 테스트
  - 컨텍스트에 없는 허구의 이미지 URL(`![](/api/assets/fake/img.png)`) 감지 테스트
  - 본문 문단 종결부 `<출처: [문서제목](/api/documents/doc_id)>` 형식 누락 감지 테스트

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  Run: `.venv\Scripts\pytest tests/test_report_reviewer.py -k "test_table_columns or test_image_whitelist or test_citation_integrity" -v`
  Expected: FAIL (신규 검증 로직 미구현)

- [ ] **Step 3: 룰베이스 감사 로직 구현**
  `app/report_reviewer.py`의 `_rule_based_audit`에 정밀 검증 로직 추가:
  - 3개 표의 존재 여부뿐 아니라 2장/3장/4장 헤딩 하위 영역별로 표가 위치하는지 검사
  - `valid_image_urls`가 주어졌을 때 본문 인용 이미지가 화이트리스트에 포함되는지 검사
  - 문단 끝 출처 태그 및 5장 출처 목록 정합성 검사

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  Run: `.venv\Scripts\pytest tests/test_report_reviewer.py -v`
  Expected: PASS (23+ 신규 테스트 전원 통과)

- [ ] **Step 5: 커밋**
  ```bash
  git add app/report_reviewer.py tests/test_report_reviewer.py
  git commit -m "feat: ReportReviewAgent 룰베이스 검수 정밀화 (표 규격, 화이트리스트 이미지, 출처 무결성)"
  ```

---

### Task 2: ReportReviewAgent 온디맨드 LLM 사실 정합성 및 인과 논리 감사 구현

**Files:**
- Modify: `app/report_reviewer.py:125-171`
- Test: `tests/test_report_reviewer.py`

**Interfaces:**
- Consumes: `report_markdown: str`, `topic: str`, `context: Optional[str]`, `deep_audit: bool = False`
- Produces: `factuality_valid: bool`, `causality_valid: bool`, `fact_defects: list[str]`

- [ ] **Step 1: 실패하는 단위 테스트 작성**
  `tests/test_report_reviewer.py`에 LLM 기반 사실 정합성 검증 모의(Mock) 테스트 추가:
  - 컨텍스트에 없는 조작된 수치/기업명(할루시네이션)이 포함된 경우 결함 탐지
  - 2장 기술 규격과 3장 시장 성장의 3단계 인과관계 부재 지적 확인

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  Run: `.venv\Scripts\pytest tests/test_report_reviewer.py -k "test_llm_fact_check" -v`
  Expected: FAIL

- [ ] **Step 3: `_llm_semantic_audit` 메서드 구현**
  `app/report_reviewer.py`에 LLM 호출 감사 함수 구현:
  - `deep_audit=True` 또는 `context` 제공 시 가동
  - 프롬프트: 원문 컨텍스트와 보고서 대조를 통한 수치/팩트 할루시네이션 점검, 기술-시장 인과성 점검
  - JSON 응답 파싱 및 안전한 폴백(룰베이스 결과 결합) 처리

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  Run: `.venv\Scripts\pytest tests/test_report_reviewer.py -v`
  Expected: PASS

- [ ] **Step 5: 커밋**
  ```bash
  git add app/report_reviewer.py tests/test_report_reviewer.py
  git commit -m "feat: ReportReviewAgent LLM 사실 정합성 및 인과 논리 검증 기능 추가"
  ```

---

### Task 3: TopicReportGenerator 생성 프롬프트 모듈화 및 스마트 컨텍스트 구성

**Files:**
- Modify: `app/topic_generator.py:93-258`
- Test: `tests/test_topic_system.py`

**Interfaces:**
- Consumes: `topic: str`, `matched_docs: list[dict]`
- Produces: `prompt: str` (구조화된 모듈형 프롬프트)

- [ ] **Step 1: 실패하는 단위 테스트 작성**
  `tests/test_topic_system.py`에 스마트 컨텍스트 추출 및 프롬프트 가이드라인 준수 테스트 추가:
  - 섹션 텍스트 단순 3000자 절단 대신 표 및 통계가 포함된 단락 우선 보존 검증

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -k "test_smart_context_preservation" -v`
  Expected: FAIL

- [ ] **Step 3: 스마트 컨텍스트 및 모듈형 프롬프트 구현**
  `app/topic_generator.py`의 `_build_prompt` 개선:
  - 섹션 텍스트 슬라이싱 시 중요 표/수치가 포함된 블록 우선 추출
  - 모놀리식 프롬프트를 명확한 역할/목차 스펙/표 규격/데이터 우선권 블록으로 구조화하여 지시 준수율 극대화

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -v`
  Expected: PASS

- [ ] **Step 5: 커밋**
  ```bash
  git add app/topic_generator.py tests/test_topic_system.py
  git commit -m "refactor: TopicReportGenerator 스마트 컨텍스트 추출 및 모듈형 프롬프트 개선"
  ```

---

### Task 4: 외과적 타겟 보정(Surgical Refinement) 프롬프트 및 퇴행 방지 메커니즘

**Files:**
- Modify: `app/topic_generator.py:441-555`
- Test: `tests/test_topic_system.py`

**Interfaces:**
- Consumes: `current_markdown: str`, `topic: str`, `feedback: dict`, `fresh_context_str: str`
- Produces: `refine_prompt: str` (퇴행 방지 및 결함 섹션 타겟 보정 지시문)

- [ ] **Step 1: 실패하는 단위 테스트 작성**
  `tests/test_topic_system.py`에 타겟 보정 지시문 검증 테스트 추가:
  - 기존 정상 섹션의 보존을 명시하고, 결함이 지적된 장(예: 3장)만을 집중 교정하는 보정 프롬프트 생성 여부 확인

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -k "test_surgical_refine_prompt" -v`
  Expected: FAIL

- [ ] **Step 3: 외과적 타겟 보정 프롬프트 구현**
  `app/topic_generator.py`의 `_build_refine_prompt` 수정:
  - 전체 무차별 재생성 요구를 제거하고, 기존 합격 섹션 불변 보존 원칙 및 결함 섹션 국소 타겟팅 지시 명시
  - Regressive Drift 방지 안전 가이드라인 수립

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -v`
  Expected: PASS

- [ ] **Step 5: 커밋**
  ```bash
  git add app/topic_generator.py tests/test_topic_system.py
  git commit -m "feat: TopicReportGenerator 외과적 타겟 보정 프롬프트 및 기존 본문 퇴행 방지"
  ```

---

### Task 5: TopicRouter 검수/보정 엔드포인트 파이프라인 연계 및 컨텍스트 전달

**Files:**
- Modify: `app/topic_router.py:146-234`
- Test: `tests/test_topic_system.py`

**Interfaces:**
- Consumes: `/api/topic/reports/{report_id}/review` (deep_audit 쿼리 파라미터 지원), `/api/topic/reports/{report_id}/refine`
- Produces: 정밀 검수 결과 JSON (컨텍스트 기반 사실 대조 피드백 포함) 및 안정 보정 응답

- [ ] **Step 1: 실패하는 단위 테스트 작성**
  `tests/test_topic_system.py`에 리뷰 엔드포인트가 원본 컨텍스트 및 이미지 화이트리스트를 수집하여 reviewer에 전달하는지 검증하는 테스트 추가.

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -k "test_review_endpoint_passes_context" -v`
  Expected: FAIL

- [ ] **Step 3: 라우터 엔드포인트 개선**
  `app/topic_router.py`의 `review_topic_report_endpoint`:
  - 관련 원본 문서 섹션 및 유효 에셋 이미지 URL 목록을 수집하여 `reviewer.review_report(..., context=..., valid_image_urls=...)`로 전달
  - `deep_audit: bool = False` 옵션 지원

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  Run: `.venv\Scripts\pytest tests/test_topic_system.py -v`
  Expected: PASS

- [ ] **Step 5: 커밋**
  ```bash
  git add app/topic_router.py tests/test_topic_system.py
  git commit -m "feat: TopicRouter 검수 엔드포인트 컨텍스트 및 화이트리스트 연계"
  ```

---

### Task 6: 전체 회귀 테스트 및 E2E 무결성 검증

**Files:**
- Run all test suites across the repository.

- [ ] **Step 1: 전체 단위 및 통합 테스트 실행**
  Run: `.venv\Scripts\pytest -v`
  Expected: 모든 테스트 파일(인제스트, 에이전트, 리포트, 라우터) 통과

- [ ] **Step 2: 품질 게이트 및 린트 검증**
  Check: 파손된 마크다운, 미사용 변수, 구문 오류 없는지 확인.
