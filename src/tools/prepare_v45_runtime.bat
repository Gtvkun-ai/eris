@echo off
setlocal EnableExtensions

REM V45: xoa bytecode cu de causal material / urge / cognition nap cung mot source.
REM Chay mot lan sau khi copy source V45 vao repo that, truoc run_eris.bat.
cd /d "%~dp0\.."

echo [V45] Xoa __pycache__, .pyc va pytest cache cu...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
for /r %%F in (*.pyc) do @if exist "%%F" del /q "%%F"
if exist ".pytest_cache" rd /s /q ".pytest_cache"

echo [V45] Compile runtime/cortex/llm/memory...
python -m compileall -q runtime cortex llm memory
if errorlevel 1 goto :fail

echo [V45] Kiem tra causal mental material + V44.1 urge + V42 cognition...
python -c "from cortex.mental_material import MENTAL_MATERIAL_VERSION; from runtime.mental_material_runtime import MENTAL_MATERIAL_RUNTIME_VERSION; from runtime.expression_urge_runtime import EXPRESSION_URGE_VERSION; from cortex.cognitive_event import COGNITIVE_EVENT_VERSION; assert MENTAL_MATERIAL_VERSION == 'eris.mental_material.v45.causal_association'; assert MENTAL_MATERIAL_RUNTIME_VERSION == MENTAL_MATERIAL_VERSION; assert EXPRESSION_URGE_VERSION == 'eris.initiative.v44_1.contentful_urge_lifecycle'; print('[V45 PREFLIGHT] PASS: ' + MENTAL_MATERIAL_VERSION + ' | ' + EXPRESSION_URGE_VERSION + ' | ' + COGNITIVE_EVENT_VERSION)"
if errorlevel 1 goto :fail

echo [V45] San sang. Bay gio chay run_eris.bat.
exit /b 0

:fail
echo [V45 PREFLIGHT] FAIL. Dung launch de tranh source/bytecode lech nhau.
exit /b 1
