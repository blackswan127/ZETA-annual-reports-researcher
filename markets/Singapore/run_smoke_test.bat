@echo off
setlocal
if not exist .venv\Scripts\python.exe (echo Run install_windows.bat first.& pause & exit /b 1)
.venv\Scripts\python.exe -m sgx_bulk smoke
pause
