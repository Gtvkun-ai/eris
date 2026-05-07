import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.appraisal import AppraisalEngine
from cortex.contracts import CognitiveBroadcast
from cortex.internal_state import PersistentInternalState


class AppraisalEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AppraisalEngine()

    def test_protective_mode_and_persistent_guard_build_protective_appraisal(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="system",
                protectiveness=0.78,
                irritation=0.24,
                confidence=0.68,
                arousal=0.52,
            ),
            ni_report=SimpleNamespace(drift_score=0.12, confidence=0.70, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="resource_guard"),
            fe_plan=SimpleNamespace(
                intent_label="ordinary_dialogue",
                session_arc="quiet_observation",
                warmth_level=0.18,
                sarcasm_level=0.16,
            ),
            broadcast=CognitiveBroadcast(label="resource_pressure", score=0.84),
        )

        payload = appraisal.to_dict()
        required_axes = {
            "valence",
            "arousal",
            "certainty",
            "agency",
            "controllability",
            "intimacy",
            "threat",
            "protectiveness",
            "jealousy_lite",
            "amusement",
            "fatigue",
            "tenderness",
        }

        self.assertEqual(payload["state_type"], "expressive_appraisal_state")
        self.assertTrue(required_axes.issubset(payload))
        self.assertEqual(appraisal.stance, "protective")
        self.assertGreaterEqual(appraisal.threat, 0.80)
        self.assertGreaterEqual(appraisal.protectiveness, 0.80)
        self.assertNotIn("emotion", appraisal.summary.lower())

    def test_low_persistent_guard_does_not_raise_protective_appraisal(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="general",
                protectiveness=0.08,
                irritation=0.04,
                confidence=0.70,
                arousal=0.18,
            ),
            ni_report=SimpleNamespace(drift_score=0.0, confidence=0.70, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(
                intent_label="ordinary_dialogue",
                session_arc="quiet_observation",
                warmth_level=0.18,
                sarcasm_level=0.16,
            ),
            broadcast=CognitiveBroadcast(label="low_salience", score=0.20),
        )

        self.assertNotEqual(appraisal.stance, "protective")
        self.assertLess(appraisal.threat, 0.66)
        self.assertLess(appraisal.protectiveness, 0.72)

    def test_attachment_chat_raises_intimacy_and_tenderness_without_calling_it_feeling(self):
        appraisal = self.engine.evaluate(
            internal_state=PersistentInternalState(
                last_focus_kind="general",
                attachment=0.72,
                social_energy=0.66,
                tenderness=0.58,
                confidence=0.64,
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.68, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_emotional"),
            fe_plan=SimpleNamespace(
                intent_label="attachment_dialogue",
                session_arc="guarded_attachment",
                warmth_level=0.48,
                sarcasm_level=0.12,
            ),
            broadcast=CognitiveBroadcast(label="user_message", score=0.78),
            channel="chat",
            user_text="toi hoi buon va can o ben toi",
        )

        context = self.engine.render_prompt_context(appraisal)

        self.assertEqual(appraisal.stance, "tender_under_cold")
        self.assertGreaterEqual(appraisal.intimacy, 0.80)
        self.assertGreaterEqual(appraisal.tenderness, 0.70)
        self.assertIn("expressive/appraisal state", context)
        self.assertIn("pre-verbal attitude", context)
        self.assertIn("not an inner feeling claim", context)


if __name__ == "__main__":
    unittest.main()
