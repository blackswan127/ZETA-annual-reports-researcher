@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set /p ZETA=Enter ZETA root [E:\GLOBAL_SUSTAINABILITY_DATABASE]:
if "%ZETA%"=="" set ZETA=E:\GLOBAL_SUSTAINABILITY_DATABASE
cse-ar run --start-year 2017 --end-year 2025 --work work --zeta-root "%ZETA%" --identity-overrides identity_overrides_TEMPLATE.csv --discovery-workers 12 --discovery-rps 3 --pdf-workers 32 --pdf-rps 12
pause
