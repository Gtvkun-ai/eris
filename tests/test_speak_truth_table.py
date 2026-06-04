import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import AgentSpeechCore, CognitiveActionPlan, CognitiveFrame, SilenceState
from runtime.autonomous_wake_governor import WakeDecision
from runtime.coordinator import RuntimeCoordinator


class SpeakTruthTableTests(unittest.TestCase):
    def _make_coordinator(self):
        return RuntimeCoordinator.__new__(RuntimeCoordinator)

    def test_truth_table_marks_meaning_shift_silence(self):
        coordinator = self._make_coordinator()
        frame = CognitiveFrame(cycle_id="c1", channel="autonomous", started_at=0.0)
        frame.speech_core = AgentSpeechCore(
            should_speak=False,
            speech_source="meaning",
            utterance_type="micro_presence",
            reason="meaning_shift_gate",
            safety_flags=("meaning_shift_gate",),
            silence_state=SilenceState(
                mode="intentional_withholding",
                intentional_withholding=True,
                reason="meaning_shift_gate",
            ),
        )
        frame.action_plan = CognitiveActionPlan(
            should_speak=False,
            speech_intent="no_speech",
            speech_act="no_speech",
            reason_to_speak="Meaning gate held the line.",
        )
        frame.final_decision = {
            "text": "",
            "animation": "",
            "parse_mode": "no_speech",
            "reason": "Meaning gate held the line.",
        }

        table = coordinator._attach_speak_truth_table(
            frame,
            wake_decision=WakeDecision(
                level="wake_main_cognition",
                should_speak=True,
                should_call_vision=False,
                should_wake_main=True,
                should_run_daydream=False,
                reason="main_threshold",
                confidence=0.92,
            ),
        )

        self.assertFalse(table["final"]["should_speak"])
        self.assertEqual(table["speech_core"]["silence_reason"], "meaning_shift_gate")
        self.assertIn("speak_truth=final=silent:no_speech", frame.action_plan.notes[-1])
        self.assertIn("speech_core=silent:meaning_shift_gate", frame.final_decision["speak_truth_summary"])

    def test_truth_table_marks_ambient_silence_hold(self):
        coordinator = self._make_coordinator()
        frame = CognitiveFrame(cycle_id="c2", channel="autonomous", started_at=0.0)
        frame.speech_core = AgentSpeechCore(
            should_speak=True,
            speech_source="freeform",
            utterance_type="micro_presence",
            reason="micro_presence",
        )
        frame.action_plan = CognitiveActionPlan(
            should_speak=False,
            speech_intent="no_speech",
            speech_act="micro_presence",
            reason_to_speak="Ambient silence cooldown held this cycle.",
        )
        frame.final_decision = {
            "text": "",
            "animation": "",
            "parse_mode": "ambient_silence",
            "reason": "ambient_silence",
        }

        table = coordinator._attach_speak_truth_table(
            frame,
            wake_decision=WakeDecision(
                level="micro_presence",
                should_speak=True,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="micro_presence_threshold",
                confidence=0.63,
            ),
            ambient_hold=True,
            ambient_reason="cooldown=120s",
        )

        self.assertFalse(table["final"]["should_speak"])
        self.assertEqual(table["ambient_silence"]["result"], "held")
        self.assertEqual(table["ambient_silence"]["reason"], "cooldown=120s")
        self.assertIn("ambient=held", frame.final_decision["speak_truth_summary"])


if __name__ == "__main__":
    unittest.main()
