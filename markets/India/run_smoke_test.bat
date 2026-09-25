@echo off
cd /d "%~dp0"
call _ack_terms.bat
if errorlevel 1 exit /b 1
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python -m india_ar_bulk --output smoke_output smoke --nse-symbol RELIANCE --year 2025
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo SMOKE TEST FINISHED SUCCESSFULLY) else (echo SMOKE TEST FAILED)
pause
exit /b %RC%
