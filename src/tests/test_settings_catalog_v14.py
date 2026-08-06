from __future__ import annotations

from runtime.runtime_settings_store import RuntimeSettingsStore
from runtime.settings_catalog import build_settings_catalog
from runtime.settings_protocol import normalize_settings_message


def _default_paths() -> set[str]:
    defaults = RuntimeSettingsStore.defaults()
    return {
        f"{section}.{key}"
        for section, values in defaults.items()
        if section != "version" and isinstance(values, dict)
        for key in values
    }


def test_catalog_covers_every_runtime_setting_without_secrets() -> None:
    defaults = RuntimeSettingsStore.defaults()
    catalog = build_settings_catalog(defaults)
    fields = {item["path"]: item for item in catalog["fields"]}

    assert catalog["schema_version"] == 16
    assert set(fields) == _default_paths()
    assert len(catalog["sections"]) == 25
    assert all(item["owner"] == "brain_runtime" for item in fields.values())
    assert fields["tts.provider"]["surface"] == "voice"
    assert fields["chat.reasoning_effort"]["surface"] == "advanced"
    assert fields["tts.provider"]["options"] == ["elevenlabs", "gemini"]
    assert fields["engagement.max_events"]["min"] == 24
    assert fields["engagement.max_events"]["max"] == 4096
    assert "opening_director.allow_sexual_content" in fields
    assert fields["opening_director.allow_sexual_content"]["label"] == "Cho phep noi dung 18+"
    rendered_fields = repr(catalog["fields"]).lower()
    assert "api_key" not in rendered_fields
    assert "secret" not in rendered_fields


def test_opening_director_defaults_are_permissive() -> None:
    defaults = RuntimeSettingsStore.defaults()["opening_director"]
    assert defaults["allow_romantic_flirt"] is True
    assert defaults["allow_sexual_content"] is True
    assert defaults["romantic_flirt_opt_in"] is True
    assert defaults["age_band"] == "confirmed_adult"


def test_scope_ownership_rejects_cross_surface_writes() -> None:
    advanced = normalize_settings_message({
        "scope": "advanced",
        "settings": {
            "chat": {"reasoning_effort": "high"},
            "danger_zone": {"maintenance_enabled": False},
            "tts": {"provider": "gemini"},
        },
    })
    assert advanced.patch["chat"]["reasoning_effort"] == "high"
    assert advanced.patch["danger_zone"]["maintenance_enabled"] is False
    assert "tts" not in advanced.patch
    assert "tts" in advanced.rejected_fields

    voice = normalize_settings_message({
        "scope": "tts",
        "settings": {
            "tts": {
                "provider": "elevenlabs",
                "elevenlabs_model": "eleven_v3",
            },
            "chat": {"reasoning_effort": "low"},
        },
    })
    assert voice.patch == {
        "tts": {
            "provider": "elevenlabs",
            "elevenlabs_model": "eleven_v3",
        }
    }
    assert "chat" in voice.rejected_fields
