import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.se import SeLens


class SeLensTests(unittest.TestCase):
    def setUp(self):
        self.lens = SeLens()

    def test_facebook_is_treated_as_work_communication(self):
        snapshot = self.lens.build_snapshot(
            {
                "active_window": "Facebook - Brave",
                "browser_url": "https://www.facebook.com/messages",
                "browser_tabs": ("Facebook",),
            }
        )

        self.assertEqual(snapshot.active_window_kind, "communication")

    def test_youtube_can_be_treated_as_focus_aid(self):
        snapshot = self.lens.build_snapshot(
            {
                "active_window": "Deep Focus Mix - YouTube - Brave",
                "browser_url": "https://www.youtube.com/watch?v=demo",
                "browser_tabs": ("Deep Focus Mix - YouTube",),
            }
        )

        self.assertEqual(snapshot.active_window_kind, "general")

    def test_coding_context_still_wins_over_media_tab_noise(self):
        snapshot = self.lens.build_snapshot(
            {
                "active_window": "main.py - Visual Studio Code",
                "browser_url": "",
                "browser_tabs": ("Deep Focus Mix - YouTube",),
            }
        )

        self.assertEqual(snapshot.active_window_kind, "coding")


if __name__ == "__main__":
    unittest.main()
