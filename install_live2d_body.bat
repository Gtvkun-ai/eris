@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem File nay nam trong thu muc src. Uu tien venv cua repo o thu muc cha.
set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -m pip install -r "%~dp0requirements-live2d.txt"
if errorlevel 1 goto :error

echo.
echo [Eris Live2D] Da cai live2d-py va glfw.
exit /b 0

:error
echo.
echo [Eris Live2D] Cai dependency that bai.
exit /b 1
