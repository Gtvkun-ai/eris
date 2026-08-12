@echo off
setlocal EnableExtensions

REM V44 Contentful Initiative: xoa bytecode cu de desire/Neuro nap cung source.
REM Chay mot lan sau khi copy source V44 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V44] Xoa __pycache__, .pyc va pytest cache cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"
if exist ".pytest_cache" rd /s /q ".pytest_cache"

echo [V44] Compile runtime/cortex/llm/memory...
python -m compileall -q runtime cortex llm memory
if errorlevel 1 goto :fail

echo [V44] Kiem tra content-first initiative + V43 mood + V42 cognition...
python -c "from runtime.expression_urge_runtime import EXPRESSION_URGE_VERSION, ExpressionUrgeRuntime; from cortex.affective_dynamics import AFFECTIVE_DYNAMICS_VERSION; from cortex.cognitive_event import COGNITIVE_EVENT_VERSION; assert EXPRESSION_URGE_VERSION == 'eris.initiative.v44.contentful_urge'; print('[V44 PREFLIGHT] PASS: ' + EXPRESSION_URGE_VERSION + ' | ' + AFFECTIVE_DYNAMICS_VERSION + ' | ' + COGNITIVE_EVENT_VERSION)"
if errorlevel 1 goto :fail

echo [V44] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V44 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
