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
            '{"text":"Toi da khoa man hinh va ngat mang cua Ngai.",'
            '"animation":"read","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"secret","next_animation":"","system_action":"","action_input":""}'
        )
        decision = self.parser.parse(raw, user_hint="ban ac qua")

        self.assertIn("khoe quyen luc", _norm(decision.text))
        self.assertEqual(decision.extracted_fact, "")

    def test_salvages_non_json_text(self):
        decision = self.parser.parse("ERIS: toi da monitor code cua du an nay roi")

        self.assertEqual(decision.animation, "read")

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
        self.assertEqual(decision.animation, "stand_walk")
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
            '{"text":"Toi da ghi nhan rang Ngai muon nghi ngoi.","animation":"idle",'
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

    def test_rewrites_overmanaged_language_into_more_natural_text(self):
        raw = (
            '{"text":"Do la mot tap hop cac tien trinh dang chay nhung thieu su dong bo hoa nhip do. '
            'Hay dung lai va chon mot phan mem duy nhat de tuong tac trong vong ba phut toi, toi se ngung theo doi cac tien trinh phu do.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertNotIn("dong bo hoa nhip do", normalized)
        self.assertNotIn("phan mem duy nhat", normalized)
        self.assertNotIn("ba phut", normalized)
        self.assertIn("giu lai mot", normalized)

    def test_rewrites_philosophical_resource_guard_style(self):
        raw = (
            '{"text":"Tam trang trung tinh la diem dung hoan hao nhat cho nhung viec khong quan trong. '
            'Moi thu khac deu chi la nhung bien so thua trong bai toan nay. '
            'Ngai dang o day de giai quyet chung hay chi de nhin toi lam mau?",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertNotIn("diem dung hoan hao", normalized)
        self.assertNotIn("bien so thua", normalized)
        self.assertNotIn("lam mau", normalized)
        self.assertTrue("may dang" in normalized or "dung yen qua lau" in normalized)

    def test_repair_sentence_boundaries_does_not_split_before_ngai(self):
        repaired = self.parser._repair_sentence_boundaries(
            "Hay dong no di de toi co the tap trung vao Ngai hon."
        )

        self.assertEqual(repaired, "Hay dong no di de toi co the tap trung vao Ngai hon.")

    def test_parse_keeps_possessive_ngai_phrase_intact(self):
        raw = (
            '{"text":"Cua so YouTube dang chiem dung mot luong lon bang thong thi giac va lam giam toc do doc hieu cua Ngai. '
            'Hay dong no di de toi co the tap trung vao cac doan code con lai.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":"","system_action":"","action_input":""}'
        )

        decision = self.parser.parse(raw)
        normalized = _norm(decision.text)

        self.assertIn("doc hieu cua ngai", normalized)
        self.assertNotIn("doc hieu cua . ngai", normalized)


if __name__ == "__main__":
    unittest.main()
