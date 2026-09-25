@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py smoke --stock-code 00700 --smoke-year 2025
if errorlevel 1 goto failed
python run.py companies
if errorlevel 1 goto failed
goto finished
:failed
echo One or more network smoke checks failed.
:finished
pause
