@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set /p OK=Type YES if your DSE/CDBL access and intended use are authorized: 
if /I not "%OK%"=="YES" exit /b 1
set DSE_ACKNOWLEDGE_TERMS=1
set /p ROOT=ZETA root [E:\GLOBAL_SUSTAINABILITY_DATABASE]: 
if "%ROOT%"=="" set ROOT=E:\GLOBAL_SUSTAINABILITY_DATABASE
dse-zeta --work work --zeta-root "%ROOT%" --start-year 2017 --end-year 2025 --discovery-workers 10 --download-workers 16 --delay 0.25 run
pause
