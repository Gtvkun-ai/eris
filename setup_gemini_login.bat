@echo off
setlocal
chcp 65001 >nul

echo =================================================================
echo   CHƯƠNG TRÌNH ĐĂNG NHẬP GOOGLE GEMINI TỰ ĐỘNG CHO WEBAI-TO-API
echo =================================================================
echo.
echo [HUONG DAN]
echo 1. Một trinh duyet (Chromium) se hien len. 
echo 2. Vui long dang nhap tai khoan Google cua ban tren do.
echo 3. Khi man hinh bao [SUCCESS] Login detected!, ban co the dong trinh duyet.
echo.
echo =================================================================
echo.

cd /d "%~dp0\tools\WebAI-to-API"

echo [INFO] Dang khoi dong trinh duyet, vui long doi...
..\..\.venv\Scripts\python.exe verify_login.py

echo.
echo [INFO] Hoan tat! Ban co the tat cua so nay roi chay file run_gemini_web2api.bat
pause
