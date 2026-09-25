@echo off
cd /d "%~dp0"
call _ack_terms.bat
if errorlevel 1 exit /b 1
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
echo FAST MODE: use only after the normal smoke/run is stable and your authorization permits this request rate.
.venv\Scripts\python -m india_ar_bulk --output output --start-year 2017 --end-year 2025 --metadata-workers 10 --nse-rps 2 --bse-rps 4 --download-workers 16 --download-rps 8 run
set RC=%ERRORLEVEL%
pause
exit /b %RC%
