@echo off
setlocal EnableExtensions

REM V43 Event-Driven Mood: xoa bytecode cu de affect/voice/body nap cung source.
REM Chay mot lan sau khi copy source V43 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V43] Xoa __pycache__, .pyc va pytest cache cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"
if exist ".pytest_cache" rd /s /q ".pytest_cache"

echo [V43] Compile runtime/cortex/llm/memory...
python -m compileall -q runtime cortex llm memory
if errorlevel 1 goto :fail

echo [V43] Kiem tra event-driven affect + shared voice projection...
python -c "from cortex.affective_dynamics import AFFECTIVE_DYNAMICS_VERSION, effective_affect_values; from cortex.cognitive_event import COGNITIVE_EVENT_VERSION; from cortex.internal_state import PersistentInternalState; from runtime.affective_voice_state import AFFECTIVE_VOICE_VERSION; s=PersistentInternalState(); a=effective_affect_values(s); assert 'valence' in a and 'playfulness' in a; print('[V43 PREFLIGHT] PASS: ' + AFFECTIVE_DYNAMICS_VERSION + ' | ' + AFFECTIVE_VOICE_VERSION + ' | ' + COGNITIVE_EVENT_VERSION)"
if errorlevel 1 goto :fail

echo [V43] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V43 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
