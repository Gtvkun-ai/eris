@echo off
REM Launcher Eris Manager Web Control Panel
title ERIS -- Manager Web UI

cd /d "%~dp0"
set "PATH=%~dp0.venv\Scripts;%PATH%"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONUTF8=1"

echo =========================================================
echo   ERIS Manager Web Control Panel
echo   Giao dien quan ly trung tam (Web UI)
echo =========================================================
echo.
echo Launching Web UI at http://127.0.0.1:19999 ...
start "" "http://127.0.0.1:19999"

".venv\Scripts\python.exe" "src\runtime\eris_manager_server.py" 19999

pause
