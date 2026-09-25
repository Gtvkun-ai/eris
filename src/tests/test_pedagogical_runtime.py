from dataclasses import replace
from types import SimpleNamespace

from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
from runtime.pedagogical_contracts import TeachingConcept, TeachingEpisode, TeachingReceipt
from runtime.pedagogical_runtime import PedagogicalRuntime, ensure_pedagogical_runtime


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
    assert snapshot["active_episode"]["autonomous_chunks_used"] == 1


def test_audio_finished_moves_dwell_anchor_forward(tmp_path):
    clock = _Clock()
    runtime = _runtime(tmp_path, clock)
    assert runtime.start_episode(_episode())
    assert runtime.commit_receipt(_receipt())
    runtime.notify_audio_finished(1010.0, source_turn_id="turn:1")
    snapshot = runtime.snapshot(now=1010.0)
    assert snapshot["active_episode"]["status"] == "dwelling"
    assert snapshot["dwell_anchor_at"] == 1010.0
    assert runtime.claim_due(worker_id="worker", now=1010.5) is None
    assert runtime.claim_due(worker_id="worker", now=1011.0) is not None


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
