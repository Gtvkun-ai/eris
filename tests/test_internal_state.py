import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import InternalStateEngine, MentalProcessSystem, PersistentInternalState
from cortex.contracts import MotivationalPressureReport, MotivationalUrge


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
        self.assertEqual(empty.subconscious_pressure, 0.0)
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


if __name__ == "__main__":
    unittest.main()
