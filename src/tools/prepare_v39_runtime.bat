@echo off
setlocal EnableExtensions

REM V39: xoa bytecode cu de Python chac chan nap Affective Voice State moi.
REM Lam viec nay truoc khi chay run_eris.bat sau moi lan copy source V39 vao repo that.
cd /d "%~dp0\.."

echo [V39] Xoa __pycache__ va .pyc cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"

echo [V39] Compile source...
python -m compileall -q runtime llm cortex
if errorlevel 1 goto :fail

echo [V39] Kiem tra affective voice + chat + surface imports...
python -c "from runtime.affective_voice_state import AFFECTIVE_VOICE_VERSION,AffectiveVoiceTracker; from runtime.eris_voice_contract import VOICE_CONTRACT_VERSION,CHAT_VOICE_CORE_V39,AUTONOMOUS_VOICE_CORE_V39; from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter; from runtime.ai_orchestrated.surface_intent import SurfaceIntentEngine; p=AIRuntimeModelRouter._public_reply_prompt('vi','ja'); assert AFFECTIVE_VOICE_VERSION=='eris.affective_voice.v39.state_authority'; assert VOICE_CONTRACT_VERSION=='eris.voice.v39.affect_authoritative'; assert 'AFFECTIVE_VOICE_STATE' in p; assert 'ấm kín' not in p; assert 'AFFECTIVE_VOICE_STATE' in CHAT_VOICE_CORE_V39; assert 'AFFECTIVE_VOICE_STATE' in AUTONOMOUS_VOICE_CORE_V39; print('[V39 PREFLIGHT] PASS:', AFFECTIVE_VOICE_VERSION, '|', VOICE_CONTRACT_VERSION)"
if errorlevel 1 goto :fail

echo [V39] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V39 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
