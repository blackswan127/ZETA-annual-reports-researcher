@echo off
setlocal
if not exist .venv\Scripts\python.exe (echo Run install_windows.bat first.& pause & exit /b 1)
echo FAST MODE increases concurrent SGX requests. If SGX sends 429 responses, use run_all_2017_2025.bat instead.
.venv\Scripts\python.exe -m sgx_bulk run --start-year 2017 --end-year 2025 --output output --discovery-workers 10 --detail-workers 12 --download-workers 10
pause
