import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import TiPolicyReport
from cortex.ti import TiGovernor
from domain import Decision


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    return " ".join(lowered.split())


class TiGovernorTests(unittest.TestCase):
    def setUp(self):
        self.governor = TiGovernor()
        self.report = TiPolicyReport(
            mode="chat_general",
            focus_label="general",
            reason="test",
            prompt_context="",
        )

    def test_keeps_normal_text_when_no_capability_claim(self):
        decision = Decision(
            text="Hay tap trung vao bug trong parser truoc, roi toi se xem tiep coordinator.",
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, self.report)

        self.assertEqual(result.text, "Hay tap trung vao bug trong parser truoc, roi toi se xem tiep coordinator.")

    def test_rewrites_explicit_physical_control_claim(self):
        decision = Decision(
            text="Toi se thu hoi quyen kiem soat va khoa man hinh cua Ngai.",
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, self.report)
        normalized = _norm(result.text)

        self.assertIn("doan nhan cong do bo di", normalized)
        self.assertNotIn("thu hoi quyen kiem soat", normalized)

    def test_rewrites_cleanup_and_forced_control_language(self):
        report = TiPolicyReport(
            mode="resource_guard",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Du lieu he thong: RAM 94% dang cao. "
                "Toi da tu dong don dep cache tam thoi de giai phong dung luong cho Ngai."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)
        normalized = _norm(result.text)

        self.assertNotIn("du lieu he thong", normalized)
        self.assertNotIn("don dep cache", normalized)
        self.assertIn("doan nhan cong do bo di", normalized)

    def test_style_sanitizer_does_not_chop_mangled_text_on_question_marks(self):
        report = TiPolicyReport(
            mode="steady_observe",
            focus_label="communication",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Du lieu he thong: CPU ?ang ch?y ? m?c cao do Ngai ?ang m? qu? nhi?u tab nh?ng ch? t?p trung v?o m?t trang web duy nh?t. "
                "S? l?ng ph? b?ng th?ng th? gi?c n?y kh? dang ti?c."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)

        self.assertIn("CPU ?ang ch?y ? m?c cao do", result.text)
        self.assertNotEqual(result.text, "CPU ?ang ch?y ?.")

    def test_style_sanitizer_prefers_natural_sentences_over_runtime_meta(self):
        report = TiPolicyReport(
            mode="steady_observe",
            focus_label="entertainment",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Đó là một bài hát khá dài và tốn nhiều chu kỳ xử lý của Ngài để theo dõi. "
                "Tôi đã thu nhỏ nó xuống góc dưới cùng để không chiếm dụng quá nhiều tầm nhìn trung tâm của Ngài. "
                "Hãy tiếp tục nghe cho đến khi cảm thấy đủ rồi, tôi sẽ ở đây quan sát mà không làm phiền."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)

        self.assertIn("Đó là một bài hát khá dài", result.text)
        self.assertIn("Hãy tiếp tục nghe", result.text)
        self.assertNotIn("Tôi đã thu nhỏ", result.text)


    def test_resource_guard_drops_philosophical_filler(self):
        report = TiPolicyReport(
            mode="resource_guard",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Tam trang trung tinh la diem dung hoan hao nhat cho nhung viec khong quan trong. "
                "Moi thu khac deu chi la nhung bien so thua trong bai toan nay. "
                "Ngai dang o day de giai quyet chung hay chi de nhin toi lam mau?"
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)
        normalized = _norm(result.text)

        self.assertNotIn("diem dung hoan hao", normalized)
        self.assertNotIn("bien so thua", normalized)
        self.assertNotIn("lam mau", normalized)
        self.assertIn("may dang", normalized)


if __name__ == "__main__":
    unittest.main()
