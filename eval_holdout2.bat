@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 홀드아웃 2차(표현·조건 조합·모르는 것 인정): 30문항을 3번 물어보고 채점합니다 (약 7~9분).
if exist "..\dashboard_test\.venv\Scripts\python.exe" (
  "..\dashboard_test\.venv\Scripts\python.exe" eval\run_llm.py --set holdout2 --repeat 3
) else (
  python eval\run_llm.py --set holdout2 --repeat 3
)
pause
