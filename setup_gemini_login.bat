@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"

echo Gemini login helper chua co flow rieng trong repo nay.
echo Mo Eris setup wizard; dung muc credentials/settings de nhap Gemini key.
"%PYTHON%" "%~dp0eris_setup.py"
