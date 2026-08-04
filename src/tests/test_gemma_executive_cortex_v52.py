from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import logging

from actions.contracts import ActionExecutionResult, ActionExecutionStatus
from llm.service import LlmService
from runtime.ai_orchestrated.executive_cortex import (
    ExecutiveCortex,
    ExecutiveDecision,
    may_release_optional_reply_baton,
)
from runtime.ai_orchestrated.executive_tools import ExecutiveTool
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


class _Blackboard:
    def public_view(self):
        return {
            "reply_expected": True,
            "seconds_since_user": 42.0,
            "seconds_since_assistant": 24.0,
        }


class _Executor:
    def __init__(self):
        self.calls = []

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


def test_executive_selects_between_deepseek_candidates_and_rewrites_semantic_target(monkeypatch):
    decisions = [{
        "action": "use_candidate",
        "candidate_index": 1,
        "semantic_target": "Open a fresh low-pressure topic without reviving the unanswered question.",
        "speech_act": "gentle_topic_opening",
        "tone": "dry_warm",
        "tool_name": "",
        "tool_input": "",
        "reply_baton": "release_optional",
        "reason": "old thread is socially closed; seed is safer",
        "confidence": 0.84,
        "intrusion_risk": 0.16,
    }]

    def invoke(_client, **_kwargs):
        return decisions.pop(0)

    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_live_executive_tool_catalog",
        lambda *_args, **_kwargs: (),
    )
    cortex = ExecutiveCortex(_Owner(), object(), invoke_structured=invoke)
    reminder = _candidate("followup_reminder", "Bring back the old question")
    seed = _candidate("random_chat", "A new premise", seed_id="seed-1")

    outcome = cortex.deliberate(_Blackboard(), [reminder, seed], snapshot={})

    assert outcome.action == "use_candidate"
    assert outcome.candidate.kind == "random_chat"
    assert outcome.candidate.topic.startswith("Open a fresh")
    assert outcome.candidate.speech_act == "gentle_topic_opening"
    assert outcome.candidate.source.startswith("gemma_executive:")


def test_executive_calls_only_live_read_only_tool_then_returns_grounded_candidate(monkeypatch):
    tool = ExecutiveTool(
        name="inspect_capability_health",
        title="health",
        description="read live capability health",
        available=True,
        availability_reason="ready",
        risk="low",
        permission_mode="read_only_auto",
        auto_callable=True,
        input_schema={"type": "object"},
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_live_executive_tool_catalog",
        lambda *_args, **_kwargs: (tool,),
    )
    decisions = [
        {
            "action": "call_tool", "candidate_index": -1, "semantic_target": "",
            "speech_act": "", "tone": "", "tool_name": "inspect_capability_health",
            "tool_input": "screen reading", "reply_baton": "preserve", "reason": "capability truth is needed",
            "confidence": 0.78, "intrusion_risk": 0.05,
        },
        {
            "action": "speak_from_tool", "candidate_index": -1,
            "semantic_target": "State that screen reading is available without claiming current screen content.",
            "speech_act": "capability_statement", "tone": "matter_of_fact_warm",
            "tool_name": "", "tool_input": "", "reply_baton": "preserve", "reason": "verified runtime fact",
            "confidence": 0.91, "intrusion_risk": 0.04,
        },
    ]

    def invoke(_client, **_kwargs):
        return decisions.pop(0)

    owner = _Owner()
    cortex = ExecutiveCortex(owner, object(), invoke_structured=invoke)
    outcome = cortex.deliberate(_Blackboard(), [], snapshot={})

    assert owner.action_executor.calls == [("inspect_capability_health", "screen reading")]
    assert owner.grounding == [("inspect_capability_health", True)]
    assert outcome.candidate is not None
    assert outcome.candidate.kind == "random_chat"
    assert outcome.candidate.evidence_refs == ("capability:screen.read:healthy",)
    assert outcome.candidate.topic.startswith("State that screen reading")


def test_executive_rejects_side_effect_tool(monkeypatch):
    tool = ExecutiveTool(
        name="project_apply_patch",
        title="patch",
        description="modify project files",
        available=True,
        availability_reason="ready",
        risk="high",
        permission_mode="autonomous_project_scope",
        auto_callable=False,
        input_schema={"type": "object"},
    )
    monkeypatch.setattr(
        "runtime.ai_orchestrated.executive_cortex.build_live_executive_tool_catalog",
        lambda *_args, **_kwargs: (tool,),
    )

    def invoke(_client, **_kwargs):
        return {
            "action": "call_tool", "candidate_index": -1, "semantic_target": "",
            "speech_act": "", "tone": "", "tool_name": "project_apply_patch",
            "tool_input": "change files", "reply_baton": "preserve", "reason": "try side effect",
            "confidence": 0.7, "intrusion_risk": 0.7,
        }

    owner = _Owner()
    cortex = ExecutiveCortex(owner, object(), invoke_structured=invoke)
    outcome = cortex.deliberate(_Blackboard(), [], snapshot={})

    assert outcome.action == "silence"
    assert owner.action_executor.calls == []


def test_llm_service_keeps_deepseek_workers_and_adds_executive_client():
    companion = object()
    observer = object()
    inner = object()
    seed = object()
    surface = object()
    executive = object()
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


def test_process_manager_builds_gemma_executive_without_touching_deepseek_workers(monkeypatch, tmp_path):
    import llm.process_manager as pm

    class _Lease:
        key = "gemini-pool-key"

    class _Pool:
        size = 7

        def acquire(self, allow_cooling=True):
            return _Lease()

    monkeypatch.setenv("ERIS_EXECUTIVE_CORTEX_ENABLED", "1")
    monkeypatch.setenv("ERIS_EXECUTIVE_MODEL", "gemma-4-31b-it")
    monkeypatch.setattr(pm, "apply_secrets_to_environ", lambda: None)
    monkeypatch.setattr(pm, "get_provider_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(pm, "get_key_pool", lambda kind: _Pool())
    monkeypatch.setattr(pm, "get_secret", lambda *args, **kwargs: "")

    manager = pm.RemoteModelProcessManager(logger=logging.getLogger("executive-test"), project_root=str(tmp_path))
    client = manager.build_executive_client()

    assert client is not None
    assert client.model_name == "gemma-4-31b-it"
    assert client.key_pool.size == 7


def test_executive_decision_parses_optional_reply_baton_safely():
    decision = ExecutiveDecision.from_mapping({
        "action": "use_candidate",
        "candidate_index": 0,
        "reply_baton": "release_optional",
        "confidence": 0.8,
        "intrusion_risk": 0.1,
    })

    assert decision.reply_baton == "release_optional"
    assert ExecutiveDecision.from_mapping({"reply_baton": "release_required"}).reply_baton == "preserve"


def test_optional_reply_baton_release_is_typed_and_low_risk_only():
    board = SimpleNamespace(
        reply_expected=True,
        engagement_active=False,
        engagement_required=False,
    )
    candidate = _candidate("random_chat", "A fresh low-pressure premise")
    decision = ExecutiveDecision(
        action="use_candidate",
        reply_baton="release_optional",
        confidence=0.81,
        intrusion_risk=0.18,
    )

    assert may_release_optional_reply_baton(board, candidate, decision) is True
    assert may_release_optional_reply_baton(
        board, _candidate("task_followup", "Ask for a required path"), decision
    ) is False
    assert may_release_optional_reply_baton(
        board, candidate, ExecutiveDecision(
            action="use_candidate",
            reply_baton="release_optional",
            confidence=0.81,
            intrusion_risk=0.61,
        )
    ) is False


def test_social_initiative_options_expose_reminder_and_seed_to_executive(monkeypatch):
    from runtime.ai_orchestrated.social_initiative import SocialInitiativeEngine

    engine = SocialInitiativeEngine(SimpleNamespace(surface_client=None))
    reminder = _candidate("followup_reminder", "Bring back the old thread")
    seed = _candidate("random_chat", "Open a new thread", seed_id="seed-ready")
    board = SimpleNamespace(
        user_busy=False,
        engagement_exclusive_focus=False,
        engagement_active=False,
    )
    monkeypatch.setattr(engine, "propose", lambda *_args, **_kwargs: reminder)
    monkeypatch.setattr(engine, "_random_chat_seed_candidate", lambda *_args, **_kwargs: seed)

    options = engine.propose_options(board, snapshot={})

    assert [item.kind for item in options] == ["followup_reminder", "random_chat"]


def test_live_tool_catalog_refreshes_against_supplied_owner(monkeypatch):
    import runtime.ai_orchestrated.executive_tools as tools

    seen = []
    definition = SimpleNamespace(
        id="inspect_social_state",
        public_name_vi="inspect social state",
        description_vi="read current social state",
        live_available=False,
        risk_level="low",
    )
    monkeypatch.setattr(
        tools, "refresh_runtime_capabilities",
        lambda *, owner=None, settings=None: seen.append(owner) or {},
    )
    monkeypatch.setattr(
        tools, "runtime_capability_snapshot",
        lambda *, refresh=False: {
            "statuses": {
                "inspect_social_state": {"available": True, "reason": "ready"}
            }
        },
    )
    monkeypatch.setattr(
        tools, "iter_public_capabilities",
        lambda *, include_unavailable=True: (definition,),
    )
    monkeypatch.setattr(
        tools, "_contract_metadata",
        lambda _capability_id: ("low", "read_only_auto", "test_contract"),
    )
    owner = object()

    catalog = tools.build_live_executive_tool_catalog(owner, refresh=True)

    assert seen == [owner]
    assert catalog[0].available is True
    assert catalog[0].auto_callable is True
