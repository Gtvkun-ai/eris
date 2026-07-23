@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PLAYWRIGHT_BROWSERS_PATH=0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -m pip install playwright
if errorlevel 1 goto :error
"%PYTHON%" -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo [Eris Tutor] Chromium da san sang.
exit /b 0

:error
echo.
echo [Eris Tutor] Cai Chromium/Playwright that bai.
exit /b 1
