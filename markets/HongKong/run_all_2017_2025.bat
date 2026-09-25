@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python run.py all --start-year 2017 --end-year 2025 --workers 16 --download-rps 8
pause
