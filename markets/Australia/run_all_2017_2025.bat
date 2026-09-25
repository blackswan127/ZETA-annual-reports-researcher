@echo off
setlocal
cd /d "%~dp0"
call _ack_terms.bat || goto :end
call .venv\Scripts\activate.bat
asx-bulk --start-year 2017 --end-year 2025 --metadata-workers 10 --metadata-rps 3 --download-workers 6 --download-rps 3 run
:end
pause
