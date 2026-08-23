@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERR] Missing venv python: %PY%
    echo       Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

"%PY%" "%~dp0_fullbuild.py" --profile release --yes
