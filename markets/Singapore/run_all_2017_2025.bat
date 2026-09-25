@echo off
setlocal
if not exist .venv\Scripts\python.exe (echo Run install_windows.bat first.& pause & exit /b 1)
.venv\Scripts\python.exe -m sgx_bulk run --start-year 2017 --end-year 2025 --output output --discovery-workers 6 --detail-workers 8 --download-workers 6
pause
