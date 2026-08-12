@echo off
setlocal EnableExtensions

REM V38: rebuild bytecode from source thật để tránh .pyc cũ kéo prompt/personality cũ trở lại.
cd /d "%~dp0\.."

echo [V38] Xoa __pycache__ va .pyc cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"

echo [V38] Compile source...
python -m compileall -q runtime llm cortex
if errorlevel 1 goto :fail

echo [V38] Kiem tra voice contract + public writer imports...
python -c "from runtime.eris_voice_contract import VOICE_CONTRACT_VERSION,surface_voice_rules; from llm.prompt_compaction import CACHEABLE_CHAT_PREFIX_V2; from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter; from llm.contracts import STYLE_FALLBACK_PROMPT; assert 'am rat it' not in STYLE_FALLBACK_PROMPT.lower(); assert surface_voice_rules(1); print('[V38 PREFLIGHT] PASS:', VOICE_CONTRACT_VERSION)"
if errorlevel 1 goto :fail

echo [V38] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V38 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
