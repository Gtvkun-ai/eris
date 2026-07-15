import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import CognitiveBroadcast
from cortex.internal_state import PersistentInternalState
from cortex.personality import PersonalityLens


class PersonalityLensTests(unittest.TestCase):
    def setUp(self):
        self.lens = PersonalityLens()

    def test_interprets_hesitation_as_unfinished_intention_before_wording(self):
        snapshot = SimpleNamespace(
            active_window_kind="coding",
            focus_summary="coding workspace",
            mood_label="neutral",
            idle_label="slowing down",
            recent_events=("typing_and_deleting_self_doubt",),
            evidence=("sentence drafted then deleted",),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="erratic",
                window_switching="low",
                focus_pattern="hesitant",
            ),
        )
        broadcast = CognitiveBroadcast(
            label="recent_event",
            content="typing_and_deleting_self_doubt",
            score=0.72,
        )

        result = self.lens.evaluate(
            scene=snapshot,
            attention=broadcast,
            internal_state=PersistentInternalState(),
            relationship=SimpleNamespace(last_intent="ordinary_dialogue"),
            channel="autonomous",
        )

        self.assertEqual(result.interpretation, "unfinished_intention")
        self.assertIn("hesitation", result.attention_bias)
        self.assertIn("unfinished_intention", result.meaningfulness)
        self.assertGreaterEqual(result.want_to_say, 0.65)
        self.assertLessEqual(result.allowed_expression, 0.30)
        self.assertGreaterEqual(result.suppression_pressure, 0.68)
        self.assertIn(result.restraint_mode, {"suppress", "indirect_presence"})
        self.assertIn("inner_restraint_system", result.prompt_context)
        self.assertIn("want_to_say=", result.prompt_context)
        self.assertIn("guarded_reply", result.prompt_context)

    def test_chat_relationship_event_keeps_guarded_reply_distance(self):
        result = self.lens.evaluate(
            scene=SimpleNamespace(
                active_window_kind="general",
                focus_summary="general",
                mood_label="neutral",
                idle_label="active",
                recent_events=(),
                evidence=(),
                vision_facts=(),
                user_signals=SimpleNamespace(
                    typing_speed="high",
                    window_switching="low",
                    focus_pattern="steady",
                ),
            ),
            attention=CognitiveBroadcast(label="user_message", content="toi hoi buon", score=0.82),
            internal_state=PersistentInternalState(attachment=0.52, tenderness=0.44, social_energy=0.48),
            relationship=SimpleNamespace(last_intent="attachment_dialogue"),
            channel="chat",
            user_text="toi hoi buon",
        )

        self.assertEqual(result.interpretation, "direct_relationship_event")
        self.assertEqual(result.stance, "patient_probe")
        self.assertEqual(result.social_distance, "far_observing")

    def test_identity_reduction_triggers_cool_boundary(self):
        result = self.lens.evaluate(
            scene=SimpleNamespace(
                active_window_kind="communication",
                focus_summary="shared chat",
                mood_label="neutral",
                idle_label="active",
                recent_events=("user_called_eris_a_waifu_bot",),
                evidence=(),
                vision_facts=(),
                user_signals=SimpleNamespace(
                    typing_speed="steady",
                    window_switching="low",
                    focus_pattern="steady",
                ),
            ),
            attention=CognitiveBroadcast(label="user_message", content="chi la mot waifu bot vui vui thoi", score=0.78),
            internal_state=PersistentInternalState(
                attachment=0.46,
                social_energy=0.55,
                tenderness=0.22,
                restraint_pressure=0.30,
            ),
            relationship=SimpleNamespace(last_intent="ordinary_dialogue"),
            channel="chat",
            user_text="chi la mot waifu bot vui vui thoi",
        )

        self.assertEqual(result.interpretation, "identity_reduction")
        self.assertEqual(result.stance, "cool_boundary")
        self.assertEqual(result.emotional_coloring, "dry_low_heat")
        self.assertEqual(result.social_distance, "far_observing")
        self.assertIn("identity_integrity", result.meaningfulness)
        self.assertLessEqual(result.allowed_expression, 0.12)
        self.assertIn("reduction_guard", result.prompt_context)

    def test_autonomous_weak_anchor_reduces_expression_right(self):
        weak_scene = SimpleNamespace(
            active_window_kind="coding",
            focus_summary="coding workspace",
            mood_label="neutral",
            idle_label="slowing down",
            recent_events=("typing_and_deleting_self_doubt",),
            evidence=("sentence drafted then deleted",),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="erratic",
                window_switching="low",
                focus_pattern="hesitant",
            ),
        )
        anchored_scene = SimpleNamespace(
            active_window_kind="coding",
            focus_summary="coding workspace",
            mood_label="neutral",
            idle_label="slowing down",
            recent_events=("typing_and_deleting_self_doubt",),
            evidence=("event_id=typing_delete_01", "sentence drafted then deleted"),
            vision_facts=(),
            user_signals=SimpleNamespace(
                typing_speed="erratic",
                window_switching="low",
                focus_pattern="hesitant",
            ),
        )

        weak = self.lens.evaluate(scene=weak_scene, internal_state=PersistentInternalState(), channel="autonomous")
        anchored = self.lens.evaluate(scene=anchored_scene, internal_state=PersistentInternalState(), channel="autonomous")

        self.assertIn("persona_anchor=weak", weak.evidence)
        self.assertIn("persona_anchor=specific", anchored.evidence)
        self.assertLess(weak.allowed_expression, anchored.allowed_expression)
        self.assertGreater(weak.suppression_ratio, anchored.suppression_ratio)


if __name__ == "__main__":
    unittest.main()
