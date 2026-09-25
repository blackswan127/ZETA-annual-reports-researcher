@echo off
setlocal
if "%INDIA_AR_ACKNOWLEDGE_TERMS%"=="1" exit /b 0

echo.
echo IMPORTANT ACCESS NOTICE
echo -----------------------
echo NSE terms restrict systematic automated collection without appropriate permission.
echo BSE data/document use is also subject to its terms and applicable rights.
echo This tool does not bypass CAPTCHA, login, paywalls, bot challenges, or access controls.
echo.
echo Continue only if you have reviewed the relevant terms and are authorized for this use.
set /p ACK=Type YES to acknowledge and continue: 
if /I not "%ACK%"=="YES" (
  echo Cancelled.
  exit /b 1
)
endlocal & set INDIA_AR_ACKNOWLEDGE_TERMS=1
exit /b 0
