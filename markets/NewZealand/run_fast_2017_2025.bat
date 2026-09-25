@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set /p OK=Type YES if your NZX access/use is authorized: 
if /I not "%OK%"=="YES" exit /b 1
set NZX_ACKNOWLEDGE_TERMS=1
set /p ROOT=ZETA root [E:\GLOBAL_SUSTAINABILITY_DATABASE]: 
if "%ROOT%"=="" set ROOT=E:\GLOBAL_SUSTAINABILITY_DATABASE
nzx-zeta --work work --zeta-root "%ROOT%" --start-year 2017 --end-year 2025 --discovery-workers 8 --download-workers 12 --delay 0.25 run
pause
