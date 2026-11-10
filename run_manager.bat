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

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"

"%PYTHON%" "%~dp0src\manager_gui.py"

