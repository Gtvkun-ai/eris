import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import InternalStateEngine, PersistentInternalState


class InternalStateEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = InternalStateEngine()

    def test_sense_update_is_smoothed(self):
        before = PersistentInternalState(arousal=0.20, protectiveness=0.10, confidence=0.40)

        after = self.engine.sense_update(
            before,
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=480.0,
                user_signals=SimpleNamespace(focus_pattern="absent", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.80, confidence=0.72, should_raise_guard=True),
            ti_report=SimpleNamespace(mode="resource_guard"),
            fe_plan=SimpleNamespace(warmth_level=0.18, sarcasm_level=0.12),
            broadcast=SimpleNamespace(score=0.84),
        )

        self.assertGreater(after.protectiveness, before.protectiveness)
        self.assertLess(after.protectiveness, 0.90)
        self.assertGreater(after.arousal, before.arousal)

    def test_commit_turn_increases_silence_pressure_after_quiet_turns(self):
        state = PersistentInternalState(silence_pressure=0.10)
        for _ in range(4):
            state = self.engine.commit_turn(
                state,
                channel="autonomous",
                snapshot=SimpleNamespace(active_window_kind="general"),
                ti_report=SimpleNamespace(mode="steady_observe"),
                appraisal=SimpleNamespace(stance="grounded"),
                speech_core=SimpleNamespace(utterance_type="no_speech", inner_thought=SimpleNamespace(intent="")),
                action_plan=SimpleNamespace(speech_act="no_speech"),
                inner_thought=SimpleNamespace(intent=""),
                was_spoken=False,
            )

        self.assertGreaterEqual(state.silence_ticks, 4)
        self.assertGreater(state.silence_pressure, 0.10)

    def test_force_speak_and_chat_raise_attachment_and_social_energy(self):
        base = PersistentInternalState(attachment=0.20, social_energy=0.20)
        sensed = self.engine.sense_update(
            base,
            channel="force_speak",
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.12, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.24, sarcasm_level=0.10),
            force_speak=True,
        )
        committed = self.engine.commit_turn(
            sensed,
            channel="chat",
            snapshot=SimpleNamespace(active_window_kind="general"),
            ti_report=SimpleNamespace(mode="chat_general"),
            appraisal=SimpleNamespace(stance="grounded"),
            speech_core=SimpleNamespace(utterance_type="inner_whim", inner_thought=SimpleNamespace(intent="inner_whim")),
            action_plan=SimpleNamespace(speech_act="inner_whim"),
            inner_thought=SimpleNamespace(intent="inner_whim"),
            was_spoken=True,
        )

        self.assertGreater(committed.attachment, base.attachment)
        self.assertGreater(committed.social_energy, base.social_energy)


if __name__ == "__main__":
    unittest.main()
