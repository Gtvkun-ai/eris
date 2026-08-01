from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ENV_PATH = ROOT / ".env"
SECRETS_PATH = ROOT / "config" / "secrets.json"

REQUIRED_IMPORTS = [
    "requests",
    "PIL",
    "psutil",
    "mss",
    "playwright",
    "uiautomation",
    "google.genai",
    "pytest",
]

IMPORTANT_ENV = [
    "ERIS_REMOTE_API_ENABLED",
    "ERIS_REMOTE_PROVIDER",
    "ERIS_REMOTE_BASE_URL",
    "ERIS_REMOTE_MODEL",
    "ERIS_REMOTE_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "ERIS_DS2API_ENABLED",
    "ERIS_DS2API_API_KEY",
    "ERIS_TTS_ENABLED",
    "ERIS_SPEECH_API_KEY",
    "ELEVENLABS_API_KEY",
    "ERIS_ELEVENLABS_API_KEY",
    "ERIS_GROQ_API_KEY",
    "OPENAI_API_KEY",
    "ERIS_HOME",
]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _flatten_secret_strings(payload: object) -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, str):
                found[key] = value.strip()
            elif isinstance(value, dict):
                found.update(_flatten_secret_strings(value))
    return found


def _load_secret_strings(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _flatten_secret_strings(payload)


def _state(ok: bool) -> str:
    return "OK" if ok else "MISS"


def main() -> int:
    sys.path.insert(0, str(SRC))
    sys.path.insert(1, str(ROOT))

    print("=== Eris Doctor ===")
    print(f"root={ROOT}")
    print(f"python={sys.executable}")
    print(f"version={sys.version.split()[0]}")
    print()

    env_values = _parse_env_file(ENV_PATH)
    secret_values = _load_secret_strings(SECRETS_PATH)

    print("Files")
    for path in (ENV_PATH, ROOT / ".env.example", SECRETS_PATH, ROOT / "project.godot", ROOT / "src" / "vision.py"):
        print(f"  {_state(path.exists())} {path.relative_to(ROOT)}")

    print()
    print("Python imports")
    missing_imports: list[str] = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
            ok = True
        except Exception:
            ok = False
            missing_imports.append(module_name)
        print(f"  {_state(ok)} {module_name}")

    print()
    print("Env/key presence (values hidden)")
    missing_critical: list[str] = []
    for name in IMPORTANT_ENV:
        env_value = env_values.get(name, "").strip()
        secret_value = secret_values.get(name, "").strip()
        filled = bool(os.environ.get(name, "").strip() or env_value or secret_value)
        source = "os-env" if os.environ.get(name, "").strip() else ("env" if env_value else ("secrets" if secret_value else "-"))
        print(f"  {_state(filled)} {name} source={source}")
        if name in {"ERIS_REMOTE_PROVIDER", "ERIS_REMOTE_MODEL"} and not filled:
            missing_critical.append(name)

    has_model_key = any(
        (os.environ.get(name, "").strip() or env_values.get(name, "").strip() or secret_values.get(name, "").strip())
        for name in ("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ERIS_GROQ_API_KEY")
    )
    if not has_model_key:
        missing_critical.append("one model API key")

    print()
    print("Recommended next commands")
    print("  .\\run_smoke_test.bat")
    print("  .\\run_runtime.bat")

    if missing_imports or missing_critical:
        print()
        if missing_imports:
            print("Missing imports: " + ", ".join(missing_imports))
            print("Fix: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        if missing_critical:
            print("Missing critical config: " + ", ".join(missing_critical))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
