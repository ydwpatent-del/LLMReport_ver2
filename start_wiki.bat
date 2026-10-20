@echo off
chcp 65001 > nul
title LLM Wiki Knowledge Ingestion Dashboard
cd /d "%~dp0"

echo ============================================================
echo   LLM Wiki Knowledge Ingestion System ^& Web Dashboard
echo ============================================================
echo.
echo  [Source] "%~dp0Source"
echo  [WikiDB] "%~dp0WikiDB"
echo  [WebUI]  http://localhost:8001
echo.
echo ============================================================

REM 1. 가상환경 확인
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 파이썬 가상환경 .venv 를 생성합니다...
    uv venv .venv
    echo [안내] 필수 라이브러리를 설치합니다...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe
)

REM 2. 기본 브라우저 자동 오픈
start http://localhost:8001

REM 3. 인제스트 에이전트 및 웹 서버 실행
.venv\Scripts\python.exe run.py

pause
