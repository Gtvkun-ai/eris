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

powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing -Uri $env:ERIS_OPEN_URL -TimeoutSec 1 -ErrorAction Stop; Start-Process $env:ERIS_OPEN_URL; exit 0 } catch { exit 1 }"
if not errorlevel 1 exit /b 0

if not exist "%~dp0tools\account_hub\server.py" (
    echo Missing tools\account_hub\server.py. Run this launcher from the full Eris source folder.
    pause
    exit /b 1
)

"%PYTHON%" -c "import fastapi, uvicorn, psutil, requests" >nul 2>&1
if errorlevel 1 (
    echo Installing Account Hub dependencies...
    "%PYTHON%" -m pip install -r "%~dp0tools\account_hub\requirements.txt"
    if errorlevel 1 (
        echo Account Hub dependencies could not be installed.
        pause
        exit /b 1
    )
)

start "Open Eris Account Hub" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "%ERIS_OPEN_URL%" 60
"%PYTHON%" -m uvicorn tools.account_hub.server:app --host 127.0.0.1 --port %HUB_PORT%
if errorlevel 1 (
    echo Account Hub failed to start. See the error above.
    pause
    exit /b 1
)

