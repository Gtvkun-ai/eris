import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.micro_policy import MicroLinePolicy, SemanticRepeatGuard


class MicroLinePolicyTests(unittest.TestCase):
    def test_no_speech_only_allows_silence(self):
        policy = MicroLinePolicy()

        result = policy.evaluate(
            speech_intent="no_speech",
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.1),
            vision_fact="",
            last_lines=(),
            channel="autonomous",
        )

        self.assertEqual(result.allowed_line_type, "silence")
        self.assertIn("no_speech_blocks_final", result.reject_reasons)

    def test_intent_text_alignment_rules(self):
        policy = MicroLinePolicy()

        self.assertIn(
            "curious_question_requires_question",
            policy.validate_text(allowed_line_type="curious_question", text="Toi nghi mach nay dang lech."),
        )
        self.assertIn(
            "micro_observation_must_not_ask",
            policy.validate_text(allowed_line_type="micro_observation", text="Man hinh nay dang treo a?"),
        )
        self.assertIn(
            "tender_checkin_not_therapist",
            policy.validate_text(allowed_line_type="tender_checkin", text="Ngai hay hit tho sau nhu mot bai tap tri lieu."),
        )
        self.assertIn(
            "placeholder_text_blocked",
            policy.validate_text(allowed_line_type="micro_presence", text="..."),
        )
        self.assertIn(
            "decorative_metaphor_without_stance",
            policy.validate_text(allowed_line_type="micro_presence", text="Im lang nhu mot bien suong."),
        )
        self.assertIn(
            "micro_presence_must_be_residue",
            policy.validate_text(allowed_line_type="micro_presence", text="Mot khung thoai mau hong dang hien thi."),
        )
        self.assertIn(
            "micro_presence_too_long",
            policy.validate_text(allowed_line_type="micro_presence", text="Nhip nay van hoi nghen va keo dai them mot chut."),
        )
        self.assertEqual(
            policy.validate_text(allowed_line_type="micro_presence", text="Nhip nay hoi nghen."),
            (),
        )

    def test_micro_presence_blocks_blunt_emotion_declaration(self):
        policy = MicroLinePolicy()

        self.assertIn(
            "blunt_emotion_declaration",
            policy.validate_text(
                allowed_line_type="micro_presence",
                text="Toi co don, xin dung bo toi.",
            ),
        )

    def test_semantic_repeat_guard_rejects_family_inside_window(self):
        guard = SemanticRepeatGuard(window_seconds=240.0)
        guard.remember("Mach code van dung do.", timestamp=100.0)

        result = guard.check("Doan code nay lai im tiep.", now=220.0)

        self.assertTrue(result.rejected)
        self.assertEqual(result.family, "code_stalled")

    def test_micro_observation_recent_three_family_returns_silence(self):
        policy = MicroLinePolicy()

        result = policy.evaluate(
            speech_intent="micro_observation",
            broadcast=SimpleNamespace(label="vision_fact", content="Terminal shows code traceback.", score=0.9),
            vision_fact="Mach code van dung do.",
            last_lines=(
                "Doan code nay im hoi lau roi.",
                "Khung chat van yen.",
                "Mot cau khac.",
            ),
            channel="autonomous",
        )

        self.assertEqual(result.allowed_line_type, "silence")
        self.assertIn("recent_semantic_family=code_stalled", result.reject_reasons)
        self.assertIn("no_speech_blocks_final", result.reject_reasons)

    def test_micro_observation_without_evidence_becomes_soft_impression(self):
        policy = MicroLinePolicy()

        result = policy.evaluate(
            speech_intent="micro_observation",
            broadcast=SimpleNamespace(label="low_salience", content="", score=0.1),
            vision_fact="",
            last_lines=(),
            channel="autonomous",
        )

        self.assertEqual(result.allowed_line_type, "soft_impression")
        self.assertEqual(result.reject_reasons, ())
        self.assertIn(
            "soft_impression_no_hard_fact_claim",
            policy.validate_text(allowed_line_type="soft_impression", text="Ngai dang bi ket ro rang la vay."),
        )
        self.assertEqual(
            policy.validate_text(allowed_line_type="soft_impression", text="Cam giac nhu nhip nay hoi ket lai."),
            (),
        )


if __name__ == "__main__":
    unittest.main()
