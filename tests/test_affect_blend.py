# -*- coding: utf-8 -*-
"""Tests cho PoC affect_blend (stance mềm + EMA inertia).

Quy ước: unittest + sys.path.insert(src) như các test cortex khác. Phần
property-based (hypothesis) là tuỳ chọn — bỏ qua nếu môi trường không có
hypothesis, để bộ test cốt lõi vẫn chạy.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.affect_blend import (
    AFFECT_AXES,
    STANCE_ANCHORS,
    StanceBlend,
    blend_stance,
    guidance_blend,
    rms_distance,
    soft_assign,
)

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True

    _AXIS_VALUE = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    _AFFECT_STRATEGY = st.fixed_dictionaries({axis: _AXIS_VALUE for axis in AFFECT_AXES})
except Exception:  # pragma: no cover
    HAS_HYPOTHESIS = False


def _is_distribution(weights, *, tol=1e-6):
    if not weights:
        return False
    if any(w < -tol for w in weights.values()):
        return False
    return abs(sum(weights.values()) - 1.0) <= 1e-6


class AffectBlendCoreTests(unittest.TestCase):
    def test_output_is_a_normalized_distribution(self):
        affect = {"threat": 0.8, "protectiveness": 0.8, "fatigue": 0.3}
        blend = blend_stance(affect)
        self.assertTrue(_is_distribution(blend.weights))
        # grounded là baseline -> luôn có mặt cùng các anchor cảm xúc.
        self.assertEqual(set(blend.weights), set(STANCE_ANCHORS) | {"grounded"})

    def test_clearly_protective_affect_picks_protective(self):
        affect = {"threat": 0.85, "protectiveness": 0.85, "tenderness": 0.4}
        blend = blend_stance(affect)
        self.assertEqual(blend.top(), "protective")
        # top() là str -> tương thích ngược với CognitiveAppraisal.stance.
        self.assertIsInstance(blend.top(), str)

    def test_mixed_affect_produces_a_real_blend_not_a_single_winner(self):
        # Vừa che chở, vừa mệt, vừa hơi mềm: đúng cái _choose_stance cũ làm phẳng.
        affect = {
            "threat": 0.6,
            "protectiveness": 0.6,
            "fatigue": 0.6,
            "tenderness": 0.55,
            "intimacy": 0.5,
        }
        blend = blend_stance(affect, temperature=0.22)
        dominant = blend.dominant(k=3)
        names = {name for name, _ in dominant}
        # Có ít nhất 2 stance đáng kể; không stance nào nuốt trọn.
        self.assertGreaterEqual(len(dominant), 2)
        self.assertLess(max(blend.weights.values()), 0.9)
        self.assertTrue({"protective", "tired"} & names)

    def test_lower_temperature_sharpens_distribution(self):
        affect = {"threat": 0.7, "protectiveness": 0.7, "fatigue": 0.45}
        sharp = blend_stance(affect, temperature=0.05)
        soft = blend_stance(affect, temperature=0.5)
        self.assertGreater(max(sharp.weights.values()), max(soft.weights.values()))
        self.assertGreater(soft.entropy(), sharp.entropy())

    def test_anchor_point_is_its_own_argmax(self):
        for name, anchor in STANCE_ANCHORS.items():
            blend = blend_stance(dict(anchor), temperature=0.12)
            self.assertEqual(blend.top(), name, f"anchor {name} should map to itself")


class AffectBlendInertiaTests(unittest.TestCase):
    def test_inertia_one_keeps_previous_distribution(self):
        prev = blend_stance({"threat": 0.85, "protectiveness": 0.85})
        # Tín hiệu mới hoàn toàn khác (mệt), nhưng inertia=1 -> giữ nguyên prev.
        new = blend_stance({"fatigue": 0.9}, prev=prev, inertia=1.0)
        for name in prev.weights:
            self.assertAlmostEqual(new.weights[name], prev.weights[name], places=6)

    def test_inertia_zero_ignores_previous_distribution(self):
        prev = blend_stance({"threat": 0.85, "protectiveness": 0.85})
        fresh = blend_stance({"fatigue": 0.9}, inertia=0.6)  # không prev
        new = blend_stance({"fatigue": 0.9}, prev=prev, inertia=0.0)
        for name in fresh.weights:
            self.assertAlmostEqual(new.weights[name], fresh.weights[name], places=6)

    def test_high_inertia_damps_flip_flop(self):
        # Trạng thái cũ rất protective, một cú mới rất tender.
        prev = blend_stance({"threat": 0.9, "protectiveness": 0.9})
        new_tender = {"tenderness": 0.85, "intimacy": 0.8, "valence": 0.4}

        slow = blend_stance(new_tender, prev=prev, inertia=0.8)
        fast = blend_stance(new_tender, prev=prev, inertia=0.1)
        # Với quán tính cao, protective vẫn còn đáng kể sau một bước (không snap).
        self.assertGreater(slow.weights["protective"], fast.weights["protective"])

    def test_repeated_high_inertia_eventually_transitions(self):
        # Quán tính làm chậm, KHÔNG khoá cứng: lặp nhiều bước thì vẫn chuyển.
        blend = blend_stance({"threat": 0.9, "protectiveness": 0.9})
        tender = {"tenderness": 0.85, "intimacy": 0.8, "valence": 0.4}
        for _ in range(12):
            blend = blend_stance(tender, prev=blend, inertia=0.7)
        self.assertEqual(blend.top(), "tender_under_cold")


class AffectBlendUtilityTests(unittest.TestCase):
    def test_guidance_blend_includes_top_stance_text(self):
        affect = {"fatigue": 0.85, "arousal": 0.2}
        blend = blend_stance(affect)
        text = guidance_blend(blend, k=2)
        self.assertIn("tired", text)
        self.assertIn("rhythm", text)  # khớp guidance "slow the rhythm..."

    def test_rms_distance_only_uses_anchor_axes(self):
        # Trục ngoài anchor không ảnh hưởng khoảng cách.
        anchor = {"fatigue": 0.8}
        near = rms_distance({"fatigue": 0.8, "threat": 0.99}, anchor)
        self.assertAlmostEqual(near, 0.0, places=6)

    def test_soft_assign_is_the_shared_primitive(self):
        # blend_stance phải bằng soft_assign trên cùng tham số (gồm baseline grounded).
        from cortex.affect_blend import AFFECT_NEUTRAL, GROUNDED_STANCE, DEFAULT_BLEND_CONFIG

        affect = {"threat": 0.5, "fatigue": 0.5}
        direct = soft_assign(
            affect,
            STANCE_ANCHORS,
            neutral=AFFECT_NEUTRAL,
            temperature=0.2,
            baseline=(GROUNDED_STANCE, DEFAULT_BLEND_CONFIG.grounded_floor),
        )
        via = blend_stance(affect, temperature=0.2).weights
        self.assertEqual(direct.keys(), via.keys())
        for name in direct:
            self.assertAlmostEqual(direct[name], via[name], places=9)

    def test_empty_affect_defaults_to_grounded_or_soft(self):
        blend = blend_stance({axis: 0.0 for axis in AFFECT_AXES})
        self.assertTrue(_is_distribution(blend.weights))
        self.assertIn(blend.top(), {"grounded", "soft_uncertain"})


import re

from cortex.affect_blend import (
    EVENT_AFFECT_PROTOTYPES,
    project_event_affect,
)


def _keyword_encoder(text):
    """Encoder giả xác định: đếm hit theo 4 nhóm khái niệm ~ 4 prototype.

    Trả vector 4 chiều. Mục đích: test project_event_affect mà không cần model thật.
    """
    t = (text or "").lower()
    groups = (
        r"struggl|drain|sad|lonel|overwhelm|fatigue|hard|tired",   # quiet_struggle
        r"relief|warm|win|calm|pleasant|resolved|worry|nice",       # relief_warmth
        r"threat|focus|goal|pressure|risk|derail|work",             # focus_threat
        r"excit|enthus|bright|energetic|positive|celebrat|eager",   # bright_excited
    )
    return [float(len(re.findall(g, t))) for g in groups]


class ProjectEventAffectTests(unittest.TestCase):
    def test_mixed_scene_reflects_both_not_zeroed_out(self):
        # Vừa có "win" (relief) vừa "drained/overwhelmed/lonely" (struggle).
        text = "a small win but i feel drained and overwhelmed and lonely"
        out = project_event_affect(text, encode=_keyword_encoder)
        self.assertIsNotNone(out)
        # Struggle chiếm ưu thế -> valence âm, nhưng KHÔNG bị triệt tiêu về 0.
        self.assertLess(out["valence"], 0.0)
        # Dịu dàng hiện diện vì có thành phần struggle.
        self.assertGreater(out["tenderness"], 0.0)

    def test_pure_positive_scene_has_positive_valence_low_tenderness(self):
        text = "celebrating an exciting bright win, feeling positive and energetic"
        out = project_event_affect(text, encode=_keyword_encoder)
        self.assertIsNotNone(out)
        self.assertGreater(out["valence"], 0.0)
        self.assertLess(out["tenderness"], out["valence"])

    def test_encoder_none_returns_none(self):
        self.assertIsNone(project_event_affect("anything", encode=lambda _t: None))

    def test_encoder_raises_returns_none_not_throw(self):
        def boom(_t):
            raise RuntimeError("model down")

        self.assertIsNone(project_event_affect("anything", encode=boom))

    def test_empty_text_returns_none(self):
        self.assertIsNone(project_event_affect("", encode=_keyword_encoder))

    def test_prototype_bank_is_nonempty(self):
        self.assertGreaterEqual(len(EVENT_AFFECT_PROTOTYPES), 3)


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class AffectBlendPropertyTests(unittest.TestCase):
    if HAS_HYPOTHESIS:

        @settings(max_examples=150)
        @given(affect=_AFFECT_STRATEGY)
        def test_always_returns_valid_distribution(self, affect):
            blend = blend_stance(affect)
            self.assertTrue(_is_distribution(blend.weights))

        @settings(max_examples=150)
        @given(affect=_AFFECT_STRATEGY, inertia=st.floats(min_value=0.0, max_value=1.0))
        def test_inertia_preserves_distribution_property(self, affect, inertia):
            prev = blend_stance({"threat": 0.7, "protectiveness": 0.7})
            blend = blend_stance(affect, prev=prev, inertia=inertia)
            self.assertTrue(_is_distribution(blend.weights))


if __name__ == "__main__":
    unittest.main()
