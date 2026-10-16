# LLM Wiki 지식 인제스트 에이전트 및 로컬/모바일 뷰어

한국 관공서 공문서(HWP/HWPX), 금융/기업 보고서(PDF), 오피스 문서(DOCX/XLSX)를 `kordoc` 도구를 활용하여 **100% 무삭제·무축약 완본 마크다운(Full-Text Markdown)**으로 자동 변환하고, 중복 생성을 방지하며 `WikiDB/`에 축적하고, 모바일 및 PC에서 시각적으로 열람할 수 있는 웹 대시보드를 제공합니다.

---

## 🌟 주요 기능

1. **자동 파일 감시 및 즉시 인제스트 (Real-time Watcher)**:
   - `Source/` 폴더에 파일(HWP, HWPX, PDF, DOCX, XLSX, MD, TXT 등)이 투입되거나 수정되면 자동으로 감지하여 변환합니다.
2. **SHA-256 기반 중복 변환 방지**:
   - 파일의 내용 해시를 `WikiDB/manifest.json`에 기록하여 동일한 파일의 중복 생성을 원천 차단합니다.
3. **100% 무삭제 및 시각 자료 인라인 보존 (`kordoc-wiki-ingest`)**:
   - 문서 내 문장, 불릿, 통계 수치, 재무제표 표를 단 하나도 생략하지 않고 전수 복원합니다.
   - 도표/차트 이미지를 `WikiDB/assets/<문서ID>/`로 추출하고 본문 해당 위치에 자동 인라인 연결합니다.
4. **모바일 & PC 반응형 로컬 웹 뷰어**:
   - 스마트폰/태블릿 및 데스크톱 브라우저에서 편리하게 접속하여 완본 마크다운, 표, 수식(KaTeX), 코드 하이라이트를 열람할 수 있습니다.
   - 인라인 이미지 클릭 시 고해상도 라이트박스 줌을 지원합니다.
   - 상단에서 원클릭 수동 스캔 및 웹 직접 파일 투입(업로드)을 지원합니다.
5. **LLM Wiki Ground Truth DB 구축**:
   - 변환된 마크다운은 상단 표준 메타데이터 헤더와 함께 `WikiDB/docs/`에 영구 보존되어 향후 구축될 RAG 및 지식 그래프(Knowledge Graph)의 데이터베이스로 즉시 활용됩니다.

---

## 📁 디렉토리 구조

```
LLMwiki_ver3/
├── Source/                   # 📥 원본 문서 투입 폴더 (HWP, HWPX, PDF 등)
├── WikiDB/                   # 📚 위키 데이터베이스 (향후 LLM 위키의 원천)
│   ├── docs/                 # 100% 무삭제 마크다운 파일 (*.md)
│   ├── assets/               # 추출된 이미지/도표 (문서별 하위 폴더)
│   └── manifest.json         # 해시 인덱스 및 변환 메타데이터
├── app/
│   ├── config.py             # 시스템 전역 설정
│   ├── hasher.py             # SHA-256 해시 계산 유틸
│   ├── manifest.py           # 매니페스트 관리자
│   ├── kordoc_engine.py      # kordoc 파싱 엔진
│   ├── ingest_agent.py       # watchdog 실시간 감시 에이전트
│   ├── server.py             # FastAPI REST API 및 웹 서버
│   └── static/               # 모바일/PC 반응형 웹 UI
├── tests/                    # 단위 및 E2E 테스트 스위트
└── run.py                    # 단일 통합 실행 엔트리포인트
```

---

## 🚀 빠른 시작 가이드

### 1. 가상환경 활성화 및 패키지 설치
```bash
# 가상환경 활성화 (Windows PowerShell)
.venv\Scripts\activate

# 패키지 설치 (이미 설치되어 있는 경우 생략 가능)
uv pip install -r requirements.txt
```

### 2. 시스템 실행 (에이전트 + 웹 대시보드)
```bash
python run.py
```

### 3. 웹 대시보드 접속
- **로컬 PC 접속**: 브라우저에서 [http://localhost:8000](http://localhost:8000) 접속
- **동일 Wi-Fi 내 스마트폰/태블릿 접속**: 브라우저에서 `http://<PC의 로컬IP>:8000` 접속

### 4. 문서 투입 방법
1. **탐색기에서 직접 투입**: `Source/` 폴더에 `.hwpx`, `.pdf`, `.docx`, `.xlsx` 등의 파일을 복사해 넣습니다.
2. **웹 대시보드에서 투입**: 화면 상단 우측의 **[문서 투입]** 버튼을 눌러 파일을 선택합니다.
