"""Tests for Task 5.2 — Body_Only_Presence instead of an empty no-op.

When the ambient-silence hold would end an idle cycle with neither speech nor a
body action, ERIS emits a throttled Body_Only_Presence motion (Req 5.4) rather
than freezing. These tests exercise the two helpers added to
``PresenceControllerMixin`` in isolation, mirroring the stub style of
``test_liveliness_output_filter.py``.
"""

from __future__ import annotations

import os
import sys
from types import MethodType, SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.presence_controller import PresenceControllerMixin
from runtime.liveliness_config import LivelinessConfig


def _make_stub(*, has_vision: bool = False, gap: float = 90.0):
    stub = SimpleNamespace()
    stub.last_ambient_body_only_at = 0.0
    stub.last_wake_decision = None
    stub.sent = []
    stub.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    stub._liveliness_config = LivelinessConfig(body_only_min_gap_sec=gap)

    stub._get_liveliness_config = MethodType(PresenceControllerMixin._get_liveliness_config, stub)
    stub._build_ambient_body_only_decision = MethodType(
        PresenceControllerMixin._build_ambient_body_only_decision, stub
    )
    stub._maybe_emit_ambient_body_only = MethodType(
        PresenceControllerMixin._maybe_emit_ambient_body_only, stub
    )

    # Collaborators stubbed as inert no-ops / capturers.
    stub._surface_has_fresh_vision_evidence = MethodType(lambda self, snap, now=None: has_vision, stub)
    stub._set_cognitive_action_plan = MethodType(lambda self, *a, **k: None, stub)
    stub._concrete_screen_signals = MethodType(lambda self, snap: (), stub)
    stub._note_autonomous_presence_action = MethodType(lambda self, **k: None, stub)
    stub._apply_position_update = MethodType(lambda self, d: None, stub)
    stub._decision_to_frame_dict = MethodType(
        lambda self, d: {"text": d.text, "animation": d.animation, "parse_mode": d.parse_mode}, stub
    )
    stub._attach_speak_truth_table = MethodType(lambda self, *a, **k: None, stub)
    stub._set_cognitive_memory_update = MethodType(lambda self, *a, **k: None, stub)
    stub._commit_internal_state_for_frame = MethodType(lambda self, *a, **k: None, stub)
    stub._finalize_cognitive_frame = MethodType(lambda self, f: None, stub)
    stub._send_decision_to_body = MethodType(lambda self, d, channel=None: self.sent.append(d), stub)
    stub._choose_autonomous_sleep_duration = MethodType(lambda self, **k: 1, stub)
    stub._sleep_interruptible = MethodType(lambda self, s: None, stub)
    return stub


def _emit(stub):
    frame = SimpleNamespace(final_decision={})
    ti_report = SimpleNamespace(mode="pattern_muse")
    snapshot = SimpleNamespace(vision_facts=())
    return stub._maybe_emit_ambient_body_only(
        frame=frame,
        snapshot=snapshot,
        ti_report=ti_report,
        fe_plan=SimpleNamespace(style_context=""),
        speech_intent="no_speech",
        cooldown=150,
        cycle_start=0.0,
    ), frame


def test_body_only_decision_idle_shift_without_vision() -> None:
    stub = _make_stub(has_vision=False)
    decision = stub._build_ambient_body_only_decision(SimpleNamespace(vision_facts=()))
    assert decision is not None
    assert decision.should_speak is False
    assert decision.text == ""
    assert decision.animation == "stand"
    assert decision.action == "MotionCommand"
    assert "idle_shift" in decision.action_input


def test_body_only_decision_observe_scene_with_vision() -> None:
    stub = _make_stub(has_vision=True)
    decision = stub._build_ambient_body_only_decision(SimpleNamespace(vision_facts=("Kiro editing eris",)))
    assert decision is not None
    assert decision.animation == "read"
    assert "quiet_observe_scene" in decision.action_input


def test_first_ambient_cycle_emits_body_only() -> None:
    stub = _make_stub()
    emitted, frame = _emit(stub)
    assert emitted is True
    assert len(stub.sent) == 1
    sent = stub.sent[0]
    assert sent.should_speak is False and sent.text == ""
    assert stub.last_ambient_body_only_at > 0.0
    assert frame.final_decision.get("reason") == "ambient_silence_body_only"


def test_body_only_throttled_within_gap() -> None:
    stub = _make_stub(gap=90.0)
    emitted_first, _ = _emit(stub)
    assert emitted_first is True
    # Immediately after, the gap has not elapsed -> no second body action.
    emitted_second, _ = _emit(stub)
    assert emitted_second is False
    assert len(stub.sent) == 1


def test_body_only_disabled_when_gap_zero_still_emits() -> None:
    # gap=0 disables the throttle entirely: every ambient hold may shift.
    stub = _make_stub(gap=0.0)
    assert _emit(stub)[0] is True
    assert _emit(stub)[0] is True
    assert len(stub.sent) == 2
