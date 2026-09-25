@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
cse-ar run --start-year 2024 --end-year 2025 --limit 3 --work work_smoke --zeta-root SMOKE_ZETA --discovery-workers 2 --discovery-rps 1 --pdf-workers 2 --pdf-rps 1
pause
