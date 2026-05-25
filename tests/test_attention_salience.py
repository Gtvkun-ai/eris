import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.attention_salience import AttentionSalienceEngine


class AttentionSalienceTests(unittest.TestCase):
    def setUp(self):
        self.engine = AttentionSalienceEngine()

    def test_low_salience_for_only_ambient_screen_context(self):
        salience = self.engine.evaluate(
            evidence=(
                {
                    "id": "ev_window",
                    "source": "active_window",
                    "claim": "Visual Studio Code",
                    "confidence": 0.72,
                    "reliability": 0.78,
                    "tags": ("active_window", "ambient_context"),
                },
                {
                    "id": "ev_focus",
                    "source": "telemetry",
                    "claim": "coding workspace",
                    "confidence": 0.68,
                    "reliability": 0.72,
                    "tags": ("focus_context", "ambient_context"),
                },
            ),
            channel="autonomous",
            write_to_frame=False,
        )

        self.assertTrue(salience.candidates)
        self.assertLess(salience.broadcast_priority, 0.50)
        self.assertFalse(salience.selected_evidence_ids)

    def test_selects_current_user_request_over_ambient_context(self):
        salience = self.engine.evaluate(
            evidence=(
                {
                    "id": "ev_window",
                    "source": "active_window",
                    "claim": "Game",
                    "confidence": 0.72,
                    "reliability": 0.78,
                    "tags": ("active_window", "ambient_context"),
                },
                {
                    "id": "ev_user",
                    "source": "user_chat",
                    "claim": "fix the Python traceback in coordinator.py",
                    "confidence": 0.98,
                    "reliability": 0.98,
                    "tags": ("user_message", "request", "technical"),
                },
            ),
            channel="autonomous",
            write_to_frame=False,
        )

        selected = {candidate.evidence_id for candidate in salience.selected_candidates}
        self.assertIn("ev_user", selected)
        self.assertNotEqual(salience.dominant_evidence_id, "ev_window")
        self.assertGreaterEqual(salience.broadcast_priority, 0.32)

    def test_cognitive_momentum_can_reenter_attention_when_alone(self):
        salience = self.engine.evaluate(
            evidence=(
                {
                    "id": "ev_window",
                    "source": "telemetry",
                    "claim": "Visual Studio Code",
                    "confidence": 0.72,
                    "reliability": 0.78,
                    "tags": ("active_window", "ambient_context"),
                },
                {
                    "id": "ev_momentum",
                    "source": "system_log",
                    "claim": "thought=thought_1; mode=associative_drift; topic=project_eris_tests",
                    "confidence": 0.86,
                    "reliability": 0.70,
                    "tags": ("cognitive_momentum", "reactivations=1", "momentum=0.72"),
                },
            ),
            channel="autonomous",
            write_to_frame=False,
        )

        self.assertEqual(salience.dominant_evidence_id, "ev_momentum")
        self.assertIn("ev_momentum", salience.selected_evidence_ids)


if __name__ == "__main__":
    unittest.main()
