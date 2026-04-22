import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import FeStyleMemory, GoalDriftReport, TelemetrySnapshot, TiPolicyReport
from cortex.fe import FeRenderer


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    return " ".join(lowered.split())


class FeRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = FeRenderer()
        self.memory = FeStyleMemory()
        self.snapshot_general = TelemetrySnapshot(
            captured_at="2026-04-07T16:00:00",
            active_window="Browser",
            active_window_kind="general",
            focus_summary="general",
        )
        self.snapshot_coding = TelemetrySnapshot(
            captured_at="2026-04-07T16:00:00",
            active_window="Godot",
            active_window_kind="coding",
            focus_summary="coding",
        )
        self.ni_report = GoalDriftReport(
            similarity=0.8,
            drift_score=0.2,
            drift_level="thap",
            prompt_context="",
        )

    def test_resource_guard_general_stays_ordinary_instead_of_forcing_technical_arc(self):
        ti_report = TiPolicyReport(
            mode="resource_guard",
            focus_label="general",
            reason="resource",
            prompt_context="",
        )

        plan = self.renderer.evaluate_autonomous(
            snapshot=self.snapshot_general,
            ni_report=self.ni_report,
            ti_report=ti_report,
            style_memory=self.memory,
            last_text="",
        )

        self.assertEqual(plan.intent_label, "ordinary_dialogue")

    def test_style_context_pushes_human_not_log_language(self):
        ti_report = TiPolicyReport(
            mode="steady_observe",
            focus_label="general",
            reason="observe",
            prompt_context="",
        )

        plan = self.renderer.evaluate_autonomous(
            snapshot=self.snapshot_coding,
            ni_report=self.ni_report,
            ti_report=ti_report,
            style_memory=self.memory,
            last_text="",
        )

        normalized = _norm(plan.style_context)

        self.assertIn("khong nhu ban log duoc nhan hoa", normalized)
        self.assertIn("dung lap khung cau kieu 'ngai dang..., con toi...'", normalized)


if __name__ == "__main__":
    unittest.main()
