@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0ErisManager.exe" (
    start "" "%~dp0ErisManager.exe"
    exit /b 0
)

if exist "%~dp0dist\ErisManager.exe" (
    start "" "%~dp0dist\ErisManager.exe"
    exit /b 0
)

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" "%~dp0src\manager_gui.py"
