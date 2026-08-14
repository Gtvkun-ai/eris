@echo off
setlocal

cd /d "%~dp0\tools\WebAI-to-API"

if not exist "config.conf" (
    echo [INFO] Copying config.conf.example to config.conf...
    copy config.conf.example config.conf
)

echo [INFO] Installing requirements...
..\..\.venv\Scripts\python.exe -m pip install -r requirements.txt pywin32 pycryptodome

echo [INFO] Starting WebAI-to-API Instance 1 (Port 8081)...
start "WebAI-to-API Server 1" ..\..\.venv\Scripts\python.exe src\run.py --host 0.0.0.0 --port 8081

cd /d "%~dp0\tools\WebAI-to-API-2"
echo [INFO] Starting WebAI-to-API Instance 2 (Port 8082)...
start "WebAI-to-API Server 2" ..\..\.venv\Scripts\python.exe src\run.py --host 0.0.0.0 --port 8082

echo [INFO] Waiting for servers to start...
timeout /t 5 /nobreak >nul

echo [INFO] Pinging servers...
curl http://localhost:8081/v1/models
echo.
curl http://localhost:8082/v1/models

echo.
echo.
echo [INFO] Servers are running in the other windows!
echo [INFO] Opening the Web UI Dashboards...
start http://localhost:8081/ui
start http://localhost:8082/ui

pause
