from dataclasses import replace
from types import SimpleNamespace

from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
from runtime.pedagogical_contracts import TeachingConcept, TeachingEpisode, TeachingReceipt
from runtime import pedagogical_runtime
from runtime.pedagogical_runtime import PedagogicalRuntime, PedagogicalRuntimeLimits, ensure_pedagogical_runtime


class _Clock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class _FakeTimer:
    instances = []

    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def _episode(*, status="ready", revision=1):
    concepts = (
        TeachingConcept("first", "First concept", "Understand first."),
        TeachingConcept("second", "Second concept", "Understand second."),
        TeachingConcept("third", "Third concept", "Understand third."),
    )
    base = TeachingEpisode.new(
        episode_id="teaching:first:1000",
        topic_key="first",
        global_goal="Learn the distinction.",
        concepts=concepts,
        now=1000.0,
        expires_at=1600.0,
    )
    from runtime.pedagogical_contracts import ComprehensionState, TeachingChunk

    return replace(
        base,
        status=status,
        plan_revision=revision,
        comprehension=ComprehensionState(current_concept_id="first"),
        pending_chunk=TeachingChunk("first:r1", "first", "Understand first.", claim="First concept"),
    )


def _receipt(*, episode_id="teaching:first:1000", revision=1, chunk_id="first:r1", successful=True):
    return TeachingReceipt(episode_id, revision, chunk_id, turn_id="turn:1", successful=successful)


def _runtime(tmp_path, clock=None, wake_callback=None):
    clock = clock or _Clock()
    return PedagogicalRuntime(
        SQLiteAtomicStateStore(tmp_path / "state.sqlite", clock=clock),
        clock=clock,
        timer_factory=_FakeTimer,
        wake_callback=wake_callback,
    )


def test_restart_clears_expired_claim_and_rearms_pending_dwell(tmp_path):
    clock = _Clock()
    store = SQLiteAtomicStateStore(tmp_path / "state.sqlite", clock=clock)
    first = PedagogicalRuntime(store, clock=clock, timer_factory=_FakeTimer)
    assert first.start_episode(_episode(status="dwelling"))
    assert first.claim_due(worker_id="worker-a", now=1001.0) is not None
    first.shutdown()

    clock.value = 1003.0
    second = PedagogicalRuntime(store, clock=clock, timer_factory=_FakeTimer)
    assert second.claim_due(worker_id="worker-b", now=1003.0) is not None


def test_stale_receipt_is_ignored(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode(revision=2))
    assert not runtime.commit_receipt(_receipt(revision=1))
    assert runtime.snapshot()["active_episode"]["status"] == "ready"


def test_user_turn_cancels_due_dwell_before_claim(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode(status="dwelling"))
    result = runtime.observe_user_turn("Wait, that is not clear", now=1001.0)
    assert result.episode.status == "observing"
    assert runtime.claim_due(worker_id="worker", now=1002.0) is None
    assert runtime.snapshot()["active_episode"]["status"] == "observing"


def test_claim_is_leased_and_cannot_be_duplicated_while_live(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode(status="dwelling"))
    first = runtime.claim_due(worker_id="worker-a", now=1001.0)
    assert first is not None
    assert runtime.claim_due(worker_id="worker-b", now=1001.1) is None
    assert runtime.snapshot(now=1001.1)["claimed"] is True


def test_claimed_dwell_directive_commits_once_and_advances_episode(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode(status="dwelling"))
    directive = runtime.claim_due(worker_id="worker-a", now=1001.0)
    assert directive is not None
    receipt = _receipt(
        episode_id=directive.episode_id,
        revision=directive.plan_revision,
        chunk_id=directive.chunk_id,
    )
    assert not runtime.commit_receipt(_receipt(chunk_id="stale"), now=1001.05)
    assert runtime.commit_receipt(receipt, now=1001.1)
    assert not runtime.commit_receipt(receipt, now=1001.2)
    snapshot = runtime.snapshot(now=1001.2)
    assert snapshot["active_episode"]["status"] == "speaking"
    assert snapshot["active_episode"]["autonomous_chunks_used"] == 1


def test_receipt_is_idempotent_and_mismatched_identity_is_rejected(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode())
    assert not runtime.commit_receipt(_receipt(episode_id="other"))
    assert not runtime.commit_receipt(_receipt(revision=2))
    assert not runtime.commit_receipt(_receipt(chunk_id="other"))
    assert runtime.commit_receipt(_receipt())
    assert not runtime.commit_receipt(_receipt())
    snapshot = runtime.snapshot()
    assert snapshot["active_episode"]["status"] == "speaking"
    assert snapshot["active_episode"]["autonomous_chunks_used"] == 0


def test_foreground_audio_completion_waits_for_user_without_rearming_same_chunk(tmp_path):
    clock = _Clock()
    runtime = _runtime(tmp_path, clock)
    assert runtime.start_episode(_episode())
    assert runtime.commit_receipt(_receipt())
    runtime.notify_audio_finished(1010.0, source_turn_id="turn:1")
    snapshot = runtime.snapshot(now=1010.0)
    assert snapshot["active_episode"]["status"] == "waiting_user"
    assert snapshot["dwell_anchor_at"] == 0.0
    assert runtime.claim_due(worker_id="worker", now=1011.0) is None


def test_runtime_limits_clamp_dwell_and_foreground_audio_does_not_repeat_chunk(tmp_path):
    clock = _Clock()
    limits = PedagogicalRuntimeLimits(minimum_dwell_seconds=2.0, maximum_dwell_seconds=3.0)
    runtime = PedagogicalRuntime(
        SQLiteAtomicStateStore(tmp_path / "state.sqlite", clock=clock),
        clock=clock,
        timer_factory=_FakeTimer,
        limits=limits,
    )
    assert runtime.start_episode(_episode())
    assert runtime.commit_receipt(_receipt(), now=1000.5)
    runtime.notify_audio_finished(1010.0, source_turn_id="turn:1")
    snapshot = runtime.snapshot(now=1010.0)
    assert snapshot["active_episode"]["status"] == "waiting_user"
    assert snapshot["active_episode"]["autonomous_chunks_used"] == 0
    assert runtime.claim_due(worker_id="worker", now=1012.0) is None


def test_runtime_loads_registered_pedagogy_limits(monkeypatch):
    values = {
        "minimum_dwell_seconds": 2.0,
        "maximum_dwell_seconds": 4.0,
        "max_autonomous_chunks": 1,
        "max_repair_attempts": 0,
        "max_consecutive_stalls": 3,
        "episode_expiry_seconds": 120.0,
    }
    monkeypatch.setattr(
        pedagogical_runtime,
        "runtime_float",
        lambda _group, name, default: values.get(name, default),
    )
    monkeypatch.setattr(
        pedagogical_runtime,
        "runtime_int",
        lambda _group, name, default: values.get(name, default),
    )
    limits = PedagogicalRuntimeLimits.from_runtime_settings()
    assert limits.dwell_seconds == 2.0
    assert limits.controller_limits.max_autonomous_chunks == 1
    assert limits.controller_limits.max_repair_attempts == 0
    assert limits.controller_limits.episode_expiry_seconds == 120.0


def test_claimed_autonomous_receipt_consumes_once_and_does_not_rearm_same_chunk(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.start_episode(_episode(status="dwelling"))
    directive = runtime.claim_due(worker_id="worker", now=1001.0)
    assert directive is not None
    receipt = _receipt(episode_id=directive.episode_id, revision=directive.plan_revision, chunk_id=directive.chunk_id)
    assert runtime.commit_receipt(receipt, now=1001.1)
    runtime.notify_audio_finished(1002.0, source_turn_id="turn:1")
    snapshot = runtime.snapshot(now=1002.0)
    assert snapshot["active_episode"]["status"] == "waiting_user"
    assert snapshot["active_episode"]["autonomous_chunks_used"] == 1
    assert runtime.claim_due(worker_id="worker-2", now=1003.0) is None


def test_cancel_and_shutdown_cancel_timers_and_preserve_episode(tmp_path):
    _FakeTimer.instances.clear()
    runtime = _runtime(tmp_path, wake_callback=lambda _reason: None)
    assert runtime.start_episode(_episode(status="dwelling"))
    first_timer = _FakeTimer.instances[-1]
    runtime.cancel_dwell("user_interrupted", now=1001.0)
    assert first_timer.cancelled
    assert runtime.snapshot()["active_episode"]["status"] == "waiting_user"

    assert runtime.start_episode(_episode(status="dwelling"))
    second_timer = _FakeTimer.instances[-1]
    runtime.shutdown()
    assert second_timer.cancelled
    assert runtime.snapshot()["active_episode"]["episode_id"] == "teaching:first:1000"


def test_ensure_runtime_honors_feature_setting_and_reuses_host_store(tmp_path, monkeypatch):
    store = SQLiteAtomicStateStore(tmp_path / "state.sqlite")
    disabled = SimpleNamespace(pedagogical_controller_enabled=False, ai_social_atomic_store=store)
    assert ensure_pedagogical_runtime(disabled) is None

    enabled = SimpleNamespace(
        pedagogical_controller_enabled=True,
        ai_social_atomic_store=store,
        _runtime_clock=lambda: 1000.0,
        _wake_autonomous_loop=lambda _reason: None,
    )
    first = ensure_pedagogical_runtime(enabled)
    second = ensure_pedagogical_runtime(enabled)
    assert isinstance(first, PedagogicalRuntime)
    assert second is first
    assert first._store is store
