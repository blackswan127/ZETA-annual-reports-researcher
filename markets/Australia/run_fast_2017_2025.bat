@echo off
setlocal
cd /d "%~dp0"
call _ack_terms.bat || goto :end
call .venv\Scripts\activate.bat
REM Increase only if your authorised ASX access remains stable. The tool still retries/backoffs on 429/5xx.
asx-bulk --start-year 2017 --end-year 2025 --metadata-workers 16 --metadata-rps 5 --download-workers 10 --download-rps 5 run
:end
pause
