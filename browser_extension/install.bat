@echo off
REM ============================================================
REM  ERIS Browser Bridge — Install Script
REM  Đăng ký Native Messaging Host vào registry của Brave/Chrome
REM  Chạy với quyền Administrator!
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   ERIS Browser Bridge - Cai dat Native Messaging Host
echo ============================================================
echo.

REM Thư mục chứa script này
set "INSTALL_DIR=%~dp0"
set "HOST_DIR=%INSTALL_DIR%native_host"
set "HOST_MANIFEST=%HOST_DIR%\com.eris.browser_bridge.json"
set "HOST_BAT=%HOST_DIR%\eris_bridge_host.bat"

REM Kiểm tra file tồn tại
if not exist "%HOST_MANIFEST%" (
    echo [LOI] Khong tim thay: %HOST_MANIFEST%
    pause & exit /b 1
)
if not exist "%HOST_BAT%" (
    echo [LOI] Khong tim thay: %HOST_BAT%
    pause & exit /b 1
)

REM ---- Lấy Extension ID ----
echo.
echo Buoc 1: Lay Extension ID tu Brave
echo.
echo Cach lay Extension ID:
echo   1. Mo Brave, vao brave://extensions
echo   2. Bat "Developer mode" goc phai tren
echo   3. Nhan "Load unpacked" chon thu muc: %INSTALL_DIR%
echo   4. Chep ID hien ra (vi du: abcdefghijklmnopabcdefghijklmnop)
echo.
set /p EXT_ID="Nhap Extension ID: "

if "%EXT_ID%"=="" (
    echo [LOI] Ban chua nhap Extension ID.
    pause & exit /b 1
)

REM ---- Cập nhật allowed_origins trong manifest ----
echo.
echo Buoc 2: Cap nhat manifest voi Extension ID...
python -c "
import json, sys
with open(r'%HOST_MANIFEST%', 'r', encoding='utf-8') as f:
    data = json.load(f)
data['path'] = r'%HOST_BAT%'.replace('\\\\', '\\\\\\\\')
data['allowed_origins'] = ['chrome-extension://%EXT_ID%/']
with open(r'%HOST_MANIFEST%', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print('[OK] Manifest da cap nhat.')
"
if errorlevel 1 (
    echo [LOI] Cap nhat manifest that bai. Kiem tra Python da cai chua.
    pause & exit /b 1
)

REM ---- Đăng ký vào Registry (Brave + Chrome) ----
echo.
echo Buoc 3: Dang ky Native Messaging Host vao Registry...

set "REG_KEY_BRAVE=HKCU\Software\BraveSoftware\NativeMessagingHosts\com.eris.browser_bridge"
set "REG_KEY_CHROME=HKCU\Software\Google\Chrome\NativeMessagingHosts\com.eris.browser_bridge"

REG ADD "%REG_KEY_BRAVE%" /ve /t REG_SZ /d "%HOST_MANIFEST%" /f > nul
if errorlevel 1 (
    echo [WARN] Khong dang ky duoc cho Brave ^(co the khong co Brave^)
) else (
    echo [OK] Da dang ky cho Brave.
)

REG ADD "%REG_KEY_CHROME%" /ve /t REG_SZ /d "%HOST_MANIFEST%" /f > nul
if errorlevel 1 (
    echo [WARN] Khong dang ky duoc cho Chrome ^(co the khong co Chrome^)
) else (
    echo [OK] Da dang ky cho Chrome.
)

REM ---- Tạo thư mục ERIS trong LOCALAPPDATA ----
if not exist "%LOCALAPPDATA%\ERIS" (
    mkdir "%LOCALAPPDATA%\ERIS"
    echo [OK] Da tao: %LOCALAPPDATA%\ERIS
)

echo.
echo ============================================================
echo   CAI DAT HOAN TAT!
echo.
echo   File cache se duoc ghi vao:
echo   %LOCALAPPDATA%\ERIS\browser_dom_state.json
echo.
echo   Restart Brave de extension hoat dong voi native host.
echo ============================================================
echo.
pause
