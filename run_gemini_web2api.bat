@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0\tools\WebAI-to-API"

if not exist "config.conf" (
    echo [INFO] Copying config.conf.example to config.conf...
    copy config.conf.example config.conf
)

echo [INFO] Installing requirements...
..\..\.venv\Scripts\python.exe -m pip install -r requirements.txt pywin32 pycryptodome

echo [INFO] Starting WebAI-to-API Server (Port 8081)...
start "WebAI-to-API Server" cmd /c "chcp 65001 >nul && ..\..\.venv\Scripts\python.exe src\run.py --host 0.0.0.0 --port 8081"

echo [INFO] Waiting for server to start...
timeout /t 5 /nobreak >nul

echo [INFO] Pinging server...
curl http://localhost:8081/v1/models

echo.
echo.
echo [INFO] Server is running in the other window!
echo [INFO] Opening the Web UI Dashboard...
start http://localhost:8081/ui

pause
