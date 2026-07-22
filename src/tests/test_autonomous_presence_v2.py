# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _plan(
    *,
    kind: str = "continuation",
    speech_act: str = "useful_followup",
    subject_key: str = "autonomous_architecture",
    topic: str = "mạch đang dở",
    importance: float = 0.72,
    intrusion: float = 0.10,
):
    from runtime.ai_orchestrated.contracts import IntentionPlan
    from runtime.ai_orchestrated.semantic_contracts import ActivitySemantics, TurnSemantics

    return IntentionPlan(
        plan_id=f"test:{kind}:{subject_key}",
        created_at=1000.0,
        channel="autonomous",
        speak=True,
        motive="model_owned_semantic",
        strategy="typed_self_turn",
        topic=topic,
        importance=importance,
        intrusion_risk=intrusion,
        confidence=0.84,
        semantics=TurnSemantics(
            turn_kind=kind,
            speech_act=speech_act,
            subject_key=subject_key,
            evidence_scope="conversation" if kind == "continuation" else "screen_delta",
            continuation_key="thread:autonomous" if kind == "continuation" else "none",
        ),
        activity=ActivitySemantics(),
    )


def test_discourse_state_does_not_treat_recency_alone_as_unresolved() -> None:
    from runtime.ai_orchestrated.discourse_state import DiscourseStateBuilder

    state = DiscourseStateBuilder().build(
        [
            {"role": "user", "content": "Tôi sửa xong rồi."},
            {"role": "assistant", "content": "Ừ, bản này đã khép được lỗi đó."},
        ],
        latest_observation={
            "discourse": {
                "status": "closed",
                "reply_expected": False,
                "assistant_may_continue": False,
                "thread_key": "combat_fix",
                "confidence": 0.91,
            }
        },
        seconds_since_user=40,
        seconds_since_assistant=20,
    )
    assert state.thread_fresh is True
    assert state.assistant_may_continue is False
    assert state.mode == "ambient"
    assert state.topic_closed is True


def test_discourse_state_obeys_observer_waiting_user_without_text_heuristic() -> None:
    from runtime.ai_orchestrated.discourse_state import DiscourseStateBuilder

    state = DiscourseStateBuilder().build(
        [{"role": "assistant", "content": "Một câu bất kỳ, dấu câu không có quyền semantic."}],
        latest_observation={
            "discourse": {
                "status": "waiting_user",
                "reply_expected": True,
                "assistant_may_continue": False,
                "unresolved_point": "user needs to answer current question",
                "thread_key": "current_activity_question",
                "confidence": 0.93,
                "evidence": ["observer:last_public_turn"],
            }
        },
        seconds_since_user=50,
        seconds_since_assistant=10,
    )
    assert state.reply_expected is True
    assert state.assistant_may_continue is False
    assert "must not nag" in state.to_dict()["instruction"]


def test_activity_session_only_accepts_main_planner_annotation_once() -> None:
    from runtime.ai_orchestrated.activity_session import ActivitySessionTracker
    from runtime.ai_orchestrated.ambient_screen_context import AmbientScreenContext
    from runtime.ai_orchestrated.semantic_contracts import ActivitySemantics

    tracker = ActivitySessionTracker()
    first = tracker.observe(
        AmbientScreenContext(
            revision=1,
            window_title="Mini World",
            process_name="miniworld.exe",
            age_seconds=0.2,
            changed_ratio=0.2,
            window_changed=True,
            content_changed=True,
            changed_text=("Victory",),
            evidence_refs=("screen:result",),
        ),
        now=1000,
    )
    # Runtime nhìn chữ Victory vẫn không được tự kết luận thắng.
    assert first.phase == "unknown"
    annotated = tracker.annotate(
        ActivitySemantics(
            activity_kind="gaming",
            phase="post_match",
            event="match result screen appeared",
            event_key="match_result_screen",
            confidence=0.88,
            evidence_refs=("screen:result", "vision:result_layout"),
        ),
        now=1001,
    )
    assert annotated.phase == "post_match"
    assert "semantic:match_result_screen" in annotated.new_event_keys

    tracker.observe(
        AmbientScreenContext(
            revision=1,
            window_title="Mini World",
            process_name="miniworld.exe",
            age_seconds=0.2,
        ),
        now=1002,
    )
    repeated = tracker.annotate(
        ActivitySemantics(
            activity_kind="gaming",
            phase="post_match",
            event="same result screen",
            event_key="match_result_screen",
            confidence=0.88,
            evidence_refs=("screen:result",),
        ),
        now=1003,
    )
    assert repeated.new_event_keys == ()
    assert all(event.detail != "Victory" for event in repeated.recent_events)


def test_initiative_uses_typed_kind_cooldowns_not_global_twenty_minutes(tmp_path: Path) -> None:
    from runtime.ai_orchestrated.initiative import InitiativeController

    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    first = _plan(subject_key="autonomous_architecture")
    assert controller.evaluate(first, now=1000, seconds_since_user=50)[0] is True
    controller.record_spoken(first, now=1000)

    second = _plan(subject_key="activity_session")
    assert controller.evaluate(second, now=1040, seconds_since_user=50) == (True, "allowed")

    environment = _plan(
        kind="environment",
        speech_act="comment_screen_change",
        subject_key="godot_window",
        topic="Godot vừa đổi cửa sổ",
    )
    controller.record_spoken(environment, now=1100)
    denied, reason = controller.evaluate(
        _plan(
            kind="environment",
            speech_act="ask_about_new_error",
            subject_key="godot_error",
            topic="Godot hiện lỗi mới",
        ),
        now=1120,
        seconds_since_user=50,
    )
    assert denied is False
    assert reason == "kind_cooldown"


def test_initiative_blocks_exact_model_semantic_signature_not_word_overlap(tmp_path: Path) -> None:
    from runtime.ai_orchestrated.initiative import InitiativeController

    controller = InitiativeController(state_path=tmp_path / "initiative.json")
    first = _plan(
        kind="environment",
        speech_act="ask_current_activity",
        subject_key="mini_world_session",
        topic="hỏi người dùng về game Mini World đang mở",
    )
    controller.record_spoken(first, now=1000)
    allowed, reason = controller.evaluate(
        _plan(
            kind="environment",
            speech_act="ask_current_activity",
            subject_key="mini_world_session",
            topic="câu chữ hoàn toàn khác nhưng semantic key vẫn giữ nguyên",
        ),
        now=1100,
        seconds_since_user=60,
    )
    assert allowed is False
    assert reason == "semantic_repeat"

    # Cùng từ ngữ nhưng speech act/subject khác thì runtime không tự đoán là lặp.
    allowed, reason = controller.evaluate(
        _plan(
            kind="environment",
            speech_act="comment_new_scene",
            subject_key="mini_world_result",
            topic="hỏi người dùng về game Mini World đang mở",
        ),
        now=1100,
        seconds_since_user=60,
    )
    assert (allowed, reason) == (True, "allowed")


def test_body_only_uses_planner_motion_hint_not_scene_keyword() -> None:
    from runtime.ai_orchestrated.orchestrator import AIAutonomousOrchestrator

    sent = []
    host = SimpleNamespace(
        logger=SimpleNamespace(debug=lambda *args, **kwargs: None),
        _send_decision_to_body=lambda decision, channel: sent.append((decision, channel)),
    )
    runtime = AIAutonomousOrchestrator(host)
    runtime.trace_store = SimpleNamespace(append=lambda *args, **kwargs: None)

    assert runtime._emit_body_only(
        reason="user_busy",
        activity_kind="arbitrary_upstream_label",
        motion_hint="focus",
        turn_seq=7,
        signature="event:1",
    ) is True
    decision, channel = sent[0]
    assert channel == "autonomous"
    assert decision.should_speak is False
    assert decision.stage_motion == "focus"
    assert decision.motion_intent == "focus"


def test_autonomous_trace_never_persists_raw_screen_text(tmp_path: Path) -> None:
    from runtime.ai_orchestrated.autonomous_trace import AutonomousTraceStore

    path = tmp_path / "trace.jsonl"
    store = AutonomousTraceStore(path=path)
    store.append("deliberation_input", {
        "turn_seq": 3,
        "screen_delta": True,
        "raw_ocr_text": "private secret",
        "mechanical_event_keys": ["screen_delta:1"],
    }, now=1000)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["screen_delta"] is True
    assert "raw_ocr_text" not in payload
    assert "private secret" not in path.read_text(encoding="utf-8")
