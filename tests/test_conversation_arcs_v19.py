from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.conversation_arc import ConversationArcRuntime
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter, PUBLIC_REPLY_SCHEMA


class _FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@dataclass
class _Semantics:
    turn_kind: str = "arc_continuation"


@dataclass
class _Plan:
    semantics: _Semantics = field(default_factory=_Semantics)


def _proposal(*, delay: float = 0.65):
    return {
        "decision": "schedule",
        "arc_id": "arc:tease:1",
        "thread_key": "thread:tease",
        "goal": "Set up a restrained tease, then return with a dry afterthought.",
        "user_reply_policy": "replan",
        "expires_after_seconds": 120,
        "beats": [
            {
                "role": "punchline",
                "objective": "Return with the small implication the first line deliberately withheld.",
                "delay_seconds": delay,
                "tone": "dry_tease",
                "max_sentences": 1,
            }
        ],
    }


def _board(*, reply_expected: bool = True, user_busy: bool = False, seconds_since_user: float = 4.0):
    return TypedCognitiveBlackboard.from_snapshot(
        {
            "time": 1004.0,
            "telemetry": {"user_busy": user_busy},
            "screen_context": {"fresh": True, "privacy_blocked": False},
            "vision_grounding": {"recommendation": "silence", "claims": []},
            "conversation_baton": {
                "reply_expected": reply_expected,
                "assistant_may_continue": False,
                "thread_fresh": True,
                "thread_key": "thread:tease",
            },
            "activity_session": {"has_new_event": False, "new_event_keys": []},
            "self_context": {"has_public_seed": False, "attention": {}},
            "discovery": {},
            "commentary_expectation": {"due": False, "required": False},
            "engagement_context": {"active": False},
            "engagement_interaction": {},
            "latest_observation": {},
            "seconds_since_user": seconds_since_user,
            "seconds_since_assistant": 4.0,
            "open_loops": [],
            "recent_public_history": [
                {"role": "assistant", "content": "Ừ, nghe cũng vô tội đấy."}
            ],
        },
        now=1004.0,
    )


def test_arc_becomes_autonomous_candidate_only_after_due_time():
    now = [1000.0]
    timers = []

    def timer_factory(delay, callback):
        timer = _FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    runtime = ConversationArcRuntime(clock=lambda: now[0], timer_factory=timer_factory, wake_callback=lambda _reason: None)
    assert runtime.schedule_from_model(
        _proposal(delay=3.0),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={"tool_intent": "none", "boundary_action": "none"},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    assert runtime.due_candidate(now=1002.9) is None

    candidate = runtime.due_candidate(now=1003.0)
    assert candidate is not None
    assert candidate.kind == "conversation_arc"
    assert candidate.anchor_id == "arc:tease:1"
    assert "small implication" in candidate.topic
    assert "first public line" not in candidate.topic.lower()
    assert timers and timers[-1].started is True


def test_audio_completion_starts_the_real_rhetorical_pause():
    now = [1000.0]
    runtime = ConversationArcRuntime(clock=lambda: now[0], timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        _proposal(delay=3.0),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    runtime.notify_audio_finished(1002.5)
    assert runtime.due_candidate(now=1005.4) is None
    assert runtime.due_candidate(now=1005.5) is not None


def test_user_interruption_yields_arc_and_returns_replan_context():
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        _proposal(),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )

    context = runtime.observe_user_turn(
        user_text="Khoan, ý em là sao?",
        user_turn_seq=2,
        now=1001.0,
    )
    assert context["goal"].startswith("Set up")
    assert context["pending_beat"]["role"] == "punchline"
    assert runtime.has_pending(now=1001.0) is False
    assert runtime.due_candidate(now=1010.0) is None


def test_successful_arc_line_advances_and_completes_state():
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        _proposal(delay=1.2),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    assert runtime.note_spoken(_Plan(), "Nhưng cái mặt em thì khai hết rồi.", now=1002.0)
    assert runtime.has_pending(now=1002.0) is False
    assert runtime.snapshot(now=1002.0)["active_arc"] is None


def test_runtime_rejects_arc_for_tool_boundary_and_question_act():
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert not runtime.schedule_from_model(
        _proposal(),
        source_turn_id="turn:1",
        source_text="Mở giúp em nhé.",
        source_turn_seq=1,
        semantic_frame={"tool_intent": "open_app"},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    assert not runtime.schedule_from_model(
        _proposal(),
        source_turn_id="turn:2",
        source_text="Thế em nghĩ sao?",
        source_turn_seq=2,
        semantic_frame={},
        assistant_act={"kind": "question"},
        now=1000.0,
    )



def test_nonverbal_interrupt_can_cancel_orphaned_setup():
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        _proposal(),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    assert runtime.cancel_active(reason="setup_audio_interrupted", now=1000.5)
    snapshot = runtime.snapshot(now=1000.5)
    assert snapshot["pending"] is False
    assert snapshot["last_interrupted_arc"]["interrupted_reason"] == "setup_audio_interrupted"

def test_arc_candidate_can_retake_reply_baton_but_still_uses_governor(tmp_path: Path):
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    runtime.schedule_from_model(
        _proposal(delay=1.2),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    candidate = runtime.due_candidate(now=1004.0)
    assert candidate is not None

    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(
        _board(reply_expected=True),
        candidate,
    )
    assert decision.action is InitiativeAction.SPEECH
    assert decision.speech_intent is not None
    assert decision.speech_intent.plan.semantics.turn_kind == "arc_continuation"
    assert decision.speech_intent.max_sentences == 1


def test_public_reply_contract_rejects_legacy_top_level_arc_path():
    assert "conversation_arc" not in PUBLIC_REPLY_SCHEMA["properties"]
    router = object.__new__(AIRuntimeModelRouter)
    router.logger = None
    payload = router._compat_public_envelope(
        {
            "semantic_frame": {},
            "assistant_act": {"kind": "answer", "proposition_mode": "new", "confidence": 0.8},
            "should_speak": True,
            "utterance": {
                "display": {"text": "Ừ, nghe cũng vô tội đấy.", "language": "vi"},
                "speech": {"text": "まあ、無実っぽくは聞こえるね。", "language": "ja"},
                "performance": {"preset": "dry_tease", "intensity": 0.6, "nonverbal_cue": ""},
            },
            "conversation_arc": _proposal(),
        }
    )
    assert "conversation_arc" not in payload
    assert payload["social_plan"]["conversation_arc"]["decision"] == "none"


def test_reserved_arc_handoff_wakes_immediately_after_short_pause():
    now = [1000.0]
    timers = []
    wakes = []

    def timer_factory(delay, callback):
        timer = _FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    runtime = ConversationArcRuntime(
        clock=lambda: now[0],
        timer_factory=timer_factory,
        wake_callback=wakes.append,
    )
    assert runtime.schedule_from_model(
        _proposal(delay=0.4),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    now[0] = 1002.0
    runtime.notify_audio_finished(1002.0)
    assert abs(timers[-1].delay - 0.4) < 1e-9
    timers[-1].callback()
    assert wakes == ["conversation_arc_due:arc:tease:1"]
    assert runtime.snapshot(now=1002.4)["reserved_continuation"] is True


def test_reserved_arc_bypasses_normal_autonomous_waiting_gates(tmp_path: Path):
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        _proposal(delay=0.25),
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    candidate = runtime.due_candidate(now=1000.25)
    assert candidate is not None

    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    decision = controller.decide(
        _board(reply_expected=True, user_busy=True, seconds_since_user=0.05),
        candidate,
    )
    assert decision.action is InitiativeAction.SPEECH
    assert decision.reason == "allowed"
    assert controller.panel_view(now=1000.25)["last_decision"]["reason"] == "reserved_arc_continuation"
