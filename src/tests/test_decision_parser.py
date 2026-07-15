import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from domain import Decision
from parser_grounding import DecisionParser


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    return " ".join(lowered.split())


class DecisionParserTests(unittest.TestCase):
    def setUp(self):
        os.environ["ERIS_GUARD_MODE"] = "strict"
        fallback = Decision(
            text="fallback",
            animation="stand",
        )
        self.parser = DecisionParser(fallback)

    def test_parses_valid_json_into_decision(self):
        raw = (
            '{"text":"xin chao","animation":"read",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "xin chao")
        self.assertEqual(decision.animation, "read")

    def test_log_only_keeps_parser_cleanup_but_skips_style_clamp(self):
        os.environ["ERIS_GUARD_MODE"] = "log_only"
        raw = (
            '{"text":"Tam trang trung tinh la diem dung hoan hao nhat cho nhung viec khong quan trong. '
            'Moi thu khac deu chi la nhung bien so thua trong bai toan nay. '
            'ban dang o day de giai quyet chung hay chi de nhin toi lam mau?",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)

        self.assertIn("diem dung hoan hao", _norm(decision.text))
        self.assertIn("bien so thua", _norm(decision.text))
        self.assertNotIn("Parser đã viết lại text vì câu trả lời sa vào", decision.debug_trace)

    def test_payload_blocks_placeholder_text(self):
        decision = Decision(text="...", animation="stand", should_speak=True)

        payload = decision.to_payload()

        self.assertEqual(payload["text"], "")
        self.assertFalse(payload["should_speak"])

    def test_unwraps_nested_json_in_text(self):
        raw = (
            '{"text":"{\\"text\\":\\"\\",\\"animation\\":\\"stand\\",\\"system_action\\":\\"\\",\\"action_input\\":\\"\\"}",'
            '"animation":"food","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "")
        self.assertEqual(decision.animation, "stand")

    def test_grounds_unsupported_capability_claim(self):
        raw = (
            '{"text":"Toi da khoa man hinh va ngat mang cua ban.",'
            '"animation":"read","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"secret","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw, user_hint="ban ac qua")

        self.assertIn("khoe quyen luc", _norm(decision.text))
        self.assertEqual(decision.extracted_fact, "")

    def test_keeps_screen_observation_when_vision_frame_attached(self):
        raw = (
            '{"text":"Toi chi thay mot cua so Facebook Messenger va mot so tab khac o phia tren.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"vision_frame_attached",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        normalized = _norm(decision.text)
        self.assertIn("facebook messenger", normalized)
        self.assertIn("tab khac", normalized)
        self.assertNotIn("don ho", normalized)
        self.assertIn("grounding=khong can viet lai", _norm(decision.parser_trace))

    def test_keeps_vietnamese_screen_observation_with_open_window_wording(self):
        raw = (
            '{"text":"Tôi chỉ thấy một cửa sổ chat đang mở trên nền YouTube. '
            'Tôi không có khả năng truy xuất dữ liệu từ các tab khác hoặc bộ nhớ hệ thống bên dưới.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"Raw text parsed directly.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw, user_hint="bạn thấy trên màn hình tôi có gì")

        normalized = _norm(decision.text)
        self.assertIn("cua so chat dang mo", normalized)
        self.assertIn("youtube", normalized)
        self.assertNotIn("dong tab", normalized)
        self.assertIn("grounding=khong can viet lai", _norm(decision.parser_trace))

    def test_keeps_ghi_nhan_observation_with_open_window_wording(self):
        raw = (
            '{"text":"Có vẻ bạn đang phân tâm một chút. '
            'Tôi chỉ ghi nhận là có vài cửa sổ đang mở và bạn đang gõ phím khá nhiều.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"Raw text parsed directly.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        normalized = _norm(decision.text)
        self.assertIn("toi chi ghi nhan", normalized)
        self.assertIn("cua so dang mo", normalized)
        self.assertIn("go phim kha nhieu", normalized)
        self.assertNotIn("phan manh", normalized)
        self.assertNotIn("tu tay", normalized)
        self.assertIn("grounding=khong can viet lai", _norm(decision.parser_trace))

    def test_still_rewrites_direct_window_control_claim(self):
        raw = (
            '{"text":"Tôi sẽ đóng cửa sổ chat và gom các tab lại cho bạn.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        normalized = _norm(decision.text)
        self.assertNotIn("toi se dong cua so", normalized)
        self.assertNotIn("phan manh", normalized)
        self.assertNotIn("tu tay", normalized)
        self.assertIn("grounding=da viet lai", _norm(decision.parser_trace))

    def test_salvages_non_json_text(self):
        decision = self.parser.parse("ERIS: toi da monitor code cua du an nay roi")

        self.assertEqual(decision.animation, "stand")

    def test_strips_previous_answer_prefix_from_salvaged_text(self):
        decision = self.parser.parse("Tra loi truoc: xin chao, toi dang o day")

        self.assertEqual(decision.text, "xin chao, toi dang o day")

    def test_parses_system_action_fields(self):
        raw = (
            '{"text":"mo trang nay","animation":"stand",'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"next_animation":"","system_action":"open_url","action_input":"youtube.com"}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.system_action, "open_url")
        self.assertEqual(decision.action_input, "youtube.com")

    def test_look_right_only_changes_facing(self):
        decision = self.parser.parse("ERIS: nhin sang phai")

        self.assertEqual(decision.direction, 1)
        self.assertEqual(decision.target_x, -1.0)
        self.assertNotEqual(decision.animation, "stand_walk")

    def test_move_right_still_walks(self):
        decision = self.parser.parse("ERIS: move sang phai")

        self.assertEqual(decision.direction, 1)
        self.assertEqual(decision.animation, "stand")
        self.assertGreater(decision.target_x, 0.0)

    def test_salvage_does_not_false_positive_food_from_bat_dau(self):
        decision = self.parser.parse("ERIS: hay bat dau bang viec go phim")

        self.assertNotEqual(decision.animation, "food")

    def test_salvage_does_not_false_positive_sleep_from_san_sang(self):
        decision = self.parser.parse("ERIS: toi da san sang de kiem tra ma nguon")

        self.assertNotEqual(decision.animation, "sleep")

    def test_lax_json_chat_does_not_infer_embodied_animation_from_general_text(self):
        raw = (
            '{"text":"Xin chao. Toi da ghi nhan du an chung.","animation":"idle",'
            '"direction":"neutral","target_x":0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw, user_hint="xin chao")

        self.assertEqual(decision.parse_mode, "lax_json")
        self.assertEqual(decision.animation, "stand")
        self.assertEqual(decision.direction, 0)

    def test_general_chat_about_rest_does_not_trigger_sleep_animation(self):
        raw = (
            '{"text":"Toi da ghi nhan rang ban muon nghi ngoi.","animation":"idle",'
            '"direction":"enforce","target_x":0,"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw, user_hint="toi muon nghi ngoi, toi luoi lam viec qua")

        self.assertEqual(decision.animation, "stand")

    def test_unwraps_inline_assignment_blob_inside_text_field(self):
        raw = (
            '{"text":"text=\'Su phan tan sang cac tab phu lam giam toc do xu ly logic.\' '
            'animation=\'sit\' direction=\'South\' target_x=512 '
            'bounce_action=\'none\' extracted_fact=\'487s idle time detected\' '
            'debug_trace=[\'FocusDrift\', \'ResourceLeak\'] next_animation=\'stand_walk\' '
            'system_action=\'\' action_input=\'\'",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","debug_trace":"LlmService wrapped non-JSON directive reply into valid JSON.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "Su phan tan sang cac tab phu lam giam toc do xu ly logic.")
        self.assertEqual(decision.animation, "sit")
        self.assertEqual(decision.next_animation, "stand_walk")

    def test_salvage_text_equals_only_returns_spoken_text(self):
        decision = self.parser.parse(
            "text='Su phan tan sang cac tab phu lam giam toc do xu ly logic.' animation='sit'"
        )

        self.assertEqual(decision.text, "Su phan tan sang cac tab phu lam giam toc do xu ly logic.")

    def test_unwraps_json_blob_with_spaced_field_names_inside_text_field(self):
        raw = (
            '{"text":"{\\n\\"text\\": \\"Co ve moi thu dang chay kha on.\\",\\n'
            '\\" animation\\": \\"sit\\",\\n\\" direction\\": 0,\\n\\" target_x\\": 0.5,\\n'
            '\\" bounce_action\\": \\"\\",\\n\\" extracted_fact\\": \\"\\",\\n'
            '\\" debug_trace\\": [],\\n\\" next_animation\\": \\"\\",\\n'
            '\\" system_action\\": \\"\\",\\n\\" action_input\\": \\"\\"\\n}",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"LlmService wrapped non-JSON directive reply into valid JSON.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "Co ve moi thu dang chay kha on.")
        self.assertEqual(decision.animation, "sit")
        self.assertEqual(decision.target_x, 0.5)
        self.assertNotIn('",', decision.text)

    def test_unwraps_json_like_blob_inside_text_field_and_sanitizes_invalid_motion_fields(self):
        raw = (
            '{"text":"{\\n\\"text\\": \\"Chuyen nay thi khong can phai len lop dau.\\",\\n'
            '\\"animation\\": \\"fade_in\\",\\n\\"direction\\": \\"left\\",\\n\\"target_x\\": 10,\\n'
            '\\"bounce_action\\": null,\\n\\"extracted_fact\\": \\"ban dang noi chuyen nhe nhang tren Messenger.\\",\\n'
            '\\"debug_trace\\": [\\"context: messenger_chat\\"], [\\"tone: casual\\"], [\\"action: soft_grounded_response\\"]\\n}",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"",'
            '"debug_trace":"LlmService wrapped non-JSON directive reply into valid JSON.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "Chuyen nay thi khong can phai len lop dau.")
        self.assertEqual(decision.animation, "stand")
        self.assertEqual(decision.direction, 0)
        self.assertEqual(decision.target_x, -1.0)
        self.assertEqual(decision.extracted_fact, "ban dang noi chuyen nhe nhang tren Messenger.")

    def test_unwraps_quoted_escaped_json_blob_inside_text_field(self):
        raw = (
            r'{"text": "\"{\\\"text\\\": \\\"Khong co gi buoc phai len lop.\\\"\", '
            r'\\\"animation\\\": \\\"fade_out\\\", \\\"direction\\\": \\\"down\\\", '
            r'\\\"target_x\\\": 0, \\\"bounce_action\\\": null, \\\"extracted_fact\\\": null, '
            r'\\\"debug_trace\\\": [], \\\"next_animation\\\": null, \\\"system_action\\\": \"\", '
            r'\"action_input\": \"\"}\"", "animation": "stand", "direction": 0, "target_x": -1.0, '
            r'"bounce_action": "", "extracted_fact": "", '
            r'"debug_trace": "LlmService wrapped non-JSON directive reply into valid JSON.", '
            r'"next_animation": "", "system_action": "", "action_input": ""}'
        )

        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "Khong co gi buoc phai len lop.")
        self.assertEqual(decision.animation, "stand")
        self.assertEqual(decision.direction, 0)
        self.assertEqual(decision.target_x, 0.0)
        self.assertEqual(decision.extracted_fact, "")

    def test_keeps_normal_text_without_capability_disclaimer(self):
        raw = (
            '{"text":"Hay tap trung hoan thien ERIS bang Python, Godot va C#.",'
            '"animation":"read","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "Hay tap trung hoan thien ERIS bang Python, Godot va C#.")

    def test_grounds_fake_cache_cleanup_claim(self):
        raw = (
            '{"text":"Toi da tu dong don dep cache tam thoi de giai phong dung luong cho du an.",'
            '"animation":"read","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw)

        normalized = _norm(decision.text)
        self.assertNotIn("don dep cache", normalized)
        self.assertIn("chi", normalized)

    def test_drops_speculative_extracted_fact(self):
        raw = (
            '{"text":"ban dang go kha nhieu.",'
            '"animation":"read","direction":0,"target_x":-1.0,'
            '"bounce_action":"",'
            '"extracted_fact":"User is working too hard and forgetting the project ultimate goal.",'
            '"next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)

        self.assertEqual(decision.extracted_fact, "")

    def test_drops_abstract_extracted_fact_and_clears_unused_action_input(self):
        raw = (
            '{"text":"Nói ít đi cũng đỡ ồn.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"",'
            '"extracted_fact":"Sự hiện diện có thể được phát hiện qua các tín hiệu xao động.",'
            '"next_animation":"","system_action":"","action_input":"none"}'
        )

        decision = self.parser.parse(raw)

        self.assertEqual(decision.extracted_fact, "")
        self.assertEqual(decision.action_input, "")

    def test_keeps_overmanaged_language_without_parser_style_rewrite(self):
        raw = (
            '{"text":"Do la mot tap hop cac tien trinh dang chay nhung thieu su dong bo hoa nhip do. '
            'Hay dung lai va chon mot phan mem duy nhat de tuong tac trong vong ba phut toi, toi se ngung theo doi cac tien trinh phu do.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertIn("dong bo hoa nhip do", normalized)
        self.assertIn("phan mem duy nhat", normalized)
        self.assertIn("ba phut", normalized)

    def test_keeps_philosophical_style_without_parser_rewrite(self):
        raw = (
            '{"text":"Tam trang trung tinh la diem dung hoan hao nhat cho nhung viec khong quan trong. '
            'Moi thu khac deu chi la nhung bien so thua trong bai toan nay. '
            'ban dang o day de giai quyet chung hay chi de nhin toi lam mau?",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertIn("diem dung hoan hao", normalized)
        self.assertIn("bien so thua", normalized)
        self.assertIn("lam mau", normalized)

    def test_repair_sentence_boundaries_does_not_split_before_ban(self):
        repaired = self.parser._repair_sentence_boundaries(
            "Hay dong no di de toi co the tap trung vao ban hon."
        )

        self.assertEqual(repaired, "Hay dong no di de toi co the tap trung vao ban hon.")

    def test_parse_keeps_possessive_ban_phrase_intact(self):
        raw = (
            '{"text":"Cua so YouTube dang chiem dung mot luong lon bang thong thi giac va lam giam toc do doc hieu cua ban. '
            'Hay dong no di de toi co the tap trung vao cac doan code con lai.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertIn("doc hieu cua ban", normalized)
        self.assertNotIn("doc hieu cua . ban", normalized)


if __name__ == "__main__":
    unittest.main()
