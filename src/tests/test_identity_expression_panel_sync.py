from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.ai_orchestrated.contracts import (
    AppraisalState,
    CognitiveObservation,
    RuntimeMindState,
    StateEvent,
)
from runtime.ai_orchestrated.expression import IdentityExpressionBridge
from runtime.ai_orchestrated.identity import IdentityProfile
from runtime.ai_orchestrated.identity_consolidator import IdentityConsolidator
from runtime.ai_orchestrated.initiative import InitiativeController
from runtime.ai_orchestrated.panel_adapter import build_ai_panel_payload
from runtime.ai_orchestrated.state_reducer import StateReducer
from transport.udp import build_panel_state_payload


def _observation(turn_seq: int = 1) -> CognitiveObservation:
    return CognitiveObservation.from_mapping(
        {
            "confidence": 0.91,
            "event_kind": "chat",
            "user_act": "correction",
            "relationship_meaning": "repair_needed",
            "repair_needed": True,
            "relational_delta": -0.4,
            "self_interpretation": {
                "summary": "Tôi đã trả lời quá tự tin và cần sửa thẳng.",
                "confidence": 0.88,
            },
            "evidence": ["user explicitly corrected the answer"],
        },
        turn_id=f"turn-{turn_seq}",
        turn_seq=turn_seq,
        source="test",
    )


def test_identity_expression_bridge_prioritizes_repair_without_public_text_rewrite() -> None:
    state = RuntimeMindState(
        appraisal=AppraisalState(irritation=0.8, embarrassment=0.7),
        latest_observation={"repair_needed": True},
    )
    expression = IdentityExpressionBridge().derive(state, requested_hint="playful")
    assert expression.preset == "repair"
    assert expression.sentence_bias == "short_direct"
    assert "repair_needed" in expression.reasons


def test_learning_freeze_survives_observer_turn_and_blocks_identity_drift() -> None:
    reducer = StateReducer(initial_state=RuntimeMindState())
    try:
        reducer.apply_now(
            StateEvent(
                kind="admin_control",
                turn_seq=0,
                turn_id="freeze",
                payload={"action": "set_learning", "enabled": False},
                source="test",
            )
        )
        before = reducer.snapshot()
        identity_version = before.identity.version
        personality_version = before.personality.version

        reducer.apply_now(StateEvent.from_observation(_observation(), base_version=before.version))
        after = reducer.snapshot()

        assert after.identity_learning_enabled is False
        assert after.identity.version == identity_version
        assert after.personality.version == personality_version
        assert after.latest_observation["repair_needed"] is True
        assert after.relationship.relational_trust == pytest.approx(before.relationship.relational_trust)
    finally:
        reducer.close()


def test_panel_contract_contains_identity_expression_controls_and_compatibility() -> None:
    state = RuntimeMindState(
        version=7,
        last_applied_turn_seq=19,
        identity=IdentityProfile(),
        identity_learning_enabled=False,
    )
    expression = {"preset": "cold_precision", "confidence": 0.82, "reasons": ["dignity_under_pressure"]}
    payload = build_ai_panel_payload(state, expression=expression)

    identity = payload["identity_runtime"]
    assert identity["schema"] == "eris.identity_runtime.panel.v1"
    assert identity["learning"]["mode"] == "observe_only"
    assert identity["expression"]["preset"] == "cold_precision"
    assert "reset_relationship" in identity["controls"]
    assert payload["depth_v2"]["expression"]["preset"] == "cold_precision"
    assert payload["private_mind_digest"]["architecture"]
    emotion_items = payload["emotion_debug"]["items"]
    assert emotion_items["calm_aroused"]["value"] >= 0.0
    assert emotion_items["emotional_stability"]["value"] >= 0.0
    assert emotion_items["attachment"]["group"] == "bond"
    assert emotion_items["expression_preset"]["value"] == "cold_precision"

    packet = build_panel_state_payload(payload)
    assert packet["type"] == "panel_state_update"
    assert packet["identity_runtime"]["learning"]["mode"] == "observe_only"
    assert packet["private_mind_digest"]["active_motives"] == []
    assert "active_conflict" in packet["private_mind_digest"]
    assert "calm_aroused" in packet["emotion_debug"]["items"]


def test_initiative_budget_persists_and_exhausts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from runtime.ai_orchestrated import initiative as initiative_module

    settings = {
        "enabled": True,
        "hourly_budget": 1,
        "minimum_interval_seconds": 60,
        "minimum_user_silence_seconds": 30,
        "importance_margin": 0.05,
        "activity_update_cooldown_seconds": 60,
    }
    monkeypatch.setattr(initiative_module, "_setting", lambda name, default: settings.get(name, default))

    path = tmp_path / "initiative.json"
    controller = InitiativeController(state_path=path)
    plan = SimpleNamespace(
        motive="share_discovery",
        strategy="share_discovery",
        importance=0.9,
        intrusion_risk=0.1,
        topic="Một discovery đủ đáng kể",
    )
    allowed, reason = controller.evaluate(plan, now=1000.0, seconds_since_user=300.0)
    assert allowed is True and reason == "allowed"
    controller.record_spoken(plan, now=1000.0)

    allowed, reason = controller.evaluate(plan, now=1100.0, seconds_since_user=300.0)
    assert allowed is False and reason == "hourly_budget_exhausted"
    assert path.exists()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert len(persisted["events"]) == 1


def test_identity_consolidator_writes_snapshot_ledger_and_imprints(tmp_path: Path) -> None:
    state = RuntimeMindState(version=4, last_applied_turn_seq=9)
    consolidator = IdentityConsolidator(root=tmp_path)
    result = consolidator.write(state, reason="test")

    assert result["ok"] is True
    snapshot = json.loads((tmp_path / "identity_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["state_version"] == 4
    assert snapshot["learning_enabled"] is True
    ledger_path = tmp_path / "identity_events.jsonl"
    assert ledger_path.exists()
    assert (tmp_path / "formative_imprints.json").exists()
    first_lines = ledger_path.read_text(encoding="utf-8").splitlines()

    # Khởi động consolidator mới không được append lại cùng ledger.
    restarted = IdentityConsolidator(root=tmp_path)
    restarted.write(state, reason="restart-test")
    assert ledger_path.read_text(encoding="utf-8").splitlines() == first_lines
    assert restarted.panel_view()["last_write_at"] > 0.0


def test_debug_console_identity_controls_use_single_writer(tmp_path: Path) -> None:
    from runtime.debug_console import DebugConsole

    reducer = StateReducer(initial_state=RuntimeMindState())
    discovery = SimpleNamespace(reset_called=0)
    initiative = SimpleNamespace(reset_called=0)
    discovery.reset = lambda: setattr(discovery, "reset_called", discovery.reset_called + 1)
    initiative.reset = lambda: setattr(initiative, "reset_called", initiative.reset_called + 1)
    consolidator = IdentityConsolidator(root=tmp_path)
    coord = SimpleNamespace(
        ai_state_reducer=reducer,
        ai_discovery_runtime=discovery,
        ai_initiative_controller=initiative,
        ai_identity_consolidator=consolidator,
    )
    console = DebugConsole(coord)
    try:
        assert "observe_only" in console.execute("identity freeze on")
        assert reducer.snapshot().identity_learning_enabled is False
        assert "normal" in console.execute("identity freeze off")
        assert reducer.snapshot().identity_learning_enabled is True
        assert "snapshot ok" in console.execute("identity snapshot")
        assert "reset all" in console.execute("identity reset all")
        assert discovery.reset_called == 1
        assert initiative.reset_called == 1
    finally:
        reducer.close()
