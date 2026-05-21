import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex import CognitionDelta, TemporalCognitionEngine
from cortex.goal_persistence import GoalPersistenceState
from cortex.internal_state import DesireDynamics, InternalStateEngine, MentalProcessSystem, PersistentInternalState
from cortex.contracts import MotivationalPressureReport, MotivationalUrge, SocialPresenceEvent


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

    def test_pressure_axes_rise_and_winner_satisfaction_decays_spoken_axis(self):
        base = PersistentInternalState(social_pressure=0.20, curiosity_pressure=0.10)
        sensed = self.engine.sense_update(
            base,
            channel="force_speak",
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.20, sarcasm_level=0.0),
            force_speak=True,
        )

        self.assertGreater(sensed.social_pressure, base.social_pressure)

        committed = self.engine.commit_turn(
            sensed,
            channel="force_speak",
            snapshot=SimpleNamespace(active_window_kind="general"),
            ti_report=SimpleNamespace(mode="steady_observe"),
            appraisal=SimpleNamespace(stance="grounded"),
            speech_core=SimpleNamespace(
                utterance_type="inner_whim",
                inner_thought=SimpleNamespace(intent="inner_whim"),
                motivation_pressure=MotivationalPressureReport(
                    winner=MotivationalUrge(label="user_requested_presence")
                ),
            ),
            action_plan=SimpleNamespace(speech_act="inner_whim"),
            inner_thought=SimpleNamespace(intent="inner_whim"),
            was_spoken=True,
        )

        self.assertLess(committed.social_pressure, sensed.social_pressure)
        self.assertGreater(committed.restraint_pressure, sensed.restraint_pressure)

    def test_subconscious_fields_round_trip_and_default_safely(self):
        state = PersistentInternalState.from_dict(
            {
                "subconscious_pressure": 0.66,
                "memory_replay_pressure": 0.44,
                "association_pressure": 0.55,
                "last_subconscious_mode": "memory_replay",
                "last_subconscious_seed": "memory_replay:quiet",
                "recent_subconscious_seeds": ["memory_replay:quiet"],
                "last_self_state_label": "engaged",
                "recent_self_state_labels": ["settled", "engaged"],
            }
        )
        empty = PersistentInternalState.from_dict({})

        self.assertAlmostEqual(state.subconscious_pressure, 0.66, places=2)
        self.assertAlmostEqual(state.memory_replay_pressure, 0.44, places=2)
        self.assertEqual(state.last_subconscious_mode, "memory_replay")
        self.assertEqual(state.recent_subconscious_seeds, ("memory_replay:quiet",))
        self.assertEqual(state.last_self_state_label, "engaged")
        self.assertEqual(state.recent_self_state_labels, ("settled", "engaged"))
        self.assertEqual(empty.subconscious_pressure, PersistentInternalState().subconscious_pressure)
        self.assertEqual(empty.last_self_state_label, "")
        self.assertIn("subconscious_pressure", state.to_dict())
        self.assertIn("last_self_state=engaged", state.to_prompt_context())

    def test_subconscious_pressures_rise_and_decay(self):
        base = PersistentInternalState(subconscious_pressure=0.10, memory_replay_pressure=0.10, association_pressure=0.10)
        sensed = self.engine.sense_update(
            base,
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="general",
                idle_seconds=500.0,
                user_signals=SimpleNamespace(focus_pattern="absent", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.22, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
        )
        committed = self.engine.commit_turn(
            sensed,
            channel="autonomous",
            snapshot=SimpleNamespace(active_window_kind="general"),
            ti_report=SimpleNamespace(mode="steady_observe"),
            appraisal=SimpleNamespace(stance="grounded"),
            speech_core=SimpleNamespace(utterance_type="inner_whim", inner_thought=SimpleNamespace(intent="inner_whim")),
            action_plan=SimpleNamespace(speech_act="inner_whim"),
            inner_thought=SimpleNamespace(intent="inner_whim"),
            subconscious_seed=SimpleNamespace(mode="memory_replay", topic_seed="memory_replay:quiet"),
            was_spoken=True,
        )

        self.assertGreater(sensed.subconscious_pressure, base.subconscious_pressure)
        self.assertGreater(sensed.memory_replay_pressure, base.memory_replay_pressure)
        self.assertLess(committed.subconscious_pressure, sensed.subconscious_pressure)
        self.assertEqual(committed.last_subconscious_seed, "memory_replay:quiet")

    def test_temporal_cognition_delta_blends_memory_tension_and_event_impulse(self):
        self.assertIsInstance(TemporalCognitionEngine().compute_delta(PersistentInternalState()), CognitionDelta)
        base = PersistentInternalState(
            memory_replay_pressure=0.05,
            cognitive_tension=0.05,
            unresolved_prediction_pressure=0.30,
            last_cognition_at=100.0,
        )
        thought_stream_report = SimpleNamespace(
            stream_tension=0.80,
            unresolved_count=2,
            momentum=SimpleNamespace(score=0.70, tension=0.60),
            active_attractor=SimpleNamespace(score=0.75, tension=0.72),
            latest_thought=SimpleNamespace(tension=0.68),
            disturbances=(
                SimpleNamespace(intensity=0.85, closes_loop=False),
            ),
        )
        after = self.engine.sense_update(
            base,
            channel="chat",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_general"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            memory_resonance=SimpleNamespace(score=0.82, attention_bias=0.60, appraisal_bias=0.40, wording_bias=0.20, silence_bias=0.10),
            thought_stream_report=thought_stream_report,
            user_text="let's wire temporal cognition",
            now=130.0,
        )

        self.assertGreater(after.memory_replay_pressure, base.memory_replay_pressure)
        self.assertGreater(after.cognitive_tension, base.cognitive_tension)
        self.assertGreater(after.last_memory_resonance, 0.0)
        self.assertGreater(after.last_unresolved_tension, 0.0)
        self.assertGreater(after.last_event_impulse, 0.0)
        self.assertAlmostEqual(after.last_elapsed_seconds, 30.0, places=2)

    def test_closure_impulse_relaxes_unresolved_prediction_pressure(self):
        base = PersistentInternalState(
            thought_stream_pressure=0.60,
            cognitive_tension=0.60,
            unresolved_prediction_pressure=0.72,
            recursive_reactivation_pressure=0.55,
            last_cognition_at=100.0,
        )
        open_report = SimpleNamespace(
            stream_tension=0.0,
            unresolved_count=0,
            momentum=SimpleNamespace(score=0.0, tension=0.0),
            active_attractor=SimpleNamespace(score=0.0, tension=0.0),
            latest_thought=SimpleNamespace(tension=0.0),
            disturbances=(SimpleNamespace(intensity=0.90, closes_loop=False),),
        )
        closure_report = SimpleNamespace(
            stream_tension=0.0,
            unresolved_count=0,
            momentum=SimpleNamespace(score=0.0, tension=0.0),
            active_attractor=SimpleNamespace(score=0.0, tension=0.0),
            latest_thought=SimpleNamespace(tension=0.0),
            disturbances=(SimpleNamespace(intensity=0.90, closes_loop=True),),
        )

        open_after = self.engine.sense_update(
            base,
            channel="chat",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_general"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            thought_stream_report=open_report,
            user_text="still open",
            now=130.0,
        )
        closure_after = self.engine.sense_update(
            base,
            channel="chat",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_general"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            thought_stream_report=closure_report,
            user_text="fixed",
            now=130.0,
        )

        self.assertLess(closure_after.unresolved_prediction_pressure, open_after.unresolved_prediction_pressure)

    def test_mental_processes_round_trip_and_prompt_context(self):
        processes = MentalProcessSystem()
        processes = replace(
            processes,
            curiosity=processes.curiosity.excite(0.70),
            tension=processes.tension.excite(0.42),
        )
        state = PersistentInternalState(mental_processes=processes)
        loaded = PersistentInternalState.from_dict(state.to_dict())

        self.assertGreater(loaded.mental_processes.curiosity.pressure, 0.0)
        self.assertIn("mental_processes", loaded.to_dict())
        self.assertIn("mental_process_system", loaded.to_prompt_context())

    def test_mental_processes_interact_and_restraint_inhibits_curiosity(self):
        base = MentalProcessSystem()
        curious = replace(base, curiosity=base.curiosity.excite(0.84))
        curious_after = curious.evolve(
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=500.0,
                user_signals=SimpleNamespace(focus_pattern="absent", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.20, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="pattern_muse"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
        )
        restrained = replace(curious, restraint=curious.restraint.excite(0.92))
        restrained_after = restrained.evolve(
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=500.0,
                user_signals=SimpleNamespace(focus_pattern="absent", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.20, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="pattern_muse"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
        )

        self.assertGreater(curious_after.background_thought.pressure, base.background_thought.pressure)
        self.assertLess(restrained_after.curiosity.activation, curious_after.curiosity.activation)

    def test_goal_persistence_promotes_user_goal_and_round_trips(self):
        base = PersistentInternalState()
        after = self.engine.sense_update(
            base,
            channel="chat",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.20, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_general"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            user_text="implement goal persistence so ERIS keeps tracking the same problem across events",
            now=100.0,
        )
        loaded = PersistentInternalState.from_dict(after.to_dict())

        self.assertEqual(after.goal_persistence.status, "active")
        self.assertGreater(after.goal_persistence.strength, 0.50)
        self.assertIn("goal_persistence", after.to_dict())
        self.assertEqual(loaded.goal_persistence.summary, after.goal_persistence.summary)
        self.assertIn("goal_persistence", loaded.to_prompt_context())

    def test_goal_persistence_can_be_reactivated_by_cognitive_momentum(self):
        base = PersistentInternalState(
            goal_persistence=GoalPersistenceState(
                summary="associative_drift:project_eris_goal_persistence",
                status="active",
                strength=0.58,
                recurrence_count=1,
                created_at=10.0,
                updated_at=10.0,
            )
        )
        report = SimpleNamespace(
            momentum=SimpleNamespace(
                affordance="attention",
                score=0.74,
                tension=0.82,
                topic_seed="associative_drift:project_eris_goal_persistence",
                evidence=("reactivations=2", "momentum=0.74"),
            ),
            active_attractor=SimpleNamespace(attractor=False, score=0.0),
            disturbances=(),
            stream_tension=0.82,
            unresolved_count=1,
            latest_thought=SimpleNamespace(tension=0.82),
        )

        after = self.engine.sense_update(
            base,
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=180.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.15, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            thought_stream_report=report,
            now=40.0,
        )

        self.assertEqual(after.goal_persistence.status, "active")
        self.assertGreater(after.goal_persistence.recurrence_count, base.goal_persistence.recurrence_count)
        self.assertGreater(after.goal_persistence.strength, base.goal_persistence.strength)

    def test_social_presence_event_updates_background_without_social_pressure_spike(self):
        base = PersistentInternalState(social_energy=0.20, social_pressure=0.12, restraint_pressure=0.10)
        presence = SocialPresenceEvent(
            present=True,
            confidence=0.72,
            intensity=0.64,
            kind="ambient_co_presence",
            evidence=("recent_activity", "same_focus_kind=coding"),
            speech_allowed=False,
        )

        after = self.engine.sense_update(
            base,
            channel="autonomous",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=4.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.0, sarcasm_level=0.0),
            social_presence_event=presence,
            now=100.0,
        )

        self.assertGreater(after.social_energy, base.social_energy)
        self.assertGreater(after.restraint_pressure, base.restraint_pressure)
        self.assertLess(after.social_pressure, 0.30)
        self.assertEqual(after.last_social_presence_kind, "ambient_co_presence")
        self.assertFalse(presence.speech_allowed)

    def test_goal_persistence_closes_on_short_closure_signal(self):
        base = PersistentInternalState(
            goal_persistence=GoalPersistenceState(
                summary="implement goal persistence across events",
                status="active",
                strength=0.74,
                urgency=0.50,
                recurrence_count=2,
                created_at=10.0,
                updated_at=20.0,
            )
        )

        after = self.engine.sense_update(
            base,
            channel="chat",
            snapshot=SimpleNamespace(
                active_window_kind="coding",
                idle_seconds=5.0,
                user_signals=SimpleNamespace(focus_pattern="steady", window_switching="low"),
            ),
            ni_report=SimpleNamespace(drift_score=0.10, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="chat_general"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            user_text="xong rồi",
            now=50.0,
        )

        self.assertEqual(after.goal_persistence.status, "closed")
        self.assertAlmostEqual(after.goal_persistence.progress, 1.0)

    def test_desire_dynamics_tracks_attraction_aversion_attachment_and_residue(self):
        base = PersistentInternalState(desire=DesireDynamics(unresolved_residue=0.12))
        after = self.engine.sense_update(
            base,
            channel="autonomous",
            snapshot=SimpleNamespace(
                captured_at="2026-05-13T01:25:00+0700",
                active_window_kind="coding",
                active_app="Godot Engine",
                active_window="Godot Engine",
                idle_seconds=520.0,
                recent_events=("alt_tab_burst", "cursor_blinking_in_silence"),
                user_signals=SimpleNamespace(focus_pattern="drifting", window_switching="high"),
            ),
            ni_report=SimpleNamespace(drift_score=0.22, confidence=0.60, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.10, sarcasm_level=0.0),
            thought_stream_report=SimpleNamespace(
                stream_tension=0.68,
                unresolved_count=2,
                latest_thought=SimpleNamespace(topic_seed="unfinished_voice_pass"),
                active_attractor=SimpleNamespace(topic_seed=""),
                disturbances=(),
            ),
            now=100.0,
        )
        committed = self.engine.commit_turn(
            after,
            channel="autonomous",
            snapshot=SimpleNamespace(active_window_kind="coding"),
            ti_report=SimpleNamespace(mode="steady_observe"),
            appraisal=SimpleNamespace(stance="grounded"),
            speech_core=SimpleNamespace(utterance_type="no_speech", inner_thought=SimpleNamespace(intent="")),
            action_plan=SimpleNamespace(speech_act="no_speech"),
            inner_thought=SimpleNamespace(intent=""),
            subconscious_seed=SimpleNamespace(mode="memory_replay", topic_seed="unfinished_voice_pass"),
            was_spoken=False,
        )

        self.assertEqual(after.desire.recurring_attraction, "late_night_coding")
        self.assertEqual(after.desire.recurring_aversion, "alt_tab_churn")
        self.assertEqual(after.desire.attention_hook, "silence_pull")
        self.assertIn(after.desire.attachment_drift, {"guarded", "defensive", "avoidant", "cooling"})
        self.assertGreater(after.desire.unresolved_residue, base.desire.unresolved_residue)
        self.assertGreater(committed.desire.unresolved_residue, after.desire.unresolved_residue)
        self.assertIn("desire_dynamics", committed.to_dict())
        self.assertIn("desire_system", committed.to_prompt_context())


if __name__ == "__main__":
    unittest.main()
