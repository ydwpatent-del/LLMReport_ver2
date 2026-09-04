# 방안 A: 코드베이스 글로벌 규칙 리팩터링 구현 계획 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 글로벌 규칙(검증 우선, 단순성, 테스트 격리, 중복 제거, 한국어 주석 통일)에 의거하여 테스트 인프라를 정상화하고 레거시 중복 코드를 제거하며 시스템 안정성을 극대화한다.

**Architecture:** 루트에 `pytest.ini`를 배치하여 모듈 경로를 자동 바인딩하고, 단위 테스트에서 외부 CLI(`npx kordoc`) 호출을 완전히 격리하여 테스트 속도를 1초대로 개선한다. `KordocWikiAgent`를 단일 주 엔진으로 확립하고 레거시 `KordocEngine`/`AIRefiner`의 중복 코드를 공통 유틸리티로 통합하며, Windows 환경 파일 잠김 대비 안전 삭제 루틴을 구축한다.

**Tech Stack:** Python 3.14, pytest, FastAPI, Uvicorn, Pydantic, Watchdog, PyMuPDF, Google GenAI SDK.

**Spec:** `docs/superpowers/specs/2026-09-04-global-rules-codebase-refactoring-design.md`

## Global Constraints

- TARGET_LANGUAGE = Korean: 모든 생각, 설명, 코드 주석 및 독스트링은 자연스러운 한국어로 작성.
- SURGICAL CHANGES: 각 작업은 최소한의 변경(diff 최소화)으로 수행하며 불필요한 전체 리포맷 지양.
- VERIFICATION: 모든 변경 전후에 단위 테스트를 실행하여 기능 퇴행이 없음을 증명.
- SIMPLICITY: 불필요한 추상화 클래스를 새로 도입하지 않고 기존 구조를 정돈·통합.

---

### Task 1: 테스트 인프라 정상화 (`pytest.ini`)

**Files:**
- Create: `pytest.ini`
- Test: `tests/test_config.py`

**Interfaces:**
- pytest 설정: `pythonpath = .` 등록

- [ ] **Step 1: `pytest.ini` 파일 작성**

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -v
```

- [ ] **Step 2: pytest 컬렉션 및 기본 테스트 통과 확인**

Run: `.venv\Scripts\pytest --collect-only`
Expected: 11개 테스트 파일에서 35개 테스트가 에러(`ModuleNotFoundError`) 없이 수집 완료.

Run: `.venv\Scripts\pytest tests/test_config.py`
Expected: PASS (1 passed)

- [ ] **Step 3: 커밋**

```bash
git add pytest.ini
git commit -m "build: add pytest.ini with pythonpath configuration"
```

---

### Task 2: 공통 유틸리티 안전성 및 CLI 탐색 보강 (`app/utils.py`)

**Files:**
- Modify: `app/utils.py`
- Test: `tests/test_utils.py`

**Interfaces:**
- Consumes: `shutil.which`, `os.chmod`, `stat`
- Produces:
  - `run_kordoc_lint(md_path: Path) -> tuple[bool, str]` (로컬 `kordoc` 우선 탐색 및 타임아웃 15초)
  - `safe_remove_file(file_path: Path) -> bool`
  - `safe_remove_dir(dir_path: Path) -> bool`

- [ ] **Step 1: 안전 삭제 및 개선된 lint 실행 테스트 작성**

`tests/test_utils.py`에 다음 테스트 추가:

```python
def test_safe_remove_file_and_dir(tmp_path: Path):
    """안전 파일 및 디렉터리 삭제 유틸리티 동작 검증."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("sample", encoding="utf-8")
    assert test_file.exists()
    assert safe_remove_file(test_file) is True
    assert not test_file.exists()

    test_dir = tmp_path / "sub_dir"
    test_dir.mkdir()
    (test_dir / "child.txt").write_text("child", encoding="utf-8")
    assert test_dir.exists()
    assert safe_remove_dir(test_dir) is True
    assert not test_dir.exists()
```

- [ ] **Step 2: 테스트 실행하여 함수 미정의 확인**

Run: `.venv\Scripts\pytest tests/test_utils.py::test_safe_remove_file_and_dir`
Expected: FAIL (ImportError or NameError: `safe_remove_file` not found)

- [ ] **Step 3: `app/utils.py`에 함수 구현**

```python
import os
import shutil
import stat
import time

def safe_remove_file(file_path: Path, max_retries: int = 3, delay: float = 0.1) -> bool:
    """Windows 파일 잠김을 고려하여 안전하게 파일을 삭제한다."""
    if not file_path.exists():
        return True
    for attempt in range(max_retries):
        try:
            try:
                os.chmod(file_path, stat.S_IWRITE)
            except Exception:
                pass
            file_path.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception as e:
            logger.warning(f"파일 삭제 실패 ({file_path.name}): {e}")
            break
    return not file_path.exists()

def safe_remove_dir(dir_path: Path, max_retries: int = 3, delay: float = 0.1) -> bool:
    """Windows 디렉터리 잠김을 고려하여 안전하게 디렉터리를 재귀 삭제한다."""
    if not dir_path.exists():
        return True
    for attempt in range(max_retries):
        try:
            shutil.rmtree(dir_path, ignore_errors=True)
            if not dir_path.exists():
                return True
            time.sleep(delay)
        except Exception as e:
            logger.warning(f"디렉터리 삭제 실패 ({dir_path.name}): {e}")
            break
    return not dir_path.exists()
```

`run_kordoc_lint`에서 로컬 `kordoc` 우선 탐색:
```python
def run_kordoc_lint(md_path: Path) -> tuple[bool, str]:
    """kordoc CLI lint 검증을 수행하고 (통과여부, 출력메시지)를 반환한다."""
    try:
        kordoc_cmd = "kordoc" if shutil.which("kordoc") else "npx -y kordoc@^4"
        cmd = f'cmd /c {kordoc_cmd} lint "{md_path.resolve()}"'
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15
        )
        passed = (res.returncode == 0)
        output = (res.stdout or res.stderr or "").strip()
        if passed:
            logger.info(f"kordoc lint 자가 검증 통과: {md_path.name}")
        else:
            logger.warning(f"kordoc lint 검증 경고 ({md_path.name}): {output}")
        return passed, output
    except Exception as e:
        logger.warning(f"kordoc lint 실행 오류 (무시됨): {e}")
        return False, str(e)
```

- [ ] **Step 4: 테스트 재실행하여 통과 확인**

Run: `.venv\Scripts\pytest tests/test_utils.py`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/utils.py tests/test_utils.py
git commit -m "feat: add safe file/dir removal utils and optimize kordoc lint search"
```

---

### Task 3: KordocWikiAgent 단위 테스트 격리 (`app/kordoc_wiki_agent.py`)

**Files:**
- Modify: `app/kordoc_wiki_agent.py`
- Modify: `tests/test_kordoc_wiki_agent.py`

**Interfaces:**
- Produces: `execute_ingest(..., skip_lint: bool = False)`

- [ ] **Step 1: `KordocWikiAgent.execute_ingest`에 `skip_lint` 인자 추가**

```python
    def execute_ingest(
        self,
        source_path: Path,
        doc_id: str,
        file_hash: str,
        enable_ocr: bool = False,
        page_range: Optional[str] = None,
        skip_lint: bool = False
    ) -> tuple[Path, list[Path], str]:
```
호출 끝 부분:
```python
        if not skip_lint:
            self._run_kordoc_lint(target_md_path)
```

- [ ] **Step 2: `tests/test_kordoc_wiki_agent.py` 단위 테스트에서 격리 설정**

`test_kordoc_wiki_agent_rule_based_pipeline`에서:
```python
    target_md, images, title = agent.execute_ingest(
        source_path=source_file,
        doc_id="test_ingest_001",
        file_hash="hash987654321",
        skip_lint=True
    )
```

- [ ] **Step 3: 테스트 실행하여 초고속(1초 이내) 통과 검증**

Run: `.venv\Scripts\pytest tests/test_kordoc_wiki_agent.py`
Expected: PASS (전체 테스트 수 초 이내 완료)

- [ ] **Step 4: 커밋**

```bash
git add app/kordoc_wiki_agent.py tests/test_kordoc_wiki_agent.py
git commit -m "test: isolate kordoc-wiki-agent tests from external npx lint execution"
```

---

### Task 4: 레거시 모듈 코드 중복 제거 및 단순화 (`app/kordoc_engine.py`, `app/ai_refiner.py`)

**Files:**
- Modify: `app/kordoc_engine.py`
- Modify: `app/ai_refiner.py`
- Test: `tests/test_kordoc_engine.py`, `tests/test_ai_refiner.py`

**Interfaces:**
- 하위 호환성 유지: `KordocEngine.convert`, `AIRefiner.refine_text` 메서드 인터페이스 유지하되, 내부 로직은 공통 유틸 함수 및 간소화된 구조 재사용.

- [ ] **Step 1: `app/kordoc_engine.py`의 중복 로직을 `app.utils` 기반으로 정리**
- [ ] **Step 2: `tests/test_kordoc_engine.py`, `tests/test_ai_refiner.py` 실행하여 통과 확인**

Run: `.venv\Scripts\pytest tests/test_kordoc_engine.py tests/test_ai_refiner.py`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add app/kordoc_engine.py app/ai_refiner.py
git commit -m "refactor: simplify legacy kordoc_engine and ai_refiner by reusing shared utilities"
```

---

### Task 5: Windows 파일 삭제 안전성 및 보안 강화 (`app/server.py`, `clean_and_reingest.py`)

**Files:**
- Modify: `app/server.py`
- Modify: `clean_and_reingest.py`
- Test: `tests/test_server.py`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: `safe_remove_file`, `safe_remove_dir` from `app.utils`

- [ ] **Step 1: `clean_and_reingest.py`에 안전 삭제 함수 적용**
- [ ] **Step 2: `app/server.py`의 `delete_document` 및 `serve_asset` 경로 보안 강화 적용**
- [ ] **Step 3: 서버 테스트 및 E2E 테스트 실행**

Run: `.venv\Scripts\pytest tests/test_server.py tests/test_e2e.py`
Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add app/server.py clean_and_reingest.py
git commit -m "fix: apply safe file removal and enhance asset path security"
```

---

### Task 6: 전체 회귀 테스트 및 시스템 무결성 검증

**Files:**
- None (전체 검증)

- [ ] **Step 1: 전체 pytest 스위트 실행**

Run: `.venv\Scripts\pytest`
Expected: 35개 이상 전체 테스트 100% 통과 (소요 시간 5초 이내)

- [ ] **Step 2: 엔트리포인트 실행 구동 점검**

Run: `.venv\Scripts\python run.py --help` 또는 임시 import 확인
Expected: 오류 없이 정상 종료

- [ ] **Step 3: 한국어 주석 및 글로벌 규칙 정적 점검 완료**
