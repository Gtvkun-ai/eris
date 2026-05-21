import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.attention import AttentionScoringProfile, AttentionWorkspace
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
                "personality_bias",
            },
        )

    def test_infj_5w4_attention_bias_prefers_unfinished_intention(self):
        event = PerceptEvent(
            kind="recent_event",
            content="typing_and_deleting_self_doubt after hovering over send",
            confidence=0.86,
            source="telemetry",
            novelty_hint="concrete_telemetry",
        )

        candidate = self.workspace.score_event(event)

        self.assertGreater(candidate.score_parts["personality_bias"], 0.0)

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

    def test_memory_resonance_can_use_embedding_similarity(self):
        event = PerceptEvent(
            kind="vision_fact",
            content="the terminal shows a startup failure",
            confidence=0.86,
            source="vision",
            novelty_hint="new_screen_fact",
        )

        def embed(text: str):
            normalized = text.lower()
            return (
                1.0 if "startup" in normalized or "boot" in normalized else 0.0,
                1.0 if "failure" in normalized or "crash" in normalized else 0.0,
            )

        workspace = AttentionWorkspace(memory_embedding_fn=embed)
        candidate = workspace.score_event(
            event,
            long_term_memory=("procedural: app boot crash usually needs logs first",),
        )

        self.assertGreater(candidate.score_parts["memory_resonance"], 0.0)

    def test_personality_bias_ignores_negated_mood_terms(self):
        negated = PerceptEvent(
            kind="user_message",
            content="toi khong buon",
            confidence=1.0,
            source="chat",
            novelty_hint="direct_user_input",
        )
        affirmed = PerceptEvent(
            kind="user_message",
            content="toi buon",
            confidence=1.0,
            source="chat",
            novelty_hint="direct_user_input",
        )

        negated_candidate = self.workspace.score_event(negated)
        affirmed_candidate = self.workspace.score_event(affirmed)

        self.assertEqual(negated_candidate.score_parts["personality_bias"], 0.0)
        self.assertGreater(affirmed_candidate.score_parts["personality_bias"], 0.0)

    def test_scoring_profile_can_learn_soft_priors_from_observations(self):
        profile = AttentionScoringProfile.from_observations(
            (
                {
                    "kind": "vision_fact",
                    "novelty_hint": "new_screen_fact",
                    "score_parts": {"risk": 0.9, "specificity": 0.8},
                },
            )
        )
        workspace = AttentionWorkspace(scoring_profile=profile, learned_profile_strength=0.5)
        event = PerceptEvent(
            kind="vision_fact",
            content="plain screen text",
            confidence=0.86,
            source="vision",
            novelty_hint="new_screen_fact",
        )

        profiled = workspace.score_event(event)
        baseline = AttentionWorkspace().score_event(event)

        self.assertGreater(profiled.score_parts["risk"], baseline.score_parts["risk"])
        self.assertGreater(profiled.score_parts["specificity"], baseline.score_parts["specificity"])

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

    def test_cognitive_momentum_can_reenter_attention_when_alone(self):
        percepts = (
            PerceptEvent(
                kind="active_window",
                content="Visual Studio Code",
                source="telemetry",
                confidence=0.72,
                novelty_hint="ambient_context",
            ),
            PerceptEvent(
                kind="cognitive_momentum",
                content="thought=thought_1; mode=associative_drift; topic=project_eris_tests",
                evidence=("reactivations=1", "momentum=0.72"),
                confidence=0.86,
                source="thought_stream",
                novelty_hint="cognitive_momentum",
            ),
        )

        candidates, broadcast = self.workspace.select(percepts)

        self.assertEqual(candidates[0].label, "cognitive_momentum")
        self.assertEqual(broadcast.label, "cognitive_momentum")
        self.assertEqual(broadcast.items[0].source, "thought_stream")

    def test_cognitive_momentum_does_not_override_current_signal(self):
        percepts = (
            PerceptEvent(
                kind="cognitive_momentum",
                content="thought=thought_1; mode=associative_drift; topic=project_eris_tests",
                evidence=("reactivations=2", "momentum=0.91"),
                confidence=1.0,
                source="thought_stream",
                novelty_hint="cognitive_momentum",
            ),
            PerceptEvent(
                kind="vision_fact",
                content="terminal shows a Python traceback",
                evidence=("vision_facts_v1",),
                confidence=0.86,
                source="vision",
                novelty_hint="new_screen_fact",
            ),
        )

        _, broadcast = self.workspace.select(
            percepts,
            snapshot=SimpleNamespace(active_window_kind="coding"),
        )

        self.assertEqual(broadcast.label, "vision_fact")
        self.assertNotIn("cognitive_momentum", {item.label for item in broadcast.items})


if __name__ == "__main__":
    unittest.main()
