# Eris Local Runbook

This runbook keeps the local developer commands in one place. Run every command from the repository root.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\setup_secrets.bat
```

`setup_secrets.bat` creates `config\secrets.json` from `config\secrets.example.json` if needed. Keep real keys, tokens, account CSV files, and runtime databases out of Git.

## Health Checks

```powershell
.\run_doctor.bat
.\run_smoke_test.bat
```

The smoke profile runs a small regression slice under `src/tests`. For a direct Python invocation:

```powershell
.\.venv\Scripts\python.exe .\run_tests.py smoke
```

## Test Profiles

```powershell
.\.venv\Scripts\python.exe .\run_tests.py
.\.venv\Scripts\python.exe .\run_tests.py src\tests\test_deepseek_provider.py
.\.venv\Scripts\python.exe .\run_tests.py humanness
```

The default profile collects only `src/tests`. Generated runtimes, vendored reference repositories, scratch probes, and service subprojects are intentionally excluded from root pytest collection.

## Runtime

```powershell
.\run_runtime.bat
```

Open `project.godot` in Godot 4 .NET only when you want the optional body UI.

## Account Tools

```powershell
.\run_deepseek_pool_ui.bat
.\apply_deepseek_pool_to_secrets.bat
.\run_elevenlabs_pool_ui.bat
.\setup_tutor_browser.bat
```

Account files and keyring material are local runtime state. If they accidentally appear in `git status`, remove them from tracking with `git rm --cached <path>` and rotate any real secret that was exposed.
