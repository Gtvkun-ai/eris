@echo off
setlocal EnableExtensions

REM V42 Event-Driven Mind: xoa bytecode cu de cognition/Neuro/Surface nap dong bo.
REM Chay mot lan sau khi copy source V42 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V42] Xoa __pycache__, .pyc va pytest cache cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"
if exist ".pytest_cache" rd /s /q ".pytest_cache"

echo [V42] Compile runtime/cortex/llm/memory...
python -m compileall -q runtime cortex llm memory
if errorlevel 1 goto :fail

echo [V42] Kiem tra event-driven cognition + typed claim authority...
python -c "from cortex.cognitive_event import COGNITIVE_EVENT_VERSION; from cortex.active_concern import ACTIVE_CONCERN_VERSION; from runtime.claim_domain_contract import CLAIM_DOMAIN_VERSION, validate_claim_manifest; from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex; assert validate_claim_manifest([], allowed_domains=('opinion',), text_present=True).allowed; assert not validate_claim_manifest(None, allowed_domains=('opinion',), text_present=True).allowed; print('[V42 PREFLIGHT] PASS: ' + COGNITIVE_EVENT_VERSION + ' | ' + ACTIVE_CONCERN_VERSION + ' | ' + CLAIM_DOMAIN_VERSION)"
if errorlevel 1 goto :fail

echo [V42] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V42 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
