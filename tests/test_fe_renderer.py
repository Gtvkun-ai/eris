import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.contracts import FeStyleMemory, GoalDriftReport, TelemetrySnapshot, TiPolicyReport
from cortex.contracts import FeStylePlan
from cortex.fe import FeRenderer
from cortex.internal_state import PersistentInternalState


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = lowered.replace("Ä‘", "d")
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
        self.state = PersistentInternalState()

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
            internal_state=self.state,
            last_text="",
        )

        self.assertEqual(plan.intent_label, "ordinary_dialogue")

    def test_style_context_uses_compact_tags_instead_of_policy_dump(self):
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
            internal_state=self.state,
            last_text="",
        )

        normalized = _norm(plan.style_context)

        self.assertIn("style_tags:", normalized)
        self.assertIn("tone=cold_soft", normalized)
        self.assertIn("stance=grounded", normalized)
        self.assertIn("attachment=guarded", normalized)
        self.assertIn("avoid: power_language, system_log_voice, policy_dump", normalized)
        self.assertNotIn("sarcasm_level", normalized)

    def test_style_context_carries_recent_response_as_do_not_repeat(self):
        ti_report = TiPolicyReport(
            mode="steady_observe",
            focus_label="coding",
            reason="observe",
            prompt_context="",
        )
        memory = FeStyleMemory(
            last_response_excerpt="Viết code cho một thế giới đang tàn lụi luôn cần chút sự kiên nhẫn.",
            continuity_strength=0.4,
            last_mode="grounded",
        )

        plan = self.renderer.evaluate_autonomous(
            snapshot=self.snapshot_coding,
            ni_report=self.ni_report,
            ti_report=ti_report,
            style_memory=memory,
            internal_state=self.state,
            last_text="",
        )

        normalized = _norm(plan.style_context)
        self.assertIn("do_not_repeat_recent_response", normalized)
        self.assertIn("change the subject", normalized)
        self.assertIn("do not mention that motif again", normalized)

    def test_emotional_chat_shifts_to_comforting_with_high_warmth(self):
        ti_report = TiPolicyReport(
            mode="chat_emotional",
            focus_label="chat",
            reason="emotional",
            prompt_context="",
        )

        plan = self.renderer.evaluate_chat(
            snapshot=self.snapshot_general,
            ni_report=self.ni_report,
            ti_report=ti_report,
            style_memory=self.memory,
            internal_state=self.state,
            user_text="toi hoi buon",
        )

        normalized = _norm(plan.style_context)
        self.assertEqual(plan.mode, "comforting")
        self.assertIn("warmth=high", normalized)
        self.assertIn("stance=comforting", normalized)
        self.assertEqual(plan.session_arc, "guarded_attachment")

    def test_topic_memory_normalizes_vietnamese_attention_drift(self):
        plan = FeStylePlan(
            mode="grounded",
            tone_label="tone=cold_soft; warmth=low; stance=grounded; attachment=guarded",
            style_context="",
            intent_label="ordinary_dialogue",
        )

        memory = self.renderer.remember_style(
            self.memory,
            plan=plan,
            rendered_text="Có vẻ Ngài đang phân tán sự chú ý khá nhiều.",
        )
        memory = self.renderer.remember_style(
            memory,
            plan=plan,
            rendered_text="Có vẻ Ngài đang phân tán một chút.",
        )

        self.assertEqual(memory.repeated_topic_tag, "attention_drift")
        self.assertEqual(memory.repeated_topic_streak, 2)

    def test_internal_state_bias_warms_and_shortens_style(self):
        ti_report = TiPolicyReport(
            mode="steady_observe",
            focus_label="general",
            reason="observe",
            prompt_context="",
        )

        plan = self.renderer.evaluate_autonomous(
            snapshot=self.snapshot_general,
            ni_report=self.ni_report,
            ti_report=ti_report,
            style_memory=self.memory,
            internal_state=PersistentInternalState(
                attachment=0.72,
                tenderness=0.62,
                protectiveness=0.64,
                fatigue=0.44,
            ),
            last_text="",
        )

        self.assertGreater(plan.warmth_level, 0.24)
        self.assertEqual(plan.brevity_bias, "short")
        self.assertTrue(any("internal_state_bias" in item for item in plan.evidence))


if __name__ == "__main__":
    unittest.main()
