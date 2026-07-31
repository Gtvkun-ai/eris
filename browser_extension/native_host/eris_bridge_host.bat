@echo off
REM Wrapper bat để Chrome/Brave biết cách gọi Python host
REM Chrome không gọi .py trực tiếp được; cần .bat làm launcher

set "SCRIPT_DIR=%~dp0"

REM Thử dùng Python từ venv của ERIS trước
set "ERIS_PYTHON=%SCRIPT_DIR%..\..\..\.venv\Scripts\python.exe"
if exist "%ERIS_PYTHON%" (
    "%ERIS_PYTHON%" "%SCRIPT_DIR%eris_bridge_host.py"
    goto :end
)

REM Fallback: Python từ PATH hệ thống
python "%SCRIPT_DIR%eris_bridge_host.py"

:end
