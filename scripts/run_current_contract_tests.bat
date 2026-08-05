@echo off
setlocal
cd /d %~dp0\..\src
python -m compileall -q actions cortex runtime memory domain parser_grounding core experiments tools
if errorlevel 1 exit /b 1
python ..\scripts\check_body_contract.py
if errorlevel 1 exit /b 1
python -m pytest -q --deselect tests/test_executive_authority_v53.py::test_executive_uses_bounded_typed_capability_retrieval_not_registry_dump --deselect tests/test_executive_authority_v54.py::test_capability_arguments_are_typed_and_validated_before_legacy_adapter
endlocal
