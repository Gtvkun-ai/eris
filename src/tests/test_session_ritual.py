import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import SocialPresenceEvent, UnresolvedTensionLoop
from cortex.goal_persistence import GoalPersistenceState
from cortex.internal_state import InternalStateEngine, PersistentInternalState
from cortex.session_ritual import SessionRitualEngine


class SessionRitualEngineTests(unittest.TestCase):
    def test_rehydrates_goal_loops_and_allows_light_greeting(self):
        engine = SessionRitualEngine()
        state = PersistentInternalState(
            cycle_count=9,
            last_focus_kind="coding",
            last_channel="chat",
            last_self_state_label="engaged",
            goal_persistence=GoalPersistenceState(
                summary="implement session ritual layer",
                status="active",
                strength=0.76,
                urgency=0.42,
            ),
        )
        report = engine.evaluate(
            snapshot=SimpleNamespace(active_window_kind="coding", idle_seconds=2.0),
            internal_state=state,
            social_presence_event=SocialPresenceEvent(
                present=True,
                confidence=0.74,
                intensity=0.62,
                kind="ambient_co_presence",
            ),
            thought_stream_report=SimpleNamespace(
                active_attractor=UnresolvedTensionLoop(
                    loop_id="loop_1",
                    topic_seed="cognition continuity",
                    score=0.70,
                    tension=0.64,
                    attractor=True,
                ),
                unresolved_loops=(
                    UnresolvedTensionLoop(
                        loop_id="loop_1",
                        topic_seed="cognition continuity",
                        score=0.70,
                        tension=0.64,
                    ),
                ),
                momentum=SimpleNamespace(unresolved=False),
            ),
            now=100.0,
        )

        self.assertTrue(report.presence_restored)
        self.assertTrue(report.continuity_restored)
        self.assertTrue(report.session_resumed)
        self.assertEqual(report.tone, "focused")
        self.assertTrue(report.should_greet)
        self.assertIn("resume_goal", report.greeting_text)
        self.assertIn("implement session ritual layer", report.greeting_text)
        self.assertIn("session_ritual", report.prompt_context)

    def test_overload_does_not_suppress_hard_startup_greeting(self):
        engine = SessionRitualEngine()
        state = PersistentInternalState(
            cycle_count=3,
            fatigue=0.80,
            last_session_greeting_at=80.0,
            last_thought_seed="memory_replay:old_loop",
        )
        report = engine.evaluate(
            snapshot=SimpleNamespace(active_window_kind="general", idle_seconds=2.0),
            internal_state=state,
            social_presence_event=SocialPresenceEvent(present=True, confidence=0.80, intensity=0.70),
            thought_stream_report=SimpleNamespace(active_attractor=UnresolvedTensionLoop(), unresolved_loops=()),
            now=100.0,
        )

        self.assertTrue(report.restored)
        self.assertEqual(report.tone, "overloaded")
        self.assertTrue(report.should_greet)

    def test_greeting_does_not_expose_internal_telemetry_labels(self):
        engine = SessionRitualEngine()
        state = PersistentInternalState(
            cycle_count=4,
            goal_persistence=GoalPersistenceState(
                summary="input_disturbance:force_speak_user_force_speak_force_speak_requested",
                status="active",
                strength=0.80,
            ),
        )
        report = engine.evaluate(
            snapshot=SimpleNamespace(active_window_kind="general", idle_seconds=2.0),
            internal_state=state,
            social_presence_event=SocialPresenceEvent(present=True, confidence=0.80, intensity=0.70),
            thought_stream_report=SimpleNamespace(
                active_attractor=UnresolvedTensionLoop(),
                unresolved_loops=(),
                momentum=SimpleNamespace(unresolved=False),
            ),
            now=100.0,
        )

        self.assertTrue(report.should_greet)
        self.assertEqual(report.greeting_text, "")
        self.assertNotIn("input_disturbance", report.greeting_text)
        self.assertNotIn("force_speak", report.greeting_text)
        self.assertNotIn("force_speak_requested", report.greeting_text)

    def test_previous_session_greeting_does_not_block_new_startup_greeting(self):
        engine = SessionRitualEngine()
        state = PersistentInternalState(
            cycle_count=4,
            last_session_greeting_at=95.0,
            goal_persistence=GoalPersistenceState(
                summary="continue the current code repair",
                status="active",
                strength=0.80,
            ),
        )
        report = engine.evaluate(
            snapshot=SimpleNamespace(active_window_kind="coding", idle_seconds=2.0),
            internal_state=state,
            social_presence_event=SocialPresenceEvent(present=True, confidence=0.80, intensity=0.70),
            thought_stream_report=SimpleNamespace(
                active_attractor=UnresolvedTensionLoop(),
                unresolved_loops=(),
                momentum=SimpleNamespace(unresolved=False),
            ),
            now=100.0,
        )

        self.assertTrue(report.should_greet)
        self.assertNotIn("greeting_cooldown", report.evidence)

    def test_internal_state_marks_session_resume(self):
        engine = InternalStateEngine()
        state = PersistentInternalState(social_energy=0.20, recursive_reactivation_pressure=0.10)
        report = SessionRitualEngine().evaluate(
            snapshot=SimpleNamespace(active_window_kind="general", idle_seconds=4.0),
            internal_state=PersistentInternalState(cycle_count=2, last_thought_seed="goal_loop"),
            social_presence_event=SocialPresenceEvent(present=True, confidence=0.70, intensity=0.60),
            thought_stream_report=SimpleNamespace(active_attractor=UnresolvedTensionLoop(), unresolved_loops=()),
            now=100.0,
        )

        after = engine.commit_session_ritual(state, session_ritual=report, now=100.0)
        loaded = PersistentInternalState.from_dict(after.to_dict())

        self.assertEqual(after.session_resume_count, 1)
        self.assertGreater(after.social_energy, state.social_energy)
        self.assertGreater(after.recursive_reactivation_pressure, state.recursive_reactivation_pressure)
        self.assertEqual(loaded.last_session_tone, after.last_session_tone)
        self.assertIn("session_ritual_state", loaded.to_prompt_context())

    def test_startup_greeting_can_happen_without_restored_continuity(self):
        report = SessionRitualEngine().evaluate(
            snapshot=SimpleNamespace(active_window_kind="general", idle_seconds=2.0),
            internal_state=PersistentInternalState(),
            social_presence_event=SocialPresenceEvent(present=True, confidence=0.70, intensity=0.60),
            thought_stream_report=SimpleNamespace(active_attractor=UnresolvedTensionLoop(), unresolved_loops=()),
            now=100.0,
        )

        self.assertTrue(report.presence_restored)
        self.assertFalse(report.continuity_restored)
        self.assertTrue(report.should_greet)
        self.assertEqual(report.greeting_text, "")

    def test_startup_greeting_does_not_require_presence_evidence(self):
        report = SessionRitualEngine().evaluate(
            snapshot=SimpleNamespace(active_window_kind="general", idle_seconds=999.0, recent_events=()),
            internal_state=PersistentInternalState(),
            social_presence_event=SocialPresenceEvent(present=False, confidence=0.0, intensity=0.0),
            thought_stream_report=SimpleNamespace(active_attractor=UnresolvedTensionLoop(), unresolved_loops=()),
            now=100.0,
        )

        self.assertFalse(report.presence_restored)
        self.assertFalse(report.continuity_restored)
        self.assertTrue(report.should_greet)


if __name__ == "__main__":
    unittest.main()
