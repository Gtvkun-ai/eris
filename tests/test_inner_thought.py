import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.inner_thought import InnerThoughtEngine


class InnerThoughtEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = InnerThoughtEngine()

    def test_force_speak_low_signal_surfaces_meta_reply_without_canned_text(self):
        thought = self.engine.evaluate(
            channel="force_speak",
            concrete_signals=(),
            broadcast=SimpleNamespace(label="user_force_speak", score=0.8),
            style_memory=SimpleNamespace(last_intent=""),
            last_text="",
        )

        self.assertTrue(thought.should_surface)
        self.assertEqual(thought.intent, "inner_whim")
        self.assertEqual(thought.topic_seed, "present_whim")
        self.assertIn("no_screen_claim", thought.risk_flags)
        self.assertIn("needs_generation", thought.risk_flags)

    def test_force_speak_rotates_recent_topic_seeds(self):
        thought = self.engine.evaluate(
            channel="force_speak",
            concrete_signals=(),
            broadcast=SimpleNamespace(label="user_force_speak", score=0.8),
            style_memory=SimpleNamespace(last_intent=""),
            recent_inner_intents=("inner_whim",),
            recent_inner_seeds=("present_whim",),
        )

        self.assertTrue(thought.should_surface)
        self.assertNotEqual(thought.intent, "inner_whim")
        self.assertNotEqual(thought.topic_seed, "present_whim")

    def test_concrete_signal_prefers_observation_layer(self):
        thought = self.engine.evaluate(
            channel="force_speak",
            concrete_signals=("Terminal shows a Python traceback.",),
        )

        self.assertFalse(thought.should_surface)
        self.assertEqual(thought.motive, "screen_signal_available")
        self.assertIn("prefer_observation", thought.risk_flags)

    def test_autonomous_requires_long_quiet_social_motive(self):
        quiet_thought = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(idle_seconds=500.0),
            appraisal=SimpleNamespace(tenderness=0.20, fatigue=0.16, certainty=0.38),
            broadcast=SimpleNamespace(label="low_salience", score=0.24),
            repeat_count=1,
        )
        active_thought = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(idle_seconds=20.0),
            appraisal=SimpleNamespace(tenderness=0.20, fatigue=0.0, certainty=0.38),
            broadcast=SimpleNamespace(label="low_salience", score=0.24),
            repeat_count=1,
        )

        self.assertTrue(quiet_thought.should_surface)
        self.assertEqual(quiet_thought.intent, "inner_whim")
        self.assertEqual(quiet_thought.topic_seed, "quiet_whim")
        self.assertFalse(active_thought.should_surface)

    def test_autonomous_repeat_guard_blocks_surface(self):
        thought = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(idle_seconds=800.0),
            appraisal=SimpleNamespace(tenderness=0.20, fatigue=0.16, certainty=0.38),
            broadcast=SimpleNamespace(label="low_salience", score=0.24),
            repeat_count=2,
        )

        self.assertFalse(thought.should_surface)
        self.assertIn("repeat_guard", thought.risk_flags)


if __name__ == "__main__":
    unittest.main()
