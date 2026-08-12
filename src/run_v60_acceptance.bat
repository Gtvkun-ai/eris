@echo off
setlocal
cd /d "%~dp0"
python -m pytest -q tests\test_v60_telemetry_meaning.py tests\test_v59_existential_desire.py tests\test_v58_initiative_controller.py tests\test_desktop_semantic_environment_v1.py tests\test_deep_environment_native_v2.py tests\test_deep_environment_scheduler_v5.py tests\test_temporal_mind_v19.py
exit /b %errorlevel%
