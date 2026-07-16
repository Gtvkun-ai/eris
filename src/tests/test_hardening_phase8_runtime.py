# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.hardening_config import HardeningConfig
from runtime.hardening_release import (
    HardeningReleaseBuilder, HardeningReleaseGuard, REQUIRED_STABLE_FEATURES,
)
from runtime.runtime_settings_store import RuntimeSettingsStore


def _validation_report(path: Path, *, status: str = "pass", turns: int = 20, complete: bool = True) -> Path:
    events = path.with_suffix(".events.jsonl")
    events.write_text("{}\n", encoding="utf-8")
    scenarios = {
        name: {"pass": 1, "fail": 0}
        for name in (
            "greeting", "panel_delivery", "normal_chat", "repair_after_correction",
            "action_confirmation", "memory_provenance", "tts_same_language",
            "provider_recovery", "surface_sanitizer", "personality_banter",
        )
    }
    path.write_text(json.dumps({
        "status": status,
        "validation_id": "phase7-ok",
        "public_turns": turns,
        "scenario_coverage": {
            "complete": complete,
            "missing": [] if complete else ["panel_delivery"],
            "results": scenarios,
        },
        "events_path": str(events),
    }), encoding="utf-8")
    return path


def _mini_source(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    root = tmp_path / "src"
    (root / "runtime").mkdir(parents=True)
    (root / "settings").mkdir(parents=True)
    authority = ("runtime/a.py", "runtime/b.py", "settings/runtime_settings.json")
    (root / "runtime/a.py").write_text("A=1\n", encoding="utf-8")
    (root / "runtime/b.py").write_text("B=2\n", encoding="utf-8")
    settings = RuntimeSettingsStore.defaults()
    settings["hardening"].update({
        "profile": "stable",
        "provider_registry_strict": True,
        "legacy_cross_language_tts": False,
        "legacy_romaji_tts": False,
    })
    (root / "settings/runtime_settings.json").write_text(json.dumps(settings), encoding="utf-8")
    (root / "logs").mkdir(parents=True)
    (root / "logs/rollout_state.json").write_text(json.dumps({
        "manual_kills": {},
        "overrides": {
            feature: {"mode": "enabled", "canary_percent": 100.0}
            for feature in REQUIRED_STABLE_FEATURES
        },
    }), encoding="utf-8")
    return root, authority


def test_release_builder_rejects_unfinished_phase7(tmp_path: Path) -> None:
    root, authority = _mini_source(tmp_path)
    report = _validation_report(tmp_path / "validation.json", status="warn", turns=20)
    with pytest.raises(ValueError):
        HardeningReleaseBuilder(root).build(
            release_id="bad",
            validation_report=report,
            authority_files=authority,
        )


def test_release_manifest_guard_detects_source_tamper(tmp_path: Path) -> None:
    root, authority = _mini_source(tmp_path)
    report = _validation_report(tmp_path / "validation.json")
    manifest = HardeningReleaseBuilder(root).build(
        release_id="stable-test",
        validation_report=report,
        authority_files=authority,
    )
    manifest_path = manifest.save(root / "config/hardening_release.json")
    config = replace(
        HardeningConfig(),
        profile="stable",
        release_manifest_path=str(manifest_path),
        provider_registry_strict=True,
    )
    first = HardeningReleaseGuard(source_root=root, manifest_path=manifest_path, config=config).verify()
    assert first.ready
    (root / "runtime/a.py").write_text("A=999\n", encoding="utf-8")
    second = HardeningReleaseGuard(source_root=root, manifest_path=manifest_path, config=config).verify()
    assert not second.ready
    assert any(item.name == "source_hash:runtime/a.py" and item.status == "fail" for item in second.findings)


def test_stable_config_forces_romaji_legacy_off(monkeypatch, tmp_path: Path) -> None:
    from runtime import tts_engine
    settings = RuntimeSettingsStore.defaults()
    settings["hardening"].update({"profile": "stable", "legacy_romaji_tts": True})
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setenv("ERIS_RUNTIME_SETTINGS_PATH", str(path))
    monkeypatch.setenv("ERIS_PROJECT_ROOT", str(tmp_path))
    from runtime.runtime_settings_store import reset_runtime_settings_store_for_tests
    reset_runtime_settings_store_for_tests()
    assert tts_engine._edge_romaji_enabled() is False
    reset_runtime_settings_store_for_tests()


def test_strict_provider_registry_does_not_bypass_action_provider() -> None:
    from runtime.coordinator import RuntimeCoordinator

    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator.provider_registry = None
    coordinator.hardening_config = replace(HardeningConfig(), provider_registry_strict=True)
    coordinator.action_executor = SimpleNamespace(execute=lambda *_: "legacy-executed")
    with pytest.raises(RuntimeError, match="action_provider_unavailable"):
        coordinator._execute_action_provider("set_volume", "50")


def test_release_guard_detects_rollout_feature_disabled(tmp_path: Path) -> None:
    root, authority = _mini_source(tmp_path)
    report = _validation_report(tmp_path / "validation-rollout.json")
    manifest = HardeningReleaseBuilder(root).build(
        release_id="stable-rollout",
        validation_report=report,
        authority_files=authority,
    )
    manifest_path = manifest.save(root / "config/hardening_release.json")
    rollout_path = root / "logs/rollout_state.json"
    rollout = json.loads(rollout_path.read_text(encoding="utf-8"))
    rollout["overrides"]["tts_language_pin"]["mode"] = "disabled"
    rollout_path.write_text(json.dumps(rollout), encoding="utf-8")
    config = replace(
        HardeningConfig(),
        profile="stable",
        release_manifest_path=str(manifest_path),
        provider_registry_strict=True,
    )
    result = HardeningReleaseGuard(source_root=root, manifest_path=manifest_path, config=config).verify()
    assert not result.ready
    assert any(item.name == "rollout_state_hash" and item.status == "fail" for item in result.findings)
