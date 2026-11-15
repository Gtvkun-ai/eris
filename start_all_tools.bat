@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ======================================================================
echo    ERIS ALL-IN-ONE TOOL LAUNCHER (DEEPSEEK + GEMINI VISION)
echo ======================================================================
echo.

:: 1. Kiem tra Docker Desktop
echo [1/3] Kiem tra Docker Desktop...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo [LOI] Docker Desktop chua duoc bat hoac dang khoi dong do dang!
    echo -> Vui long mo Docker Desktop tu Start Menu/Desktop.
    echo -> Doi icon goc duoi ben trai hien mau xanh la cay (Engine running).
    echo -> Sau do bam lai file nay!
    echo.
    pause
    exit /b 1
)
echo [OK]  Docker Desktop dang hoat dong tot.

:: 2. Khoi dong toan bo containers Docker
echo.
echo [2/3] Dang khoi dong cac cong cu AI ngam (Whale2API + Gemini Vision)...
cd /d "%~dp0tools\whale2api"
docker compose up -d
if errorlevel 1 (
    echo.
    echo [LOI] Khoi dong Docker Compose that bai. Xem chi tiet loi o tren.
    pause
    exit /b 1
)

echo.
echo [OK]  DeepSeek Whale2API gateway: http://127.0.0.1:5103
echo [OK]  DeepSeek Pool WebUI:        http://127.0.0.1:5010
echo [OK]  Gemini Vision service:     http://127.0.0.1:8000

:: 3. Mo giao dien Account Hub
echo.
echo [3/3] Dang khoi chay Eris Account Hub de quan ly tai khoan...
cd /d "%~dp0"
start "Eris Account Hub" "%~dp0run_manager.bat"

echo.
echo ======================================================================
echo [HOAN TAT] Tat ca cac tool da san sang!
echo Ban co the nap tai khoan tren trinh duyet va khoi chay run_eris.bat!
echo ======================================================================
timeout /t 5 >nul
exit /b 0
