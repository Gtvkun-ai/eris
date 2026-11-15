@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ======================================================================
echo    DANG DUNG TOAN BO DICH VU AI NGAM (DOCKER)
echo ======================================================================
echo.

cd /d "%~dp0tools\whale2api"
docker compose down
echo.
echo [OK] Da giai phong RAM va tat toan bo containers Docker!
timeout /t 3 >nul
exit /b 0
