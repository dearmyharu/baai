@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo AI 분석가 평가: 평가셋 36문항을 Gemini에게 물어보고 채점합니다 (약 5분).
if exist "..\dashboard_test\.venv\Scripts\python.exe" (
  "..\dashboard_test\.venv\Scripts\python.exe" eval\run_llm.py
) else (
  python eval\run_llm.py
)
pause
