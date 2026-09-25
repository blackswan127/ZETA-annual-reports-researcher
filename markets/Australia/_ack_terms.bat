@echo off
if "%ASX_ACKNOWLEDGE_TERMS%"=="1" exit /b 0
echo.
echo IMPORTANT - ASX TERMS
 echo ASX states that company announcements are for private/personal use and
 echo that commercial use or aggregation requires ASX express written authority.
echo.
set /p ACK=If you have reviewed the ASX terms and are authorised for your intended use, type YES: 
if /I not "%ACK%"=="YES" (
  echo Not acknowledged. Exiting without network access.
  exit /b 1
)
set ASX_ACKNOWLEDGE_TERMS=1
exit /b 0
