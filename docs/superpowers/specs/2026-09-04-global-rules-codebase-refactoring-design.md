# 방안 A: 완전 정돈형 리팩터링 설계 스펙 (Design Spec)

- **작성일**: 2026-09-04
- **대상 프로젝트**: LLM Wiki 지식 인제스트 에이전트 및 웹 대시보드 (`LLMwiki_ver3`)
- **적용 규칙**: 글로벌 규칙 10대 원칙 (READ BEFORE YOU WRITE, SIMPLICITY, SURGICAL CHANGES, VERIFICATION 등) 및 한국어 주석 표준

---

## 1. 배경 및 목적

현재 코드베이스는 kordoc 및 Gemini 멀티모달 API를 기반으로 100% 무삭제 마크다운 변환 및 웹 대시보드를 제공하는 완성도 높은 구조를 갖추고 있습니다. 그러나 다음 문제들로 인해 테스트와 실행 신뢰성에 저해가 발생하고 있습니다:
1. `pytest` 단독 실행 시 `PYTHONPATH` 부재로 인한 임포트 에러
2. 단위 테스트 실행 중 외부 CLI(`npx kordoc`) 및 네트워크 호출로 인한 2~3분 단위의 블로킹 지연
3. `KordocWikiAgent`와 레거시 `KordocEngine`/`AIRefiner` 간의 코드 중복 (Wrong Abstraction)
4. Windows 환경 파일 잠김(`PermissionError`) 시 안전한 정리 루틴 부재

본 설계는 글로벌 규칙의 **V. VERIFICATION(검증 우선)**, **III. SIMPLICITY(단순성)**, **IV. SURGICAL CHANGES(정밀한 변경)** 원칙에 따라 시스템을 견고하고 가볍게 정돈하는 것을 목적으로 합니다.

---

## 2. 아키텍처 및 세부 설계

### 2.1 테스트 인프라 정상화 (`pytest.ini`)
- 프로젝트 루트에 `pytest.ini`를 신설하여 루트 디렉터리를 `pythonpath`로 등록합니다.
- 이를 통해 어떤 경로에서 `pytest`를 실행하더라도 `from app....` 임포트가 즉각 정상 동작하도록 보장합니다.

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -v
```

### 2.2 단위 테스트 격리 및 외부 CLI 호출 분리
- **문제 해결**: `test_kordoc_wiki_agent_rule_based_pipeline` 등 단위 테스트에서 `_run_kordoc_lint`가 실제 `npx`를 호출하여 네트워크 대기가 발생하는 문제를 원천 차단합니다.
- **설계**:
  - `KordocWikiAgent.execute_ingest`에 `skip_lint: bool = False` 파라미터를 추가(기본값 `False`).
  - 단위 테스트에서는 `skip_lint=True`를 전달하거나 테스트 픽스처에서 `_run_kordoc_lint`를 모킹(Mocking)하여, 순수 로직 검증에 집중하고 실행 시간을 수 분에서 **1초 이내**로 단축합니다.
  - `app/utils.py`의 `run_kordoc_lint`: 시스템에 전역 설치된 `kordoc` 명령어가 있는지 `shutil.which("kordoc")`로 먼저 확인하고, 있는 경우 직접 실행하여 `npx` 네트워크 해석 비용을 절감합니다.

### 2.3 엔진 통합 및 레거시 모듈 단순화 (Wrong Abstraction 해소)
- **현황**:
  - `run.py`와 `clean_and_reingest.py`는 `KordocWikiAgent`만 사용.
  - `app/kordoc_engine.py`와 `app/ai_refiner.py`는 과거 버전의 코드로, 이미지 추출 및 메타데이터 헤더 생성 등 중복 로직이 방치됨.
- **설계**:
  - 시스템의 단일 주 엔진을 `KordocWikiAgent`로 통일합니다.
  - `KordocEngine`은 기존 테스트 호환성을 유지하되, 내부에서 중복 코드를 유지하지 않고 `KordocWikiAgent`의 메서드나 `app/utils.py`의 공통 함수를 호출하는 경량 파사드(Facade)로 단순화합니다.
  - `AIRefiner` 역시 중복 정규식 로직을 공통 유틸 함수(`app/utils.py`)와 일원화합니다.

### 2.4 Windows 파일 핸들링 안전성 및 보안 강화
- **파일/폴더 삭제 안정성**:
  - Windows에서 백그라운드 프로세스가 파일 핸들을 물고 있을 때 발생하는 `PermissionError`를 방지하기 위해, `app/utils.py`에 `safe_remove_file(path)` 및 `safe_remove_dir(path)` 유틸리티를 추가합니다. (삭제 실패 시 읽기전용 해제 및 잠시 대기 후 재시도)
  - `clean_and_reingest.py`와 `app/server.py`의 문서 삭제 API에 적용합니다.
- **에셋 서빙 보안**:
  - `app/server.py`의 `serve_asset`에서 `Path.resolve()`를 통해 요청된 경로가 `settings.assets_dir` 내부인지 검증하여 잠재적 Path Traversal을 방지합니다.

---

## 3. 변경 대상 파일 목록

1. **[NEW] `pytest.ini`**: pytest 설정 파일
2. **[MODIFY] `app/utils.py`**:
   - `run_kordoc_lint`: 로컬 `kordoc` 명령어 우선 탐색 로직 추가
   - `safe_remove_file`, `safe_remove_dir`: 안전한 Windows 파일/폴더 삭제 헬퍼 추가
3. **[MODIFY] `app/kordoc_wiki_agent.py`**:
   - `execute_ingest`: `skip_lint` 옵션 추가 (기본값 `False`)
4. **[MODIFY] `app/kordoc_engine.py` & `app/ai_refiner.py`**:
   - 중복 로직 제거 및 공통 유틸/에이전트 위임 구조로 단순화 (하위 호환성 유지)
5. **[MODIFY] `app/server.py`**:
   - 에셋 서빙 경로 보안 검증 (`Path.resolve()`) 및 안전 삭제 헬퍼 적용
6. **[MODIFY] `clean_and_reingest.py`**:
   - 안전 삭제 헬퍼 적용으로 Windows 파일 잠김 대비
7. **[MODIFY] `tests/test_kordoc_wiki_agent.py` & 기타 테스트**:
   - 단위 테스트에서 외부 CLI 의존성 격리 (`skip_lint=True` 또는 mock 적용)
   - 35개 전체 테스트가 5초 이내에 100% 통과하도록 정비

---

## 4. 검증 계획 (Verification Plan)

1. **테스트 스위트 전체 자동 실행**:
   - `.venv\Scripts\pytest` 명령 단독 실행으로 35개 이상의 테스트 전체가 에러 없이 100% Pass하는지 확인 (목표 실행 시간: 5초 이내).
2. **단위 테스트 격리 확인**:
   - 네트워크 및 npx 대기 없이 `test_kordoc_wiki_agent.py`가 1초 이내에 완료되는지 확인.
3. **서버 및 에이전트 구동 확인**:
   - `python run.py` 기동 테스트를 통해 서버 초기화 및 파일 감시 정상 작동 확인.
4. **글로벌 규칙 준수 검증**:
   - 모든 신규/수정 함수에 한국어 주석 및 docstring이 명확하게 작성되었는지 확인.
