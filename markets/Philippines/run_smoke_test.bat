@echo off
setlocal
set PSE_TERMS_ACKNOWLEDGED=1
set PYTHONPATH=%~dp0src;%~dp0..\..
py -m phl_pse_bulk.cli smoke --acknowledge-terms --output-root "%~dp0..\..\GLOBAL_SUSTAINABILITY_DATABASE"
endlocal
