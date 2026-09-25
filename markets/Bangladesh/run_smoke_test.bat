@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
cls
echo Review DSE website terms/permissions for your intended use before automation.
echo Public source: https://dse.ternary.com.bd/
echo.
set /p OK=Type YES to perform the bounded live smoke test: 
if /I not "%OK%"=="YES" exit /b 1
set DSE_ACKNOWLEDGE_TERMS=1
dse-zeta smoke-test
pause
