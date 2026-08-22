@echo off
REM _setup_gemini_pool_auth.bat
REM Chay 3 lan, moi lan login 1 account Google de luu auth state
REM Sau khi setup xong, dung _start_gemini_pool.bat de chay pool
REM
setlocal
chcp 65001 >nul
cd /d "%~dp0tools\WebAI-to-API"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" set "VENV_PY=python"

if "%1"=="" (
    echo Usage: _setup_gemini_pool_auth.bat [1^|2^|3]
    echo.
    echo   1 = Setup account 1 ^(saves to runtime\auth-1\gemini.json^)
    echo   2 = Setup account 2 ^(saves to runtime\auth-2\gemini.json^)
    echo   3 = Setup account 3 ^(saves to runtime\auth-3\gemini.json^)
    echo.
    echo Chay 3 lan voi tham so 1, 2, 3 tuong ung voi 3 account Google.
    pause
    exit /b 1
)

set "SLOT=%1"
set "AUTH_DIR=runtime\auth-%SLOT%"
mkdir "%AUTH_DIR%" 2>nul

echo.
echo [SETUP] Configuring account slot %SLOT% -> %AUTH_DIR%\gemini.json
echo [SETUP] A Chrome window will open. Log in to Google account #%SLOT%.
echo [SETUP] After login, close the browser. Auth state will be saved automatically.
echo.
pause

set PLAYWRIGHT_AUTH_STATE_DIR=%AUTH_DIR%
"%VENV_PY%" verify_login.py

echo.
echo [DONE] Account %SLOT% saved to %AUTH_DIR%\gemini.json
echo        Run this script again with 2 or 3 for other accounts.
pause
