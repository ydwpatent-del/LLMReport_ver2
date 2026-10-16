@echo off
chcp 65001 > nul
title LLM Wiki 지식 인제스트 대시보드

cd /d "%~dp0"

echo ============================================================
echo   🚀 LLM Wiki 지식 인제스트 시스템 및 웹 대시보드
echo ============================================================
echo.
echo  📂 원본 문서 투입: "%~dp0Source"
echo  📚 위키 DB 저장소: "%~dp0WikiDB"
echo  🌐 웹 대시보드:   http://localhost:8001
echo.
echo ============================================================

:: 1. 가상환경 확인
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 파이썬 가상환경(.venv)을 생성합니다...
    uv venv .venv
    echo [안내] 필수 라이브러리를 설치합니다...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe
)

:: 2. 기본 브라우저 자동 오픈
start http://localhost:8001

:: 3. 인제스트 에이전트 및 웹 서버 실행
.venv\Scripts\python.exe run.py

pause
