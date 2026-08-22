@echo off
REM _start_gemini_pool.bat
REM Tu dong phat hien tat ca runtime\auth-*\gemini.json va start 1 WebAI instance moi auth dir
REM Port bat dau tu 8081, tang dan: 8081, 8082, 8083, 8084...
REM
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0tools\WebAI-to-API"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" set "VENV_PY=python"

echo.
echo  ================================================
echo    ERIS -- Gemini Playwright Pool (auto-detect)
echo  ================================================
echo.

set PORT=8081
set COUNT=0
set ENDPOINTS=

REM Quet tat ca auth-* directory co gemini.json
for /d %%D in (runtime\auth-*) do (
    if exist "%%D\gemini.json" (
        set /a COUNT+=1
        echo [POOL] Found: %%D ^(port !PORT!^)

        start "Gemini-Pool-!COUNT!" cmd /c "set PLAYWRIGHT_AUTH_STATE_DIR=%%D && set PLAYWRIGHT_HEADLESS=true && ""%VENV_PY%"" src\run.py --host 127.0.0.1 --port !PORT!"

        if "!ENDPOINTS!"=="" (
            set ENDPOINTS=http://127.0.0.1:!PORT!
        ) else (
            set ENDPOINTS=!ENDPOINTS!,http://127.0.0.1:!PORT!
        )

        set /a PORT+=1
        timeout /t 1 /nobreak >nul
    )
)

if !COUNT!==0 (
    echo [ERROR] Khong tim thay auth state nao!
    echo [ERROR] Chay truoc: _setup_gemini_pool_auth.bat 1
    pause
    exit /b 1
)

echo.
echo [POOL] Started !COUNT! instance^(s^)
echo [POOL] Endpoints: !ENDPOINTS!

REM Luu endpoints vao file de Eris doc
echo !ENDPOINTS! > "%~dp0.eris_state\gemini_pool_endpoints.txt"

REM Export cho session hien tai
set GEMINI_POOL_ENDPOINTS=!ENDPOINTS!

echo [POOL] Waiting 10s for warmup...
timeout /t 10 /nobreak >nul

echo.
echo [POOL] Health check:
set CHECK_PORT=8081
for /l %%I in (1,1,!COUNT!) do (
    netstat -ano | findstr ":!CHECK_PORT!" | findstr "LISTENING" >nul 2>nul
    if !ERRORLEVEL!==0 (
        echo   [OK] :!CHECK_PORT! LISTENING
    ) else (
        echo   [WARN] :!CHECK_PORT! not ready yet
    )
    set /a CHECK_PORT+=1
)

echo.
echo [DONE] Pool ready. GEMINI_POOL_ENDPOINTS=!ENDPOINTS!
pause
