@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "ERIS_PROJECT_ROOT=%~dp0"
set "HF_HOME=%~dp0.cache\huggingface"
set "XDG_CACHE_HOME=%~dp0.cache"
if not exist "%~dp0.eris_state" mkdir "%~dp0.eris_state"
if not defined ERIS_AGENT_SERVICE_DISCOVERY set "ERIS_AGENT_SERVICE_DISCOVERY=%~dp0.eris_state\agent_service.json"
set "ERIS_HOME=%~dp0.eris_home"
set "ERIS_STATE_DIR=%~dp0.eris_state"

rem VS Code service mode: no desktop app, no autonomous speech, no TTS warmup.
set "ERIS_VSCODE_SERVICE_MODE=1"
if not defined ERIS_RUNTIME_SETTINGS_PATH set "ERIS_RUNTIME_SETTINGS_PATH=%~dp0.eris_state\vscode_service_runtime_settings.json"
set "ERIS_TTS_ENABLED=0"
set "ERIS_COMMENTARY_ENABLED=0"
set "ERIS_AUTONOMOUS_EXPRESSION_ENABLED=0"
set "ERIS_INITIATIVE_ENABLED=0"
set "ERIS_AI_STARTUP_GREETING_ENABLED=0"
set "ERIS_AI_STARTUP_SCREEN_OPENING=0"
set "ERIS_AI_STARTUP_FORCE_SPEAK=0"
set "ERIS_RANDOM_CHAT_SEED_RESERVOIR_ENABLED=0"
set "ERIS_BACKGROUND_TUTOR_ENABLED=0"
set "ERIS_BACKGROUND_OBSERVER=0"
set "ERIS_MEMORY_BACKGROUND_DIGEST=0"
set "ERIS_BROWSER_BRIDGE_ENABLED=0"
set "ERIS_CHESS_BRIDGE_ENABLED=0"
set "ERIS_ELEVENLABS_POOL_UI_ENABLED=0"

if not exist "%~dp0config\secrets.json" (
    echo [SETUP] Missing config\secrets.json.
    exit /b 1
)

"%PYTHON%" "%~dp0src\vision.py"
