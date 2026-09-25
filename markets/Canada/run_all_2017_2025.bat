@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat

echo CANADA ZETA MASS ANNUAL REPORT RUN - FY2017-FY2025
echo ----------------------------------------------------
set /p "TMX_FILE=Full path to official current TSX/TSXV issuer CSV/XLSX: "
if "%TMX_FILE%"=="" goto :bad
if not exist "%TMX_FILE%" (
  echo File not found: %TMX_FILE%
  goto :bad
)
set /p "ZROOT=Final ZETA root [GLOBAL_SUSTAINABILITY_DATABASE]: "
if "%ZROOT%"=="" set "ZROOT=GLOBAL_SUSTAINABILITY_DATABASE"
set /p "OVERRIDES=Optional identity overrides CSV (Enter to skip): "
set /p "SEDAR=Optional AUTHORIZED SEDAR DDS manifest (Enter to skip): "

if "%OVERRIDES%"=="" goto :no_overrides
if not exist "%OVERRIDES%" (
  echo Overrides file not found: %OVERRIDES%
  goto :bad
)
:no_overrides
if "%SEDAR%"=="" goto :no_sedar
if not exist "%SEDAR%" (
  echo SEDAR manifest not found: %SEDAR%
  goto :bad
)
:no_sedar

if not "%OVERRIDES%"=="" if not "%SEDAR%"=="" goto :both
if not "%OVERRIDES%"=="" goto :only_overrides
if not "%SEDAR%"=="" goto :only_sedar

canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 run --universe-file "%TMX_FILE%"
goto :after_run

:both
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 run --universe-file "%TMX_FILE%" --identity-overrides "%OVERRIDES%" --sedar-manifest "%SEDAR%"
goto :after_run

:only_overrides
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 run --universe-file "%TMX_FILE%" --identity-overrides "%OVERRIDES%"
goto :after_run

:only_sedar
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 run --universe-file "%TMX_FILE%" --sedar-manifest "%SEDAR%"

:after_run
if errorlevel 1 goto :bad

echo.
echo COMPLETE. Inspect work\audit\coverage.csv and work\audit\repair_queue.csv.
pause
exit /b 0

:bad
echo Run failed or input was invalid.
pause
exit /b 1
