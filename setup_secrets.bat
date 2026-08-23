@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "config" mkdir "config"

if not exist "config\secrets.example.json" (
    echo [ERROR] Missing config\secrets.example.json
    exit /b 1
)

if not exist "config\secrets.json" (
    copy /Y "config\secrets.example.json" "config\secrets.json" >nul
    echo [OK] Created config\secrets.json from template.
) else (
    echo [OK] config\secrets.json already exists; keeping it.
)

echo.
echo Fill real keys in: %CD%\config\secrets.json
echo Guide:             %CD%\config\SECRETS_SETUP.md
echo.

if /I "%~1"=="--no-open" exit /b 0

if exist "config\SECRETS_SETUP.md" start "" notepad "config\SECRETS_SETUP.md"
start "" notepad "config\secrets.json"
exit /b 0
