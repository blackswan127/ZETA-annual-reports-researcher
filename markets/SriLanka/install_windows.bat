@echo off
cd /d "%~dp0"
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .
echo Installation complete.
pause
