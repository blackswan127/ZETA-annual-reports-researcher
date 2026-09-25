@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py status
pause
