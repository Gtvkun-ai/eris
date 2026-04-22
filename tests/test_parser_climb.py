import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from domain import Decision
from parser_grounding import DecisionParser


class DecisionParserClimbTests(unittest.TestCase):
    def setUp(self):
        self.parser = DecisionParser(Decision(text="fallback", animation="stand"))

    def test_salvaged_wall_climb_text_uses_climb_animation(self):
        decision = self.parser.parse("ERIS: toi se leo tuong de len tren")

        self.assertEqual(decision.animation, "climb")

    def test_reaching_top_edge_uses_climb_top_animation(self):
        decision = self.parser.parse("ERIS: toi da leo len mep tren, den dinh cao nhat roi")

        self.assertEqual(decision.animation, "climb_top")

    def test_climb_to_top_middle_builds_multi_step_sequence(self):
        decision = self.parser.parse("ERIS: leo len tren dinh mep giua di")

        self.assertEqual(decision.animation, "climb")
        self.assertEqual(decision.next_animation, "climb_top")
        self.assertEqual(decision.target_x, 0.5)

    def test_climb_to_top_and_hold_without_middle_keeps_top_sequence(self):
        decision = self.parser.parse("ERIS: leo len mep dinh roi dung lai")

        self.assertEqual(decision.animation, "climb")
        self.assertEqual(decision.next_animation, "climb_top")
        self.assertEqual(decision.target_x, -1.0)

    def test_embodied_command_suppresses_roleplay_text_when_salvaged(self):
        raw = (
            "Dinh cua he thong la trang thai tap trung tuyet doi vao mot muc tieu duy nhat. "
            "Viec leo len do doi hoi nang luong lon va su kien nhan."
        )
        decision = self.parser.parse(raw, user_hint="leo len dinh o giua di")

        self.assertEqual(decision.text, "")
        self.assertEqual(decision.animation, "climb")
        self.assertEqual(decision.next_animation, "climb_top")
        self.assertEqual(decision.target_x, 0.5)

    def test_regular_climb_does_not_promote_to_climb_top(self):
        decision = self.parser.parse("ERIS: toi dang climb sang ben phai tren tuong")

        self.assertEqual(decision.animation, "climb")

    def test_reverse_climb_down_stays_climb(self):
        decision = self.parser.parse("ERIS: toi leo nguoc lai xuong duoi ben trai cua tuong")

        self.assertEqual(decision.animation, "climb")

    def test_drop_from_climb_to_left_uses_air_swing_l(self):
        decision = self.parser.parse("ERIS: toi dang climb ben trai roi buong tay roi xuong")

        self.assertEqual(decision.animation, "air_swing_l")

    def test_drop_from_climb_to_right_uses_air_swing_r(self):
        decision = self.parser.parse("ERIS: toi dang climb sang ben phai va tha ra roi rot xuong")

        self.assertEqual(decision.animation, "air_swing_r")


if __name__ == "__main__":
    unittest.main()
