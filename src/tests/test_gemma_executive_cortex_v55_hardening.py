from __future__ import annotations

from types import SimpleNamespace

from actions.capability_registry import (
    capability_argument_mode,
    iter_public_capabilities,
    validate_registry_contract_coverage,
)
from runtime.ai_orchestrated.executive_cortex import (
    ExecutiveCortex,
    ExecutiveEvent,
    ExecutiveState,
)
from runtime.ai_orchestrated.executive_tools import CapabilityIndex, ExecutiveTool
from runtime.capability_claim_guard import guard_public_capability_claims


class _Owner:
    pass


def _decision(action: str, **changes):
    value = {
        "action": action,
        "affordance_id": "",
        "semantic_target": "",
        "speech_act": "",
        "tone": "",
        "capability_goal": "",
        "required_effect": "",
        "maximum_risk": "low",
        "capability_domain": "",
        "capability_ids": [],
        "capability_id": "",
        "capability_arguments": {},
        "reply_baton": "preserve",
        "phase": "quiet_presence",
        "trajectory": "leave_topic_at_rest",
        "reconsider_on": [{"kind": "seed_available", "minimum_strength": 0.75}],
        "review_after_seconds": 90,
        "reason": "test",
        "confidence": 0.85,
        "intrusion_risk": 0.1,
    }
    value.update(changes)
    return value


def _tool() -> ExecutiveTool:
    return ExecutiveTool(
        capability_id="read_visible_ui_text",
        title="read visible UI text",
        description="Read visible text from the active window.",
        effect="observe",
        domain="environment",
        available=True,
        availability_reason="ready",
        risk="low",
        permission_mode="read_only_auto",
        auto_callable=True,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}},
            "required": [],
        },
    )


def test_interactive_capability_planning_does_not_mutate_conversation_policy(monkeypatch):
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_a, **_k: CapabilityIndex(1, 1, {"observe": 1}, {"environment": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_a, **_k: (_tool(),),
    )
    calls = iter(
        [
            _decision("discover_capabilities", required_effect="observe", capability_domain="environment"),
            _decision(
                "select_capability",
                capability_id="read_visible_ui_text",
                capability_arguments={"query": "active window"},
            ),
        ]
    )
    initial = {
        "revision": 7,
        "phase": "quiet_presence",
        "trajectory": "leave_topic_at_rest",
        "reconsider_on": [{"kind": "seed_available", "minimum_strength": 0.8}],
        "review_due_at": 1400.0,
        "preferred_lane": "seed",
        "updated_at": 1000.0,
    }
    persisted = []
    cortex = ExecutiveCortex(
        _Owner(),
        object(),
        invoke_structured=lambda *_a, **_k: next(calls),
        initial_state=initial,
        persist=persisted.append,
        clock=lambda: 1001.0,
        wall_clock=lambda: 10_001.0,
    )
    before = cortex.state
    directive = cortex.plan_interactive("Em có đọc được màn hình không?", snapshot={})
    assert directive.status == "selected"
    assert cortex.state == before
    assert persisted == []


def test_executive_state_persists_policy_but_not_failure_backoff(monkeypatch):
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_a, **_k: CapabilityIndex(1, 0, {}, {}),
    )
    stored = []
    now = 2000.0
    cortex = ExecutiveCortex(
        _Owner(),
        object(),
        invoke_structured=lambda *_a, **_k: _decision("silence"),
        persist=stored.append,
        clock=lambda: now,
        wall_clock=lambda: 20_000.0,
    )
    cortex.deliberate(SimpleNamespace(public_view=lambda: {}), [], snapshot={})
    assert len(stored) == 1
    payload = stored[0]
    assert payload["schema"] == "eris.executive_state.v2"
    assert payload["phase"] == "quiet_presence"
    assert payload["trajectory"] == "leave_topic_at_rest"
    assert "retry_not_before" not in payload
    assert payload["review_due_wallclock"] == 20_090.0

    restored = ExecutiveState.from_persisted_mapping(
        payload, runtime_now=50.0, wall_now=20_001.0
    )
    assert restored.revision == 1
    assert restored.phase == "quiet_presence"
    assert restored.reconsider_on[0].kind == "seed_available"
    assert restored.retry_not_before == 0.0
    assert restored.review_due_at == 139.0


def test_stale_persisted_executive_state_resets_to_default():
    restored = ExecutiveState.from_persisted_mapping(
        {
            "schema": "eris.executive_state.v2",
            "revision": 9,
            "phase": "quiet_presence",
            "trajectory": "old_policy",
            "updated_at_wallclock": 100.0,
        },
        runtime_now=50.0,
        wall_now=22_000.0,
        maximum_age_seconds=6_000.0,
    )
    assert restored.revision == 0
    assert restored.phase == "unresolved"
    assert restored.trajectory == "observe_before_acting"



def test_wallclock_persistence_survives_runtime_clock_reset():
    state = ExecutiveState(
        revision=3,
        phase="quiet_presence",
        trajectory="wait_for_seed",
        review_due_at=1_090.0,
        updated_at=1_000.0,
    )
    payload = state.to_persisted_dict(runtime_now=1_010.0, wall_now=50_000.0)
    restored = ExecutiveState.from_persisted_mapping(
        payload, runtime_now=5.0, wall_now=50_020.0
    )
    assert restored.revision == 3
    assert restored.review_due_at == 65.0
    assert restored.updated_at == 0.0


def test_scored_event_policy_uses_threshold_and_provenance_without_renaming():
    initial = {
        "revision": 4,
        "phase": "quiet_presence",
        "trajectory": "wait",
        "reconsider_on": [{"kind": "scene_delta", "minimum_strength": 0.65}],
        "review_due_at": 0,
        "updated_at": 1000.0,
    }
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=lambda *_a, **_k: {}, initial_state=initial, clock=lambda: 1001.0)
    assert cortex.should_reconsider([ExecutiveEvent("scene_delta", 0.64, "window_telemetry", revision=11)])[0] is False
    allowed, reason = cortex.should_reconsider(
        [ExecutiveEvent("scene_delta", 0.72, "window_telemetry", revision=12, metadata={"window": "Code"})]
    )
    assert allowed is True
    assert reason == "executive_policy:scene_delta:0.72"


def test_capability_contract_coverage_is_complete_and_context_sensors_are_not_callable():
    valid, missing = validate_registry_contract_coverage()
    definitions = tuple(iter_public_capabilities())
    assert valid is True
    assert missing == ()
    assert len(definitions) == 46
    context_only = [item for item in definitions if item.exposure == "context_only"]
    assert len(context_only) == 8
    assert all(item.callable is False for item in context_only)
    assert all(capability_argument_mode(item.id) == "context_only" for item in context_only)


def test_capability_claim_guard_fails_closed_on_false_denial(monkeypatch):
    monkeypatch.setattr(
        "runtime.capability_claim_guard.runtime_capability_snapshot",
        lambda **_kwargs: {"statuses": {"read_visible_ui_text": {"available": True}}},
    )
    payload = {
        "should_speak": True,
        "text": "Tôi không thể nhìn thấy màn hình.",
        "speech_text": "Tôi không thể nhìn thấy màn hình.",
        "self_capability_claims": [
            {"capability_id": "read_visible_ui_text", "state": "unavailable", "basis": "model"}
        ],
    }
    result = guard_public_capability_claims(payload, owner=_Owner())
    assert result.allowed is False
    assert result.payload["should_speak"] is False
    assert result.payload["text"] == ""
    assert result.violations == ("false_unavailable_claim:read_visible_ui_text",)


def test_capability_claim_guard_accepts_exact_selected_capability(monkeypatch):
    monkeypatch.setattr(
        "runtime.capability_claim_guard.runtime_capability_snapshot",
        lambda **_kwargs: {"statuses": {}},
    )
    payload = {
        "should_speak": True,
        "text": "Em đọc được phần chữ đang hiện.",
        "self_capability_claims": [
            {"capability_id": "read_visible_ui_text", "state": "available", "basis": "verified_tool"}
        ],
    }
    result = guard_public_capability_claims(
        payload,
        owner=_Owner(),
        executive_directive={"status": "selected", "capability_id": "read_visible_ui_text"},
    )
    assert result.allowed is True
    assert result.payload["text"] == payload["text"]
