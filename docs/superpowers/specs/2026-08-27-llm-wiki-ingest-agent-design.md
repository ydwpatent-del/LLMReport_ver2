# LLM Wiki 무삭제 지식 인제스트 에이전트 및 로컬/모바일 뷰어 설계 사양서 (Design Spec)

- **작성일자**: 2026-08-27
- **대상 프로젝트**: `LLMwiki_ver3`
- **목적**: `Source/` 폴더에 투입되는 다양한 형식(HWP, HWPX, PDF, DOCX, XLSX 등)의 문서를 `kordoc-wiki-ingest` 기반으로 100% 무삭제 마크다운으로 자동 변환하고, 중복 생성을 방지하며, 향후 LLM 위키의 데이터베이스가 될 `WikiDB/`에 체계적으로 적재하고, 모바일 및 PC에서 시각적으로 열람 가능한 반응형 로컬 웹 대시보드를 제공한다.

---

## 1. 글로벌 규칙 및 개발 철학 준수

1. **한국어 통일 (TARGET_LANGUAGE = Korean)**:
   - 모든 주석, docstring, 웹 UI 안내 문구, 로그 메시지는 자연스러운 한국어로 작성합니다.
   - 식별자(함수명, 변수명, 클래스명 등)는 표준 영어 표기법(PEP 8)을 준수합니다.
2. **단순성 및 최소 의존성 (Simplicity & Minimal Dependencies)**:
   - 불필요한 추상화나 무거운 프레임워크 빌드 체인을 배제하고, Python `FastAPI` + `uvicorn` + `watchdog` 최소 세트로 백엔드를 구성합니다.
   - 프론트엔드는 빌드 도구 없이 브라우저에서 직접 로드 가능한 모던 반응형 SPA(Tailwind CSS CDN, Marked.js, KaTeX, Highlight.js)로 구성하여 모바일/PC 호스팅 및 배포를 극대화합니다.
3. **무결성 및 중복 방지 (Zero-Loss & Deduplication)**:
   - 파일 내용의 SHA-256 해시값과 메타데이터를 기반으로 중복 변환을 방지합니다.
   - `kordoc-wiki-ingest`의 5대 원칙(Zero Info Loss, Visual Context Inlining, Multimodal Dual-Mode, Lint 자가검증)을 자동화 파이프라인에 반영합니다.

---

## 2. 시스템 아키텍처 및 디렉토리 구조

```
LLMwiki_ver3/
├── Source/                   # [입력] 사용자가 원본 문서를 투입하는 폴더
├── WikiDB/                   # [저장소] 향후 LLM Wiki의 Ground Truth DB
│   ├── docs/                 # 무삭제 마크다운 완본 파일 (*.md)
│   ├── assets/               # 추출된 이미지/도표 (문서별 하위 디렉토리)
│   └── manifest.json         # 변환 이력, 파일 해시, 메타데이터 인덱스
├── app/
│   ├── __init__.py
│   ├── config.py             # 기본 경로 및 서버 환경 설정
│   ├── hasher.py             # SHA-256 해시 계산 및 무결성 검증 유틸
│   ├── ingest_agent.py       # watchdog 기반 감시 및 kordoc 변환 파이프라인
│   ├── server.py             # FastAPI REST API 및 정적 파일 라우팅
│   └── static/               # 반응형 모던 웹 대시보드
│       ├── index.html        # 단일 페이지 뷰어 레이아웃
│       ├── app.js            # 마크다운 렌더링, 실시간 폴링, UI 이벤트 처리
│       └── style.css         # 모바일 터치 및 다크/라이트 모드 스타일
├── tests/
│   ├── __init__.py
│   ├── test_hasher.py        # 해시 및 중복 검사 단위 테스트
│   └── test_pipeline.py      # 인제스트 파이프라인 및 API 테스트
├── run.py                    # 서버 & 감시 에이전트 동시 실행 스크립트
└── requirements.txt          # Python 필수 라이브러리 목록
```

---

## 3. 핵심 모듈별 상세 설계

### 3.1 `WikiDB/manifest.json` 스키마
중복 변환 방지 및 문서 색인을 위해 다음과 같은 JSON 구조를 유지합니다:

```json
{
  "version": "1.0.0",
  "last_updated": "2026-08-27T15:55:00+09:00",
  "documents": {
    "<doc_id>": {
      "id": "20260827_sample_report",
      "original_filename": "sample_report.hwpx",
      "source_path": "Source/sample_report.hwpx",
      "file_hash": "a1b2c3d4...",
      "file_size": 1048576,
      "modified_time": 1756281600.0,
      "target_md_path": "WikiDB/docs/20260827_sample_report.md",
      "assets_dir": "WikiDB/assets/20260827_sample_report/",
      "status": "completed",
      "ingested_at": "2026-08-27T15:55:00+09:00",
      "title": "2026년도 신규 사업 계획서",
      "error_message": null
    }
  }
}
```

### 3.2 `app/ingest_agent.py` (인제스트 에이전트)
- **동작 원리**:
  1. `watchdog.observers.Observer`를 활용하여 `Source/` 폴더의 생성(`on_created`) 및 수정(`on_modified`) 이벤트를 감지합니다.
  2. 파일이 완전히 기록될 때까지 짧은 안정화 대기(Debounce)를 수행합니다.
  3. 지원 확장자(`.hwp`, `.hwpx`, `.pdf`, `.docx`, `.xlsx`, `.md`, `.txt`)인지 확인합니다.
  4. 파일의 SHA-256 해시를 계산하고 `manifest.json`과 비교합니다. 동일한 해시가 존재하면 처리를 건너뜁니다(`skipped`).
  5. 신규/변경된 파일이면 `kordoc` CLI 명령(`cmd /c npx -y kordoc@^4 "<filepath>" -o "<temp_md>"`)을 실행합니다.
  6. 산출된 이미지들을 `WikiDB/assets/<doc_id>/`로 정리하고 본문의 이미지 링크를 웹 접근 경로(`/api/assets/<doc_id>/<img_name>`)로 자동 변환합니다.
  7. 상단 메타데이터 블록(발행정보, 문서제목, 원본 해시)을 주입한 후 `WikiDB/docs/<doc_id>.md`에 최종 저장합니다.
  8. `manifest.json`을 원자적(Atomic)으로 갱신합니다.

### 3.3 `app/server.py` (FastAPI 백엔드)
- **제공 엔드포인트**:
  - `GET /`: 반응형 웹 대시보드 (`static/index.html`) 제공
  - `GET /api/documents`: 전체 인제스트 문서 목록 및 메타데이터 조회
  - `GET /api/documents/{doc_id}`: 특정 문서의 원본 마크다운 내용 조회
  - `GET /api/assets/{doc_id}/{filename}`: 추출된 이미지/도표 정적 파일 제공
  - `POST /api/scan`: Source 폴더 즉시 전체 재검사 및 동기화 수동 실행
  - `POST /api/upload`: 웹 화면에서 Source 폴더로 파일 직접 업로드
  - `GET /api/stats`: 전체 문서 수, 변환 현황, 저장소 용량 통계

### 3.4 `app/static/` (반응형 로컬 웹 뷰어)
- **UI 구성**:
  - **헤더**: 시스템 타이틀, 실시간 감시 상태(🟢 감시 중), [수동 스캔] 및 [파일 업로드] 버튼
  - **좌측 사이드바 (PC) / 슬라이드 메뉴 (모바일)**: 문서 목록 검색, 필터링, 최근 변환 이력
  - **중앙 본문 영역**:
    - 문서 메타데이터 카드 (문서명, 원본 형식, 변환 시각, 원본 파일 크기)
    - 마크다운 완전 렌더링 (헤딩 위계, 표, 인라인 이미지, 수식)
    - 이미지 클릭 시 고해상도 확대 모달 (라이트박스)
  - **우측 네비게이션 (PC)**: 문서 내 목차(TOC) 바로가기

---

## 4. 검증 계획 (Verification Plan)

1. **단위 테스트 (`tests/test_hasher.py`)**:
   - 동일 파일 및 변경된 파일에 대한 SHA-256 해시 무결성 검증
   - 중복 감지 및 건너뛰기 로직 테스트
2. **통합 파이프라인 테스트 (`tests/test_pipeline.py`)**:
   - `Source/` 폴더에 샘플 텍스트/마크다운 파일 투입 후 `WikiDB/` 적재 확인
   - `manifest.json` 자동 갱신 및 상태 필드 검증
   - FastAPI 엔드포인트 응답 검증
3. **E2E 및 웹 대시보드 검증**:
   - 로컬 서버 구동 (`python run.py`)
   - 웹 브라우저 접속 및 모바일 뷰포트(반응형) 렌더링 확인
   - 이미지 라이트박스 및 마크다운 표 렌더링 확인
