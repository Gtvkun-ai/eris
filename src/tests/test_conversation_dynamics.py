import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.conversation_dynamics import ConversationDynamicsEngine, ConversationDynamicsState


class ConversationDynamicsTests(unittest.TestCase):
    def setUp(self):
        self.engine = ConversationDynamicsEngine()

    def test_neutral_chat_keeps_low_tension(self):
        report = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="xin chao",
            last_assistant_text="",
            repeat_count=1,
        )

        self.assertEqual(report.state.mode, "settled")
        self.assertLessEqual(report.state.semantic_tension, 0.05)
        self.assertLessEqual(report.state.conversation_pressure, 0.05)

    def test_denial_creates_repair_mode(self):
        report = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="sai roi, y toi khong phai vay",
            last_assistant_text="old wrong frame",
            repeat_count=1,
        )

        self.assertEqual(report.state.mode, "repair")
        self.assertTrue(report.correction_detected)
        self.assertEqual(report.state.last_failure.type, "misread")
        self.assertIn("repair_first", report.state.adaptation_flags)

    def test_missing_piece_maps_to_underacted_failure(self):
        report = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="Thiếu là: state transition thật",
            last_assistant_text="just add memory",
            repeat_count=1,
        )

        self.assertEqual(report.state.mode, "repair")
        self.assertEqual(report.state.last_failure.type, "underacted")
        self.assertIn("state transition", report.state.last_failure.correction_needed)

    def test_repeated_correction_raises_pressure(self):
        first = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="sai roi",
            last_assistant_text="a",
            repeat_count=1,
        )
        second = self.engine.evaluate_chat(
            first.state,
            user_text="khong phai y toi",
            last_assistant_text="b",
            repeat_count=2,
        )

        self.assertGreater(second.state.conversation_pressure, first.state.conversation_pressure)
        self.assertEqual(second.state.correction_streak, 2)

    def test_clean_followup_decays_pressure(self):
        tense = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="sai roi",
            last_assistant_text="a",
            repeat_count=1,
        ).state
        clean = self.engine.evaluate_chat(
            tense,
            user_text="gio tiep tuc phan implementation",
            last_assistant_text="",
            repeat_count=1,
        )

        self.assertLess(clean.state.semantic_tension, tense.semantic_tension)
        self.assertLess(clean.state.conversation_pressure, tense.conversation_pressure)

    def test_positive_length_comment_does_not_infer_overexplained(self):
        failure = self.engine.infer_failure(
            "doan nay dai nhung on",
            last_assistant_text="long but accepted answer",
        )

        self.assertNotEqual(failure.type, "overexplained")

    def test_minor_correction_does_not_force_repair_mode(self):
        report = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="typo thoi, doi ten bien nay mot chut",
            last_assistant_text="old answer",
            repeat_count=1,
        )

        self.assertTrue(report.correction_detected)
        self.assertLess(report.state.correction_severity, 0.35)
        self.assertEqual(report.state.mode, "settled")
        self.assertIn("avoid_overrepair", report.state.adaptation_flags)

    def test_continuity_curve_tracks_recovery_after_repair(self):
        tense = self.engine.evaluate_chat(
            ConversationDynamicsState(),
            user_text="sai roi, y toi khong phai vay",
            last_assistant_text="old wrong frame",
            repeat_count=1,
        ).state
        clean = self.engine.evaluate_chat(
            tense,
            user_text="ok dung roi, tiep tuc implement",
            last_assistant_text="Dung roi, de toi sua lai truc tiep.",
            repeat_count=1,
        )

        self.assertEqual(clean.state.continuity_curve.alignment_trend, "converging")
        self.assertIn("recovering", clean.state.continuity_curve.rolling_arc)
        self.assertIn("continuity_curve", clean.prompt_context)

    def test_ok_but_wrong_does_not_count_as_relief(self):
        report = self.engine.evaluate_chat(
            ConversationDynamicsState(mode="repair", conversation_pressure=0.45),
            user_text="ok nhung sai",
            last_assistant_text="",
            repeat_count=1,
        )

        self.assertTrue(report.correction_detected)
        self.assertEqual(report.state.mode, "repair")
        self.assertEqual(report.state.conversational_relief, 0.0)

    def test_frustration_estimate_is_weighted_by_context(self):
        mild = self.engine.estimate_frustration("met mot chut", correction_detected=True)
        escalated = self.engine.estimate_frustration("sai nua, da noi bao lan roi", correction_detected=True)

        self.assertLess(mild, 0.10)
        self.assertGreater(escalated, 0.65)


if __name__ == "__main__":
    unittest.main()
