@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
cls
echo DSE ZETA FY2017-FY2025 production run
echo Current DSE equity universe + CDBL ISIN enrichment + issuer annual-report archives.
echo.
set /p OK=Type YES if your DSE/CDBL access and intended use are authorized: 
if /I not "%OK%"=="YES" exit /b 1
set DSE_ACKNOWLEDGE_TERMS=1
set /p ROOT=ZETA root [E:\GLOBAL_SUSTAINABILITY_DATABASE]: 
if "%ROOT%"=="" set ROOT=E:\GLOBAL_SUSTAINABILITY_DATABASE
set /p UNIVERSE=Authorized/current universe CSV (optional; Enter = live DSE): 
set /p OVERRIDE=Identity overrides CSV (optional): 
set /p MANIFEST=Authorized historical manifest (optional): 
set /p GLEIF=Attempt conservative exact-match GLEIF LEI enrichment? [Y/N]: 
set EXTRA=
if not "%UNIVERSE%"=="" set EXTRA=%EXTRA% --universe-csv "%UNIVERSE%"
if not "%OVERRIDE%"=="" set EXTRA=%EXTRA% --identity-overrides "%OVERRIDE%"
if not "%MANIFEST%"=="" set EXTRA=%EXTRA% --authorized-manifest "%MANIFEST%"
if /I "%GLEIF%"=="Y" set EXTRA=%EXTRA% --gleif
dse-zeta --work work --zeta-root "%ROOT%" --start-year 2017 --end-year 2025 run %EXTRA%
dse-zeta --work work --zeta-root "%ROOT%" audit
echo.
echo COMPLETE. Review work\audit\coverage.csv and work\audit\repair_queue.csv
pause
