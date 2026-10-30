@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"
set "HF_HOME=%~dp0.cache\huggingface"
set "XDG_CACHE_HOME=%~dp0.cache"
set "ERIS_AGENT_SERVICE_DISCOVERY=%~dp0.eris_state\agent_service.json"
set "ERIS_HOME=%~dp0.eris_home"
set "ERIS_STATE_DIR=%~dp0.eris_state"

if not exist "%~dp0config\secrets.json" (
    echo [SETUP] Missing config\secrets.json.
    echo [SETUP] Opening secrets setup now. Fill keys, save, then run this launcher again.
    if exist "%~dp0setup_secrets.bat" call "%~dp0setup_secrets.bat"
    pause
    exit /b 1
)


if exist "%~dp0Eris.exe" (
    start "Eris Runtime" "%~dp0Eris.exe"
) else (
    start "Eris Runtime" cmd /k ""%PYTHON%" "%~dp0src\vision.py""
)
