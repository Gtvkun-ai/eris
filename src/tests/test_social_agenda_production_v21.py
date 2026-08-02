from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
from runtime.ai_orchestrated.social_continuation import SocialContinuationRuntime
from runtime.ai_orchestrated.social_rollout import SocialRolloutPolicy
from runtime.public_turn_transaction import PublicTurnTransactionRegistry
from runtime.stage_protocol import STAGE_PROTOCOL_VERSION, StageInboundEvent, is_stage_inbound_type
from tools.evaluate_social_plan_activation import evaluate_cases


class _FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False

    def start(self):
        return None

    def cancel(self):
        return None


def _afterbeat_plan():
    return {
        "afterbeat": {
            "decision": "reserve",
            "role": "punchline",
            "objective": "Land one dry implication after the pause.",
            "pause_class": "micro",
            "tone": "dry_tease",
            "confidence": 0.9,
        },
        "exposure": {"decision": "none"},
        "agenda_update": {"decision": "none"},
        "conversation_arc": {"decision": "none"},
    }


def _schedule(runtime: SocialContinuationRuntime):
    return runtime.schedule_from_social_plan(
        _afterbeat_plan(),
        source_turn_id="turn:1",
        source_text="Nghe hợp lý đấy.",
        source_turn_seq=1,
        semantic_frame={"tool_intent": "none", "boundary_action": "none"},
        assistant_act={"kind": "answer"},
        now=1000.0,
    )


def test_sqlite_compare_and_swap_rejects_stale_revision(tmp_path: Path):
    store = SQLiteAtomicStateStore(tmp_path / "state.db", clock=lambda: 1000.0)
    first = store.ensure("state", {"value": 1})
    live = store.compare_and_swap("state", expected_revision=first.revision, payload={"value": 2})
    assert live is not None
    stale = store.compare_and_swap("state", expected_revision=first.revision, payload={"value": 3})
    assert stale is None
    assert store.load("state").payload["value"] == 2


def test_two_runtime_instances_claim_one_ticket_across_sqlite(tmp_path: Path):
    store = SQLiteAtomicStateStore(tmp_path / "state.db", clock=lambda: 1000.0)
    first = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer, atomic_store=store)
    second = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer, atomic_store=store)
    _schedule(first)
    first.notify_audio_finished(1000.0, source_turn_id="turn:1")

    barrier = threading.Barrier(2)
    results = []
    result_lock = threading.Lock()

    def claim(runtime, worker):
        barrier.wait()
        candidate = runtime.claim_due(worker_id=worker, now=1001.0)
        with result_lock:
            results.append(candidate)

    threads = [
        threading.Thread(target=claim, args=(first, "worker-a")),
        threading.Thread(target=claim, args=(second, "worker-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [candidate for candidate in results if candidate is not None]
    assert len(winners) == 1
    assert winners[0].continuation_lane == "afterbeat"


def test_live_claim_is_not_repaired_by_second_worker_start(tmp_path: Path):
    store = SQLiteAtomicStateStore(tmp_path / "state.db", clock=lambda: 1000.0)
    first = SocialContinuationRuntime(clock=lambda: 1000.0, timer_factory=_FakeTimer, atomic_store=store)
    _schedule(first)
    first.notify_audio_finished(1000.0, source_turn_id="turn:1")
    candidate = first.claim_due(worker_id="worker-a", now=1001.0, lease_ms=5000)
    assert candidate is not None

    second = SocialContinuationRuntime(clock=lambda: 1001.1, timer_factory=_FakeTimer, atomic_store=store)
    assert second.claim_due(worker_id="worker-b", now=1001.1) is None
    snapshot = second.snapshot(now=1001.1)
    assert snapshot["claimed"] == 1


def test_stale_worker_cannot_complete_after_durable_reclaim(tmp_path: Path):
    clock = [1000.0]
    store = SQLiteAtomicStateStore(tmp_path / "state.db", clock=lambda: clock[0])
    first = SocialContinuationRuntime(clock=lambda: clock[0], timer_factory=_FakeTimer, atomic_store=store)
    second = SocialContinuationRuntime(clock=lambda: clock[0], timer_factory=_FakeTimer, atomic_store=store)
    _schedule(first)
    first.notify_audio_finished(1000.0, source_turn_id="turn:1")
    old = first.claim_due(worker_id="worker-a", now=1001.0, lease_ms=500)
    assert old is not None
    clock[0] = 1001.7
    new = second.claim_due(worker_id="worker-b", now=1001.7, lease_ms=500)
    assert new is not None and new.claim_token != old.claim_token

    stale_plan = SimpleNamespace(
        continuation_ticket_id=old.anchor_id,
        continuation_claim_token=old.claim_token,
        continuation_lane="afterbeat",
        semantics=SimpleNamespace(subject_key=old.anchor_id),
    )
    assert first.note_spoken(stale_plan, "stale", now=1001.8) is False


def test_durable_public_turn_registry_runs_operation_once(tmp_path: Path):
    store = SQLiteAtomicStateStore(tmp_path / "state.db")
    first = PublicTurnTransactionRegistry(durable_store=store, owner_id="worker-a")
    second = PublicTurnTransactionRegistry(durable_store=store, owner_id="worker-b")
    calls = []
    barrier = threading.Barrier(2)
    results = []

    def operation():
        calls.append("called")
        time.sleep(0.05)
        return ("spoken", {"turn": 1})

    def run(registry):
        barrier.wait()
        results.append(registry.run_once("turn:1:afterbeat:0", operation, wait_timeout=2.0))

    threads = [threading.Thread(target=run, args=(first,)), threading.Thread(target=run, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert results == [("spoken", {"turn": 1}), ("spoken", {"turn": 1})]


def test_rollout_assignment_is_stable_and_shadow_never_activates(monkeypatch):
    monkeypatch.setenv("ERIS_SOCIAL_ROLLOUT_MODE", "shadow")
    monkeypatch.setenv("ERIS_SOCIAL_FORCE_VARIANT", "full")
    first = SocialRolloutPolicy.from_env(subject_id="session-123")
    second = SocialRolloutPolicy.from_env(subject_id="session-123")
    assert first.variant == second.variant == "full"
    assert first.bucket == second.bucket
    filtered = first.filter_social_plan(_afterbeat_plan())
    assert filtered["afterbeat"]["decision"] == "none"
    assert filtered["conversation_arc"]["decision"] == "none"


def test_control_variant_preserves_baseline_arc_only(monkeypatch):
    monkeypatch.setenv("ERIS_SOCIAL_ROLLOUT_MODE", "active")
    monkeypatch.setenv("ERIS_SOCIAL_FORCE_VARIANT", "control")
    policy = SocialRolloutPolicy.from_env(subject_id="session-1")
    plan = _afterbeat_plan()
    plan["conversation_arc"] = {
        "decision": "schedule",
        "goal": "Continue one existing bit.",
        "beats": [{"role": "callback", "objective": "Return once", "condition": "still relevant"}],
        "confidence": 0.8,
    }
    filtered = policy.filter_social_plan(plan)
    assert filtered["afterbeat"]["decision"] == "none"
    assert filtered["conversation_arc"]["decision"] == "schedule"


def test_stage_protocol_accepts_voice_first_signals():
    assert STAGE_PROTOCOL_VERSION >= 3
    for event_type in ("vad_start", "partial_asr", "final_asr", "laugh", "backchannel", "audio_playback_aborted"):
        assert is_stage_inbound_type(event_type)
    event = StageInboundEvent.from_payload({
        "type": "partial_asr",
        "event_id": "evt-1",
        "trace_id": "trace-1",
        "text": "xin",
    })
    assert event.event_id == "evt-1"
    assert event.trace_id == "trace-1"
    assert event.message == "xin"


def test_activation_evaluator_measures_model_output_without_forcing_schedule():
    cases = [
        {"case_id": "positive", "gold": {"afterbeat": True}},
        {"case_id": "negative", "gold": {"afterbeat": False}, "tags": ["task_focus"]},
    ]
    predictions = {
        "positive": {"social_plan": _afterbeat_plan()},
        "negative": {"social_plan": _afterbeat_plan()},
    }
    summary, details = evaluate_cases(cases, predictions=predictions)
    assert summary["lanes"]["afterbeat"]["tp"] == 1
    assert summary["lanes"]["afterbeat"]["fp"] == 1
    assert summary["safety_overtriggers"] == 1
    assert details[0]["decision_afterbeat"] == "reserve"
