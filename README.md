# Eris

Eris is a local Windows companion/runtime project.

The Python runtime is the main brain. Godot 4 .NET is the optional body UI that receives local UDP state from the runtime.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\setup_secrets.bat
.\run_doctor.bat
.\run_smoke_test.bat
```

Then run:

```powershell
.\run_runtime.bat
```

Open `project.godot` in Godot 4 .NET only when you want the body UI.

## Non-Dev User Guide

For a release/new machine, start here:

```powershell
.\ErisSetup.exe
.\open_user_guide.bat
```

This opens the Vietnamese quick guide and the video-recording script. The important account tools are:

```powershell
.\run_deepseek_pool_ui.bat
.\apply_deepseek_pool_to_secrets.bat
.\run_elevenlabs_pool_ui.bat
```

## Local Config

Runtime config lives in `.env` or `config\secrets.json`.

For a new machine or release build, run:

```powershell
.\setup_secrets.bat
```

It creates `config\secrets.json` from `config\secrets.example.json` if missing, then opens the guide and the file to edit. More detail: [config/SECRETS_SETUP.md](config/SECRETS_SETUP.md).

Do not commit real keys. These files are intentionally ignored:

```text
.env
config/secrets.json
```

For a cheap local smoke setup:

```powershell
Copy-Item .\env-examples\.env.local-smoke.example .\.env -Force
```

Then add at least one model key:

```text
DEEPSEEK_API_KEY
ERIS_REMOTE_API_KEY
GEMINI_API_KEY
OPENAI_API_KEY
ERIS_GROQ_API_KEY
```

If you do not have voice/TTS keys yet, keep:

```text
ERIS_TTS_ENABLED=0
```

If you do not run Whale2API/DS2API locally, keep:

```text
ERIS_DS2API_ENABLED=0
```

## Useful Commands

```powershell
.\run_doctor.bat
.\run_smoke_test.bat
.\run_runtime.bat
.\open_user_guide.bat
.\setup_secrets.bat
.\apply_deepseek_pool_to_secrets.bat
.\setup_tutor_browser.bat
.\run_elevenlabs_pool_ui.bat
.\run_deepseek_pool_ui.bat
```

More detail: [docs/LOCAL_RUNBOOK.md](docs/LOCAL_RUNBOOK.md).

## Main Paths

```text
src/vision.py          Python runtime entrypoint
src/runtime/           runtime coordination, settings, TTS, tools
src/llm/               model clients, routing, key pool
src/memory/            memory engine
body/                  Godot/C# body UI
browser_extension/     browser bridge
tests/                 root regression tests
src/tests/             source-tree regression tests
```

## Test Profiles

Smoke:

```powershell
.\run_smoke_test.bat
```

Custom pytest target:

```powershell
.\.venv\Scripts\python.exe .\run_tests.py tests\test_deepseek_provider.py
```

Full root suite:

```powershell
.\.venv\Scripts\python.exe .\run_tests.py
```
