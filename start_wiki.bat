@echo off
chcp 65001 > nul
title LLM Wiki 지식 인제스트 대시보드

cd /d "%~dp0"

echo ============================================================
echo   🚀 LLM Wiki 지식 인제스트 시스템 및 웹 대시보드 실행 중...
echo ============================================================
echo.
echo  📂 원본 문서 투입: "%~dp0Source"
echo  📚 위키 DB 저장소: "%~dp0WikiDB"
echo  🌐 웹 대시보드:   http://localhost:8000
echo.
echo ============================================================

:: 1. 가상환경 확인
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 파이썬 가상환경(.venv)을 생성합니다...
    uv venv .venv
    echo [안내] 필수 라이브러리를 설치합니다...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe
)

:: 2. 기본 브라우저에서 대시보드 자동 열기 (백그라운드에서 1.5초 후 실행)
start "" cmd /c "timeout /t 2 /nobreak > nul && start http://localhost:8000"

:: 3. 인제스트 에이전트 및 웹 서버 실행
.venv\Scripts\python.exe run.py

pause
