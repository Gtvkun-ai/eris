@echo off
setlocal
if "%~1"=="" (
  echo Cach dung: run_v62_runtime_probe.bat "C:\duong-dan\eris_run_....txt"
  exit /b 2
)
python "%~dp0tools\v62_runtime_probe.py" "%~1"
exit /b %ERRORLEVEL%
