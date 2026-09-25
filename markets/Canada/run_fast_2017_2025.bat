@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set /p "TMX_FILE=Full path to official current TSX/TSXV issuer CSV/XLSX: "
if "%TMX_FILE%"=="" exit /b 1
if not exist "%TMX_FILE%" exit /b 1
set /p "ZROOT=Final ZETA root [GLOBAL_SUSTAINABILITY_DATABASE]: "
if "%ZROOT%"=="" set "ZROOT=GLOBAL_SUSTAINABILITY_DATABASE"
set /p "SEDAR=Optional AUTHORIZED SEDAR DDS manifest (Enter to skip): "
if "%SEDAR%"=="" goto :without_sedar
if not exist "%SEDAR%" exit /b 1
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 --metadata-workers 16 --download-workers 16 --metadata-rps 4 --download-rps 8 run --universe-file "%TMX_FILE%" --sedar-manifest "%SEDAR%"
goto :done
:without_sedar
canada-zeta-ar --work work --zeta-root "%ZROOT%" --start-year 2017 --end-year 2025 --metadata-workers 16 --download-workers 16 --metadata-rps 4 --download-rps 8 run --universe-file "%TMX_FILE%"
:done
pause
