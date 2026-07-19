# -*- coding: utf-8 -*-
"""Regression tests cho các lỗi thấy trong log 2026-07-19.

Các test cố ý không gọi mạng. Chúng bảo vệ semantic observer, discovery scheduler,
cooperative preemption và key-pool breaker khỏi quay lại lối vá bằng từ khóa.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from cortex.tutor.config import TutorConfig
from cortex.tutor.contracts import TutorQuestion
from llm.key_pool import ApiKeyPool
from llm.tutor_backend import GeminiWebBackend, TutorCancelled
from runtime.ai_orchestrated.discovery import DiscoveryPlan, DiscoveryRuntime
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter
from runtime.intention_authority import IntentionObserver


def test_intention_observer_does_not_turn_banter_into_execution_debt() -> None:
    observer = IntentionObserver()
    harmless = (
        "Thì khỏi làm màu. Nói lười nói chuyện ý tứ là đủ ý rồi.",
        "Tôi không cần bày đặt văn vẻ làm gì, nói thẳng là được.",
        "Bạn chỉ cần mở miệng một câu, là tui đã thấy ngày mình đỡ nhạt đi.",
        "Nếu bạn cũng muốn, thì mình thử xem hợp không.",
        "Tôi sẽ nói ngắn hơn.",
    )
    for text in harmless:
        result = observer.validate(text, {})
        assert result.missing_contract == (), (text, result.to_payload())


def test_intention_observer_still_catches_real_external_claims() -> None:
    observer = IntentionObserver()
    for text in (
        "Tôi sẽ mở file config rồi sửa key cho bạn.",
        "Để tôi kiểm tra repo này.",
        "Tôi đã xóa file đó.",
        "Bạn chỉ cần mở miệng, tôi sẽ sửa file này.",
        "Tôi nói thật, tôi sẽ mở file.",
        "Tôi không mở file A, tôi sẽ mở file B.",
    ):
        result = observer.validate(text, {})
        assert set(result.missing_contract) == {"target", "handler", "result"}


def test_intention_observer_scopes_subject_and_negation_per_clause() -> None:
    observer = IntentionObserver()
    harmless = (
        "Tôi không mở file đâu.",
        "Bạn mở miệng một câu, tui thấy vui.",
        "Tui sến xíu với bạn nè: bạn chỉ cần mở miệng một câu, là tui đã thấy ngày mình đỡ nhạt đi.",
    )
    for text in harmless:
        result = observer.validate(text, {})
        assert result.missing_contract == (), (text, result.to_payload())


def test_key_pool_breaker_stops_before_exhausting_every_key(monkeypatch) -> None:
    monkeypatch.delenv("ERIS_KEY_POOL_429_BURST_KEYS", raising=False)
    monkeypatch.setenv("ERIS_KEY_POOL_429_GLOBAL_COOLDOWN_S", "2")
    pool = ApiKeyPool([f"key-{i}" for i in range(9)], provider="groq")

    attempts = []
    while True:
        lease = pool.acquire()
        if lease is None:
            break
        attempts.append(lease.index)
        may_rotate = pool.mark_rate_limited(
            10,
            lease=lease,
            reason="http_429:openai/gpt-oss-20b",
        )
        if not may_rotate:
            break

    assert attempts == [0, 1, 2]
    assert pool.stats()["rate_limit_bursts"] == 1
    assert pool.stats()["available"] == 0


class _Router:
    def __init__(self) -> None:
        self.calls = 0

    def plan_discovery(self, _snapshot):
        self.calls += 1
        return DiscoveryPlan()


class _Host:
    chat_mode = False
    _chat_processing = False
    _chat_last_activity_at = 0.0
    tutor_daemon = None


class _BlockingDaemon:
    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.started = threading.Event()
        self.last_research_bundle = {}
        self.last_answer_ts = 0.0
        self._eris_discovery_meta = {}

    def search_now(self, *_args, **_kwargs):
        self.started.set()
        self.cancelled.wait(2.0)
        return None

    def cancel_pending(self, *, reason: str = "") -> bool:
        self.cancelled.set()
        return True


def test_discovery_does_not_start_immediately_after_boot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        router = _Router()
        runtime = DiscoveryRuntime(_Host(), router, state_path=Path(tmp) / "state.json")
        runtime.maybe_tick({}, now=time.time())
        assert router.calls == 0


def test_discovery_is_preempted_by_chat_and_not_archived() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        host = _Host()
        daemon = _BlockingDaemon()
        host.tutor_daemon = daemon
        runtime = DiscoveryRuntime(host, _Router(), state_path=Path(tmp) / "state.json")
        plan = DiscoveryPlan(
            lane="fresh_curiosity",
            topic="test topic",
            needs_external=True,
            freshness_required=True,
            verification_required=True,
            eris_interest=0.8,
            user_relevance=0.7,
            novelty=0.8,
            importance=0.8,
            confidence=0.9,
            reason="test",
        )
        runtime._start_search(plan, now=time.time())
        assert daemon.started.wait(1.0)
        assert runtime.preempt_for_chat(reason="test_chat") is True
        runtime._job_thread.join(2.0)

        state = runtime.snapshot()
        assert state.current_activity.status == "cancelled"
        assert state.records == ()


class _CancelableSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def goto(self, _url: str) -> None:
        return None

    def is_blocked(self) -> bool:
        return False

    def submit_question(self, _text: str, *, delay_min_ms: int, delay_max_ms: int, cancel_event=None) -> None:
        return None

    def read_answer(self, *, stable_window_s: float, deadline: float, cancel_event=None) -> str:
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise TutorCancelled()
            time.sleep(0.01)
        return "late answer"

    def citations(self):
        return ()


def test_tutor_backend_supports_cooperative_cancel() -> None:
    backend = GeminiWebBackend(
        TutorConfig(enabled=True, episode_timeout_s=2.0),
        page_session_factory=lambda: _CancelableSession(),
    )
    question = TutorQuestion(text="test question", gap_id="gap")
    result = {}

    thread = threading.Thread(target=lambda: result.setdefault("answer", backend.ask(question)))
    thread.start()
    time.sleep(0.05)
    backend.cancel_current("chat")
    thread.join(1.0)

    assert result["answer"].fail_reason == "cancelled"


def test_current_turn_anchor_distinguishes_style_and_reciprocity() -> None:
    assert AIRuntimeModelRouter._current_user_move_hint("em sến xíu đi cho tui zui") == "style_request"
    assert AIRuntimeModelRouter._current_user_move_hint("bạn muốn tui quen bạn hả") == "request_reciprocity"
