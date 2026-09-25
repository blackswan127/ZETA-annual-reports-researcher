@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set /p "SEDAR=Full path to AUTHORIZED SEDAR DDS manifest: "
if not exist "%SEDAR%" (
  echo File not found.
  pause
  exit /b 1
)
canada-zeta-ar --work work --start-year 2017 --end-year 2025 import-sedar "%SEDAR%"
canada-zeta-ar --work work --start-year 2017 --end-year 2025 resolve
canada-zeta-ar --work work --start-year 2017 --end-year 2025 audit
pause
