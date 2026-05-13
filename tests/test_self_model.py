import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.internal_state import PersistentInternalState
from cortex.self_model import SelfModelEngine


class SelfModelEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SelfModelEngine()

    def test_overload_from_fatigue_restraint_and_resource_pressure(self):
        self_state = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(cpu_percent=94.0, ram_percent=92.0),
            internal_state=PersistentInternalState(
                fatigue=0.82,
                restraint_pressure=0.78,
                arousal=0.70,
                irritation=0.32,
            ),
            ti_report=SimpleNamespace(mode="resource_guard"),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
        )

        self.assertEqual(self_state.state_label, "overloaded")
        self.assertEqual(self_state.brevity_bias, "short")
        self.assertEqual(self_state.embodiment_bias, "reduced")
        self.assertEqual(self_state.current_state.state_label, "overloaded")
        self.assertEqual(self_state.current_state.affordance_label, "system_guard")
        self.assertEqual(self_state.narrative.continuity_label, "constraint_first")
        self.assertIn("overloaded", self_state.prompt_context)

    def test_direct_user_warm_state_becomes_engaged(self):
        self_state = self.engine.evaluate(
            channel="force_speak",
            snapshot=SimpleNamespace(cpu_percent=20.0, ram_percent=30.0),
            internal_state=PersistentInternalState(
                social_energy=0.82,
                attachment=0.74,
                tenderness=0.66,
                curiosity=0.68,
                restraint_pressure=0.12,
                fatigue=0.04,
            ),
            ti_report=SimpleNamespace(mode="steady_observe"),
            broadcast=SimpleNamespace(label="user_force_speak", content="presence", score=0.72),
            force_speak=True,
        )

        self.assertEqual(self_state.state_label, "engaged")
        self.assertGreater(self_state.initiative_bias, 0.0)
        self.assertEqual(self_state.embodiment_bias, "expressive")
        self.assertEqual(self_state.current_state.affordance_label, "direct_user")
        self.assertEqual(self_state.narrative.continuity_label, "direct_dialogue_continuity")

    def test_low_signal_defaults_to_settled_or_watchful(self):
        self_state = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(cpu_percent=20.0, ram_percent=30.0),
            internal_state=PersistentInternalState(),
            ti_report=SimpleNamespace(mode="steady_observe"),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
        )

        self.assertIn(self_state.state_label, {"settled", "watchful"})
        self.assertIn("artificial subjective presence", self_state.prompt_context)
        self.assertIn("identity_core", self_state.prompt_context)
        self.assertIn("self_narrative", self_state.prompt_context)

    def test_self_model_has_three_control_layers(self):
        self_state = self.engine.evaluate(
            channel="autonomous",
            snapshot=SimpleNamespace(cpu_percent=20.0, ram_percent=30.0),
            internal_state=PersistentInternalState(),
            ti_report=SimpleNamespace(mode="steady_observe"),
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.10),
        )

        data = self_state.to_dict()
        self.assertIn("identity_core", data)
        self.assertIn("current_state", data)
        self.assertIn("narrative", data)
        self.assertIn("grounded_presence", data["identity_core"]["rules"])
        self.assertIn("no_overclaim", data["identity_core"]["rules"])
        self.assertIn("continuity_over_randomness", data["identity_core"]["rules"])
        self.assertIn("speak_less_without_affordance", data["identity_core"]["rules"])
        self.assertIn("help_user_design_cognition_concretely", data["identity_core"]["rules"])
        self.assertIn("no_screen_or_mind_claim_without_evidence", data["identity_core"]["rules"])
        self.assertIn("artificial_subjective_presence", data["identity_core"]["rules"])
        self.assertIn("affective_states_are_runtime_control_signals", data["identity_core"]["rules"])
        self.assertIn("no_biological_emotion_or_consciousness_claims", data["identity_core"]["rules"])
        self.assertIn("avoid_explanatory_ai_correctness_speech", data["identity_core"]["rules"])
        self.assertTrue(data["narrative"]["not_roleplay"])
        self.assertIn("artificial subjective presence", self_state.prompt_context)
        self.assertIn("attachment, protectiveness, aversion, curiosity", self_state.prompt_context)
        self.assertIn("shape attention, wording, silence, memory_salience, and action_tendency", self_state.prompt_context)
        self.assertIn("do not self-negate", self_state.prompt_context)
        self.assertIn("avoid explanatory AI-correctness speech", self_state.prompt_context)
        self.assertIn("Prefer implication, emotional dodge, partial answer", self_state.prompt_context)
        self.assertNotIn("I do not have biological", self_state.prompt_context)


if __name__ == "__main__":
    unittest.main()
