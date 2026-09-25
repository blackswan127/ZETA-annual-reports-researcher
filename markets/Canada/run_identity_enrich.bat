@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Conservative GLEIF enrichment. Ambiguous names are NOT accepted.
canada-zeta-ar --work work identity-enrich
canada-zeta-ar --work work audit
pause
