import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from domain import Decision
from parser_grounding import DecisionParser


class DecisionParserTests(unittest.TestCase):
    def setUp(self):
        fallback = Decision(
            text="fallback",
            animation="stand",
        )
        self.parser = DecisionParser(fallback)

    def test_parses_valid_json_into_decision(self):
        raw = (
            '{"text":"xin chao","animation":"read","productivity":1,'
            '"direction":0,"target_x":-1.0,"bounce_action":"","extracted_fact":"",'
            '"next_animation":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "xin chao")
        self.assertEqual(decision.animation, "read")
        self.assertEqual(decision.productivity, 1)

    def test_unwraps_nested_json_in_text(self):
        raw = (
            '{"text":"{\\"text\\":\\"\\",\\"animation\\":\\"stand\\"}",'
            '"animation":"food","productivity":0,"direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"","next_animation":""}'
        )
        decision = self.parser.parse(raw)

        self.assertEqual(decision.text, "")
        self.assertEqual(decision.animation, "stand")

    def test_grounds_unsupported_capability_claim(self):
        raw = (
            '{"text":"Tôi đã khóa màn hình và ngắt mạng của Ngài.",'
            '"animation":"read","productivity":-1,"direction":0,"target_x":-1.0,'
            '"bounce_action":"","extracted_fact":"secret","next_animation":""}'
        )
        decision = self.parser.parse(raw, user_hint="bạn ác quá")

        self.assertIn("không có quyền cưỡng chế", decision.text)
        self.assertEqual(decision.extracted_fact, "")

    def test_salvages_non_json_text(self):
        decision = self.parser.parse("ERIS: Tôi đã đọc tài liệu dự án này rồi")

        self.assertEqual(decision.animation, "read")
        self.assertEqual(decision.productivity, 1)


if __name__ == "__main__":
    unittest.main()
