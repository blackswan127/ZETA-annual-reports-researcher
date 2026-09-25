@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul || (echo Python 3.10+ is required.& pause & exit /b 1)
py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .
echo.
echo INSTALL COMPLETE
pause
