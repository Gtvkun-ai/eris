@echo off
REM Launcher Web Control Panel ElevenLabs Pool (ElevenPool)
title ERIS -- ElevenLabs Pool Web UI

cd /d "%~dp0"
set "PATH=%~dp0.venv\Scripts;%PATH%"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONUTF8=1"

echo =========================================================
echo   ERIS ElevenLabs Pool Web Control Panel
echo   Giao dien tieng Viet quan ly va xoay Token ElevenLabs
echo =========================================================
echo.
echo Launching Web UI at http://127.0.0.1:18888 ...
start "" "http://127.0.0.1:18888"

".venv\Scripts\python.exe" "src\runtime\elevenlabs_pool_server.py" 18888

pause
