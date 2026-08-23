@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"

if exist "%~dp0gemini_manager\manager_api.py" (
    set "ERIS_OPEN_URL=http://127.0.0.1:8000"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "!ERIS_OPEN_URL!" 1
    if not errorlevel 1 exit /b 0

    start "Open Gemini Web2API" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "!ERIS_OPEN_URL!" 60
    "%PYTHON%" -m uvicorn gemini_manager.manager_api:app --host 127.0.0.1 --port 8000
) else (
    echo gemini_manager\manager_api.py not found.
    exit /b 1
)
