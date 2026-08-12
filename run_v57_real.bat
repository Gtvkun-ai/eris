@echo off
chcp 65001 >nul
set PYTHONUTF8=1
python src\tools\run_v57_live_simulation.py --scenario all --strict
set CODE=%ERRORLEVEL%
echo.
if "%CODE%"=="0" (
  echo V57 REAL BEHAVIOR: PASS
) else (
  echo V57 REAL BEHAVIOR: FAIL / INVALID. Xem thu muc v57_reports.
)
exit /b %CODE%
