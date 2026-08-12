@echo off
setlocal
cd /d "%~dp0"
echo [V58] Chay test CHU DONG that: Eris phai tu mo loi sau khoang lang, roi biet im neu user chua dap.
python tools\run_v58_initiative_live.py --wait 180 --guard-wait 55
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo [V58] PASS
) else (
  echo [V58] FAIL/INVALID - xem thu muc v58_reports
)
exit /b %RC%
