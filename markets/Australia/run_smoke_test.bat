@echo off
setlocal
cd /d "%~dp0"
call _ack_terms.bat || goto :end
call .venv\Scripts\activate.bat
asx-bulk smoke --ticker BHP --year 2025
:end
pause
