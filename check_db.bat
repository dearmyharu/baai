@echo off
chcp 65001 > nul
cd /d "%~dp0"
if exist "..\dashboard_test\.venv\Scripts\python.exe" (
  "..\dashboard_test\.venv\Scripts\python.exe" check_db.py
) else (
  python check_db.py
)
pause
