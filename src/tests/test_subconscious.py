import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import PersistentInternalState
from cortex.contracts import CognitiveDisturbance
from cortex.thought_stream import SubconsciousEngine


class SubconsciousEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SubconsciousEngine()

    def test_generates_memory_replay_from_recent_memory(self):
        report = self.engine.evaluate(
            snapshot=SimpleNamespace(idle_seconds=260.0, active_window_kind="general", user_signals=SimpleNamespace(focus_pattern="quiet")),
            internal_state=PersistentInternalState(subconscious_pressure=0.60, memory_replay_pressure=0.78),
            long_term_memory=("relationship/no_screen_signal: User likes small curiosity when there is no screen signal.",),
            now=10.0,
        )

        self.assertEqual(report.latest_seed.mode, "memory_replay")
        self.assertIn("memory_replay:", report.latest_seed.topic_seed)
        self.assertEqual(report.latest_thought.mode, "memory_replay")
        self.assertGreater(report.stream_tension, 0.0)
        self.assertIn("thought_stream=unfinished_prediction", report.continuity_notes)
        self.assertIn("memory_replay_available", report.latest_seed.evidence)
        self.assertIn("no_screen_claim", report.latest_seed.risk_flags)
        self.assertIn("thought_stream_surface", report.latest_seed.risk_flags)

    def test_generates_associative_drift_during_quiet_idle(self):
        report = self.engine.evaluate(
            snapshot=SimpleNamespace(idle_seconds=180.0, active_window_kind="coding", user_signals=SimpleNamespace(focus_pattern="steady")),
            internal_state=PersistentInternalState(subconscious_pressure=0.58, association_pressure=0.76, curiosity_pressure=0.64),
            long_term_memory=(),
            last_text="A small question about rhythm.",
            now=11.0,
        )

        self.assertEqual(report.latest_seed.mode, "associative_drift")
        self.assertIn("associative_drift:", report.latest_seed.topic_seed)
        self.assertEqual(report.latest_thought.unresolved_reason, "association has not found a stable connection yet")
        self.assertGreaterEqual(report.surface_pressure, 0.70)

    def test_rotates_away_from_recent_seeds(self):
        repeated = self.engine.evaluate(
            snapshot=SimpleNamespace(idle_seconds=600.0, active_window_kind="general", user_signals=SimpleNamespace(focus_pattern="quiet")),
            internal_state=PersistentInternalState(subconscious_pressure=0.72, silence_pressure=0.72),
            recent_subconscious_seeds=("quiet_self_muse:present_room",),
            now=12.0,
        )

        self.assertFalse(repeated.latest_seed.mode)
        self.assertEqual(repeated.latest_thought.mode, "quiet_self_muse")
        self.assertEqual(repeated.suppression_reason, "recent_seed_repeat")

    def test_suppresses_when_restraint_is_high_and_pressure_is_modest(self):
        report = self.engine.evaluate(
            snapshot=SimpleNamespace(idle_seconds=120.0, active_window_kind="general", user_signals=SimpleNamespace(focus_pattern="steady")),
            internal_state=PersistentInternalState(subconscious_pressure=0.42, association_pressure=0.46, restraint_pressure=0.90),
            last_text="small curiosity",
            now=13.0,
        )

        self.assertFalse(report.latest_seed.mode)
        self.assertEqual(report.suppression_reason, "restraint_pressure")

    def test_input_disturbance_enters_existing_stream(self):
        report = self.engine.evaluate(
            snapshot=SimpleNamespace(idle_seconds=20.0, active_window_kind="coding", user_signals=SimpleNamespace(focus_pattern="steady")),
            internal_state=PersistentInternalState(social_pressure=0.54, curiosity_pressure=0.42),
            disturbances=(
                CognitiveDisturbance(
                    channel="chat",
                    kind="user_message",
                    content="continuous substrate, not a fresh cognition",
                    evidence=("direct_user_input",),
                    intensity=1.0,
                    timestamp=100.0,
                ),
            ),
            now=100.0,
        )

        self.assertEqual(report.latest_thought.mode, "input_disturbance")
        self.assertIn("input_disturbance:", report.latest_thought.topic_seed)
        self.assertEqual(report.disturbances[0].channel, "chat")
        self.assertTrue(any(item.startswith("disturbance=chat:user_message") for item in report.latest_thought.evidence))
        self.assertIn("disturbance=chat:user_message", report.continuity_notes)

    def test_recurrent_unresolved_project_fragment_builds_momentum(self):
        snapshot = SimpleNamespace(
            idle_seconds=180.0,
            active_window_kind="coding",
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )
        state = PersistentInternalState(
            subconscious_pressure=0.70,
            association_pressure=0.82,
            curiosity_pressure=0.70,
            thought_stream_pressure=0.72,
            cognitive_tension=0.74,
        )

        self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="project eris cognitive momentum rules",
            now=20.0,
        )
        report = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="project eris cognitive momentum rules",
            now=30.0,
        )

        self.assertEqual(report.momentum.affordance, "attention")
        self.assertEqual(report.momentum.topic_seed, report.latest_thought.topic_seed)
        self.assertGreaterEqual(report.momentum.score, 0.58)
        self.assertIn("cognitive_momentum", report.momentum.risk_flags)
        self.assertIn("momentum_affordance=attention", report.continuity_notes)

    def test_explicit_closure_closes_momentum(self):
        snapshot = SimpleNamespace(
            idle_seconds=180.0,
            active_window_kind="coding",
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )
        state = PersistentInternalState(
            subconscious_pressure=0.70,
            association_pressure=0.82,
            curiosity_pressure=0.70,
        )
        self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="project eris closure rule",
            now=40.0,
        )
        active = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="project eris closure rule",
            now=50.0,
        )
        closed = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="project eris closure rule",
            closure_signals=(f"resolved {active.latest_thought.topic_seed}",),
            now=60.0,
        )

        self.assertTrue(closed.latest_thought.resolved)
        self.assertEqual(closed.suppression_reason, "closed")
        self.assertEqual(closed.momentum.score, 0.0)
        self.assertEqual(closed.unresolved_count, 0)

    def test_idle_tick_reheats_unresolved_loop_as_silent_pressure(self):
        snapshot = SimpleNamespace(
            idle_seconds=240.0,
            active_window_kind="coding",
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )
        state = PersistentInternalState(
            subconscious_pressure=0.66,
            association_pressure=0.78,
            curiosity_pressure=0.66,
            thought_stream_pressure=0.70,
            cognitive_tension=0.64,
        )

        first = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="phase continuity chat force autonomous shared substrate",
            now=70.0,
        )
        reheated = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=PersistentInternalState(restraint_pressure=0.20),
            last_text="different idle tick should not seed a new loop",
            now=80.0,
        )

        self.assertEqual(reheated.latest_thought.topic_seed, first.latest_thought.topic_seed)
        self.assertIn("loop_reheated", reheated.latest_thought.evidence)
        self.assertIn("silent_pressure_update", reheated.latest_thought.evidence)
        self.assertIn("silent_pressure", reheated.latest_thought.risk_flags)
        self.assertIn("why chat/force/autonomous", reheated.latest_thought.partial_text)
        self.assertFalse(reheated.latest_seed.mode)
        self.assertEqual(reheated.suppression_reason, "silent_pressure")
        self.assertGreater(reheated.latest_thought.tension, first.latest_thought.tension * 0.90)

    def test_reheated_loop_links_matching_memory_resonance_silently(self):
        snapshot = SimpleNamespace(
            idle_seconds=300.0,
            active_window_kind="coding",
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )
        state = PersistentInternalState(
            subconscious_pressure=0.64,
            association_pressure=0.76,
            curiosity_pressure=0.62,
            thought_stream_pressure=0.68,
        )

        self.engine.evaluate(
            snapshot=snapshot,
            internal_state=state,
            last_text="output guard raw final naturalness",
            now=90.0,
        )
        reheated = self.engine.evaluate(
            snapshot=snapshot,
            internal_state=PersistentInternalState(restraint_pressure=0.12),
            long_term_memory=("relationship/output_guard: raw line felt alive but final answer was squeezed by guard.",),
            last_text="idle",
            now=100.0,
        )

        self.assertIn("memory_resonance_linked", reheated.latest_thought.evidence)
        self.assertTrue(any(item.startswith("memory_resonance:") for item in reheated.latest_thought.associations))
        self.assertIn("output_guard", reheated.latest_thought.source_memory)
        self.assertFalse(reheated.latest_seed.mode)


if __name__ == "__main__":
    unittest.main()
