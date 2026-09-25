@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.10+ and enable the launcher.
  pause
  exit /b 1
)
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -e ".[dev]"
if errorlevel 1 goto :fail
echo.
echo INSTALL PASS
python -m india_ar_bulk --help >nul
if errorlevel 1 goto :fail
pause
exit /b 0
:fail
echo INSTALL FAILED
pause
exit /b 1
