@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 처음 보는 질문 평가(오버피팅 확인): 28문항을 3번 물어보고 채점합니다 (약 6~8분).
if exist "..\dashboard_test\.venv\Scripts\python.exe" (
  "..\dashboard_test\.venv\Scripts\python.exe" eval\run_llm.py --set holdout --repeat 3
) else (
  python eval\run_llm.py --set holdout --repeat 3
)
pause
