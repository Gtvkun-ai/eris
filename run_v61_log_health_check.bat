@echo off
setlocal EnableExtensions
chcp 65001 >nul
if "%~1"=="" (
  echo Usage: run_v61_log_health_check.bat ^<duong_dan_log.txt^>
  exit /b 2
)
python "%~dp0tools\check_v61_runtime_log.py" "%~1"
exit /b %ERRORLEVEL%
