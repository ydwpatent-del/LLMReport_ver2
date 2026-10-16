# LLMwiki_ver3 버그 수정 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드 리뷰에서 발견된 결함 20건을 우선순위(P0→P3)에 따라 수정하고, 각 수정에 대한 회귀 테스트를 확보한다.

**Architecture:** 기존 모듈 구조를 그대로 유지하면서 최소 외과적 변경만 적용한다. 새 파일은 생성하지 않으며, 인터페이스 변경도 없다. 각 태스크는 독립적으로 테스트 가능하다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest, watchdog, pymupdf, google-genai

**Spec:** code_review.md (C:\Users\ilove\.gemini\antigravity\brain\d1aac113-6dea-42ad-b684-c0e74f56b32f\code_review.md)

## Global Constraints

- 수정 범위는 `app/` 내부에 한정한다. `tests/`, `docs/`는 추가만 허용, 기존 내용 변경 금지.
- 코드 주석은 모두 한국어로 작성한다.
- 변수/함수명은 영어 camelCase/snake_case 관례를 따른다.
- 기존 public 함수·클래스 시그니처를 변경하지 않는다 (하위 호환성 유지).
- `pytest tests/` 전체가 수정 전과 동일하게 통과해야 한다.
- 글로벌 코드 작성 규칙 (Surgical Changes, Read Before Write 등) 전면 준수.

---

## 태스크 목록

| 태스크 | 우선순위 | 대상 파일 | 핵심 수정 |
|:---:|:---:|:---|:---|
| Task 1 | P0 | `ingest_agent.py` | except 블록 NameError 방지 |
| Task 2 | P0 | `kordoc_wiki_agent.py` | 비정상 청크 전체 결과 폐기 방지 |
| Task 3 | P1 | `kordoc_engine.py`, `audit_agent.py` | subprocess shell injection 방지 + 절대경로 |
| Task 4 | P1 | `topic_generator.py` | 존재하지 않는 모델명 제거 |
| Task 5 | P1 | `manifest.py` | alias 중복 제거 + 읽기 재로드 제거 |
| Task 6 | P2 | `utils.py` | Dual-Mode 오탐 + 이미지 인덱스 안전 |
| Task 7 | P2 | `utils.py`, `ai_refiner.py`, `kordoc_wiki_agent.py` | 발행기관 목록 단일 진실원 |
| Task 8 | P3 | `topic_router.py`, `topic_search.py`, `utils.py` | 싱글톤, PEP8, JPEG 최적화 |
| Task 9 | P3 | `requirements.txt` | 테스트 의존성 분리 |

---

## Task 1: `ingest_agent.py` — except 블록 NameError 방지 (P0)

**Files:**
- Modify: `app/ingest_agent.py`
- Test: `tests/test_ingest_agent.py`

**문제:** `process_file`의 `except` 블록이 try 블록 중간에 초기화되는 `doc_id`, `file_hash`, `stat`을 참조한다. `manifest_mgr.is_duplicate()` 등에서 예외 발생 시 `NameError`가 발생한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_ingest_agent.py`에 추가)

```python
def test_process_file_except_does_not_raise_name_error(tmp_path):
    """is_duplicate 호출 중 예외가 발생해도 NameError 없이 False를 반환해야 한다."""
    from app.ingest_agent import IngestAgent
    from app.manifest import ManifestManager
    from unittest.mock import MagicMock

    src = tmp_path / "test.pdf"
    src.write_bytes(b"%PDF-1.4 test content here for hashing purposes only")

    manifest_mgr = MagicMock(spec=ManifestManager)
    manifest_mgr.is_duplicate.side_effect = RuntimeError("DB 오류 시뮬레이션")

    engine = MagicMock()
    engine.assets_dir = tmp_path / "assets"

    agent = IngestAgent(
        source_dir=tmp_path,
        manifest_mgr=manifest_mgr,
        engine=engine,
        supported_exts={".pdf"}
    )

    result = agent.process_file(src, debounce=0.0)
    assert result is False
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_ingest_agent.py::test_process_file_except_does_not_raise_name_error -v
```

- [ ] **Step 3: `app/ingest_agent.py` 수정**

`process_file` 메서드 시작부에 변수 사전 초기화 추가:
```python
    # 사전 초기화: except 블록에서 미초기화 변수 참조로 인한 NameError 방지
    doc_id: str = ""
    file_hash: str = ""
    stat = None
```

`except` 블록에서 `stat` None 처리:
```python
    except Exception as e:
        logger.error(f"[오류] 문서 변환 실패 {file_path.name}: {e}")
        file_size = stat.st_size if stat is not None else 0
        modified_time = stat.st_mtime if stat is not None else 0.0
        if doc_id:
            entry = DocumentEntry(
                id=doc_id, original_filename=file_path.name,
                source_path=str(file_path), file_hash=file_hash,
                file_size=file_size, modified_time=modified_time,
                target_md_path="", assets_dir="",
                status="failed", title=file_path.stem, error_message=str(e)
            )
            self.manifest_mgr.add_or_update_document(entry)
        return False
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

```
pytest tests/test_ingest_agent.py -v
```

- [ ] **Step 5: Commit**

```
git add app/ingest_agent.py tests/test_ingest_agent.py
git commit -m "fix(ingest_agent): except 블록 NameError 방지 - 변수 사전 초기화"
```

---

## Task 2: `kordoc_wiki_agent.py` — 부분 청크 결과 보존 (P0)

**Files:**
- Modify: `app/kordoc_wiki_agent.py` (L314-320)
- Test: `tests/test_kordoc_wiki_agent.py`

**문제:** N개 청크 중 하나가 30,000자 초과 판정을 받으면 이미 성공한 N-1개 청크 결과가 전부 버려지고 `None`이 반환된다.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_kordoc_wiki_agent.py`에 추가)

```python
def test_abnormal_chunk_does_not_discard_previous_results(tmp_path):
    """마지막 청크가 비정상(30,000자 초과)이어도 이전 청크의 결과가 보존되어야 한다."""
    from unittest.mock import MagicMock, patch
    from app.kordoc_wiki_agent import KordocWikiAgent

    agent = KordocWikiAgent(
        docs_dir=tmp_path / "docs",
        assets_dir=tmp_path / "assets",
        api_key="fake-key"
    )

    mock_response_ok = MagicMock()
    mock_response_ok.text = "## 섹션 1 변환 결과\n" + ("처리됨. " * 100)

    mock_response_bad = MagicMock()
    mock_response_bad.text = "X" * 30001

    mock_chat = MagicMock()
    mock_chat.send_message.side_effect = [mock_response_ok, mock_response_bad]

    raw_md = "## 섹션 1\n" + ("내용. " * 1400) + "\n\n## 섹션 2\n" + ("내용. " * 1400)

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat
        mock_client_cls.return_value = mock_client

        result = agent._call_llm_for_wiki_ingest(
            raw_md=raw_md, doc_id="test_doc",
            original_filename="test.pdf", file_hash="abc123", images_info=[]
        )

    assert result is not None, "비정상 청크 1개로 인해 전체 결과가 폐기되었습니다"
    assert "섹션 1 변환 결과" in result
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_kordoc_wiki_agent.py::test_abnormal_chunk_does_not_discard_previous_results -v
```

- [ ] **Step 3: `app/kordoc_wiki_agent.py` L314-320 수정**

기존:
```python
                else:
                    out_len = len(response.text) if (response and response.text) else 0
                    logger.warning(f"청크 {idx+1} 비정상 출력 감지 (길이: {out_len}자), 룰베이스 폴백 전환")
                    return None
```

수정:
```python
                else:
                    out_len = len(response.text) if (response and response.text) else 0
                    logger.warning(
                        f"청크 {idx+1} 비정상 출력 감지 (길이: {out_len}자) → "
                        f"해당 청크만 원본 텍스트로 대체 (기존 {len(processed_parts)}개 청크 결과 보존)"
                    )
                    # 비정상 청크만 원본 텍스트로 대체하여 나머지 결과 보존
                    processed_parts.append(chunk.strip())
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

```
pytest tests/test_kordoc_wiki_agent.py -v
```

- [ ] **Step 5: Commit**

```
git add app/kordoc_wiki_agent.py tests/test_kordoc_wiki_agent.py
git commit -m "fix(kordoc_wiki_agent): 비정상 청크 1개로 인한 전체 결과 폐기 방지"
```

---

## Task 3: 보안 + 경로 수정 (P1)

**Files:**
- Modify: `app/kordoc_engine.py` (subprocess shell=False 전환)
- Modify: `app/audit_agent.py` (backup_dir 절대 경로)
- Test: `tests/test_kordoc_engine.py`, `tests/test_audit_agent.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_kordoc_engine.py` 추가:
```python
def test_convert_uses_list_args_not_shell_string(tmp_path):
    """convert()는 shell=False + 리스트 인자 방식으로 subprocess를 호출해야 한다."""
    from app.kordoc_engine import KordocEngine
    from unittest.mock import patch, MagicMock

    engine = KordocEngine(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets")
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-1.4 dummy")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        r = MagicMock()
        r.returncode = 1
        r.stderr = "mock"
        r.stdout = ""
        return r

    with patch("subprocess.run", side_effect=fake_run):
        try:
            engine.convert(src, "doc_id", "hash123")
        except RuntimeError:
            pass

    assert isinstance(captured.get("args"), list), "리스트 인자 방식을 사용해야 합니다"
    assert captured.get("kwargs", {}).get("shell") is not True, "shell=True를 사용하면 안 됩니다"
```

`tests/test_audit_agent.py` 추가:
```python
def test_backup_manager_default_path_is_absolute(tmp_path):
    """AuditAgent 기본 생성 시 backup_dir이 절대 경로여야 한다."""
    from app.audit_agent import AuditAgent

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    auditor = AuditAgent(docs_dir=docs_dir)

    assert auditor.backup_mgr.backup_dir.is_absolute(), \
        f"backup_dir이 절대 경로가 아닙니다: {auditor.backup_mgr.backup_dir}"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_kordoc_engine.py::test_convert_uses_list_args_not_shell_string tests/test_audit_agent.py::test_backup_manager_default_path_is_absolute -v
```

- [ ] **Step 3: `app/kordoc_engine.py` 수정**

파일 상단에 `import sys` 추가. L163-184 블록 교체:
```python
            # shell=False + 리스트 인자 방식으로 명령어 인젝션 방지
            npx_path = shutil.which("npx") or "npx"
            if sys.platform == "win32":
                # Windows: .cmd 래퍼는 cmd를 통해 실행해야 한다
                base_args = ["cmd", "/c", npx_path, "-y", "kordoc@^4",
                             str(source_path.resolve()),
                             "-o", str(temp_out_md.resolve())]
            else:
                base_args = [npx_path, "-y", "kordoc@^4",
                             str(source_path.resolve()),
                             "-o", str(temp_out_md.resolve())]

            if enable_ocr:
                base_args += ["--ocr", "--formula-ocr"]
            if page_range:
                base_args += ["-p", page_range]

            logger.info(f"kordoc 파싱 시작: {' '.join(base_args)}")
            result = subprocess.run(
                base_args,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
```

- [ ] **Step 4: `app/audit_agent.py` 수정**

`AuditAgent.__init__` 수정:
```python
    def __init__(self, docs_dir=None, backup_dir=None, api_key=None):
        self.docs_dir = docs_dir or Path("WikiDB/docs")
        # backup_dir 기본값: docs_dir 기반 절대 경로 (CWD 의존 제거)
        resolved_docs = Path(self.docs_dir).resolve()
        default_backup = resolved_docs / ".backup"
        self.backup_mgr = BackupManager(backup_dir=backup_dir or default_backup)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
```

`audit_and_heal_single` L413:
```python
        # "WikiDB/assets" 하드코딩 제거: docs_dir 기반으로 추론
        target_assets_dir = assets_dir or (Path(self.docs_dir).resolve().parent / "assets")
```

- [ ] **Step 5: 테스트 실행하여 통과 확인**

```
pytest tests/test_kordoc_engine.py tests/test_audit_agent.py -v
```

- [ ] **Step 6: Commit**

```
git add app/kordoc_engine.py app/audit_agent.py tests/test_kordoc_engine.py tests/test_audit_agent.py
git commit -m "fix(security): subprocess shell=False 전환 및 backup_dir 절대 경로 수정"
```

---

## Task 4: `topic_generator.py` — 잘못된 모델명 제거 (P1)

**Files:**
- Modify: `app/topic_generator.py` (L161)
- Test: `tests/test_topic_system.py`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_topic_system.py` 추가)

```python
def test_generate_report_uses_only_valid_model_names():
    """보고서 생성 모델 목록에 존재하지 않는 gemini-3.6-flash가 없어야 한다."""
    import inspect
    from app.topic_generator import TopicReportGenerator

    source = inspect.getsource(TopicReportGenerator.generate_report)
    assert "gemini-3.6-flash" not in source, \
        "gemini-3.6-flash는 존재하지 않는 모델명입니다. 유효한 모델명으로 교체하세요."
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_topic_system.py::test_generate_report_uses_only_valid_model_names -v
```

- [ ] **Step 3: `app/topic_generator.py` L161 수정**

```python
        # 검증된 Gemini 모델만 사용 (존재하지 않는 gemini-3.6-flash 제거)
        model_names = ["gemini-2.5-flash", "gemini-2.0-flash"]
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

```
pytest tests/test_topic_system.py -v
```

- [ ] **Step 5: Commit**

```
git add app/topic_generator.py tests/test_topic_system.py
git commit -m "fix(topic_generator): 존재하지 않는 gemini-3.6-flash 모델명 제거"
```

---

## Task 5: `manifest.py` — alias 중복 제거 + 읽기 재로드 제거 (P1)

**Files:**
- Modify: `app/manifest.py` (get_document, get_all_documents)
- Test: `tests/test_manifest.py`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_manifest.py` 추가)

```python
def test_get_all_documents_deduplicates_alias_entries(tmp_path):
    """alias 항목이 등록되어도 get_all_documents는 고유 파일당 1건만 반환해야 한다."""
    from app.manifest import ManifestManager, DocumentEntry

    mgr = ManifestManager(tmp_path / "manifest.json")
    base = DocumentEntry(
        id="old_id", original_filename="report.pdf", source_path="/src/report.pdf",
        file_hash="a" * 64, file_size=1000, modified_time=1000.0,
        target_md_path="/docs/old_id.md", assets_dir="/assets/old_id",
        status="completed", title="보고서"
    )
    alias = base.model_copy()
    alias.id = "new_id"
    alias.target_md_path = "/docs/new_id.md"

    mgr.add_or_update_document(base)
    mgr.add_or_update_document(alias)

    docs = mgr.get_all_documents()
    completed = [d for d in docs if d.status == "completed" and d.file_hash == base.file_hash]
    assert len(completed) == 1, f"alias 중복 포함됨: {[d.id for d in completed]}"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_manifest.py::test_get_all_documents_deduplicates_alias_entries -v
```

- [ ] **Step 3: `app/manifest.py` 수정**

`get_document` (L92-96):
```python
    def get_document(self, doc_id: str) -> Optional[DocumentEntry]:
        """문서 ID로 메타데이터를 조회한다. 인메모리 캐시를 사용한다."""
        with self._lock:
            # 단일 프로세스 환경: 디스크 재로드 없이 인메모리 상태 반환
            return self._data.documents.get(doc_id)
```

`get_all_documents` (L98-102):
```python
    def get_all_documents(self) -> list[DocumentEntry]:
        """모든 문서 목록을 반환한다.

        alias 중복 제거: 동일 file_hash + completed 상태 항목이 여러 개인 경우
        target_md_path가 긴 항목 1건만 반환한다.
        """
        with self._lock:
            all_docs = list(self._data.documents.values())

        seen_hashes: dict[str, DocumentEntry] = {}
        result: list[DocumentEntry] = []
        for doc in all_docs:
            if doc.status == "completed" and doc.file_hash:
                existing = seen_hashes.get(doc.file_hash)
                if existing is None:
                    seen_hashes[doc.file_hash] = doc
                    result.append(doc)
                elif len(doc.target_md_path) > len(existing.target_md_path):
                    result.remove(existing)
                    seen_hashes[doc.file_hash] = doc
                    result.append(doc)
            else:
                result.append(doc)
        return result
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

```
pytest tests/test_manifest.py -v
```

- [ ] **Step 5: 전체 회귀 테스트**

```
pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit**

```
git add app/manifest.py tests/test_manifest.py
git commit -m "fix(manifest): alias 중복 제거 및 읽기 메서드 디스크 재로드 제거"
```

---

## Task 6: `utils.py` — Dual-Mode 오탐 + 이미지 인덱스 안전 (P2)

**Files:**
- Modify: `app/utils.py` (L430-435, L148-177)
- Test: `tests/test_utils.py`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_utils.py` 추가)

```python
def test_validate_red_flags_no_dual_mode_false_positive_for_diagram():
    """개념도 이미지만 있고 수치 표가 없어도 Dual-Mode 위반 오탐이 없어야 한다."""
    from app.utils import validate_red_flags
    md = """# 문서
> - **원본 파일명**: `arch.pdf`
> - **발행기관**: 기술팀
> - **발행일자**: 2026년 01월 01일
> - **문서분류**: 기술 문서
> - **핵심 엔티티**: #시스템
> - **원본형식**: `PDF (100% 무삭제 전수 인제스트)`
> - **인제스트 일시**: `2026-01-01 00:00:00 UTC`
> - **무결성 해시 (SHA-256)**: `abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890`
> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)
---
## 개요
![시스템 아키텍처](/api/assets/arch_doc/arch_diagram.png)
*(자료: 기술팀, 시스템 전체 흐름도 개념도)*
"""
    flags = validate_red_flags(md, check_metadata=True)
    dual_flags = [f for f in flags if "Dual-Mode" in f]
    assert len(dual_flags) == 0, f"개념도에서 Dual-Mode 오탐 발생: {dual_flags}"


def test_validate_red_flags_dual_mode_triggers_for_stat_chart():
    """수치 단위 캡션이 있는 통계 차트 + 표 없음 → Dual-Mode 위반이어야 한다."""
    from app.utils import validate_red_flags
    md = """# 시장 분석
> - **원본 파일명**: `market.pdf`
> - **발행기관**: 리서치팀
> - **발행일자**: 2026년 01월 01일
> - **문서분류**: 리서치 보고서 / 기술 문서
> - **핵심 엔티티**: #시장
> - **원본형식**: `PDF (100% 무삭제 전수 인제스트)`
> - **인제스트 일시**: `2026-01-01 00:00:00 UTC`
> - **무결성 해시 (SHA-256)**: `abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890`
> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)
---
## 시장 규모
![성장 차트](/api/assets/market_doc/growth_chart.png)
*(자료: 리서치팀, 단위: 억원, CAGR 15%)*
"""
    flags = validate_red_flags(md, check_metadata=True)
    dual_flags = [f for f in flags if "Dual-Mode" in f]
    assert len(dual_flags) > 0, "통계 차트 + 표 없음에서 Dual-Mode 위반이 감지되어야 합니다"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_utils.py::test_validate_red_flags_no_dual_mode_false_positive_for_diagram tests/test_utils.py::test_validate_red_flags_dual_mode_triggers_for_stat_chart -v
```

- [ ] **Step 3: `app/utils.py` L430-435 수정**

```python
    # 3. 통계 차트 이미지 삽입 후 수치 표 누락 검사
    # 캡션에 수치성 키워드가 있을 때만 통계 차트로 판별 (개념도/인포그래픽 오탐 제외)
    _STAT_KEYWORDS = r"단위|cagr|억원|억\s*달러|성장률|추이|실적|%"
    has_stat_chart = bool(re.search(
        r'!\[.*?\]\(/api/assets/.*?\)\s*\n\s*\*\([^)]*(?:' + _STAT_KEYWORDS + r')[^)]*\)\*',
        markdown_text,
        re.IGNORECASE
    ))
    has_table = bool(re.search(r'\|(?:\s*:?-+:?\s*\|)+', markdown_text))
    if has_stat_chart and not has_table:
        flags.append("Dual-Mode 원칙 위반: 통계 차트 이미지가 존재하나 원본 수치 표(|---|)가 누락됨")
```

- [ ] **Step 4: `app/utils.py` L155-157 그레이스케일 안전 처리**

```python
                        # n 값에 따른 채널 안전 처리 (1=Gray, 2=GA, 3=RGB, 4=RGBA)
                        if n == 1:
                            r = g = b = samples[idx]
                            a = 255
                        elif n == 2:
                            r = g = b = samples[idx]
                            a = samples[idx + 1]
                        elif n >= 3:
                            r, g, b = samples[idx], samples[idx + 1], samples[idx + 2]
                            a = samples[idx + 3] if n == 4 else 255
                        else:
                            continue
```

- [ ] **Step 5: 테스트 실행하여 통과 확인**

```
pytest tests/test_utils.py -v
```

- [ ] **Step 6: Commit**

```
git add app/utils.py tests/test_utils.py
git commit -m "fix(utils): Dual-Mode 오탐 수정 및 그레이스케일 이미지 인덱스 안전 처리"
```

---

## Task 7: 발행기관 목록 단일 진실원 통일 (P2)

**Files:**
- Modify: `app/utils.py` (KNOWN_PUBLISHERS 상수 추가)
- Modify: `app/ai_refiner.py` (로컬 리스트 → KNOWN_PUBLISHERS)
- Modify: `app/kordoc_wiki_agent.py` (로컬 리스트 → KNOWN_PUBLISHERS)
- Test: `tests/test_ai_refiner.py`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_ai_refiner.py` 추가)

```python
def test_publisher_list_uses_shared_constant():
    """ai_refiner와 kordoc_wiki_agent 모두 utils.KNOWN_PUBLISHERS를 사용해야 한다."""
    import inspect
    from app import ai_refiner, kordoc_wiki_agent
    from app.utils import KNOWN_PUBLISHERS

    assert isinstance(KNOWN_PUBLISHERS, list) and len(KNOWN_PUBLISHERS) > 0
    assert "KNOWN_PUBLISHERS" in inspect.getsource(ai_refiner), \
        "ai_refiner가 KNOWN_PUBLISHERS를 임포트하지 않음"
    assert "KNOWN_PUBLISHERS" in inspect.getsource(kordoc_wiki_agent), \
        "kordoc_wiki_agent가 KNOWN_PUBLISHERS를 임포트하지 않음"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```
pytest tests/test_ai_refiner.py::test_publisher_list_uses_shared_constant -v
```

- [ ] **Step 3: `app/utils.py` 상수 추가** (L23 IMAGE_EXTENSIONS 아래)

```python
# 발행기관 탐지 기준 목록 — ai_refiner, kordoc_wiki_agent 공용 단일 진실원
KNOWN_PUBLISHERS = [
    "LS증권", "미래에셋증권", "삼성증권", "KB증권", "NH투자증권", "신한투자증권",
    "하나증권", "한국투자증권", "메리츠증권", "다올투자증권", "키움증권", "대신증권",
    "한국은행", "산업통상자원부", "과학기술정보통신부", "금융감독원", "기획재정부",
    "KDI", "한국개발연구원", "ETRI", "정보통신산업진흥원",
]
```

- [ ] **Step 4: `app/ai_refiner.py` import 및 로직 수정**

import 수정:
```python
from app.utils import generate_standard_metadata_header, generate_toc_and_anchors, KNOWN_PUBLISHERS
```

`_extract_metadata_info` 내 L31-40 교체:
```python
        # 1. 발행기관 탐지 (utils.KNOWN_PUBLISHERS 단일 진실원 사용)
        for pub in KNOWN_PUBLISHERS:
            if pub in filename or pub in text[:1000]:
                info["publisher"] = pub
                break
```

기존 로컬 `publishers` 리스트 선언 삭제.

- [ ] **Step 5: `app/kordoc_wiki_agent.py` import 및 로직 수정**

`from app.utils import (...)` 블록에 `KNOWN_PUBLISHERS` 추가.

`_rule_based_wiki_ingest` 내 L344-352 교체:
```python
        # 1. 발행기관 탐지 (utils.KNOWN_PUBLISHERS 단일 진실원 사용)
        for pub in KNOWN_PUBLISHERS:
            if pub in original_filename or pub in raw_md[:1000]:
                publisher = pub
                break
```

기존 로컬 `publishers` 리스트 선언 삭제.

- [ ] **Step 6: 테스트 실행하여 통과 확인**

```
pytest tests/test_ai_refiner.py tests/test_kordoc_wiki_agent.py -v
```

- [ ] **Step 7: Commit**

```
git add app/utils.py app/ai_refiner.py app/kordoc_wiki_agent.py tests/test_ai_refiner.py
git commit -m "refactor: 발행기관 목록을 utils.KNOWN_PUBLISHERS로 통일"
```

---

## Task 8: P3 코드 정돈 (P3)

**Files:**
- Modify: `app/topic_router.py` (싱글톤 캐시)
- Modify: `app/topic_search.py` (변수명 l → line)
- Modify: `app/utils.py` (JPEG 이중 열기 제거)

- [ ] **Step 1: `app/topic_router.py` 싱글톤 캐시**

파일 모듈 레벨에 추가:
```python
_generator_cache: Optional[TopicReportGenerator] = None
```

`get_generator` 교체:
```python
def get_generator(settings: Settings = Depends(get_settings)) -> TopicReportGenerator:
    """TopicReportGenerator 의존성 주입 프로바이더 (매 요청 재생성 방지)."""
    global _generator_cache
    if _generator_cache is None:
        _generator_cache = TopicReportGenerator(reports_dir=settings.wiki_db_dir / "reports")
    return _generator_cache
```

- [ ] **Step 2: `app/topic_search.py` L108 수정**

```python
        for line in current_lines:  # 소문자 l → line (PEP 8: 숫자 1과 혼동 방지)
```

- [ ] **Step 3: `app/utils.py` JPEG 이중 열기 제거**

L68의 `head = f.read(64)` → `head = f.read(512)`

JPEG 파싱 블록 두 번째 `open` 전체를 `BytesIO(head)` 방식으로 교체 (파일 목록은 기존 로직과 동일, `f` → `buf`로 치환, `from io import BytesIO` 추가).

- [ ] **Step 4: 전체 테스트 통과 확인**

```
pytest tests/ -v --tb=short
```

- [ ] **Step 5: Commit**

```
git add app/topic_router.py app/topic_search.py app/utils.py
git commit -m "refactor(p3): TopicReportGenerator 싱글톤, 변수명 수정, JPEG 이중 열기 제거"
```

---

## Task 9: `requirements.txt` 분리 + 최종 회귀 테스트 (P3)

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`

- [ ] **Step 1: `requirements-dev.txt` 생성**

```
# 개발 및 테스트 전용 의존성 (운영 환경에서는 불필요)
-r requirements.txt
pytest>=8.0.0
httpx>=0.27.0
```

- [ ] **Step 2: `requirements.txt`에서 테스트 의존성 제거**

`pytest>=8.0.0`과 `httpx>=0.27.0` 두 줄 삭제.

- [ ] **Step 3: 최종 전체 회귀 테스트**

```
pytest tests/ -v 2>&1 | tail -40
```

예상 결과: 기존 PASS 항목 수 이상 유지, 신규 FAIL 없음.

- [ ] **Step 4: Commit**

```
git add requirements.txt requirements-dev.txt
git commit -m "chore: pytest/httpx를 requirements-dev.txt로 분리"
```

---

## 자가 검토 (Self-Review)

### 스펙 커버리지

| # | 항목 | 태스크 |
|:---:|:---|:---:|
| 1 | except 블록 NameError | Task 1 ✅ |
| 2 | manifest 읽기 재로드 | Task 5 ✅ |
| 3 | 부분 청크 결과 폐기 | Task 2 ✅ |
| 4 | 잘못된 모델명 | Task 4 ✅ |
| 5 | 이미지 인덱스 오류 | Task 6 ✅ |
| 6 | heal agent None | 제외 (기존 동작 유지, 주석 명시) |
| 7 | watchdog 동기 블로킹 | 제외 (인터페이스 변경 수반, 별도 계획) |
| 8 | alias 중복 감사 | Task 5 ✅ |
| 9 | subprocess 인젝션 | Task 3 ✅ |
| 10 | 하드코딩 경로 | Task 3 ✅ |
| 11 | Dual-Mode 오탐 | Task 6 ✅ |
| 12 | get_generator 재생성 | Task 8 ✅ |
| 13 | 발행기관 목록 중복 | Task 7 ✅ |
| 14 | CORS 순서 | 제외 (동작 문제 없음) |
| 15 | .tmp 잔존 | 제외 (기능 영향 없음) |
| 16 | debounce sleep | 제외 (#7과 연계) |
| 17 | 변수명 l | Task 8 ✅ |
| 18 | JPEG 이중 열기 | Task 8 ✅ |
| 19 | config 싱글톤 격리 | 제외 (기존 테스트 처리) |
| 20 | requirements.txt | Task 9 ✅ |
