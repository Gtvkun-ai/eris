import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.attention import AttentionWorkspace
from cortex.contracts import PerceptEvent


class AttentionWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.workspace = AttentionWorkspace()

    def test_low_salience_for_only_ambient_screen_context(self):
        percepts = (
            PerceptEvent(
                kind="active_window",
                content="Visual Studio Code",
                source="telemetry",
                confidence=0.72,
                novelty_hint="ambient_context",
            ),
            PerceptEvent(
                kind="focus_context",
                content="coding workspace",
                source="telemetry",
                confidence=0.68,
                novelty_hint="ambient_context",
            ),
        )

        candidates, broadcast = self.workspace.select(percepts)

        self.assertTrue(candidates)
        self.assertEqual(broadcast.label, "low_salience")
        self.assertEqual(broadcast.content, "")
        self.assertEqual(broadcast.items, ())

    def test_broadcasts_only_top_one_to_three_winners(self):
        percepts = (
            PerceptEvent(
                kind="active_window",
                content="Game",
                source="telemetry",
                confidence=0.72,
                novelty_hint="ambient_context",
            ),
            PerceptEvent(
                kind="vision_fact",
                content="terminal shows a Python traceback",
                evidence=("vision_facts_v1",),
                confidence=0.86,
                source="vision",
                novelty_hint="new_screen_fact",
            ),
            PerceptEvent(
                kind="resource_pressure",
                content="CPU 94% / RAM 91%",
                confidence=0.90,
                source="telemetry",
                novelty_hint="threshold_crossed",
            ),
        )

        candidates, broadcast = self.workspace.select(
            percepts,
            snapshot=SimpleNamespace(active_window_kind="coding"),
        )

        self.assertLessEqual(len(broadcast.items), 3)
        self.assertGreaterEqual(len(broadcast.items), 1)
        self.assertNotIn("active_window", {item.label for item in broadcast.items})
        self.assertTrue(all(item.score >= self.workspace.broadcast_threshold for item in broadcast.items))
        self.assertEqual(
            set(candidates[0].score_parts),
            {
                "novelty",
                "specificity",
                "user_relevance",
                "risk",
                "social_charge",
                "recency",
                "memory_resonance",
            },
        )

    def test_memory_resonance_is_part_of_score(self):
        event = PerceptEvent(
            kind="vision_fact",
            content="Project Zomboid cooking broadcast is visible",
            confidence=0.86,
            source="vision",
            novelty_hint="new_screen_fact",
        )

        without_memory = self.workspace.score_event(event)
        with_memory = self.workspace.score_event(
            event,
            long_term_memory=("Project Zomboid cooking broadcast rewards early survival prep",),
        )

        self.assertEqual(without_memory.score_parts["memory_resonance"], 0.0)
        self.assertGreater(with_memory.score_parts["memory_resonance"], 0.0)
        self.assertGreater(with_memory.score, without_memory.score)

    def test_norm_deviation_is_scored_as_baseline_comparison(self):
        event = PerceptEvent(
            kind="norm_deviation",
            content="active_app=youtube differs from norm visual studio code",
            confidence=0.66,
            source="memory",
            evidence=("norm_memory",),
            novelty_hint="baseline_deviation",
        )

        candidate = self.workspace.score_event(event)

        self.assertGreater(candidate.score_parts["novelty"], 0.8)
        self.assertGreater(candidate.score_parts["user_relevance"], 0.4)


if __name__ == "__main__":
    unittest.main()
