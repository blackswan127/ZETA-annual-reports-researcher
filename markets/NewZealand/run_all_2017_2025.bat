@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
cls
echo NZX ZETA FY2017-FY2025 production run
echo Review NZX terms/data licensing before public-site automation.
echo For commercial/bulk use prefer an authorized NZX Data Product export.
echo.
set /p OK=Type YES if your use is authorized: 
if /I not "%OK%"=="YES" exit /b 1
set NZX_ACKNOWLEDGE_TERMS=1
set /p ROOT=ZETA root [E:\GLOBAL_SUSTAINABILITY_DATABASE]: 
if "%ROOT%"=="" set ROOT=E:\GLOBAL_SUSTAINABILITY_DATABASE
set /p UNIVERSE=Authorized/current universe CSV (optional; Enter = live NZX board): 
set /p OVERRIDE=Identity overrides CSV (optional, press Enter to skip): 
set /p MANIFEST=Authorized NZX historical manifest (optional, press Enter to skip): 
set EXTRA=
if not "%UNIVERSE%"=="" set EXTRA=%EXTRA% --universe-csv "%UNIVERSE%"
if not "%OVERRIDE%"=="" set EXTRA=%EXTRA% --identity-overrides "%OVERRIDE%"
if not "%MANIFEST%"=="" set EXTRA=%EXTRA% --authorized-manifest "%MANIFEST%"
nzx-zeta --work work --zeta-root "%ROOT%" --start-year 2017 --end-year 2025 run %EXTRA%
nzx-zeta --work work --zeta-root "%ROOT%" audit
echo.
echo COMPLETE. Review work\audit\coverage.csv and work\audit\repair_queue.csv
pause
