from __future__ import annotations

from runtime.companion_model_routing import CompanionRoutingPolicy
from runtime.runtime_settings_store import (
    RuntimeSettingsStore,
    get_runtime_settings_store,
    reset_runtime_settings_store_for_tests,
)


def test_v12_settings_migrate_companion_routing_defaults() -> None:
    migrated, changed = RuntimeSettingsStore._migrate_payload(
        {"version": 12, "chat": {"language": "vi"}}
    )
    assert changed is True
    assert migrated["version"] == 14
    assert migrated["chat"]["companion_routing_enabled"] is True
    assert migrated["chat"]["companion_pro_threshold"] == 0.58
    assert migrated["chat"]["companion_style_uses_pro"] is True


def test_companion_routing_policy_reads_live_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ERIS_RUNTIME_SETTINGS_PATH", str(tmp_path / "settings.json"))
    reset_runtime_settings_store_for_tests()
    try:
        store = get_runtime_settings_store()
        result = store.apply_patch(
            {
                "chat": {
                    "companion_pro_threshold": 0.73,
                    "companion_style_uses_pro": False,
                    "companion_simple_turns_stay_flash": False,
                }
            }
        )
        assert result.rejected == ()
        policy = CompanionRoutingPolicy.from_runtime()
        assert policy.pro_threshold == 0.73
        assert policy.route_style_to_pro is False
        assert policy.simple_turns_stay_flash is False
    finally:
        reset_runtime_settings_store_for_tests()
