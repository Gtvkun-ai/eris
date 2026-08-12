@echo off
setlocal
cd /d "%~dp0"
if not exist v60_reports mkdir v60_reports
python tools\deep_environment_windows_e2e.py --output v60_reports\v60_windows_environment_probe.json
exit /b %errorlevel%
