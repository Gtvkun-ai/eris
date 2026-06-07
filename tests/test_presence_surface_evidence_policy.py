from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.surface_arbiter import SurfaceDecision
from runtime.presence_controller import MicroPresenceCue, PresenceControllerMixin


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


class _FailingArbiter:
    def arbitrate(self, **kwargs):
        raise AssertionError("stale current-context surface should not reach wording arbitration")


class _RecordingArbiter:
    def __init__(self):
        self.calls = 0
        self.last_kwargs = {}

    def arbitrate(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return SurfaceDecision(
            text="",
            body_only=True,
            should_speak=False,
            source="recording_arbiter",
            generation_mode="body_only",
            kind="memory_resonance",
            reason="recorded",
        )


class _FakePresenceController(PresenceControllerMixin):
    def __init__(self, facts=(), *, arbiter=None):
        self.logger = _Logger()
        self.vision_facts = ("old stale fact",)
        self.vision_last_capture_at = time.time() - 999.0
        self.autonomous_presence_blocked_until = 0.0
        self.presence_maintenance_silent_cycles = 0
        self.private_mind_digest = {}
        self.private_mind_speech_bias = {}
        self.private_mind_thought_pressure = 0.0
        self.active_memory_resonance = None
        self.thought_stream = None
        self.refresh_calls = 0
        self.refresh_force_flags = []
        self._facts = tuple(facts)
        self._test_arbiter = arbiter or _FailingArbiter()

    def _maybe_update_screen_facts(self, **kwargs):
        self.refresh_calls += 1
        self.refresh_force_flags.append(bool(kwargs.get("force_refresh")))
        self.vision_last_capture_at = time.time()
        self.vision_facts = self._facts
        if kwargs.get("snapshot") is not None:
            kwargs["snapshot"].vision_facts = self._facts
        return self._facts

    def _attach_screen_facts(self, snapshot, facts):
        snapshot.vision_facts = tuple(facts)
        return "vision_facts_attached"

    def _build_endogenous_surface_impulses(self, **kwargs):
        return ()

    def _blind_frustration_surface_impulse(self, **kwargs):
        return None

    def _drain_private_mind_surface_impulses(self, **kwargs):
        return ()

    def _get_internal_state(self):
        return None

    def _surface_arbiter(self):
        return self._test_arbiter


def test_surface_current_context_triggers_one_forced_vision_refresh() -> None:
    controller = _FakePresenceController(facts=("terminal shows traceback",))
    snapshot = SimpleNamespace(vision_facts=("old stale fact",))
    cue = MicroPresenceCue(
        needs_micro_presence=True,
        focus_family="coding",
        confidence=0.70,
        missing_evidence_ids=True,
        reason="technical_help_screen_context",
        evidence=("active_window=code",),
        should_call_llm=True,
    )

    wants_current, fresh = controller._surface_refresh_vision_once_if_needed(
        snapshot=snapshot,
        cue=cue,
        surface_kind="technical_help",
        extra_impulses=(),
    )

    assert wants_current is True
    assert fresh is True
    assert controller.refresh_calls == 1
    assert controller.refresh_force_flags == [True]
    assert snapshot.vision_facts == ("terminal shows traceback",)


def test_surface_current_context_stays_body_only_when_refresh_has_no_fresh_evidence() -> None:
    controller = _FakePresenceController(facts=())
    snapshot = SimpleNamespace(vision_facts=("old stale fact",))
    frame = SimpleNamespace(internal_state_after=None, internal_state_before=None)
    cue = MicroPresenceCue(
        needs_micro_presence=True,
        focus_family="coding",
        confidence=0.74,
        missing_evidence_ids=True,
        reason="technical_help_screen_context",
        evidence=("active_window=code",),
        should_call_llm=True,
    )

    result = controller._build_surface_arbiter_result(
        frame=frame,
        snapshot=snapshot,
        surface_kind="technical_help",
        presence_cue=cue,
        force_llm=True,
    )

    assert result.decision is not None
    assert result.decision.should_speak is False
    assert result.surface is not None
    assert result.surface.reason == "stale_screen_evidence_no_refresh"
    assert controller.refresh_calls == 1


def test_surface_current_context_can_fall_back_to_rich_memory_seed_without_screen_claim() -> None:
    arbiter = _RecordingArbiter()
    controller = _FakePresenceController(facts=(), arbiter=arbiter)
    activation = SimpleNamespace(
        may_surface=True,
        text="A remembered pattern about debugging vision starvation.",
        evidence_ids=("memory.ev.1",),
        record_id="mem-1",
        layer="semantic",
    )
    controller.active_memory_resonance = SimpleNamespace(
        score=0.70,
        attention_bias=0.60,
        wording_bias=0.62,
        dominant_layer="semantic",
        activations=(activation,),
    )
    snapshot = SimpleNamespace(vision_facts=("old stale fact",))
    frame = SimpleNamespace(internal_state_after=None, internal_state_before=None)
    cue = MicroPresenceCue(
        needs_micro_presence=True,
        focus_family="coding",
        confidence=0.74,
        missing_evidence_ids=True,
        reason="technical_help_screen_context",
        evidence=("active_window=code",),
        should_call_llm=True,
    )

    result = controller._build_surface_arbiter_result(
        frame=frame,
        snapshot=snapshot,
        surface_kind="technical_help",
        presence_cue=cue,
        force_llm=True,
    )

    assert result.surface is not None
    assert result.surface.source == "recording_arbiter"
    assert arbiter.calls == 1
    impulses = arbiter.last_kwargs["extra_impulses"]
    assert any(getattr(item, "kind", "") == "memory_resonance" for item in impulses)
    assert snapshot.vision_facts == ()
