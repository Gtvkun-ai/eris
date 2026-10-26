@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"

set "HUB_PORT=9000"
set "ERIS_OPEN_URL=http://127.0.0.1:%HUB_PORT%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "%ERIS_OPEN_URL%" 1
if not errorlevel 1 exit /b 0

"%PYTHON%" -m uvicorn tools.account_hub.server:app --host 127.0.0.1 --port %HUB_PORT% --reload

