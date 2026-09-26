@echo off
setlocal
set PSE_TERMS_ACKNOWLEDGED=1
set PYTHONPATH=%~dp0src;%~dp0..\..
py -m pytest -v %~dp0tests
endlocal
