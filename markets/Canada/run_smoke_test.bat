@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo === Offline deterministic suite ===
python -m pytest -q
if errorlevel 1 goto :fail

echo.
echo === CLI + ZETA smoke using verified RBC sample ===
if exist smoke_work rmdir /s /q smoke_work
if exist smoke_zeta rmdir /s /q smoke_zeta
canada-zeta-ar --work smoke_work --zeta-root smoke_zeta --start-year 2025 --end-year 2025 universe --universe-file input\tmx_current_list.example.csv
if errorlevel 1 goto :fail
canada-zeta-ar --work smoke_work --zeta-root smoke_zeta --start-year 2025 --end-year 2025 discover-sites --limit 1
if errorlevel 1 goto :fail
canada-zeta-ar --work smoke_work --zeta-root smoke_zeta --start-year 2025 --end-year 2025 resolve
canada-zeta-ar --work smoke_work --zeta-root smoke_zeta --start-year 2025 --end-year 2025 audit
if errorlevel 1 goto :fail

echo.
echo SMOKE TEST PASS.
echo Note: this live smoke validates issuer-site discovery. It intentionally does not scrape SEDAR+.
pause
exit /b 0
:fail
echo.
echo SMOKE TEST FAILED. Inspect the error and smoke_work\audit\events.csv.
pause
exit /b 1
