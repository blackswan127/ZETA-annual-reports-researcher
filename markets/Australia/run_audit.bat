@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
asx-bulk --start-year 2017 --end-year 2025 audit
pause
