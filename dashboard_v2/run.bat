@echo off
chcp 65001 > nul
cd /d "%~dp0"
if exist "..\dashboard_test\.venv\Scripts\python.exe" (
  "..\dashboard_test\.venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
pause
