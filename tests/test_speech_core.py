import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import PersistentInternalState
from cortex.speech_core import SpeechCoreEngine
from cortex.contracts import SelfState, SubconsciousSeed


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
            internal_state=PersistentInternalState(),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.delivery, "speak")
        self.assertEqual(core.grounding, "ungrounded")
        self.assertIn(core.utterance_type, {"inner_whim", "curious_question", "random_chatter"})
        self.assertIn("no_screen_claim", core.safety_flags)
        self.assertEqual(core.motivation_pressure.winner.label, "user_requested_presence")

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
            internal_state=PersistentInternalState(),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "vision")
        self.assertEqual(core.utterance_type, "vision_comment")
        self.assertEqual(core.grounding, "screen_vision")
        self.assertEqual(core.motivation_pressure.winner.label, "screen_vision")

    def test_autonomous_quiet_room_uses_inner_whim_not_relational_checkin(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=500.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.20, fatigue=0.16, certainty=0.38),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.24),
            ti_report=SimpleNamespace(mode="social_watch"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=PersistentInternalState(silence_pressure=0.62, boredom=0.48),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "freeform")
        self.assertEqual(core.utterance_type, "inner_whim")
        self.assertIn(core.motivation_pressure.winner.label, {"social_presence", "curiosity"})

    def test_relational_checkin_requires_explicit_emotional_signal(self):
        calm = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            internal_state=PersistentInternalState(),
        )
        emotional = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="toi buon", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            internal_state=PersistentInternalState(),
        )

        self.assertNotEqual(calm.utterance_type, "relational_checkin")
        self.assertEqual(emotional.utterance_type, "relational_checkin")
        self.assertIn("explicit_emotional_signal", emotional.safety_flags)
        self.assertEqual(emotional.motivation_pressure.winner.label, "tender_checkin")

    def test_autonomous_repeat_guard_can_hold_silence(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=10.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.10, fatigue=0.0, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.1),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=3,
            internal_state=PersistentInternalState(silence_pressure=0.10),
        )

        self.assertFalse(core.should_speak)
        self.assertEqual(core.delivery, "silence")
        self.assertEqual(core.utterance_type, "no_speech")
        self.assertEqual(core.motivation_pressure.winner.label, "silence_restraint")
        self.assertEqual(core.motivation_pressure.suppressed_by, "quiet_guard")

    def test_autonomous_silence_pressure_can_surface_freeform_presence(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=30.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.08, certainty=0.32),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.12),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=PersistentInternalState(silence_pressure=0.72, boredom=0.54),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "freeform")

    def test_strong_subconscious_seed_can_surface_freeform_presence(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=120.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.08, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=PersistentInternalState(subconscious_pressure=0.72, restraint_pressure=0.10),
            subconscious_seed=SubconsciousSeed(
                mode="memory_replay",
                topic_seed="memory_replay:quiet_checkin",
                pressure=0.78,
                novelty=0.82,
            ),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "freeform")
        self.assertEqual(core.utterance_type, "curious_question")
        self.assertEqual(core.motivation_pressure.winner.label, "thought_stream_surface")
        self.assertIn("subconscious_seed", core.safety_flags)
        self.assertIn("thought_stream_surface", core.safety_flags)

    def test_concrete_signal_still_beats_subconscious_seed(self):
        core = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=120.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.08, certainty=0.30),
            broadcast=SimpleNamespace(label="vision_fact", content="traceback", score=0.90),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            concrete_signals=("Terminal shows a Python traceback.",),
            vision_signals=("Terminal shows a Python traceback.",),
            screen_comment_allowed=True,
            repeat_count=1,
            internal_state=PersistentInternalState(subconscious_pressure=0.72),
            subconscious_seed=SubconsciousSeed(
                mode="quiet_self_muse",
                topic_seed="quiet_self_muse:present_room",
                pressure=0.82,
                novelty=0.82,
            ),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.speech_source, "vision")
        self.assertEqual(core.motivation_pressure.winner.label, "screen_vision")

    def test_overloaded_self_state_suppresses_borderline_autonomous_presence(self):
        base = PersistentInternalState(silence_pressure=0.56, boredom=0.42, restraint_pressure=0.58, fatigue=0.74)
        neutral = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=430.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.10, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=base,
        )
        overloaded = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=430.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.10, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=base,
            self_state=SelfState(state_label="overloaded", overload=0.78, engagement=0.12, embodiment_bias="reduced"),
        )

        self.assertTrue(neutral.should_speak)
        self.assertFalse(overloaded.should_speak)
        self.assertEqual(overloaded.motivation_pressure.winner.label, "silence_restraint")

    def test_engaged_self_state_surfaces_borderline_autonomous_presence(self):
        state = PersistentInternalState(silence_pressure=0.44, boredom=0.20, social_pressure=0.54, curiosity_pressure=0.44)
        calm = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=200.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.08, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=state,
        )
        engaged = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(mood_label="neutral", idle_seconds=200.0),
            appraisal=SimpleNamespace(stance="grounded", tenderness=0.12, fatigue=0.08, certainty=0.30),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            repeat_count=1,
            internal_state=state,
            self_state=SelfState(state_label="engaged", overload=0.10, engagement=0.82, embodiment_bias="expressive"),
        )

        self.assertFalse(calm.should_speak)
        self.assertTrue(engaged.should_speak)
        self.assertIn(engaged.motivation_pressure.winner.label, {"social_presence", "curiosity"})

    def test_force_speak_still_speaks_when_self_state_is_overloaded(self):
        core = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(mood_label="neutral"),
            appraisal=SimpleNamespace(stance="grounded"),
            broadcast=SimpleNamespace(label="user_force_speak", content="", score=0.8),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(tone_label=""),
            internal_state=PersistentInternalState(fatigue=0.80, restraint_pressure=0.72),
            self_state=SelfState(state_label="overloaded", overload=0.84, engagement=0.18, embodiment_bias="reduced"),
        )

        self.assertTrue(core.should_speak)
        self.assertEqual(core.delivery, "speak")
        self.assertIn("no_screen_claim", core.safety_flags)


if __name__ == "__main__":
    unittest.main()
