from __future__ import annotations

from types import SimpleNamespace

from runtime.background_living_user_observer import (
    BackgroundLivingUserObserverConfig,
    BackgroundLivingUserObserverService,
)
from runtime.inference_broker import lane_policy


def test_curator_lane_is_not_shed_during_active_chat():
    policy = lane_policy("memory_curator")
    assert policy.optional is False
    assert policy.max_concurrency == 1


def test_background_living_user_observer_processes_queued_turn():
    calls = []

    class LivingUser:
        def observe_turn(self, text, *, evidence_ids, context=None):
            calls.append((text, tuple(evidence_ids), dict(context or {})))
            return SimpleNamespace(applied=2, rejected=1)

    service = BackgroundLivingUserObserverService(
        LivingUser(),
        config=BackgroundLivingUserObserverConfig(enabled=True, max_queue_size=4),
    )
    assert service.enqueue_user_turn("xin chào", turn_id="turn_7", context={"channel": "chat"}) is True
    assert service.drain_once_for_tests() == 1

    assert len(calls) == 1
    text, evidence_ids, context = calls[0]
    assert text == "xin chào"
    assert evidence_ids == ("turn_7",)
    assert context["background_lane"] == "curator"
    assert service.stats.processed == 1
    assert service.stats.applied == 2
    assert service.stats.rejected == 1
