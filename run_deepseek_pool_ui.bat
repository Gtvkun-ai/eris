@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "WHALE_DIR=%~dp0tools\whale2api"
set "WHALE2API_DATABASE_PATH=%WHALE_DIR%\docker-data\whale2api\whale2api.db"
set "POOL_UI_PORT=5010"
if not exist "%WHALE_DIR%\accounts.template.csv" (
    > "%WHALE_DIR%\accounts.template.csv" echo email,password
    >> "%WHALE_DIR%\accounts.template.csv" echo email1@example.com,password1
    >> "%WHALE_DIR%\accounts.template.csv" echo email2@example.com,password2
)
if exist "%WHALE_DIR%\.env" (
    for /f "tokens=1,* delims==" %%A in ('findstr /b /c:"POOL_UI_PORT=" "%WHALE_DIR%\.env" 2^>nul') do set "POOL_UI_PORT=%%B"
)
if not defined POOL_UI_ADMIN_TOKEN set "POOL_UI_ADMIN_TOKEN=123456"
set "ERIS_OPEN_URL=http://127.0.0.1:%POOL_UI_PORT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "%ERIS_OPEN_URL%" 1
if not errorlevel 1 exit /b 0

if not exist "%WHALE_DIR%\poolui.exe" (
    echo Missing file: %WHALE_DIR%\poolui.exe
    pause
    exit /b 1
)

start "Open DeepSeek Pool UI" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0tools\open_url_when_ready.ps1" "%ERIS_OPEN_URL%" 60
pushd "%WHALE_DIR%"
echo.
echo [DeepSeek Pool] CSV mau da co tai:
echo %WHALE_DIR%\accounts.template.csv
echo Sua file nay thanh email/password that roi trong Pool UI bam Nhap CSV.
echo.
"%WHALE_DIR%\poolui.exe"
popd
