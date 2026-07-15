# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from runtime.hardening_baseline import HardeningBaseline
from runtime.hardening_canary import CanaryConfig, HardeningCanaryManager
from runtime.hardening_verifier import HardeningVerifier
from runtime.observability import ErisObservability
from runtime.rollout_control import RolloutController
from runtime.speech_provider_chain import (
    CallableSpeechProvider,
    SameLanguageSpeechFallbackChain,
    SpeechFallbackRequest,
)


def _snapshot(*, false_success: int = 0, action_total: int = 10):
    return {
        "hardening_public_turn_total": {"count": 24, "sum": 24.0},
        "action_confirmation_total": {"count": action_total, "sum": float(action_total)},
        "false_success_action_rate": {"count": false_success, "sum": float(false_success)},
        "memory_provenance_total": {"count": 8, "sum": 8.0},
        "memory_assert_without_provenance_rate": {"count": 0, "sum": 0.0},
        "repair_state_event_total": {"count": 10, "sum": 10.0},
        "repair_loop_rate": {"count": 0, "sum": 0.0},
        "tts_locale_switch_rate": {"count": 0, "sum": 0.0},
        "surface_sensitive_leak_total": {"count": 0, "sum": 0.0},
        "chat_latency_ms": {"count": 24, "sum": 24000.0, "p95": 1500.0},
        "tts_latency_ms": {"count": 24, "sum": 36000.0, "p95": 2500.0},
    }


def test_speech_fallback_chain_rejects_wrong_locale_then_uses_same_language():
    calls = []

    def wrong(request):
        calls.append("wrong")
        return b"ja-audio", {"locale": "ja-JP", "voice": "ja-JP-NanamiNeural"}

    def right(request):
        calls.append("right")
        return b"vi-audio", {"locale": "vi-VN", "voice": "vi-VN-HoaiMyNeural"}

    chain = SameLanguageSpeechFallbackChain((
        CallableSpeechProvider("wrong", wrong),
        CallableSpeechProvider("right", right),
    ))
    result = chain.synthesize(SpeechFallbackRequest("Xin chào", "vi", "vi-VN", cause="RateLimitError"))
    assert result.audio == b"vi-audio"
    assert result.provider == "right"
    assert calls == ["wrong", "right"]
    assert result.attempts[0].error_kind == "locale_mismatch"
    assert result.attempts[1].success is True


def test_speech_fallback_chain_calls_each_provider_at_most_once():
    calls = {"a": 0, "b": 0}

    def fail_a(request):
        calls["a"] += 1
        raise RuntimeError("quota")

    def fail_b(request):
        calls["b"] += 1
        return b""

    chain = SameLanguageSpeechFallbackChain((
        CallableSpeechProvider("a", fail_a),
        CallableSpeechProvider("b", fail_b),
    ))
    result = chain.synthesize(SpeechFallbackRequest("test", "en", "en-US"))
    assert result.success is False
    assert calls == {"a": 1, "b": 1}


def test_baseline_roundtrip_and_verifier_uses_measured_rate(tmp_path):
    baseline = HardeningBaseline.from_snapshot(_snapshot(false_success=1, action_total=10), source="stable.jsonl")
    path = tmp_path / "baseline.json"
    baseline.save(path)
    loaded = HardeningBaseline.load(path)
    assert loaded.false_success_action_rate == 0.1
    assert loaded.source == "stable.jsonl"

    passing = HardeningVerifier(baseline=loaded).verify(_snapshot(false_success=1, action_total=10))
    assert not any(item.name == "false_success_action_rate" and item.status == "fail" for item in passing.findings)

    failing = HardeningVerifier(baseline=loaded).verify(_snapshot(false_success=2, action_total=10))
    finding = next(item for item in failing.findings if item.name == "false_success_action_rate")
    assert finding.status == "fail"
    assert str(finding.threshold) == "<=0.120000"
    assert failing.baseline["source"] == "stable.jsonl"


def test_observability_window_excludes_old_metrics(tmp_path):
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "obs.jsonl")
    store.write_jsonl = False
    store.increment("hardening_public_turn_total", timestamp=1.0) if False else None
    # emit cho phép timestamp chính xác; increment cố ý không nhận timestamp.
    store.emit("metric", "hardening_public_turn_total", value=5, timestamp=10.0)
    store.emit("metric", "hardening_public_turn_total", value=2, timestamp=20.0)
    snapshot = store.metric_snapshot_since(15.0)
    assert snapshot["hardening_public_turn_total"]["sum"] == 2.0
    assert len(store.events_since(15.0)) == 1


def test_provider_health_snapshot_can_be_replayed_from_jsonl(tmp_path):
    path = tmp_path / "obs.jsonl"
    store = ErisObservability(enabled=True, jsonl_path=path)
    store.write_jsonl = True
    store.log("provider_health_snapshot", fields={
        "providers": {"speech": {"ready": True, "provider": "speech_engine"}}
    })
    replay = ErisObservability.replay_jsonl(path)
    fields = replay.latest_fields("provider_health_snapshot")
    assert fields["providers"]["speech"]["ready"] is True


def _record_clean_canary_metrics(store: ErisObservability, index: int) -> None:
    store.increment("hardening_public_turn_total")
    store.observe("chat_latency_ms", 1000 + index)
    store.observe("tts_latency_ms", 1600 + index)
    if index <= 10:
        store.increment("action_confirmation_total")
    if index <= 8:
        store.increment("memory_provenance_total")
    if index <= 10:
        store.increment("repair_state_event_total")


def test_canary_auto_finalizes_exact_window_and_writes_evidence(tmp_path):
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "all.jsonl")
    store.write_jsonl = False
    controller = RolloutController(state_path=tmp_path / "rollout.json", observability=store)
    manager = HardeningCanaryManager(
        observability=store,
        rollout_controller=controller,
        provider_health_fn=lambda: {
            "action": {"ready": True, "provider": "action_executor"},
            "memory": {"ready": True, "provider": "memory_kernel"},
        },
        config=CanaryConfig(
            enabled=True,
            target_turns=20,
            auto_rollback=False,
            evidence_dir=str(tmp_path / "canary"),
            release_id="phase6-test",
        ),
    )
    state = manager.start(session_id="canary-test")
    assert state is not None
    completion = None
    for index in range(1, 21):
        _record_clean_canary_metrics(store, index)
        completion = manager.record_public_turn(turn_id=f"turn-{index}")
    assert completion is not None
    assert completion.report["status"] == "pass"
    assert completion.state["public_turns"] == 20
    assert Path(completion.evidence_path).exists()
    assert Path(completion.events_path).exists()
    payload = json.loads(Path(completion.evidence_path).read_text(encoding="utf-8"))
    assert payload["state"]["release_id"] == "phase6-test"
    assert payload["verification"]["public_turns"] == 20


def test_canary_disabled_does_not_start(tmp_path):
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "all.jsonl")
    manager = HardeningCanaryManager(
        observability=store,
        rollout_controller=RolloutController(state_path=tmp_path / "rollout.json"),
        config=CanaryConfig(enabled=False),
    )
    assert manager.start() is None
    assert manager.status()["status"] == "disabled"


def test_canary_fail_can_apply_language_pin_rollback(tmp_path):
    store = ErisObservability(enabled=True, jsonl_path=tmp_path / "all.jsonl")
    store.write_jsonl = False
    controller = RolloutController(state_path=tmp_path / "rollout.json", observability=store)
    manager = HardeningCanaryManager(
        observability=store,
        rollout_controller=controller,
        provider_health_fn=lambda: {"speech": {"ready": True, "provider": "speech_engine"}},
        config=CanaryConfig(
            enabled=True,
            target_turns=20,
            auto_rollback=True,
            evidence_dir=str(tmp_path / "canary"),
        ),
    )
    manager.start(session_id="canary-fail")
    completion = None
    for index in range(1, 21):
        _record_clean_canary_metrics(store, index)
        if index == 7:
            store.increment("tts_locale_switch_rate")
        completion = manager.record_public_turn(turn_id=f"turn-{index}")
    assert completion is not None
    assert completion.report["status"] == "fail"
    assert completion.rollback_applied is True
    assert controller.decide("tts_language_pin", session_id="probe").killed is True
