import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.speech_core import SpeechCoreEngine


class SpeechCoreEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SpeechCoreEngine()

    def test_force_speak_uses_freeform_presence_when_no_screen_signal(self):
        core = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.delivery, "speak")
        self.assertEqual(core.grounding, "ungrounded")
        self.assertIn(core.utterance_type, {"inner_whim", "curious_question", "random_chatter"})
        self.assertIn("no_screen_claim", core.safety_flags)

    def test_force_speak_prefers_vision_comment_when_visual_signal_exists(self):
        core = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="vision_fact", content="traceback", score=0.9),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            concrete_signals=("Terminal shows a Python traceback.",),
            vision_signals=("Terminal shows a Python traceback.",),
            screen_comment_allowed=True,
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "vision")
        self.assertEqual(core.utterance_type, "vision_comment")
        self.assertEqual(core.grounding, "screen_vision")

    def test_autonomous_quiet_room_uses_inner_whim_not_relational_checkin(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=500.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.20, fatigue=0.16, certainty=0.38),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.24),
            ti_report=SimpleNamespace(mode="social_watch"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "freeform")
        self.assertEqual(core.utterance_type, "inner_whim")

    def test_relational_checkin_requires_explicit_emotional_signal(self):
        calm = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
        )
        emotional = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="toi buon", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
        )

        self.assertNotEqual(calm.utterance_type, "relational_checkin")
        self.assertEqual(emotional.utterance_type, "relational_checkin")
        self.assertIn("explicit_emotional_signal", emotional.safety_flags)

    def test_autonomous_repeat_guard_can_hold_silence(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=10.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.10, fatigue=0.0, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.1),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=3,
        )

        self.assertFalse(core.should_speak)
        self.assertEqual(core.delivery, "silence")
        self.assertEqual(core.utterance_type, "no_speech")


if __name__ == "__main__":
    unittest.main()
