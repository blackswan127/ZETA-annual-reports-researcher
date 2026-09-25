@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.10+ and retry.
  pause
  exit /b 1
)
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .[dev]
if errorlevel 1 (
  echo Installation failed.
  pause
  exit /b 1
)
echo.
echo Installation complete.
echo Next: run_smoke_test.bat
pause
