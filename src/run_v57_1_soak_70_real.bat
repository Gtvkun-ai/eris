@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo V57.1 LIVE SOAK 70 turn: moi turn goi Eris provider that va behavioral judge that.
echo Da sua false-positive repetition, memory evidence va language drift.
echo Luu y: lenh nay co the ton kha nhieu API request/token.
echo.
python tools\run_v57_live_simulation.py --scenario all --soak-turns 70 --restart-every 10 --strict
set CODE=%ERRORLEVEL%
echo.
if "%CODE%"=="0" (
  echo V57.1 LIVE SOAK: PASS
) else (
  echo V57.1 LIVE SOAK: FAIL / INVALID. Xem thu muc v57_reports.
)
exit /b %CODE%
