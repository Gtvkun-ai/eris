@echo off
setlocal EnableExtensions

REM V40: xoa bytecode cu de Python nap dung cognitive continuity + affective voice.
REM Chay mot lan sau khi copy source V40 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V40] Xoa __pycache__ va .pyc cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"

echo [V40] Compile source...
python -m compileall -q runtime llm cortex
if errorlevel 1 goto :fail

echo [V40] Kiem tra ActiveConcern + Neuro proposal + V39 affective voice imports...
python -c "from cortex.active_concern import ACTIVE_CONCERN_VERSION,ActiveConcernView,semantic_overlap; from runtime.active_concern_runtime import ActiveConcernRuntime; from runtime.subject_proposals import AutonomousProposalSource; from runtime.affective_voice_state import AFFECTIVE_VOICE_VERSION; from runtime.eris_voice_contract import VOICE_CONTRACT_VERSION; assert ACTIVE_CONCERN_VERSION=='eris.cognitive_continuity.v40.active_concern'; assert AFFECTIVE_VOICE_VERSION=='eris.affective_voice.v39.state_authority'; assert VOICE_CONTRACT_VERSION=='eris.voice.v39.affect_authoritative'; assert semantic_overlap('autonomy can restraint','restraint keeps autonomy')>0; v=ActiveConcernView(concern_id='preflight',subject='continuity'); assert v.concern_id=='preflight'; print('[V40 PREFLIGHT] PASS:', ACTIVE_CONCERN_VERSION, '|', AFFECTIVE_VOICE_VERSION)"
if errorlevel 1 goto :fail

echo [V40] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V40 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
