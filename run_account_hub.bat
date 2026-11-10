@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"

echo =======================================================
echo [ACCOUNT HUB] Đang khởi động Eris Account Hub tại:
echo               http://127.0.0.1:9000
echo =======================================================
start "" http://127.0.0.1:9000
"%PYTHON%" "%~dp0tools\account_hub\server.py"
pause

