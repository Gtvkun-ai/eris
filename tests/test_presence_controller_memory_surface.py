from __future__ import annotations

from types import SimpleNamespace
import unittest

from runtime.presence_controller import PresenceControllerMixin


class DummyPresenceController(PresenceControllerMixin):
    def __init__(self, resonance=None):
        self.active_memory_resonance = resonance
        self.presence_maintenance_silent_cycles = 5

    def _get_internal_state(self):  # pragma: no cover - kept for mixin fallback shape
        return None


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


if __name__ == "__main__":
    unittest.main()
