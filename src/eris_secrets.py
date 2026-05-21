import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SECRETS_PATH = _PROJECT_ROOT / "config" / "secrets.json"


@lru_cache(maxsize=1)
def _load_secrets() -> dict[str, Any]:
    if not _SECRETS_PATH.is_file():
        return {}
    try:
        payload = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lookup(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()

    for section_name in ("api_keys", "env", "secrets"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        value = section.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def get_secret(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value

    payload = _load_secrets()
    for name in names:
        value = _lookup(payload, name)
        if value:
            return value

    return default


def apply_secrets_to_environ() -> None:
    payload = _load_secrets()
    sections: list[dict[str, Any]] = [payload]
    for section_name in ("api_keys", "env", "secrets"):
        section = payload.get(section_name)
        if isinstance(section, dict):
            sections.append(section)

    for section in sections:
        for key, value in section.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if key and value.strip() and not os.environ.get(key):
                os.environ[key] = value.strip()
