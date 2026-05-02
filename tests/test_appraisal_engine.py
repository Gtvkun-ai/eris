import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.appraisal import AppraisalEngine
from cortex.contracts import CognitiveBroadcast


class AppraisalEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AppraisalEngine()

    def test_resource_pressure_builds_protective_expressive_appraisal_state(self):
        appraisal = self.engine.evaluate(
            snapshot=SimpleNamespace(
                active_window_kind="system",
                idle_seconds=8.0,
                cpu_percent=94.0,
                ram_percent=91.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
                claim_style="soft_grounded",
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

    def test_resource_metrics_alone_do_not_raise_protective_appraisal(self):
        appraisal = self.engine.evaluate(
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=4.0,
                cpu_percent=99.0,
                ram_percent=98.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
                claim_style="soft_grounded",
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
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=0.0,
                cpu_percent=20.0,
                ram_percent=35.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
                claim_style="soft_grounded",
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
