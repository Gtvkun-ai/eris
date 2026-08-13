from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from runtime.ai_orchestrated.cognitive_blackboard import TypedCognitiveBlackboard
from runtime.ai_orchestrated.conversation_arc import ConversationArcRuntime
from runtime.ai_orchestrated.initiative import InitiativeAction, InitiativeController
from runtime.ai_orchestrated.model_router import (
    AIRuntimeModelRouter,
    PUBLIC_REPLY_SCHEMA,
    SOCIAL_PLAN_SCHEMA,
)
from runtime.ai_orchestrated.social_agenda import SocialAgendaStore
from runtime.ai_orchestrated.social_continuation import SocialContinuationRuntime
from runtime.tts_engine import _effective_elevenlabs_speed


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


def _empty_social_plan():
    return {
        "afterbeat": {
            "decision": "none",
            "role": "afterthought",
            "objective": "",
            "pause_class": "short",
            "tone": "neutral",
            "confidence": 0.0,
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
            "decision": "none",
            "goal_type": "none",
            "objective": "",
            "desired_user_state": "",
            "strategy": "",
            "horizon": "session",
            "success_signals": [],
            "stop_signals": [],
            "salience": 0.0,
            "evidence_refs": [],
        },
        "conversation_arc": {
            "decision": "none",
            "goal": "",
            "beats": [],
            "confidence": 0.0,
        },
    }


def _board(*, reply_expected=False, user_busy=False, seconds_since_user=90.0):
    return TypedCognitiveBlackboard.from_snapshot(
        {
            "time": 1000.0,
            "telemetry": {"user_busy": user_busy},
            "screen_context": {"fresh": True, "privacy_blocked": False},
            "vision_grounding": {"recommendation": "silence", "claims": []},
            "conversation_baton": {
                "reply_expected": reply_expected,
                "assistant_may_continue": False,
                "thread_fresh": True,
                "thread_key": "thread:test",
            },
            "activity_session": {"has_new_event": False, "new_event_keys": []},
            "self_context": {"has_public_seed": False, "attention": {}},
            "discovery": {},
            "commentary_expectation": {"due": False, "required": False},
            "engagement_context": {"active": False},
            "engagement_interaction": {},
            "latest_observation": {},
            "seconds_since_user": seconds_since_user,
            "seconds_since_assistant": 90.0,
            "open_loops": [],
            "recent_public_history": [],
        },
        now=1000.0,
    )


def _afterbeat_plan():
    plan = _empty_social_plan()
    plan["afterbeat"] = {
        "decision": "reserve",
        "role": "punchline",
        "objective": "Add the dry implication deliberately withheld by the first line.",
        "pause_class": "micro",
        "tone": "dry_tease",
        "confidence": 0.9,
    }
    return plan


def _exposure_plan():
    plan = _empty_social_plan()
    plan["exposure"] = {
        "decision": "open",
        "kind": "playful_vulnerability",
        "level": 0.72,
        "expects_reaction": True,
        "reaction_window_class": "micro",
        "expected_responses": ["laugh", "deny", "freeze", "counter_tease"],
        "silence_hypotheses": ["user_is_processing", "user_is_preparing_to_speak"],
        "recovery_style": "soft_embarrassed_tease",
        "confidence": 0.82,
    }
    return plan


def _schedule(runtime: SocialContinuationRuntime, plan, now=1000.0):
    return runtime.schedule_from_social_plan(
        plan,
        source_turn_id="turn:1",
        source_text="Ừ, nghe cũng vô tội đấy.",
        source_turn_seq=1,
        semantic_frame={"tool_intent": "none", "boundary_action": "none"},
        assistant_act={"kind": "answer"},
        now=now,
    )


def test_public_reply_schema_requires_all_social_plan_appraisals():
    assert "social_plan" in PUBLIC_REPLY_SCHEMA["required"]
    assert set(SOCIAL_PLAN_SCHEMA["required"]) == {
        "afterbeat", "exposure", "agenda_update", "conversation_arc"
    }

    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_empty_social_plan(), SOCIAL_PLAN_SCHEMA)


def test_compat_envelope_fills_none_social_plan_and_ignores_legacy_arc():
    router = object.__new__(AIRuntimeModelRouter)
    router.logger = None
    payload = router._compat_public_envelope(
        {
            "semantic_frame": {},
            "assistant_act": {"kind": "answer", "proposition_mode": "new", "confidence": 0.8},
            "should_speak": True,
            "utterance": {
                "display": {"text": "Được.", "language": "vi"},
                "speech": {"text": "うん。", "language": "ja"},
                "performance": {"preset": "neutral", "intensity": 0.4, "nonverbal_cue": ""},
            },
            "conversation_arc": {
                "decision": "schedule",
                "arc_id": "legacy:1",
                "thread_key": "thread:1",
                "goal": "Continue the bit if it still lands.",
                "user_reply_policy": "replan",
                "expires_after_seconds": 120,
                "beats": [{
                    "role": "callback",
                    "objective": "Return to the shared joke once.",
                    "delay_seconds": 9.0,
                    "tone": "playful",
                    "max_sentences": 1,
                }],
            },
        }
    )
    assert set(payload["social_plan"]) == set(_empty_social_plan())
    assert payload["social_plan"]["conversation_arc"]["decision"] == "none"
    assert "conversation_arc" not in payload


def test_afterbeat_claim_is_atomic_under_concurrency():
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert _schedule(runtime, _afterbeat_plan()) == {"afterbeat": True, "exposure": False}
    assert runtime.notify_audio_finished(1000.0, source_turn_id="turn:1") == 1
    affordance = runtime.peek_due(now=1001.0, interaction_busy=False)
    assert affordance is not None
    assert affordance.candidate.expression_commitment["origin"] == "social_continuation"

    barrier = threading.Barrier(8)
    results = []
    lock = threading.Lock()

    def worker(index):
        barrier.wait()
        candidate = runtime.claim_due(worker_id=f"w{index}", now=1001.0)
        with lock:
            results.append(candidate)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [candidate for candidate in results if candidate is not None]
    assert len(winners) == 1
    assert winners[0].continuation_lane == "afterbeat"
    assert runtime.snapshot(now=1001.0)["claimed"] == 1


def test_afterbeat_lease_reclaim_rejects_stale_completion():
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    _schedule(runtime, _afterbeat_plan())
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    first = runtime.claim_due(worker_id="w1", now=1001.0, lease_ms=500)
    assert first is not None
    second = runtime.claim_due(worker_id="w2", now=1001.6, lease_ms=500)
    assert second is not None
    assert second.claim_token != first.claim_token

    stale_plan = SimpleNamespace(
        continuation_ticket_id=first.anchor_id,
        continuation_claim_token=first.claim_token,
        continuation_lane="afterbeat",
        semantics=SimpleNamespace(subject_key=first.anchor_id),
    )
    assert runtime.note_spoken(stale_plan, "stale", now=1001.7) is False

    live_plan = SimpleNamespace(
        continuation_ticket_id=second.anchor_id,
        continuation_claim_token=second.claim_token,
        continuation_lane="afterbeat",
        semantics=SimpleNamespace(subject_key=second.anchor_id),
    )
    assert runtime.note_spoken(live_plan, "fresh", now=1001.7) is True


def test_user_signal_cancels_reserved_afterbeat_before_playback():
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    _schedule(runtime, _afterbeat_plan())
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    result = runtime.observe_user_signal(signal="vad_start", now=1000.1)
    assert result["cancelled_afterbeats"] == 1
    assert runtime.claim_due(worker_id="w", now=1002.0) is None


def test_social_exposure_waits_for_reaction_and_recovers_at_most_once():
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert _schedule(runtime, _exposure_plan()) == {"afterbeat": False, "exposure": True}
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    assert runtime.claim_due(worker_id="w", now=1000.8) is None
    candidate = runtime.claim_due(worker_id="w", now=1000.9)
    assert candidate is not None
    assert candidate.kind == "social_exposure_recovery"

    plan = SimpleNamespace(
        continuation_ticket_id=candidate.anchor_id,
        continuation_claim_token=candidate.claim_token,
        continuation_lane="social_exposure",
        semantics=SimpleNamespace(subject_key=candidate.anchor_id),
    )
    assert runtime.note_spoken(plan, "Tôi nói hơi bất ngờ quá nhỉ.", now=1001.0)
    assert runtime.claim_due(worker_id="w2", now=1002.0) is None


def test_user_reaction_resolves_social_exposure_without_recovery():
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    _schedule(runtime, _exposure_plan())
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    result = runtime.observe_user_signal(signal="laugh", text="haha", now=1000.3)
    assert result["resolved_exposures"] == 1
    assert runtime.claim_due(worker_id="w", now=1002.0) is None


def _agenda_update():
    return {
        "decision": "open",
        "goal_type": "build_shared_bit",
        "objective": "Turn the anime trope into a sparse recurring reference.",
        "desired_user_state": "amused_and_involved",
        "strategy": "test_once_observe_then_callback_sparingly",
        "horizon": "session",
        "success_signals": ["user_laughs", "user_counter_teases"],
        "stop_signals": ["explicit_boundary", "two_low_engagement_responses"],
        "salience": 0.74,
        "evidence_refs": ["turn:1"],
    }


def test_exposure_outcome_updates_scene_partner_state():
    store = SocialAgendaStore(clock=lambda: 1000.0)
    runtime = SocialContinuationRuntime(
        clock=lambda: 1000.0,
        timer_factory=_FakeTimer,
        outcome_callback=store.observe_exposure_outcome,
    )
    _schedule(runtime, _exposure_plan())
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    runtime.observe_user_signal(signal="laugh", text="haha", now=1000.3)

    partner = store.snapshot(now=1000.3)["scene_partner"]
    assert partner["tease_tolerance_estimate"] > 0.35
    assert partner["hypotheses"][-1]["state"] == "playfully_engaged"


def test_social_agenda_opens_advances_and_closes_after_two_low_engagement_turns():
    store = SocialAgendaStore(clock=lambda: 1000.0)
    assert store.apply_update(_agenda_update(), source_turn_id="turn:1", now=1000.0)
    candidate = store.claim_due(_board(seconds_since_user=90.0), worker_id="test-worker", now=1001.0)
    assert candidate is not None
    assert candidate.kind == "social_agenda"

    first = store.observe_user_turn(user_text="ừ", now=1002.0)
    second = store.observe_user_turn(user_text="ok", now=1003.0)
    assert first["closed"] == 0
    assert second["closed"] == 1
    assert store.snapshot(now=1003.0)["active_goal_count"] == 0


def test_social_agenda_move_claim_is_atomic_and_completes_once():
    store = SocialAgendaStore(clock=lambda: 1000.0)
    store.apply_update(_agenda_update(), source_turn_id="turn:1", now=1000.0)
    board = _board(seconds_since_user=90.0)
    affordance = store.peek_due(board, now=1001.0)
    assert affordance is not None
    assert affordance.candidate.expression_commitment["origin"] == "social_agenda"
    barrier = threading.Barrier(6)
    results = []
    lock = threading.Lock()

    def worker(index):
        barrier.wait()
        candidate = store.claim_due(
            board,
            worker_id=f"agenda-worker-{index}",
            now=1001.0,
        )
        with lock:
            results.append(candidate)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [candidate for candidate in results if candidate is not None]
    assert len(winners) == 1
    candidate = winners[0]
    assert candidate.continuation_lane == "social_agenda"
    assert candidate.claim_token
    assert store.snapshot(now=1001.0)["claimed_goal_count"] == 1

    plan = SimpleNamespace(
        continuation_ticket_id=candidate.anchor_id,
        continuation_claim_token=candidate.claim_token,
        semantics=SimpleNamespace(
            turn_kind="social_agenda",
            subject_key=candidate.anchor_id,
        ),
    )
    assert store.note_spoken(plan, now=1002.0) is True
    snapshot = store.snapshot(now=1002.0)
    assert snapshot["claimed_goal_count"] == 0
    active = [goal for goal in snapshot["goals"] if goal["status"] == "active"]
    assert active[0]["move_seq"] == 1


def test_explicit_boundary_closes_agenda_and_blocks_future_move():
    store = SocialAgendaStore(clock=lambda: 1000.0)
    store.apply_update(_agenda_update(), source_turn_id="turn:1", now=1000.0)
    result = store.observe_user_turn(user_text="Đừng trêu vậy nữa.", now=1001.0)
    assert result["boundary"] is True
    assert result["closed"] == 1
    snapshot = store.snapshot(now=1001.0)
    assert "explicit_social_boundary" in snapshot["scene_partner"]["boundary_flags"]
    assert store.claim_due(_board(seconds_since_user=90.0), worker_id="test-worker", now=1100.0) is None


def test_afterbeat_governor_preserves_claim_and_idempotency(tmp_path):
    runtime = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    _schedule(runtime, _afterbeat_plan())
    runtime.notify_audio_finished(1000.0, source_turn_id="turn:1")
    candidate = runtime.claim_due(worker_id="w", now=1001.0)
    assert candidate is not None

    decision = InitiativeController(state_path=tmp_path / "initiative.json").decide(
        _board(reply_expected=True, user_busy=False),
        candidate,
    )
    assert decision.action is InitiativeAction.SPEECH
    plan = decision.speech_intent.plan
    assert plan.continuation_lane == "afterbeat"
    assert plan.continuation_ticket_id == candidate.anchor_id
    assert plan.continuation_claim_token == candidate.claim_token
    assert plan.continuation_idempotency_key == candidate.idempotency_key


def test_conversation_arc_claim_prevents_double_wake():
    runtime = ConversationArcRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer)
    assert runtime.schedule_from_model(
        {
            "decision": "schedule",
            "goal": "Continue only if the bit still fits.",
            "beats": [{
                "role": "callback",
                "objective": "Make one restrained callback.",
                "condition": "user_reengages_playfully",
                "tone": "playful",
            }],
            "confidence": 0.8,
        },
        source_turn_id="turn:1",
        source_text="Setup.",
        source_turn_seq=1,
        semantic_frame={},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )
    affordance = runtime.peek_due(now=1008.0, interaction_busy=False)
    assert affordance is not None
    assert affordance.candidate.expression_commitment["origin"] == "conversation_arc"
    first = runtime.claim_due(worker_id="w1", now=1008.0)
    second = runtime.claim_due(worker_id="w2", now=1008.0)
    assert first is not None
    assert second is None
    assert first.continuation_lane == "conversation_arc"


def test_elevenlabs_speed_is_clamped_to_provider_range():
    assert _effective_elevenlabs_speed(1.2, 1.2) == pytest.approx(1.2)
    assert _effective_elevenlabs_speed(0.3, 0.5) == pytest.approx(0.7)
    assert _effective_elevenlabs_speed(1.0, 1.04) == pytest.approx(1.092)
