from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.ambient_silence_policy import (
    ambient_silence_cooldown_seconds,
    muse_directive_active,
    should_hold_ambient_silence,
)
from runtime.liveliness_tracker import DecisionRecord, LivelinessTracker


# --- Muse / ambient-silence policy (Req 4) -------------------------------

def test_muse_directive_active() -> None:
    assert muse_directive_active(SimpleNamespace(mode="pattern_muse")) is True
    assert muse_directive_active(SimpleNamespace(mode="pattern_watch")) is False


def test_muse_is_not_held_by_cooldown() -> None:
    snapshot = SimpleNamespace(active_window_kind="coding")
    ti = SimpleNamespace(mode="pattern_muse")
    held, reason = should_hold_ambient_silence(
        snapshot=snapshot,
        ti_report=ti,
        last_text="vừa nói xong",
        last_autonomous_spoken_at=1000.0,
        now=1001.0,  # 1s later, far inside the 150s cooldown
    )
    assert held is False
    assert reason == "muse_exempt"


def test_non_muse_quiet_mode_still_held_within_cooldown() -> None:
    snapshot = SimpleNamespace(active_window_kind="coding")
    ti = SimpleNamespace(mode="pattern_watch")
    held, reason = should_hold_ambient_silence(
        snapshot=snapshot,
        ti_report=ti,
        last_text="vừa nói xong",
        last_autonomous_spoken_at=1000.0,
        now=1001.0,
    )
    assert held is True
    assert reason.startswith("cooldown=")


def test_cooldown_seconds_table() -> None:
    assert ambient_silence_cooldown_seconds(SimpleNamespace(active_window_kind=""), SimpleNamespace(mode="resource_guard")) == 0
    assert ambient_silence_cooldown_seconds(SimpleNamespace(active_window_kind="coding"), SimpleNamespace(mode="")) == 60


# --- Liveliness tracker (Req 5, 6) ---------------------------------------

def _grounded(cycle: str, text: str, t: float, source: str = "vision_fact") -> DecisionRecord:
    return DecisionRecord(
        cycle_id=cycle,
        emitted_kind="grounded_line",
        seed_source=source,
        seed_confidence=0.8,
        candidate_count=3,
        grounding_evidence=("vision_fact",),
        text=text,
        timestamp=t,
    )


def test_tracker_retention_bound() -> None:
    tracker = LivelinessTracker(retention=10)
    for i in range(25):
        tracker.record(_grounded(f"c{i}", f"line {i}", float(i)))
    assert len(tracker.recent()) == 10


def test_for_cycle_groups_records() -> None:
    tracker = LivelinessTracker()
    tracker.record(_grounded("c1", "a", 1.0))
    tracker.record(
        DecisionRecord(cycle_id="c1", emitted_kind="silence", no_seed_reason="low_pressure", timestamp=1.0)
    )
    assert len(tracker.for_cycle("c1")) == 2


def test_window_metrics_distinct_and_proportion() -> None:
    tracker = LivelinessTracker()
    now = 10_000.0
    # 3 distinct grounded lines + 1 repeat + 1 non-grounded spoken.
    tracker.record(_grounded("c1", "Panel kia mở năm file.", now - 100))
    tracker.record(_grounded("c2", "Terminal đang chạy test.", now - 80))
    tracker.record(_grounded("c3", "Trình duyệt mở tab tài liệu.", now - 60))
    tracker.record(_grounded("c4", "Panel kia mở năm file.", now - 40))  # repeat text
    tracker.record(
        DecisionRecord(
            cycle_id="c5",
            emitted_kind="grounded_line",
            seed_source="private_life",  # not a grounded source
            text="Một ý riêng thoáng qua.",
            timestamp=now - 20,
        )
    )
    m = tracker.window_metrics(window_sec=3600.0, now=now)
    assert m.total_lines == 5
    assert m.grounded_lines == 4
    assert m.distinct_grounded_count == 3
    assert m.single_line_max_repeat == 2
    assert 0.0 < m.grounded_proportion <= 1.0
