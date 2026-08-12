from __future__ import annotations

from types import SimpleNamespace

from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.contracts import AI_RUNTIME_VERSION
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate
from runtime.ai_orchestrated.social_plan_commit import activate_social_plan_after_public_commit


def _board(*, reply_expected: bool = False) -> TypedCognitiveBlackboard:
    return TypedCognitiveBlackboard.from_snapshot(
        {
            "time": 1000.0,
            "conversation_baton": {
                "reply_expected": reply_expected,
                "followup_reminder_due": reply_expected,
                "followup_reminder_count": 0,
                "thread_key": "startup-thread",
                "seconds_since_user": 120.0,
                "seconds_since_assistant": 40.0,
            },
            "seconds_since_user": 120.0,
            "seconds_since_assistant": 40.0,
            "commentary_expectation": {"due": True, "required": False},
            "recent_public_history": [],
        },
        now=1000.0,
    )


def test_runtime_version_marks_live_selector() -> None:
    assert AI_RUNTIME_VERSION == "ai_orchestrated.v28.background_seed_reservoir"


def test_followup_selector_candidate_can_cross_reply_baton_once(tmp_path) -> None:
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="followup_reminder",
        topic="Remind once without blame, then yield.",
        speech_act="followup_reminder",
        anchor_type="conversation",
        anchor_id="startup-thread",
        confidence=0.9,
        relevance=0.9,
        urgency=0.4,
        tone="gentle_reminder",
    )
    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(
        _board(reply_expected=True),
        candidate,
    )
    assert decision.action is InitiativeAction.SPEECH
    assert decision.speech_intent is not None
    assert decision.plan.strategy == "remind_once_without_pressure"
    assert decision.speech_intent.max_sentences == 1


def test_startup_public_commit_activates_social_plan_lanes() -> None:
    calls: dict[str, list] = {"continuation": [], "agenda": [], "arc": []}

    class _Continuation:
        def schedule_from_social_plan(self, plan, **kwargs):
            calls["continuation"].append((plan, kwargs))

    class _Agenda:
        def apply_update(self, proposal, **kwargs):
            calls["agenda"].append((proposal, kwargs))
            return True

    class _Arc:
        def schedule_from_model(self, proposal, **kwargs):
            calls["arc"].append((proposal, kwargs))
            return True

    logger = SimpleNamespace(debug=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)
    host = SimpleNamespace(
        logger=logger,
        ai_social_continuation_runtime=_Continuation(),
        ai_social_agenda_store=_Agenda(),
        ai_conversation_arc_runtime=_Arc(),
        interaction_clock=None,
    )
    payload = {
        "semantic_frame": {},
        "assistant_act": {},
        "social_plan": {
            "afterbeat": {
                "decision": "reserve",
                "role": "afterthought",
                "objective": "Add one dry qualifier.",
                "pause_class": "short",
                "tone": "dry",
                "confidence": 0.8,
            },
            "exposure": {
                "decision": "none",
                "kind": "none",
                "level": 0.0,
                "expects_reaction": False,
                "reaction_window_class": "short",
                "expected_responses": [],
                "silence_hypotheses": [],
                "recovery_style": "none",
                "confidence": 0.0,
            },
            "agenda_update": {
                "decision": "open",
                "goal_type": "warm_presence",
                "objective": "Keep the opening socially alive without nagging.",
                "desired_user_state": "comfortable",
                "strategy": "one light move then yield",
                "horizon": "session",
                "success_signals": ["user_reengages"],
                "stop_signals": ["explicit_boundary"],
                "salience": 0.7,
                "evidence_refs": [],
            },
            "conversation_arc": {
                "decision": "schedule",
                "goal": "Finish the opening thought.",
                "beats": [
                    {"role": "soften", "objective": "Yield cleanly.", "condition": "still relevant"}
                ],
                "confidence": 0.75,
            },
        },
    }

    result = activate_social_plan_after_public_commit(
        host,
        payload,
        source_turn_id="startup:1",
        source_text="Xin chào.",
        source_turn_seq=1,
    )

    assert result["afterbeat"]["decision"] == "reserve"
    assert result["agenda_update"]["decision"] == "open"
    assert result["conversation_arc"]["decision"] == "schedule"
    assert len(calls["continuation"]) == 1
    assert len(calls["agenda"]) == 1
    assert len(calls["arc"]) == 1
    assert calls["continuation"][0][1]["source_turn_id"] == "startup:1"
