import os
import sys
import unicodedata
import unittest
from types import SimpleNamespace

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

    def test_style_sanitizer_strips_dangling_json_punctuation(self):
        report = TiPolicyReport(
            mode="steady_observe",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text='Co ve moi thu dang chay kha on.",',
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)

        self.assertEqual(result.text, "Co ve moi thu dang chay kha on.")

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

    def test_resource_guard_rewrites_loose_window_metaphor(self):
        report = TiPolicyReport(
            mode="resource_guard",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text="Cửa sổ mở ra thì không ai biết nó sẽ đóng lại lúc nào.",
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)
        normalized = _norm(result.text)

        self.assertNotIn("cua so mo ra", normalized)
        self.assertIn("may dang", normalized)

    def test_resource_guard_keeps_grounded_resource_line(self):
        report = TiPolicyReport(
            mode="resource_guard",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text="Máy đang căng rồi, tôi nói gọn thôi.",
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)

        self.assertEqual(result.text, "Máy đang căng rồi, tôi nói gọn thôi.")

    def test_chat_general_keeps_two_natural_sentences_without_default_truncation(self):
        decision = Decision(
            text=(
                "Nghe như Ngài đang thử xem tôi có né câu hỏi này không. "
                "Tôi không né, chỉ là tôi muốn trả lời thẳng hơn một chút."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, self.report)

        self.assertIn("Nghe như Ngài đang thử", result.text)
        self.assertIn("Tôi không né", result.text)

    def test_editor_only_removes_heavy_meta_sentence_and_keeps_natural_parts(self):
        report = TiPolicyReport(
            mode="steady_observe",
            focus_label="general",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Ngài mở quá nhiều tab thật. "
                "Đây là một cấu trúc quản lý nhịp độ khá méo và tạo ra kết quả hữu ích rất đáng ngờ. "
                "Giữ lại một thứ đáng làm trước đã."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)
        normalized = _norm(result.text)

        self.assertIn("ngai mo qua nhieu tab that", normalized)
        self.assertIn("giu lai mot thu dang lam truoc da", normalized)
        self.assertNotIn("cau truc quan ly", normalized)
        self.assertNotIn("ket qua huu ich", normalized)

    def test_focus_guard_rewrites_productivity_mindreading(self):
        report = TiPolicyReport(
            mode="focus_guard",
            focus_label="coding",
            reason="test",
            prompt_context="",
        )
        decision = Decision(
            text=(
                "Ngai dang go kha nhieu nhung van chua chot duoc y chinh. "
                "Toi chi muon nhac Ngai dung lam viec qua cang thang ma quen muc tieu cuoi cung."
            ),
            animation="stand",
        )

        result = self.governor.enforce_decision(decision, report)
        normalized = _norm(result.text)

        self.assertNotIn("chua chot", normalized)
        self.assertNotIn("cang thang", normalized)
        self.assertNotIn("muc tieu cuoi cung", normalized)
        self.assertIn("chi nhin boi canh", normalized)
        self.assertIn("khoi cham diem", normalized)

    def test_autonomous_code_context_stays_ambient_not_focus_guard(self):
        snapshot = SimpleNamespace(
            active_window_kind="coding",
            focus_summary="coding workspace",
            idle_seconds=4.0,
            cpu_percent=35.0,
            ram_percent=58.0,
            inferred_pos_x=0.5,
        )
        ni_report = SimpleNamespace(
            should_raise_guard=True,
            drift_score=0.88,
            drift_level="cao",
        )

        report = self.governor.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=ni_report,
            ni_state_label="OFF_GOAL",
            ni_state_streak=8,
            idle_cycles=1,
            last_text="",
        )

        self.assertEqual(report.mode, "steady_observe")
        self.assertNotIn("attention_drift", report.prompt_context)
        self.assertNotIn("focus_guard", report.prompt_context)
        self.assertIn("không nhắc tập trung", report.prompt_context)

    def test_autonomous_ignores_resource_pressure_for_max_throughput(self):
        snapshot = SimpleNamespace(
            active_window_kind="general",
            focus_summary="general",
            idle_seconds=3.0,
            cpu_percent=98.0,
            ram_percent=97.0,
            inferred_pos_x=0.5,
        )

        report = self.governor.evaluate_autonomous(
            snapshot=snapshot,
            ni_report=None,
            idle_cycles=1,
            last_text="",
        )

        self.assertEqual(report.mode, "steady_observe")
        self.assertEqual(report.animation_hint, "stand")
        self.assertFalse(report.force_animation)
        self.assertTrue(report.allow_idle_variation)
        self.assertNotIn("resource", report.prompt_context.lower())


if __name__ == "__main__":
    unittest.main()
