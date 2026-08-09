from __future__ import annotations

import logging
from types import SimpleNamespace

from actions.capability_registry import (
    capability_input_schema,
    encode_capability_arguments,
    validate_capability_arguments,
)
from actions.contracts import ActionExecutionResult, ActionExecutionStatus
from llm.service import LlmService
from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.cognitive_blackboard import CognitiveAnchor, TypedCognitiveBlackboard
from runtime.ai_orchestrated.executive_cortex import (
    ExecutiveCortex,
    ExecutiveDecision,
    ExecutiveEvent,
    may_release_optional_reply_baton,
)
from runtime.ai_orchestrated.executive_tools import CapabilityIndex, ExecutiveTool
from runtime.ai_orchestrated.social_initiative import SocialInitiativeEngine, SocialSpeechCandidate


class _Blackboard:
    reply_expected = True
    engagement_active = False
    engagement_required = False
    followup_state = "waiting"

    def public_view(self):
        return {
            "reply_expected": True,
            "seconds_since_user": 42.0,
            "seconds_since_assistant": 24.0,
        }


class _Executor:
    def __init__(self):
        self.calls = []

    def execute_capability(self, name, arguments):
        from actions.capability_registry import encode_capability_arguments
        return self.execute(name, encode_capability_arguments(name, arguments))

    def execute(self, name, action_input):
        self.calls.append((name, action_input))
        return ActionExecutionResult(
            action_name=name,
            action_input=action_input,
            success=True,
            message="Runtime confirms the screen-reading capability is healthy.",
            status=ActionExecutionStatus.OBSERVED,
            observed=True,
            evidence=("capability:screen.read:healthy",),
        )


class _Owner:
    def __init__(self):
        self.action_executor = _Executor()
        self.grounding = []

    def _record_tool_grounding(self, result, *, action_name):
        self.grounding.append((action_name, result.success))


def _candidate(kind, topic, *, seed_id=""):
    return SocialSpeechCandidate(
        decision="candidate",
        kind=kind,
        topic=topic,
        speech_act=kind,
        anchor_type="conversation" if kind == "followup_reminder" else "idle",
        anchor_id=seed_id or kind,
        confidence=0.8,
        relevance=0.8,
        reason=f"upstream:{kind}",
        source="deepseek_worker",
        seed_id=seed_id,
    )


def _tool(
    *,
    capability_id="inspect_capability_health",
    auto_callable=True,
    risk="low",
    effect="inspect",
    domain="cognition",
):
    return ExecutiveTool(
        capability_id=capability_id,
        title=capability_id,
        description=f"live contract for {capability_id}",
        effect=effect,
        domain=domain,
        available=True,
        availability_reason="ready",
        risk=risk,
        permission_mode="read_only_auto" if auto_callable else "autonomous_project_scope",
        auto_callable=auto_callable,
        input_schema=(
            capability_input_schema(capability_id)
            if not capability_id.startswith("observe_")
            else {"type": "object", "additionalProperties": False, "properties": {}, "required": []}
        ),
    )


def _decision(action, **changes):
    payload = {
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
        "trajectory": "avoid_pressure",
        "reconsider_on": [
            {"kind": "user_turn", "minimum_strength": 0.0},
            {"kind": "seed_available", "minimum_strength": 0.7},
            {"kind": "scene_delta", "minimum_strength": 0.6},
        ],
        "review_after_seconds": 0,
        "reason": "test",
        "confidence": 0.8,
        "intrusion_risk": 0.1,
    }
    payload.update(changes)
    return payload


def test_executive_selects_exact_affordance_and_rewrites_semantic_target(monkeypatch):
    reminder = ExecutiveAffordance(
        "followup:1", "followup", 1, _candidate("followup_reminder", "Bring back the old question")
    )
    seed = ExecutiveAffordance(
        "seed:1", "random_chat_seed", 1, _candidate("random_chat", "A new premise", seed_id="seed-1")
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(1, 0, {}, {}),
    )
    cortex = ExecutiveCortex(
        _Owner(),
        object(),
        invoke_structured=lambda *_a, **_k: _decision(
            "select_affordance",
            affordance_id="seed:1",
            semantic_target="Open a fresh low-pressure topic without reviving the unanswered question.",
            speech_act="gentle_topic_opening",
            tone="dry_warm",
            reply_baton="release_optional",
            reason="old thread is socially closed; seed is safer",
        ),
    )
    outcome = cortex.deliberate(_Blackboard(), [reminder, seed], snapshot={})
    assert outcome.action == "use_candidate"
    assert outcome.selected_affordance_id == "seed:1"
    assert outcome.candidate.kind == "random_chat"
    assert outcome.candidate.topic.startswith("Open a fresh")
    assert outcome.candidate.source.startswith("gemma_executive:")
    assert cortex.state.trajectory == "avoid_pressure"


def test_executive_policy_reopens_only_on_selected_events_or_timer(monkeypatch):
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(1, 0, {}, {}),
    )
    cortex = ExecutiveCortex(
        _Owner(),
        object(),
        invoke_structured=lambda *_a, **_k: _decision(
            "silence",
            reconsider_on=[{"kind": "seed_available", "minimum_strength": 0.7}],
            review_after_seconds=30,
        ),
    )
    cortex.deliberate(_Blackboard(), [], snapshot={})
    state = cortex.state
    assert cortex.should_reconsider([ExecutiveEvent("scene_delta", 0.9, "test")], now=state.updated_at + 2)[0] is False
    assert cortex.should_reconsider([ExecutiveEvent("seed_available", 0.69, "test")], now=state.updated_at + 2)[0] is False
    assert cortex.should_reconsider([ExecutiveEvent("seed_available", 0.8, "test")], now=state.updated_at + 2)[0] is True
    assert cortex.should_reconsider([], now=state.updated_at + 31)[0] is True


def test_executive_discovers_then_invokes_exact_offered_typed_capability(monkeypatch):
    tool = _tool(
        capability_id="read_visible_ui_text",
        effect="observe",
        domain="environment",
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(2, 1, {"observe": 1}, {"environment": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: (tool,),
    )
    decisions = [
        _decision(
            "discover_capabilities",
            capability_goal="read the currently visible UI text",
            required_effect="observe",
            capability_domain="environment",
        ),
        _decision(
            "invoke_capability",
            required_effect="observe",
            capability_id="read_visible_ui_text",
            capability_arguments={"query": "screen reading"},
        ),
        _decision(
            "speak_from_capability",
            semantic_target="State the verified runtime finding without overclaiming unseen content.",
            speech_act="capability_statement",
            tone="matter_of_fact_warm",
            reason="verified runtime fact",
        ),
    ]
    owner = _Owner()
    cortex = ExecutiveCortex(owner, object(), invoke_structured=lambda *_a, **_k: decisions.pop(0))
    outcome = cortex.deliberate(_Blackboard(), [], snapshot={})
    assert owner.action_executor.calls == [("read_visible_ui_text", "screen reading")]
    assert owner.grounding == [("read_visible_ui_text", True)]
    assert outcome.candidate is not None
    assert outcome.candidate.kind == "grounded_tool_finding"
    assert outcome.candidate.anchor_type == "runtime_capability"
    assert outcome.candidate.evidence_refs == ("capability:screen.read:healthy",)


def test_gemma_semantically_shortlists_before_full_schemas(monkeypatch):
    tools = tuple(
        _tool(capability_id=f"observe_{index}", effect="observe", domain="environment")
        for index in range(8)
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(3, 8, {"observe": 8}, {"environment": 8}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: tools,
    )
    seen_payloads = []
    decisions = [
        _decision("discover_capabilities", capability_goal="read semantic screen content", required_effect="observe"),
        _decision("shortlist_capabilities", capability_ids=["observe_6", "observe_2"]),
        _decision("select_capability", capability_id="observe_6", capability_arguments={}),
    ]

    def invoke(_client, **kwargs):
        seen_payloads.append(kwargs["payload"])
        return decisions.pop(0)

    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=invoke)
    directive = cortex.plan_interactive("Can you inspect the screen semantically?", snapshot={})
    assert directive.status == "selected"
    assert directive.capability_id == "observe_6"
    assert len(seen_payloads[1]["capability_candidates"]) == 8
    assert seen_payloads[1]["offered_capabilities"] == []
    assert [item["capability_id"] for item in seen_payloads[2]["offered_capabilities"]] == [
        "observe_6", "observe_2"
    ]


def test_executive_rejects_non_auto_callable_capability(monkeypatch):
    tool = _tool(capability_id="project_apply_patch", auto_callable=False, risk="high", effect="write", domain="project")
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(2, 1, {"write": 1}, {"project": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: (tool,),
    )
    decisions = [
        _decision("discover_capabilities", required_effect="write", maximum_risk="high"),
        _decision(
            "invoke_capability",
            required_effect="write",
            maximum_risk="high",
            capability_id="project_apply_patch",
            capability_arguments={"patch": "--- a/x\n+++ b/x"},
        ),
    ]
    owner = _Owner()
    cortex = ExecutiveCortex(owner, object(), invoke_structured=lambda *_a, **_k: decisions.pop(0))
    outcome = cortex.deliberate(_Blackboard(), [], snapshot={})
    assert outcome.action == "silence"
    assert owner.action_executor.calls == []


def test_invalid_typed_arguments_are_rejected_before_execution(monkeypatch):
    tool = _tool(capability_id="read_visible_ui_text", effect="observe", domain="environment")
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(2, 1, {"observe": 1}, {"environment": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: (tool,),
    )
    decisions = [
        _decision("discover_capabilities", required_effect="observe"),
        _decision(
            "invoke_capability",
            capability_id="read_visible_ui_text",
            capability_arguments={"unknown": "bad"},
        ),
    ]
    owner = _Owner()
    outcome = ExecutiveCortex(owner, object(), invoke_structured=lambda *_a, **_k: decisions.pop(0)).deliberate(
        _Blackboard(), [], snapshot={}
    )
    assert outcome.action == "silence"
    assert owner.action_executor.calls == []


def test_input_contracts_validate_and_encode_without_semantic_aliases():
    assert validate_capability_arguments("project_read_file", {"path": "a.py", "max_chars": 1000}) == (True, "valid")
    encoded = encode_capability_arguments("project_read_file", {"path": "a.py", "max_chars": 1000})
    assert encoded == '{"path":"a.py","max_chars":1000}'
    assert validate_capability_arguments("set_volume", {})[0] is False
    assert encode_capability_arguments("set_volume", {"level": 35}) == "35"


def test_executive_failure_sets_mechanical_retry_backoff(monkeypatch):
    monkeypatch.setenv("ERIS_EXECUTIVE_FAILURE_BACKOFF_S", "30")
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(1, 0, {}, {}),
    )
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=lambda *_a, **_k: {})
    cortex.deliberate(_Blackboard(), [], snapshot={})
    state = cortex.state
    allowed, reason = cortex.should_reconsider(["strong_seed"], now=state.retry_not_before - 1)
    assert allowed is False
    assert reason == "executive_policy:failure_backoff"


def test_invalid_or_empty_model_response_is_unavailable_not_fake_silence(monkeypatch):
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(1, 0, {}, {}),
    )
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=lambda *_a, **_k: {})
    outcome = cortex.deliberate(_Blackboard(), [], snapshot={})
    assert outcome.decision.action == "unavailable"
    assert outcome.reason == "executive_model_or_schema_failure"


def test_llm_service_keeps_deepseek_workers_and_adds_executive_client():
    companion, observer, inner, seed, surface, executive = (object() for _ in range(6))
    service = LlmService(
        companion,
        observer_client=observer,
        inner_client=inner,
        seed_client=seed,
        surface_client=surface,
        executive_client=executive,
    )
    assert service.observer_client is observer
    assert service.inner_client is inner
    assert service.seed_client is seed
    assert service.surface_client is surface
    assert service.executive_client is executive



def test_optional_reply_baton_release_uses_previous_typed_state_not_new_candidate_kind():
    board = SimpleNamespace(
        reply_expected=True,
        engagement_active=False,
        engagement_required=False,
        followup_state="waiting",
    )
    decision = ExecutiveDecision(
        action="select_affordance",
        reply_baton="release_optional",
        confidence=0.81,
        intrusion_risk=0.18,
    )
    assert may_release_optional_reply_baton(board, decision) is True
    assert may_release_optional_reply_baton(
        board,
        ExecutiveDecision(
            action="select_affordance",
            reply_baton="release_optional",
            confidence=0.81,
            intrusion_risk=0.61,
        ),
    ) is False


def test_social_initiative_collects_reminder_despite_reply_expected_and_preserves_target():
    engine = SocialInitiativeEngine(SimpleNamespace(surface_client=None))
    board = TypedCognitiveBlackboard(
        now=100.0,
        reply_expected=True,
        followup_state="reminder_due",
        followup_reminder_due=True,
        anchors=(
            CognitiveAnchor(
                kind="conversation",
                anchor_id="thread-1",
                topic_seed="Which exact file should be created?",
                confidence=0.9,
                priority=0.9,
                metadata={"followup_reminder": True},
            ),
        ),
    )
    affordances = engine.collect_affordances(board, snapshot={})
    reminder = next(item for item in affordances if item.candidate.kind == "followup_reminder")
    assert "Which exact file should be created?" in reminder.candidate.topic


def test_hard_capability_filter_has_no_semantic_top_n(monkeypatch):
    import runtime.ai_orchestrated.executive_tools as tools

    definitions = tuple(
        SimpleNamespace(
            id=f"observe_{index}", public_name_vi=f"observe {index}", description_vi=f"description {index}",
            effect="observe", live_available=True, risk_level="low", visible_in_ui_group="environment",
        )
        for index in range(12)
    )
    monkeypatch.setattr(tools, "refresh_runtime_capabilities", lambda **_kwargs: {})
    monkeypatch.setattr(
        tools,
        "runtime_capability_snapshot",
        lambda *, refresh=False: {
            "revision": 3,
            "statuses": {item.id: {"available": True, "reason": "ready"} for item in definitions},
        },
    )
    monkeypatch.setattr(tools, "iter_public_capabilities", lambda **_kwargs: definitions)
    monkeypatch.setattr(tools, "_contract_metadata", lambda _cap: ("low", "read_only_auto", "environment_contract"))
    monkeypatch.setattr(
        tools,
        "capability_input_schema",
        lambda _cap: {"type": "object", "additionalProperties": False, "properties": {}, "required": []},
    )
    observed = tools.filter_executive_tools(object(), required_effect="observe", maximum_risk="low")
    assert len(observed) == 12
    assert [item.capability_id for item in observed] == sorted(item.id for item in definitions)


def test_interactive_executive_selects_exact_offered_capability(monkeypatch):
    tool = _tool(capability_id="read_visible_ui_text", effect="observe", domain="environment")
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(4, 1, {"observe": 1}, {"environment": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: (tool,),
    )
    decisions = [
        _decision("discover_capabilities", required_effect="observe", capability_domain="environment"),
        _decision(
            "select_capability",
            required_effect="observe",
            capability_id="read_visible_ui_text",
            capability_arguments={"query": "active window"},
            semantic_target="Inspect the current visible UI before answering.",
        ),
    ]
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=lambda *_a, **_k: decisions.pop(0))
    directive = cortex.plan_interactive("Em nhìn được màn hình không?", snapshot={})
    assert directive.status == "selected"
    assert directive.capability_id == "read_visible_ui_text"
    assert directive.capability_arguments == {"query": "active window"}


def test_interactive_executive_cannot_invent_unoffered_capability(monkeypatch):
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_capability_index",
        lambda *_args, **_kwargs: CapabilityIndex(4, 1, {"observe": 1}, {"environment": 1}),
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.filter_executive_tools",
        lambda *_args, **_kwargs: (_tool(capability_id="read_visible_ui_text", effect="observe", domain="environment"),),
    )
    decisions = [
        _decision("discover_capabilities", required_effect="observe"),
        _decision("select_capability", capability_id="imaginary_screen_oracle", capability_arguments={}),
    ]
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=lambda *_a, **_k: decisions.pop(0))
    directive = cortex.plan_interactive("Can you see this?", snapshot={})
    assert directive.status == "unavailable"
    assert directive.reason == "interactive_capability_not_offered"
