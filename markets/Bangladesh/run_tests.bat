@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
set PYTHONPATH=%CD%\src
python -m pytest -q
pause
