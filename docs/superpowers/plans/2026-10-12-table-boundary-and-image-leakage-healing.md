# 마크다운 표 종결 경계 파손 및 이미지 셀 흡수 방지 자율 치유 구현 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마크다운 표(Table) 종결 후 빈 줄(개행 2개) 누락으로 인해 표 직후의 단위/출처 주석 및 인라인 도표 이미지가 표의 셀(`<td>`) 안으로 흡수되어 우측 열들이 텅 빈 더미 셀로 파손 렌더링되는 현상을 근본적으로 차단하고, 특정 파일명/키워드에 대한 하드코딩 없이 일반화된 자율 치유(Self-Healing) 및 4중 방어 체계를 구축한다.

**Architecture:**
1. **백엔드 표 경계 자율 치유 엔진 (`app/utils.py`)**: 
   - 표 헤더 시작 전 및 데이터 행 종결 후 빈 줄(`\n\n`) 강제 보장.
   - 표 직후의 `*(단위:...)*`, `*(도표:...)*`, `<출처:...>` 및 `![...](...)` 이미지 태그를 표 외부의 독립 블록으로 분리.
   - 인라인 복합 태그(`<출처:...>![도표...`) 줄바꿈 격리.
2. **보고서 수명주기 전반의 Self-Healing 결합 (`app/topic_generator.py`)**:
   - 신규 생성(`save_report`), 피드백 보정(`refine_report`), 기존 보고서 조회(`get_report_detail`) 시 자동으로 표 경계를 감지·치유하여 기존 디스크 보고서도 즉시 정상화.
3. **LLM 생성 및 보정 프롬프트 표준화 (`app/topic_generator.py`)**:
   - 표 시작뿐 아니라 표 종료 시점의 개행 2개(`\n\n`) 격리 의무화 및 이미지 단독 행 배치 규칙 강화.
4. **품질 검수 에이전트 결함 탐지 확장 (`app/report_reviewer.py`)**:
   - 표 내부에 이미지 태그가 오염되었거나 비정상적으로 빈 셀만 나열된 파손 행을 감지하여 자동 보정 권고사항 제시.
5. **프론트엔드 마크다운 렌더링 안전망 (`app/static/app.js`)**:
   - 브라우저의 `marked.parse` 실행 직전 표 경계 정규화를 선제 적용하여 렌더링 파손 원천 차단.

**Tech Stack:** Python 3.14+, FastAPI, Google GenAI SDK, JavaScript (Marked.js), Pytest, Regex

---

## Global Constraints
- **하드코딩 절대 금지**: 특정 보고서 ID(`REPORT_AI에이전트_...`), 특정 업체명(`MarketsandMarkets`), 특정 이미지 파일명을 하드코딩하여 예외 처리하는 것을 일체 금지하며, 마크다운 GFM 규격 기반의 일반화된 정규식 및 파서 로직으로 구현한다.
- **글로벌 규칙 엄격 준수**: 모든 주석, docstring, 설명은 한국어로 작성하며 식별자는 표준 영문을 사용한다.
- **하위 호환성 유지**: 기존 132개 전체 테스트 스위트의 무결성을 유지한다.

---

### Task 1: 마크다운 표 경계 자율 치유 함수 `heal_markdown_table_boundaries` 구현 및 단위 테스트

**Files:**
- Modify: `app/utils.py`
- Create/Modify: `tests/test_table_healing.py`

**Interfaces:**
- Consumes: `markdown_text: str`
- Produces: `str` (표 경계 및 인라인 이미지가 완벽히 격리·정돈된 마크다운)

- [ ] **Step 1: 실패하는 단위 테스트 작성 (`tests/test_table_healing.py`)**
  - 테스트 케이스 1: 표 마지막 행 바로 뒤에 빈 줄 없이 `*(단위:...)*` 주석이 붙은 경우 자동으로 `\n\n` 삽입 검증.
  - 테스트 케이스 2: 표 마지막 행 바로 뒤에 `<출처:...>![도표](...)` 가 붙은 경우 표와 이미지 문단이 분리되는지 검증.
  - 테스트 케이스 3: 표 헤더 시작 직전에 텍스트가 빈 줄 없이 붙은 경우(`Text\n| Col1 | Col2 |`) 분리 검증.
  - 테스트 케이스 4: 정상적인 기존 표 및 리스트, 코드 블록 내부의 파이프(`|`)가 오작동하지 않는지 무손실 보존 검증.

- [ ] **Step 2: 테스트 실행 및 실패 확인**
  - Run: `.venv\Scripts\pytest tests/test_table_healing.py -v`
  - Expected: FAIL (미구현 상태)

- [ ] **Step 3: `heal_markdown_table_boundaries` 함수 구현 (`app/utils.py`)**
  - 마크다운 행 단위 상태 머신(State Machine) 또는 정규식을 통해 표 블록(`^\|.+\|$`)의 시작과 끝을 추적.
  - 표 블록이 끝난 직후 다음 행이 빈 줄이 아니고 비-표 행(Non-table line)인 경우 무조건 빈 줄(`\n\n`)을 삽입하여 표 종결 보장.
  - `<출처:...>![...](...)` 또는 `*(...)*![...](...)` 와 같이 한 행에 합쳐진 태그를 분리(`\n\n![]()`).
  - `clean_markdown_typography` 내부 파이프라인에 결합.

- [ ] **Step 4: 테스트 실행 및 통과 확인**
  - Run: `.venv\Scripts\pytest tests/test_table_healing.py -v`
  - Expected: PASS

---

### Task 2: 보고서 저장·조회·보정 수명주기 내 자율 치유 연동 (`app/topic_generator.py`)

**Files:**
- Modify: `app/topic_generator.py:33-91, 423-428, 496-506, 716-727`

**Interfaces:**
- Consumes: 원본 보고서 문자열
- Produces: 표 경계가 완벽히 치유된 정규화 보고서

- [ ] **Step 1: `TopicReportGenerator.deduplicate_citations` 및 `get_report_detail`에 표 치유 연동**
  - `deduplicate_citations` 실행 시 `heal_markdown_table_boundaries`가 자동으로 수행되도록 연결.
  - 사용자가 대시보드에서 기존 보고서를 클릭하거나 API로 조회할 때, 디스크의 기존 보고서 내용에 파손된 표가 있으면 실시간으로 자율 치유(Self-Healing)하여 저장 및 반환.
- [ ] **Step 2: 실제 저장된 `REPORT_AI에이전트_1791793610.md` 파일 대상 자율 치유 검증 테스트 작성**
  - `tests/test_table_healing.py`에 실제 저장된 보고서 샘플을 로드하여 표 뒤 이미지가 분리되고 파이썬 `markdown` 파서로 파싱 시 `<table>` 내부에 `<img>`가 들어가지 않음을 증명하는 테스트 추가.
- [ ] **Step 3: 테스트 실행 및 통과 확인**
  - Run: `.venv\Scripts\pytest tests/test_table_healing.py -k "test_real_report_healing" -v`
  - Expected: PASS

---

### Task 3: AI 보고서 생성 및 보정 프롬프트 표준화 (`app/topic_generator.py`)

**Files:**
- Modify: `app/topic_generator.py:345-351, 593-596`

- [ ] **Step 1: `_build_prompt` 프롬프트 규칙 보강**
  - `[6. 전문 어조 및 서식 무결성 규칙]` 내 마크다운 표 문법 무결성 섹션에 **"표 종결 격리 (Table Terminator Isolation)"** 지침 추가:
    - "표의 마지막 데이터 행(`| ... |`) 다음에는 반드시 2개의 개행(빈 줄)을 넣어 표 블록을 완전히 닫으십시오."
    - "표 하단의 단위/출처 주석(`*(단위:...)*`)이나 도표 이미지(`![]()`)는 표와 절대 같은 줄이나 바로 다음 줄에 붙이지 말고, 독립된 빈 줄을 두고 별도 문단으로 작성하십시오."
    - "출처 태그(`<출처:...>`)와 이미지 태그(`![]()`)를 한 줄에 연달아 붙여 쓰지 말고 반드시 줄바꿈으로 분리하십시오."
- [ ] **Step 2: `_build_refine_prompt` 보정 프롬프트 규칙 동일 보강**
  - 외과적 보정 시에도 표 종결 규칙을 동일하게 주입하여 LLM이 표를 다시 생성하거나 수정할 때 동일 결함이 재발하지 않도록 방어.

---

### Task 4: 품질 검수 에이전트 결함 탐지 규칙 추가 (`app/report_reviewer.py`)

**Files:**
- Modify: `app/report_reviewer.py:80-140`
- Modify: `tests/test_report_reviewer.py`

- [ ] **Step 1: 실패하는 단위 테스트 작성 (`tests/test_report_reviewer.py`)**
  - 표 내부에 이미지 태그가 침투했거나, 표의 마지막 행 뒤에 빈 칸 열만 있는 비정상 더미 행이 포함된 마크다운을 감사할 때 `tables_valid`가 False가 되고 결함(`defects`)에 표 파손이 지적되는지 검증하는 테스트 추가.
- [ ] **Step 2: `_rule_based_audit`에 표 내부 이미지 오염 및 파손 행 검사 로직 추가**
  - 표 블록 내부에서 `![]()` 패턴이 발견되거나, 열 수 불일치로 인한 빈 셀 누출 감지 시 결함 목록에 구체적 보정 가이드 등록.
- [ ] **Step 3: 테스트 실행 및 통과 확인**
  - Run: `.venv\Scripts\pytest tests/test_report_reviewer.py -k "test_table_boundary_defect" -v`
  - Expected: PASS

---

### Task 5: 프론트엔드 마크다운 렌더링 전처리 안전망 강화 (`app/static/app.js`)

**Files:**
- Modify: `app/static/app.js:1140-1175`

- [ ] **Step 1: `renderTopicMarkdown(mdText)` 내 표 경계 정규화 정규식 적용**
  - `marked.parse` 호출 전:
    - 표 행(`| ... |`) 직후 개행이 1개만 있고 다음 줄이 `|`로 시작하지 않는 경우(`(?<=\|)\n(?=[^\|\n])`), `\n\n`으로 교체.
    - 태그 인라인 접착(`>![`, `)*![`)을 줄바꿈(`>\n\n![`, `)*\n\n![`)으로 분리.
- [ ] **Step 2: 브라우저 렌더링 무결성 확인**
  - 프론트엔드에서 테이블 아래 도표가 더 이상 `<td>` 안으로 들어가지 않고 정상 독립 `figure` 블록으로 표시되는지 확인.

---

### Task 6: 전체 회귀 검증 및 종합 점검

**Files:**
- 全 테스트 파일

- [ ] **Step 1: 전체 단위 테스트 실행**
  - Run: `.venv\Scripts\pytest -v`
  - Expected: 133개 이상 전체 테스트 통과 (기존 132개 + 신규 테스트)
- [ ] **Step 2: 실제 보고서 12종 전수 PDF 변환 및 HTML 내보내기 정합성 검증**
  - PyMuPDF 및 HTML 내보내기 시 조판 오류 없이 깔끔하게 테이블과 도표가 분리되는지 확인.
