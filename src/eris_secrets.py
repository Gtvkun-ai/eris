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


def _lookup_path(payload: dict[str, Any], path: str, *, default: Any = None) -> Any:
    if not path:
        return default

    current: Any = payload
    for part in str(path).split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def _provider_slot_payload(payload: dict[str, Any], provider: str, slot: str) -> dict[str, Any]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    provider_payload = providers.get(str(provider).strip().lower())
    if not isinstance(provider_payload, dict):
        return {}

    slot_name = str(slot or "default").strip()
    direct = provider_payload.get(slot_name)
    if isinstance(direct, dict):
        return direct

    # Backward-safe: cho phép providers.gemini = {"api_key": "...", ...}
    if any(key in provider_payload for key in ("api_key", "base_url", "model", "organization", "project")):
        return provider_payload
    return {}


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


def get_config(path: str, default: Any = None) -> Any:
    """Đọc config lồng nhau từ env hoặc secrets.json.

    Ưu tiên env nếu path không có dấu chấm hoặc nếu biến env cùng tên tồn tại.
    Ví dụ:
    - get_config("ERIS_REMOTE_MODEL")
    - get_config("subconscious_runtime.lanes.lane3.model")
    """

    env_value = os.environ.get(path, None)
    if isinstance(env_value, str) and env_value.strip():
        return env_value.strip()

    payload = _load_secrets()
    if "." not in path:
        direct = _lookup(payload, path)
        if direct:
            return direct

    value = _lookup_path(payload, path, default=default)
    return value


def get_provider_profile(provider: str, *, slot: str = "default", default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lấy cấu hình provider theo slot riêng.

    Ví dụ:
    - get_provider_profile("gemini", slot="remote_main")
    - get_provider_profile("openai", slot="lane3_synthesis")
    """

    payload = _load_secrets()
    profile = _provider_slot_payload(payload, provider, slot)
    if profile:
        return dict(profile)
    return dict(default or {})


def get_agent_profile(
    agent_name: str,
    *,
    default_provider: str = "",
    default_slot: str = "default",
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve provider profile cho một job/agent cụ thể.

    Schema:
    {
      "agent_keys": {
        "search_web": {"provider": "gemini", "slot": "search_web"}
      }
    }
    """

    payload = _load_secrets()
    agent_keys = payload.get("agent_keys")
    provider = default_provider
    slot = default_slot
    if isinstance(agent_keys, dict):
        agent_payload = agent_keys.get(agent_name)
        if isinstance(agent_payload, dict):
            provider = str(agent_payload.get("provider") or provider or "").strip().lower()
            slot = str(agent_payload.get("slot") or slot or "default").strip()
            direct_profile = agent_payload.get("profile")
            if isinstance(direct_profile, dict):
                return dict(direct_profile)

    if provider:
        profile = get_provider_profile(provider, slot=slot, default=default)
        if profile:
            merged = dict(profile)
            merged.setdefault("provider", provider)
            merged.setdefault("slot", slot)
            return merged
    return dict(default or {})


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
