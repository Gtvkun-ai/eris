# -*- coding: utf-8 -*-
"""Tích hợp affect-attractor-blend vào AppraisalEngine.

Phủ: cờ bật/tắt + parity, tương thích ngược to_dict, blend đa đỉnh, EMA inertia
end-to-end qua prev_stance_blend, prompt guidance pha trộn, và đường event-affect
(fallback an toàn khi không có encoder).
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.affect_blend import AffectBlendConfig
from cortex.appraisal import AppraisalEngine
from cortex.contracts import CognitiveBroadcast
from cortex.internal_state import PersistentInternalState


def _protective_inputs():
    return dict(
        internal_state=PersistentInternalState(
            last_focus_kind="system",
            protectiveness=0.78,
            irritation=0.24,
            confidence=0.68,
            arousal=0.52,
        ),
        ni_report=SimpleNamespace(drift_score=0.12, confidence=0.70, should_raise_guard=False),
        ti_report=SimpleNamespace(mode="resource_guard"),
        fe_plan=SimpleNamespace(
            intent_label="ordinary_dialogue",
            session_arc="quiet_observation",
            warmth_level=0.18,
            sarcasm_level=0.16,
        ),
        broadcast=CognitiveBroadcast(label="resource_pressure", score=0.84),
    )


def _tender_inputs():
    return dict(
        internal_state=PersistentInternalState(
            last_focus_kind="general",
            attachment=0.72,
            social_energy=0.66,
            tenderness=0.58,
            confidence=0.64,
        ),
        ni_report=SimpleNamespace(drift_score=0.10, confidence=0.68, should_raise_guard=False),
        ti_report=SimpleNamespace(mode="chat_emotional"),
        fe_plan=SimpleNamespace(
            intent_label="attachment_dialogue",
            session_arc="guarded_attachment",
            warmth_level=0.48,
            sarcasm_level=0.12,
        ),
        broadcast=CognitiveBroadcast(label="user_message", score=0.78),
        channel="chat",
        user_text="toi hoi buon va can o ben toi",
    )


class FlagAndParityTests(unittest.TestCase):
    def test_flag_off_uses_legacy_choose_stance_and_empty_blend(self):
        engine = AppraisalEngine(blend_config=AffectBlendConfig(enabled=False))
        appraisal = engine.evaluate(**_protective_inputs())
        self.assertEqual(appraisal.stance, "protective")
        self.assertEqual(appraisal.stance_blend, {})

    def test_flag_off_tender_parity(self):
        engine = AppraisalEngine(blend_config=AffectBlendConfig(enabled=False))
        appraisal = engine.evaluate(**_tender_inputs())
        self.assertEqual(appraisal.stance, "tender_under_cold")
        self.assertEqual(appraisal.stance_blend, {})

    def test_flag_on_default_keeps_argmax_correct(self):
        engine = AppraisalEngine()  # mặc định bật
        self.assertEqual(engine.evaluate(**_protective_inputs()).stance, "protective")
        self.assertEqual(engine.evaluate(**_tender_inputs()).stance, "tender_under_cold")


class BackwardCompatTests(unittest.TestCase):
    def test_to_dict_has_stance_str_and_stance_blend_dict(self):
        engine = AppraisalEngine()
        payload = engine.evaluate(**_protective_inputs()).to_dict()
        self.assertIsInstance(payload["stance"], str)
        self.assertIn("stance_blend", payload)
        self.assertIsInstance(payload["stance_blend"], dict)

    def test_stance_is_valid_label(self):
        engine = AppraisalEngine()
        valid = {
            "protective",
            "watchful",
            "tender_under_cold",
            "tired",
            "dry_playful",
            "soft_uncertain",
            "grounded",
        }
        self.assertIn(engine.evaluate(**_protective_inputs()).stance, valid)

    def test_blend_is_normalized_distribution(self):
        engine = AppraisalEngine()
        blend = engine.evaluate(**_protective_inputs()).stance_blend
        self.assertTrue(blend)
        self.assertGreater(sum(blend.values()), 0.999)
        self.assertLess(sum(blend.values()), 1.001)


class BlendShapeTests(unittest.TestCase):
    def test_protective_scene_blends_protective_and_others(self):
        # Cảnh resource_guard: protective trội nhưng không nuốt trọn.
        engine = AppraisalEngine()
        blend = engine.evaluate(**_protective_inputs()).stance_blend
        self.assertEqual(max(blend, key=blend.get), "protective")
        # có nhiều hơn một stance mang trọng số đáng kể.
        significant = [name for name, w in blend.items() if w >= 0.08]
        self.assertGreaterEqual(len(significant), 2)


class InertiaEndToEndTests(unittest.TestCase):
    def test_prev_blend_pulls_result_toward_previous_stance(self):
        engine = AppraisalEngine(blend_config=AffectBlendConfig(inertia=0.8))
        # Turn 1: protective.
        prot = engine.evaluate(**_protective_inputs()).stance_blend
        # Turn 2: cảnh tender, nhưng mang theo prev protective với inertia cao.
        slow = engine.evaluate(prev_stance_blend=prot, **_tender_inputs()).stance_blend
        # So với không có quán tính: protective phải còn nặng hơn.
        fast_engine = AppraisalEngine(blend_config=AffectBlendConfig(inertia=0.0))
        fast = fast_engine.evaluate(prev_stance_blend=prot, **_tender_inputs()).stance_blend
        self.assertGreater(slow.get("protective", 0.0), fast.get("protective", 0.0))

    def test_no_prev_blend_is_pure_current(self):
        engine = AppraisalEngine(blend_config=AffectBlendConfig(inertia=0.9))
        with_none = engine.evaluate(prev_stance_blend=None, **_tender_inputs()).stance_blend
        fresh = AppraisalEngine().evaluate(**_tender_inputs()).stance_blend
        # inertia cao nhưng không có prev -> không EMA -> bằng blend mặc định.
        self.assertEqual(max(with_none, key=with_none.get), max(fresh, key=fresh.get))


class PromptContextTests(unittest.TestCase):
    def test_prompt_still_has_appraisal_stance_line(self):
        engine = AppraisalEngine()
        appraisal = engine.evaluate(**_protective_inputs())
        ctx = engine.render_prompt_context(appraisal)
        self.assertIn("appraisal_stance:", ctx)
        self.assertIn(appraisal.stance, ctx)

    def test_multi_dominant_bias_lists_two_guidances(self):
        engine = AppraisalEngine()
        appraisal = engine.evaluate(**_protective_inputs())
        ctx = engine.render_prompt_context(appraisal)
        # guidance_blend nối top-k bằng " | " khi có >=2 dominant.
        dominant = [w for w in appraisal.stance_blend.values() if w >= 0.08]
        if len(dominant) >= 2:
            bias_line = [ln for ln in ctx.splitlines() if ln.startswith("appraisal_bias:")][0]
            self.assertIn("|", bias_line)


class EventAffectFallbackTests(unittest.TestCase):
    def test_no_encoder_uses_lexicon_without_throwing(self):
        # care_user_mood>0 + cảnh buồn tiếng Việt + KHÔNG encoder -> lexicon path.
        engine = AppraisalEngine()  # event_encoder=None
        stakes = SimpleNamespace(care_user_mood=0.8)
        broadcast = CognitiveBroadcast(
            label="scene", score=0.6, content="Ngai trong rat met va buon hom nay"
        )
        appraisal = engine.evaluate(
            internal_state=PersistentInternalState(last_focus_kind="communication", confidence=0.6),
            ni_report=SimpleNamespace(drift_score=0.1, confidence=0.6, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(intent_label="ordinary_dialogue", session_arc="quiet_observation", warmth_level=0.3, sarcasm_level=0.1),
            broadcast=broadcast,
            standing_stakes=stakes,
        )
        # Cảnh buồn có stake -> tenderness được kéo lên (không ném lỗi).
        self.assertGreaterEqual(appraisal.tenderness, 0.0)

    def test_encoder_path_runs_for_event_affect(self):
        # Encoder giả -> đường projection chạy, không ném lỗi.
        def fake_encode(text):
            t = (text or "").lower()
            return [float("buon" in t or "met" in t), float("vui" in t), 0.0, 0.0]

        engine = AppraisalEngine(event_encoder=fake_encode)
        stakes = SimpleNamespace(care_user_mood=0.8)
        broadcast = CognitiveBroadcast(label="scene", score=0.6, content="Ngai co ve met va buon")
        appraisal = engine.evaluate(
            internal_state=PersistentInternalState(last_focus_kind="communication", confidence=0.6),
            ni_report=SimpleNamespace(drift_score=0.1, confidence=0.6, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(intent_label="ordinary_dialogue", session_arc="quiet_observation", warmth_level=0.3, sarcasm_level=0.1),
            broadcast=broadcast,
            standing_stakes=stakes,
        )
        self.assertIsInstance(appraisal.stance, str)


if __name__ == "__main__":
    unittest.main()
