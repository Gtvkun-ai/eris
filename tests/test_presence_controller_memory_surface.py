from __future__ import annotations

from types import SimpleNamespace
import unittest

from cortex.surface_arbiter import SurfaceArbiter
from runtime.presence_controller import MicroPresenceCue, PresenceControllerMixin


class DummyLogger:
    def info(self, *args, **kwargs):
        return None


class DummyPresenceController(PresenceControllerMixin):
    def __init__(self, resonance=None):
        self.active_memory_resonance = resonance
        self.presence_maintenance_silent_cycles = 5
        self.autonomous_presence_blocked_until = 0.0
        self.private_mind_digest = {}
        self.private_mind_speech_bias = {}
        self.private_mind_thought_pressure = 0.0
        self.thought_stream = None
        self.logger = DummyLogger()

    def _get_internal_state(self):  # pragma: no cover - kept for mixin fallback shape
        return None

    def _current_ego_surface_state(self):
        return {}


class PresenceControllerMemorySurfaceTests(unittest.TestCase):
    def test_public_memory_resonance_becomes_surface_impulse(self) -> None:
        activation = SimpleNamespace(
            may_surface=True,
            text="A remembered pattern about debugging vision starvation.",
            evidence_ids=("memory.ev.1",),
            record_id="mem-1",
            layer="semantic",
        )
        resonance = SimpleNamespace(
            score=0.62,
            attention_bias=0.40,
            wording_bias=0.55,
            silence_bias=0.05,
            dominant_layer="semantic",
            activations=(activation,),
        )

        controller = DummyPresenceController(resonance)
        impulses = controller._build_endogenous_surface_impulses(
            snapshot=SimpleNamespace(active_window_kind="coding"),
        )

        memory_impulses = [item for item in impulses if item.kind == "memory_resonance"]
        self.assertEqual(len(memory_impulses), 1)
        self.assertEqual(memory_impulses[0].speech_act, "light_muse")
        self.assertFalse(memory_impulses[0].missing_evidence_ids)

    def test_silent_memory_resonance_does_not_surface(self) -> None:
        activation = SimpleNamespace(
            may_surface=False,
            text="Private affective residue.",
            evidence_ids=("memory.ev.2",),
            record_id="mem-2",
            layer="affective_residue",
        )
        resonance = SimpleNamespace(
            score=0.50,
            attention_bias=0.10,
            wording_bias=0.10,
            silence_bias=0.80,
            dominant_layer="affective_residue",
            activations=(activation,),
        )

        controller = DummyPresenceController(resonance)
        impulses = controller._build_endogenous_surface_impulses(
            snapshot=SimpleNamespace(active_window_kind="coding"),
        )

        self.assertFalse(any(item.kind == "memory_resonance" for item in impulses))

    def test_surface_seed_compiler_feeds_reengagement_with_thought_seed(self) -> None:
        captured = []

        def generator(*, impulse, snapshot=None, force_llm=False):
            captured.append(impulse)
            return ("Một ý nhỏ mắc lại.", "mock")

        frame = SimpleNamespace(
            thought_stream_report=SimpleNamespace(
                latest_seed=SimpleNamespace(
                    public_seed="public-safe thought about the surface gate",
                    topic_seed="surface gate",
                    pressure=0.56,
                    momentum_score=0.52,
                    evidence=("anchor=recent_silence",),
                    recommended_route="surface_candidate",
                    impulse_kind="inner_whim",
                    root_source="thought_stream",
                    action_opportunity="surface one rooted aside",
                )
            ),
            internal_state_after=None,
            internal_state_before=None,
        )
        cue = MicroPresenceCue(
            needs_micro_presence=True,
            focus_family="general_idle",
            confidence=0.46,
            missing_evidence_ids=True,
            reason="long_silence_reengagement",
            evidence=("idle_seconds=120.0",),
            should_call_llm=True,
        )
        controller = DummyPresenceController()
        controller._low_level_surface_arbiter = SurfaceArbiter(llm_micro_gen=generator)

        result = controller._build_surface_arbiter_result(
            frame=frame,
            snapshot=SimpleNamespace(active_window_kind="general_idle", vision_facts=(), recent_events=(), idle_seconds=120.0),
            surface_kind="re_engagement",
            force_llm=True,
            presence_cue=cue,
        )

        self.assertIsNotNone(result.decision)
        self.assertTrue(captured)
        self.assertEqual(captured[0].source, "surface_seed_compiler")
        self.assertEqual(captured[0].topic_seed, "public-safe thought about the surface gate")


if __name__ == "__main__":
    unittest.main()
