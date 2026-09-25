@echo off
cd /d "%~dp0"
call _ack_terms.bat
if errorlevel 1 exit /b 1
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python -m india_ar_bulk --output output --start-year 2017 --end-year 2025 --metadata-workers 6 --nse-rps 1.5 --bse-rps 2.5 --download-workers 8 --download-rps 4 run
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo RUN COMPLETE. Review output\audit\missing.csv) else (echo RUN STOPPED WITH ERRORS. Re-running is safe.)
pause
exit /b %RC%
