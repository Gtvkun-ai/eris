import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.se import SeLens


class SeLensTests(unittest.TestCase):
    def setUp(self):
        self.se_lens = SeLens()

    def test_build_snapshot_preserves_dataset_like_fields(self):
        raw = {
            "captured_at": "14:10",
            "active_window": "VS Code",
            "browser_url": "",
            "browser_tabs": (),
            "open_windows": ("VS Code", "Terminal"),
            "cpu_percent": 18.0,
            "ram_percent": 54.0,
            "mood_score": 50,
            "inferred_pos_x": 0.5,
            "idle_seconds": 120,
            "recent_events": ["build_failed_3x", "traceback_visible"],
            "user_signals": {
                "typing_speed": "low",
                "window_switching": "low",
                "focus_pattern": "stuck",
            },
            "evidence": [
                "build failed 3 times in 4 minutes",
                "traceback is visible in terminal",
            ],
            "claim_style": "soft_grounded",
        }

        snapshot = self.se_lens.build_snapshot(raw)

        self.assertEqual(snapshot.active_app, "VS Code")
        self.assertEqual(snapshot.recent_events, ("build_failed_3x", "traceback_visible"))
        self.assertEqual(snapshot.user_signals.typing_speed, "low")
        self.assertEqual(snapshot.user_signals.window_switching, "low")
        self.assertEqual(snapshot.user_signals.focus_pattern, "stuck")
        self.assertEqual(
            snapshot.evidence,
            (
                "build failed 3 times in 4 minutes",
                "traceback is visible in terminal",
            ),
        )
        self.assertEqual(snapshot.claim_style, "soft_grounded")

        machine_context = snapshot.to_machine_context()
        self.assertEqual(machine_context["time"], "14:10")
        self.assertEqual(machine_context["active_app"], "VS Code")
        self.assertEqual(machine_context["user_signals"]["focus_pattern"], "stuck")

    def test_build_snapshot_derives_machine_context_from_sparse_runtime_fields(self):
        raw = {
            "captured_at": "22:15",
            "active_window": "Netflix - Chrome",
            "browser_url": "https://www.netflix.com/watch/demo",
            "browser_tabs": ("Netflix", "GitHub", "Docs", "Chat"),
            "open_windows": ("Netflix - Chrome", "Discord", "VS Code", "Spotify", "Terminal", "Docs"),
            "cpu_percent": 21.0,
            "ram_percent": 62.0,
            "mood_score": 50,
            "inferred_pos_x": 0.5,
            "idle_seconds": 640,
        }

        snapshot = self.se_lens.build_snapshot(raw)

        self.assertEqual(snapshot.active_window_kind, "entertainment")
        self.assertIn("browser_url_visible", snapshot.recent_events)
        self.assertIn("many_browser_tabs_visible", snapshot.recent_events)
        self.assertEqual(snapshot.user_signals.typing_speed, "zero")
        self.assertEqual(snapshot.user_signals.focus_pattern, "passive_consumption")
        self.assertTrue(snapshot.evidence)
        self.assertEqual(snapshot.claim_style, "soft_grounded")

        formatted = self.se_lens.format_snapshot(snapshot)
        self.assertIn("recent_events", formatted)
        self.assertIn("user_signals", formatted)
        self.assertIn("claim_style", formatted)

    def test_format_directive_snapshot_uses_soft_background_cues(self):
        raw = {
            "captured_at": "22:15",
            "active_window": "Godot Engine",
            "active_app": "Godot Engine",
            "browser_tabs": ("Docs", "GitHub", "Discord", "YouTube", "Mail"),
            "open_windows": (
                "Godot Engine",
                "VS Code",
                "Terminal",
                "Discord",
                "Chrome",
                "Spotify",
                "Explorer",
                "Settings",
                "Notion",
                "Paint",
            ),
            "idle_seconds": 90,
            "cpu_percent": 14.0,
            "ram_percent": 42.0,
            "mood_score": 50,
            "inferred_pos_x": 0.5,
        }

        snapshot = self.se_lens.build_snapshot(raw)

        formatted = self.se_lens.format_directive_snapshot(snapshot)

        self.assertIn("Ambient cues from runtime", formatted)
        self.assertIn("room_feel:", formatted)
        self.assertIn("human_rhythm:", formatted)
        self.assertIn("claim_style", formatted)
        self.assertIn("visible_context:", formatted)
        self.assertNotIn("some movement", formatted)
        self.assertNotIn("open_windows", formatted)
        self.assertNotIn("browser_tabs", formatted)
        self.assertNotIn("typing=", formatted)
        self.assertNotIn("window_switching", formatted)
        self.assertNotIn("10 windows are open", formatted)

    def test_directive_snapshot_includes_only_concrete_screen_facts(self):
        raw = {
            "captured_at": "14:10",
            "active_window": "VS Code",
            "browser_url": "",
            "browser_tabs": (),
            "open_windows": ("VS Code", "Terminal"),
            "cpu_percent": 18.0,
            "ram_percent": 54.0,
            "mood_score": 50,
            "inferred_pos_x": 0.5,
            "idle_seconds": 120,
            "recent_events": ["build_failed_3x", "traceback_visible"],
            "user_signals": {
                "typing_speed": "low",
                "window_switching": "low",
                "focus_pattern": "stuck",
            },
            "evidence": [
                "build failed 3 times in 4 minutes",
                "traceback is visible in terminal",
            ],
            "claim_style": "soft_grounded",
        }

        snapshot = self.se_lens.build_snapshot(raw)
        formatted = self.se_lens.format_directive_snapshot(snapshot)

        self.assertIn("screen_facts", formatted)
        self.assertIn("build_failed_3x", formatted)
        self.assertIn("traceback is visible in terminal", formatted)
        self.assertNotIn("2 windows are open", formatted)

    def test_directive_snapshot_reads_vision_facts_without_polluting_recent_events(self):
        raw = {
            "captured_at": "14:10",
            "active_window": "VS Code",
            "recent_events": ["general_window_active"],
            "evidence": ["active window is VS Code"],
            "vision_facts": ["terminal shows traceback"],
        }

        snapshot = self.se_lens.build_snapshot(raw)
        formatted = self.se_lens.format_directive_snapshot(snapshot)

        self.assertEqual(snapshot.recent_events, ("general_window_active",))
        self.assertEqual(snapshot.vision_facts, ("terminal shows traceback",))
        self.assertIn("screen_facts", formatted)
        self.assertIn("terminal shows traceback", formatted)

    def test_high_resources_remain_raw_telemetry_not_behavior_cues(self):
        raw = {
            "captured_at": "22:15",
            "active_window": "Godot Engine",
            "active_app": "Godot Engine",
            "browser_tabs": (),
            "open_windows": ("Godot Engine",),
            "idle_seconds": 3,
            "cpu_percent": 98.0,
            "ram_percent": 97.0,
            "mood_score": 50,
            "inferred_pos_x": 0.5,
        }

        snapshot = self.se_lens.build_snapshot(raw)
        formatted = self.se_lens.format_directive_snapshot(snapshot)

        self.assertEqual(snapshot.cpu_percent, 98.0)
        self.assertEqual(snapshot.ram_percent, 97.0)
        self.assertNotIn("resource_pressure", snapshot.recent_events)
        self.assertFalse(any("cpu usage is elevated" in item for item in snapshot.evidence))
        self.assertFalse(any("ram usage is elevated" in item for item in snapshot.evidence))
        self.assertNotIn("resources look tight", formatted)


if __name__ == "__main__":
    unittest.main()
