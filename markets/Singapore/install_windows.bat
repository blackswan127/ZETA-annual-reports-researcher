@echo off
setlocal
where py >nul 2>nul || (echo Python launcher not found. Install Python 3.11+ from python.org and enable PATH.& pause & exit /b 1)
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
echo.
echo Installed successfully.
echo Next run: run_smoke_test.bat
pause
