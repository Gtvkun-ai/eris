from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.background_memory_digest_kernel import (
    BackgroundMemoryDigestKernelConfig,
    BackgroundMemoryDigestKernelService,
)
from runtime.state_commit_service import StateCommitServiceMixin


class _DummyLogger:
    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


class _RecordingKernel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest(self, text: str, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return SimpleNamespace(
            committed_count=1,
            to_dict=lambda: {"committed_count": 1, "mode": kwargs.get("mode")},
        )


class _DummyStateCommitRuntime(StateCommitServiceMixin):
    def __init__(self) -> None:
        self.logger = _DummyLogger()
        self.memory_kernel = _RecordingKernel()
        self.memory_state = None


def test_user_turn_commit_uses_memory_kernel_fast_ingest() -> None:
    runtime = _DummyStateCommitRuntime()
    frame = SimpleNamespace(
        frame_id="frame-123",
        channel="chat",
        permission=None,
        commit_requests=[],
    )

    runtime._add_user_turn_memory_commit_requests(frame, "toi thich code", turn_id="turn:1")

    assert len(runtime.memory_kernel.calls) == 1
    call = runtime.memory_kernel.calls[0]
    assert call["text"] == "toi thich code"
    assert call["mode"] == "fast"
    assert call["turn_id"] == "turn:1"
    assert call["evidence_ids"] == ["turn:1"]
    assert frame.commit_requests == []


def test_background_digest_requeues_recent_user_input_instead_of_dropping() -> None:
    kernel = _RecordingKernel()
    service = BackgroundMemoryDigestKernelService(
        kernel,
        config=BackgroundMemoryDigestKernelConfig(
            enabled=True,
            worker_idle_sleep=0.001,
            user_input_pause_seconds=0.01,
            requeue_delay_seconds=0.01,
            pause_on_user_input=True,
            idle_only=False,
            only_when_remote_inflight=False,
        ),
        logger=_DummyLogger(),
    )

    assert service.enqueue_user_turn("toi thich code", turn_id="turn:1") is True

    processed = service.drain_once_for_tests()
    assert processed == 0
    assert service.stats.processed == 0
    assert service.stats.skipped == 0
    assert len(kernel.calls) == 0

    delayed_job = service._queue.get_nowait()
    assert delayed_job.not_before > delayed_job.created_at
    service._queue.put_nowait(delayed_job)

    time.sleep(0.06)

    processed = service.drain_once_for_tests()
    assert processed == 1
    assert service.stats.processed == 1
    assert len(kernel.calls) == 1
