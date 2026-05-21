import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.meaning import MeaningLayer


class MeaningLayerTests(unittest.TestCase):
    def setUp(self):
        self.layer = MeaningLayer()

    def test_code_idle_long_maps_to_cognitive_stall(self):
        snapshot = SimpleNamespace(
            active_window="main.py - Visual Studio Code",
            active_app="Visual Studio Code",
            active_window_kind="coding",
            focus_summary="coding workspace",
            browser_url="",
            browser_tabs=(),
            open_windows=(),
            idle_seconds=140.0,
            idle_label="idle",
            recent_events=(),
            evidence=(),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="stuck",
            ),
        )

        result = self.layer.evaluate(snapshot=snapshot, recent_families=())

        self.assertEqual(result.source_fact, "code_idle_long")
        self.assertEqual(result.meaning, "cognitive_stall")
        self.assertIn("overthinking", result.secondary_meanings)
        self.assertTrue(result.meaning_shift)
        self.assertEqual(result.reaction, "quiet_observe")
        self.assertEqual(result.mood_residue, "dry concern")
        self.assertGreater(result.emotional_pressure, 0.0)
        self.assertIn("hesitation", result.attention_bias)
        self.assertEqual(result.reaction_impulse, "brief_indirect_reaction")
        self.assertIn("private pressure layer", result.prompt_context)
        self.assertIn("Do not say the internal_family out loud", result.prompt_context)

    def test_recent_family_blocks_autonomous_meaning_shift(self):
        snapshot = SimpleNamespace(
            active_window="main.py - Visual Studio Code",
            active_window_kind="coding",
            focus_summary="coding workspace",
            idle_seconds=180.0,
            recent_events=(),
            evidence=(),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="stuck",
            ),
        )

        result = self.layer.evaluate(
            snapshot=snapshot,
            recent_families=("decompression", "cognitive_stall"),
        )

        self.assertFalse(result.meaning_shift)
        self.assertEqual(result.shift_reason, "recent_semantic_family=cognitive_stall")

    def test_force_speak_becomes_requested_presence(self):
        result = self.layer.evaluate(channel="force_speak", force_speak=True)

        self.assertEqual(result.meaning, "requested_presence")
        self.assertTrue(result.meaning_shift)
        self.assertEqual(result.reaction, "relationship_ack")

    def test_long_idle_without_hard_fact_becomes_ambient_meaning(self):
        snapshot = SimpleNamespace(
            active_window="",
            active_window_kind="general",
            focus_summary="general",
            idle_seconds=360.0,
            recent_events=(),
            evidence=(),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="zero",
                window_switching="low",
                focus_pattern="quiet",
            ),
        )

        result = self.layer.evaluate(snapshot=snapshot)

        self.assertEqual(result.source_fact, "ambient_idle")
        self.assertEqual(result.meaning, "ambient_stillness")
        self.assertEqual(result.meaning_signal, "ambient_meaning")
        self.assertFalse(result.meaning_shift)
        self.assertIn("continuity", result.secondary_meanings)


if __name__ == "__main__":
    unittest.main()
