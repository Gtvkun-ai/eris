import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.attention_salience import (
    AttentionSalienceEngine,
    DEFAULT_STANDING_STAKES,
    StandingStakes,
    StandingTheme,
)


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


class StandingStakesTests(unittest.TestCase):
    """TẦNG 3 — stakes: chứng minh vector quan tâm không còn toàn 0."""

    def setUp(self):
        self.engine = AttentionSalienceEngine()

    def _youtube_evidence(self):
        return (
            {
                "id": "ev_youtube",
                "source": "active_window",
                "claim": "YouTube - đang xem video",
                "confidence": 0.74,
                "reliability": 0.76,
                "tags": ("active_window", "ambient_context", "browser"),
            },
        )

    def test_without_stakes_youtube_tab_stays_inert(self):
        # Hành vi cũ: không stake -> mọi trục quan tâm ~0, không được chọn.
        salience = self.engine.evaluate(
            evidence=self._youtube_evidence(),
            channel="autonomous",
            write_to_frame=False,
        )
        dominant = salience.candidates[0]
        self.assertEqual(dominant.score_breakdown.standing_interest, 0.0)
        self.assertEqual(dominant.score_breakdown.goal_relevance, 0.0)
        self.assertEqual(dominant.score_breakdown.user_relevance, 0.0)
        self.assertFalse(salience.selected_evidence_ids)

    def test_stakes_make_what_he_watches_salient(self):
        # Có stake -> "Ngài đang xem video" chạm theme + care_user_activity,
        # interest vector không còn 0 và evidence được chọn.
        salience = self.engine.evaluate(
            evidence=self._youtube_evidence(),
            channel="autonomous",
            write_to_frame=False,
            standing_stakes=DEFAULT_STANDING_STAKES,
        )
        dominant = salience.candidates[0]
        b = dominant.score_breakdown
        self.assertGreater(b.standing_interest, 0.0)
        self.assertGreater(b.goal_relevance, 0.0)
        self.assertGreater(b.user_relevance, 0.0)
        self.assertGreater(dominant.score, 0.32)
        self.assertIn("ev_youtube", salience.selected_evidence_ids)

    def test_stakes_do_not_override_real_user_request(self):
        # Prior thiên lệch là attention bias, không được áp đảo user_request thật.
        salience = self.engine.evaluate(
            evidence=(
                {
                    "id": "ev_youtube",
                    "source": "active_window",
                    "claim": "YouTube - đang xem video",
                    "confidence": 0.74,
                    "reliability": 0.76,
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
            channel="chat",
            write_to_frame=False,
            standing_stakes=DEFAULT_STANDING_STAKES,
        )
        self.assertEqual(salience.dominant_evidence_id, "ev_user")

    def test_empty_stakes_behaves_like_none(self):
        empty = StandingStakes()
        with_empty = self.engine.evaluate(
            evidence=self._youtube_evidence(),
            channel="autonomous",
            write_to_frame=False,
            standing_stakes=empty,
        )
        self.engine.reset_memory()
        without = self.engine.evaluate(
            evidence=self._youtube_evidence(),
            channel="autonomous",
            write_to_frame=False,
        )
        self.assertAlmostEqual(
            with_empty.candidates[0].score,
            without.candidates[0].score,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
