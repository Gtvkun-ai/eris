@echo off
setlocal
cd /d "%~dp0"
echo [V59] Chay test HIEN SINH that: clone long-arc hien tai sang sandbox, de user im va xem Eris co tu mo mot nhip quan he dung luc khong.
python tools\run_v59_existential_initiative_live.py --wait 180 --guard-wait 55
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo [V59] PASS
) else if "%RC%"=="3" (
  echo [V59] RELATIONSHIP_NOT_MATURE - long-arc chua du chin, day la phanh dung thiet ke.
) else (
  echo [V59] FAIL/INVALID - xem thu muc v59_reports
)
exit /b %RC%
