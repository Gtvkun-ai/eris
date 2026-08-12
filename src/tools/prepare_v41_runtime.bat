@echo off
setlocal EnableExtensions

REM V41 Memory Hygiene: xoa bytecode cu de source admission/cleanup/panel duoc nap dong bo.
REM Chay mot lan sau khi copy source V41 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V41] Xoa __pycache__ va .pyc cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"

echo [V41] Compile memory/runtime/cortex...
python -m compileall -q memory runtime cortex
if errorlevel 1 goto :fail

echo [V41] Kiem tra admission + feed trace + DeepSeek cleanup protocol...
python -c "from memory.memory_admission import MemoryAdmissionPolicy; from memory.memory_feed_trace import MemoryFeedTraceJournal; from runtime.memory_gc_service import MemoryGCService; from runtime.living_user_panel import handle_memory_panel_request; from runtime.behavior_observation import BehaviorSignal; from cortex.private_mind.thought_continuity import ThoughtContinuityStore; p=MemoryAdmissionPolicy(); assert p is not None; assert BehaviorSignal(family='x',source='y',public_text='raw').to_persisted_dict()['public_text']==''; print('[V41 PREFLIGHT] PASS: eris.memory_hygiene.v41.admission | eris.memory_feed_trace.v41 | deepseek_cleanup_control')"
if errorlevel 1 goto :fail

echo [V41] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V41 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
