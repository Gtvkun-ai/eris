@echo off
REM Khoi dong ERIS Browser Bridge HTTP Server (chay nen, an cua so)
set "SCRIPT_DIR=%~dp0"

set "ERIS_PYTHON=%SCRIPT_DIR%..\..\..\..\.venv\Scripts\pythonw.exe"
if not exist "%ERIS_PYTHON%" set "ERIS_PYTHON=%SCRIPT_DIR%..\..\.venv\Scripts\pythonw.exe"
if not exist "%ERIS_PYTHON%" set "ERIS_PYTHON=pythonw"

start "" "%ERIS_PYTHON%" "%SCRIPT_DIR%eris_bridge_server.py"
echo [ERIS Bridge] Server khoi dong xong tren port 7422.
