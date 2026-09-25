@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set /p ZROOT=Final ZETA root [GLOBAL_SUSTAINABILITY_DATABASE]: 
if "%ZROOT%"=="" set "ZROOT=GLOBAL_SUSTAINABILITY_DATABASE"
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 repair-missing
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 finalize
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 audit
if errorlevel 1 (
  echo Repair failed. See work\audit\events.csv.
  pause
  exit /b 1
)
echo Repair pass complete. See work\audit\repair_queue.csv.
pause
