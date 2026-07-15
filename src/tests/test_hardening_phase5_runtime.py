# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime.hardening_verifier import HardeningVerifier
from runtime.provider_adapters import (
    ActionExecutorProvider,
    MemoryKernelProvider,
    SpeechEngineProvider,
    TokenPressureBudgetProvider,
    build_provider_registry,
)
from runtime.provider_interfaces import ProviderRegistry


class _Action:
    def execute(self, action_name, action_input=""):
        return (action_name, action_input)


class _Speech:
    _ok = True
    _closed = False

    def __init__(self):
        self.called = None

    def synthesize(self, text, **kwargs):
        self.called = (text, kwargs)
        return b"wav"

    def cache_signature(self):
        return "voice|model|vi"


class _Memory:
    def recall(self, request):
        return {"query": request}

    def commit(self, record):
        return {"committed": record}


class _Governor:
    def plan_request(self, provider, **kwargs):
        return {"provider": provider, **kwargs}


@dataclass
class _Contract:
    language: str = "vi"
    locale: str = "vi-VN"
    voice_family: str = "eris_vi"
    turn_id: str = "turn-1"
    segment_id: int = 2


def test_provider_registry_builds_all_runtime_adapters():
    registry = build_provider_registry(
        action_executor=_Action(), speech_engine=_Speech(), memory=_Memory(), budget_governor=_Governor()
    )
    assert registry.kinds() == ("action", "budget", "memory", "speech")
    assert all(item.ready for item in registry.health().values())
    result = registry.get("action").execute("set_volume", "50")
    assert result.action_name == "set_volume"
    assert result.action_input == "50"
    assert result.success is False


def test_registry_rejects_duplicate_but_replace_supports_hot_reload():
    registry = ProviderRegistry()
    registry.register("action", ActionExecutorProvider(_Action()))
    with pytest.raises(KeyError):
        registry.register("action", ActionExecutorProvider(_Action()))
    replacement = ActionExecutorProvider(_Action())
    registry.replace("action", replacement)
    assert registry.get("action") is replacement
    assert registry.unregister("action") is replacement
    assert registry.get_optional("action") is None


def test_speech_adapter_preserves_language_and_voice_contract():
    engine = _Speech()
    provider = SpeechEngineProvider(engine)
    assert provider.synthesize(_Contract(), "Xin chào") == b"wav"
    text, kwargs = engine.called
    assert text == "Xin chào"
    assert kwargs["language_hint"] == "vi"
    assert kwargs["locale"] == "vi-VN"
    assert kwargs["voice_family"] == "eris_vi"
    assert kwargs["turn_id"] == "turn-1"
    assert kwargs["segment_id"] == 2


def test_memory_and_budget_adapters_use_existing_runtime_methods():
    memory = MemoryKernelProvider(_Memory())
    assert memory.query("tên") == {"query": "tên"}
    assert memory.commit({"name": "Nam"}) == {"committed": {"name": "Nam"}}
    budget = TokenPressureBudgetProvider(_Governor())
    plan = budget.plan(provider="gemini", lane="chat", prompt_tokens=5000, output_tokens=800)
    assert plan["provider"] == "gemini"
    assert plan["lane"] == "chat"
    assert plan["requested_output_tokens"] == 800


def _good_snapshot():
    return {
        "hardening_public_turn_total": {"count": 24, "sum": 24.0},
        "action_confirmation_total": {"count": 10, "sum": 10.0},
        "false_success_action_rate": {"count": 0, "sum": 0.0},
        "memory_provenance_total": {"count": 8, "sum": 8.0},
        "memory_assert_without_provenance_rate": {"count": 0, "sum": 0.0},
        "repair_state_event_total": {"count": 12, "sum": 12.0},
        "repair_loop_rate": {"count": 0, "sum": 0.0},
        "tts_fallback_total": {"count": 4, "sum": 4.0},
        "tts_fallback_same_language_rate": {"count": 4, "sum": 4.0},
        "tts_locale_switch_rate": {"count": 0, "sum": 0.0},
        "surface_sensitive_leak_total": {"count": 0, "sum": 0.0},
        "chat_latency_ms": {"count": 24, "sum": 24000.0, "p95": 1600.0},
        "tts_latency_ms": {"count": 24, "sum": 36000.0, "p95": 2400.0},
    }


def test_verifier_passes_clean_canary_with_ready_providers(monkeypatch):
    monkeypatch.setenv("ERIS_HARDENING_VERIFY_MIN_TURNS", "20")
    monkeypatch.setenv("ERIS_HARDENING_VERIFY_MIN_ACTIONS", "5")
    report = HardeningVerifier().verify(
        _good_snapshot(),
        provider_health={
            "action": {"ready": True, "provider": "action_executor"},
            "memory": {"ready": True, "provider": "memory_kernel"},
        },
    )
    assert report.status == "pass"
    assert report.public_turns == 24
    assert not [item for item in report.findings if item.status == "fail"]


def test_verifier_fails_hard_zero_invariants():
    snapshot = _good_snapshot()
    snapshot["tts_locale_switch_rate"] = {"count": 1, "sum": 1.0}
    snapshot["surface_sensitive_leak_total"] = {"count": 1, "sum": 1.0}
    report = HardeningVerifier().verify(snapshot)
    assert report.status == "fail"
    failed = {item.name for item in report.findings if item.status == "fail"}
    assert "tts_locale_switch_rate" in failed
    assert "surface_sensitive_leak_total" in failed


def test_verifier_warns_when_live_sample_is_too_small(monkeypatch):
    monkeypatch.setenv("ERIS_HARDENING_VERIFY_MIN_TURNS", "20")
    snapshot = _good_snapshot()
    snapshot["hardening_public_turn_total"] = {"count": 4, "sum": 4.0}
    report = HardeningVerifier().verify(snapshot)
    finding = next(item for item in report.findings if item.name == "public_turn_sample")
    assert finding.status == "warn"


def test_verifier_fails_unhealthy_registered_provider():
    report = HardeningVerifier().verify(
        _good_snapshot(),
        provider_health={"speech": {"ready": False, "provider": "speech_engine", "reason": "tts_not_ready"}},
    )
    assert report.status == "fail"
    assert any(item.name == "provider_ready:speech" and item.status == "fail" for item in report.findings)


def test_rollout_registers_p1_repair_and_repeat_features():
    from runtime.rollout_control import FEATURES

    assert "repair_state_ttl" in FEATURES
    assert "semantic_repeat_guard" in FEATURES


def test_health_gate_rolls_back_repair_state_feature(tmp_path):
    from runtime.hardening_rollout import HardeningHealthGate
    from runtime.rollout_control import RolloutController

    controller = RolloutController(state_path=tmp_path / "rollout.json")
    gate = HardeningHealthGate(controller)
    gate.min_samples = 1
    gate.repair_loop_baseline = 0.01
    findings = gate.evaluate({
        "repair_state_event_total": {"count": 10, "sum": 10.0},
        "repair_loop_rate": {"count": 2, "sum": 2.0},
    })
    finding = next(item for item in findings if item.metric == "repair_loop_rate")
    assert finding.feature == "repair_state_ttl"
    assert finding.triggered is True
    assert controller.decide("repair_state_ttl", session_id="x").killed is True
