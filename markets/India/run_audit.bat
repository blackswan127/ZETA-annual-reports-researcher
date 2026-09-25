@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python -m india_ar_bulk --output output --start-year 2017 --end-year 2025 audit
pause
