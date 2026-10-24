@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\export_ai_zip.ps1"
set "EXPORT_RESULT=%ERRORLEVEL%"
if not "%EXPORT_RESULT%"=="0" echo Export failed. See the error above.
if /I not "%~1"=="--no-pause" pause
exit /b %EXPORT_RESULT%
