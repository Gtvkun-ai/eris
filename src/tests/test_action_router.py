import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from actions import ActionRouter


class ActionRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = ActionRouter()

    def test_routes_now_playing_questions(self):
        routed = self.router.route_chat("ban thay ten nhac toi dang nghe la gi")
        self.assertEqual(routed, ("get_now_playing", ""))

    def test_routes_now_playing_follow_up_from_previous_action(self):
        routed = self.router.route_chat("nhac tren youtube ay", last_action="get_now_playing")
        self.assertEqual(routed, ("get_now_playing", ""))

    def test_routes_youtube_media_question(self):
        routed = self.router.route_chat("thay nhac toi mo o youtube hay khong")
        self.assertEqual(routed, ("get_now_playing", ""))

    def test_routes_open_url(self):
        routed = self.router.route_chat("mo youtube.com/watch?v=abc")
        self.assertEqual(routed, ("open_url", "youtube.com/watch?v=abc"))

    def test_routes_set_volume(self):
        routed = self.router.route_chat("set volume 35")
        self.assertEqual(routed, ("set_volume", "35"))

    def test_routes_copy_text(self):
        routed = self.router.route_chat("copy hello world")
        self.assertEqual(routed, ("copy_text", "hello world"))

    def test_routes_weather_question_with_full_context(self):
        routed = self.router.route_chat("ngay mai tai Sai Gon quan 10 co thoi tiet nhu nao")
        self.assertEqual(routed, ("get_weather", "ngay mai tai Sai Gon quan 10 co thoi tiet nhu nao"))


if __name__ == "__main__":
    unittest.main()
