@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
cls
echo Review NZX Website Terms and confirm your intended access/use is authorized.
echo https://www.nzx.com/meta-pages/terms-of-use
echo.
set /p OK=Type YES to perform the bounded live smoke test: 
if /I not "%OK%"=="YES" exit /b 1
set NZX_ACKNOWLEDGE_TERMS=1
nzx-zeta smoke-test
pause
