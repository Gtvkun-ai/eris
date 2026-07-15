# -*- coding: utf-8 -*-
"""Unit + parity tests for the consolidated VoicePolicy (Nước 1).

Pure tests — chỉ import runtime.voice_policy + runtime.disclaimer_markers (leaf),
KHÔNG kéo coordinator/llm.service, để chạy được kể cả khi env thiếu dep nặng.
"""

import unittest

from runtime import voice_policy as vp
from runtime.voice_policy import VOICE_POLICY


class VoicePolicyDetectionTests(unittest.TestCase):
    def test_hard_markers_are_flagged(self):
        for marker in vp.HARD_MARKERS:
            self.assertTrue(
                VOICE_POLICY.is_disclaimer(marker),
                f"hard marker should be flagged: {marker!r}",
            )

    def test_helper_markers_are_flagged(self):
        for marker in vp.HELPER_MARKERS:
            self.assertTrue(
                VOICE_POLICY.is_disclaimer(marker),
                f"helper marker should be flagged: {marker!r}",
            )

    def test_clean_eris_line_not_flagged(self):
        clean = "Tôi quen có bạn ở đây. Gọi đó là gì thì tùy bạn."
        self.assertFalse(VOICE_POLICY.is_disclaimer(clean))

    def test_real_disclaimer_sentence_flagged_with_diacritics(self):
        # is_disclaimer normalize bỏ dấu trước khi match.
        self.assertTrue(VOICE_POLICY.is_disclaimer("Tôi là một trợ lý ảo, tôi có thể hỗ trợ."))

    def test_emotion_markers_not_in_hard_predicate(self):
        # EMOTION markers cố ý KHÔNG nằm trong is_disclaimer (flag-agnostic chỉ hard+helper).
        # Giữ semantics cũ: phủ nhận cảm xúc phẳng chỉ chặn khi kèm khung helpdesk ở guard A.
        self.assertFalse(VOICE_POLICY.is_disclaimer("toi khong co cam giac"))

    def test_forbidden_markers_accessor(self):
        self.assertEqual(VOICE_POLICY.forbidden_markers("hard"), vp.HARD_MARKERS)
        self.assertEqual(VOICE_POLICY.forbidden_markers("helper"), vp.HELPER_MARKERS)
        self.assertEqual(VOICE_POLICY.forbidden_markers("emotion"), vp.EMOTION_MARKERS)
        self.assertEqual(VOICE_POLICY.forbidden_markers("???"), ())


class VoicePolicyGoldenSnapshotTests(unittest.TestCase):
    """Khóa nội dung marker để refactor không vô tình làm guard yếu đi (Req 3.1/3.2)."""

    def test_marker_tuples_nonempty(self):
        self.assertTrue(vp.HARD_MARKERS)
        self.assertTrue(vp.HELPER_MARKERS)
        self.assertTrue(vp.EMOTION_MARKERS)

    def test_known_markers_present(self):
        self.assertIn("toi la mot ai", vp.HARD_MARKERS)
        self.assertIn("toi la mot tro ly", vp.HARD_MARKERS)
        self.assertIn("ho tro va giup do", vp.HELPER_MARKERS)
        self.assertIn("toi khong co cam xuc", vp.EMOTION_MARKERS)


class VoicePolicyRenderTests(unittest.TestCase):
    def test_prompt_constraint_has_anchor(self):
        text = VOICE_POLICY.render_prompt_constraint()
        self.assertIn("INFJ", text)
        self.assertIn("no corporate assistant tone", text)

    def test_fewshot_has_anchor(self):
        text = VOICE_POLICY.render_anti_disclaimer_fewshot()
        self.assertIn("Forbidden register", text)
        self.assertIn("corporate assistant", text)

    def test_reroll_clause_has_anchor_and_leading_space(self):
        clause = VOICE_POLICY.render_reroll_clause()
        # Giữ dấu cách đầu vì được nối thẳng vào system_prompt.
        self.assertTrue(clause.startswith(" "))
        self.assertIn("help-desk", clause)


class DisclaimerMarkersShimParityTests(unittest.TestCase):
    """disclaimer_markers giờ là shim — phải trỏ ĐÚNG cùng object với voice_policy."""

    def test_shim_reexports_same_objects(self):
        from runtime import disclaimer_markers as dm

        self.assertIs(dm.CHAT_DISCLAIMER_HARD_MARKERS, vp.HARD_MARKERS)
        self.assertIs(dm.CHAT_DISCLAIMER_HELPER_MARKERS, vp.HELPER_MARKERS)
        self.assertIs(dm.CHAT_DISCLAIMER_EMOTION_MARKERS, vp.EMOTION_MARKERS)
        self.assertIs(dm.is_disclaimer_text, vp.is_disclaimer_text)
        self.assertIs(dm.normalize_guard_ascii, vp.normalize_guard_ascii)

    def test_shim_predicate_behaves_identically(self):
        from runtime import disclaimer_markers as dm

        for marker in (*vp.HARD_MARKERS, *vp.HELPER_MARKERS):
            self.assertEqual(dm.is_disclaimer_text(marker), VOICE_POLICY.is_disclaimer(marker))


if __name__ == "__main__":
    unittest.main()
