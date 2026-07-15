# -*- coding: utf-8 -*-
"""tests/test_situation_model.py

Bộ test cho Situation Model — vòng dự đoán → quan sát → sai số.
Ánh xạ tới acceptance criteria trong .kiro/specs/predictive-situation-model.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.situation_model import (
    Prediction,
    PredictionErrorResult,
    SituationModel,
    SituationModelConfig,
)
from cortex.attention_salience import (
    AttentionSalienceEngine,
    AttentionCandidate,
    SalienceFactorBreakdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class WordEmbeddingProvider:
    """Provider tất định: ánh xạ từ khóa -> vector 4 chiều (luôn non-zero)."""

    def embed(self, text):
        t = str(text or "").lower()
        return (
            0.1,  # dim nền để vector không bao giờ toàn 0
            1.0 if any(k in t for k in ("code", "cortex", "build", "godot")) else 0.0,
            1.0 if any(k in t for k in ("video", "youtube", "xem", "phim")) else 0.0,
            1.0 if any(k in t for k in ("music", "nhạc", "nhac")) else 0.0,
        )


def make_frame(claims, sources=None, timestamp=1000.0):
    sources = sources or ["active_window"] * len(claims)
    evidence = [
        SimpleNamespace(
            claim=c, source=s, confidence=0.8, reliability=0.8, timestamp=timestamp,
        )
        for c, s in zip(claims, sources)
    ]
    return SimpleNamespace(evidence=evidence, timestamp=timestamp)


def make_candidate(claim, fingerprint="fp1", tokens=()):
    return AttentionCandidate(
        candidate_id="c1",
        evidence_id="e1",
        source_signal_id="s1",
        source="active_window",
        claim=claim,
        timestamp=1000.0,
        confidence=0.8,
        reliability=0.8,
        privacy_level="normal",
        raw_or_inferred="raw",
        fingerprint=fingerprint,
        text_tokens=tuple(tokens),
    )


def enabled_model(**overrides):
    params = {"enabled": True, "cold_start_min_percepts": 2}
    params.update(overrides)
    cfg = SituationModelConfig(**params)
    return SituationModel(cfg, embedding_provider=WordEmbeddingProvider())


# ---------------------------------------------------------------------------
# Config + bất biến trọng số
# ---------------------------------------------------------------------------

class ConfigTests(unittest.TestCase):
    def test_weight_hierarchy_invariant(self):
        cfg = SituationModelConfig(prediction_error_weight=0.5, habituation_weight=0.9).normalized()
        self.assertLess(cfg.habituation_weight, cfg.prediction_error_weight)

    def test_default_enabled(self):
        self.assertTrue(SituationModelConfig().enabled)

    def test_thresholds_clamped(self):
        cfg = SituationModelConfig(expectation_violation_threshold=5.0, salience_floor=-1.0).normalized()
        self.assertEqual(cfg.expectation_violation_threshold, 1.0)
        self.assertEqual(cfg.salience_floor, 0.0)


# ---------------------------------------------------------------------------
# Prediction error
# ---------------------------------------------------------------------------

class PredictionErrorTests(unittest.TestCase):
    def test_cosine_low_error_when_match(self):
        sm = enabled_model()
        pred = Prediction(description="bạn tiếp tục: code cortex", embedding=WordEmbeddingProvider().embed("code cortex"), embedding_available=True)
        from cortex.situation_model import PerceptView
        percept = PerceptView(text="code cortex module", tokens=("code", "cortex"), embedding=WordEmbeddingProvider().embed("code cortex module"))
        res = sm._compute_error(pred, percept)
        self.assertTrue(res.defined)
        self.assertFalse(res.degraded)
        self.assertLess(res.value, 0.2)

    def test_cosine_high_error_when_diff(self):
        sm = enabled_model()
        from cortex.situation_model import PerceptView
        pred = Prediction(description="code cortex", embedding=WordEmbeddingProvider().embed("code cortex"), embedding_available=True)
        percept = PerceptView(text="xem video youtube", tokens=("xem", "video"), embedding=WordEmbeddingProvider().embed("xem video youtube"))
        res = sm._compute_error(pred, percept)
        self.assertTrue(res.defined)
        self.assertGreater(res.value, 0.3)

    def test_fallback_degraded_without_embedding(self):
        sm = SituationModel(SituationModelConfig(enabled=True, cold_start_min_percepts=2))  # no provider
        from cortex.situation_model import PerceptView
        pred = Prediction(description="code cortex")  # no embedding
        percept = PerceptView(text="code cortex", tokens=("code", "cortex"))
        res = sm._compute_error(pred, percept)
        self.assertTrue(res.defined)
        self.assertTrue(res.degraded)

    def test_no_prev_prediction_undefined(self):
        sm = enabled_model()
        from cortex.situation_model import PerceptView
        res = sm._compute_cycle_error(Prediction(), PerceptView(text="x", tokens=("x",)))
        self.assertFalse(res.defined)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class LifecycleTests(unittest.TestCase):
    def test_state_persists_and_cycle_increments(self):
        sm = enabled_model()
        sm.observe_and_update(make_frame(["code cortex"]))
        self.assertEqual(sm.state.cycle_count, 1)
        sm.observe_and_update(make_frame(["code cortex again"]))
        self.assertEqual(sm.state.cycle_count, 2)
        self.assertEqual(sm.state.observed_percept_count, 2)

    def test_first_cycle_error_undefined(self):
        sm = enabled_model()
        update = sm.observe_and_update(make_frame(["code cortex"]))
        # Chu kỳ đầu chưa có prediction trước -> error không xác định.
        self.assertFalse(update.error.defined)

    def test_empty_percept_holds_state(self):
        sm = enabled_model()
        sm.observe_and_update(make_frame(["code cortex"]))
        before = sm.serialize()
        update = sm.observe_and_update(make_frame([]))  # percept rỗng
        self.assertFalse(update.error.defined)
        self.assertEqual(update.error.reason, "no_percept")
        # observed_percept_count không tăng khi percept rỗng
        self.assertEqual(sm.state.observed_percept_count, before["observed_percept_count"])
        self.assertEqual(sm.state.cycle_count, before["cycle_count"] + 1)

    def test_prediction_created_each_cycle(self):
        sm = enabled_model()
        sm.observe_and_update(make_frame(["code cortex"]))
        self.assertFalse(sm.state.last_prediction.is_empty)
        self.assertLessEqual(len(sm.state.last_prediction.description), 280)

    def test_cold_start_prediction_confidence_zero(self):
        sm = enabled_model(cold_start_min_percepts=5)
        sm.observe_and_update(make_frame(["code cortex"]))
        self.assertEqual(sm.state.last_prediction.confidence, 0.0)

    def test_expectation_violation_recorded(self):
        sm = enabled_model(expectation_violation_threshold=0.3)
        sm.observe_and_update(make_frame(["code cortex"]))      # tạo prediction "code"
        update = sm.observe_and_update(make_frame(["xem video youtube"]))  # lệch mạnh
        self.assertTrue(update.error.defined)
        self.assertGreaterEqual(update.error.value, 0.3)
        self.assertIsNotNone(update.violation)
        self.assertIsNotNone(sm.expose_violation())

    def test_determinism_replay(self):
        seq = [make_frame(["code cortex"]), make_frame(["xem video"]), make_frame(["code build"])]
        sm1 = enabled_model()
        sm2 = enabled_model()
        for f in seq:
            sm1.observe_and_update(f, now=500.0)
        for f in seq:
            sm2.observe_and_update(f, now=500.0)
        self.assertEqual(sm1.serialize(), sm2.serialize())

    def test_reset_clears_state(self):
        sm = enabled_model()
        sm.observe_and_update(make_frame(["code cortex"]))
        sm.reset()
        self.assertEqual(sm.state.cycle_count, 0)
        self.assertEqual(sm.state.observed_percept_count, 0)
        self.assertTrue(sm.state.last_prediction.is_empty)
        self.assertEqual(sm.state.engagement_trend, "on_dinh")

    def test_serialize_fields(self):
        sm = enabled_model()
        sm.observe_and_update(make_frame(["code cortex"]))
        data = sm.serialize()
        for key in ("content_thread", "engagement_trend", "open_loops", "last_prediction", "last_error"):
            self.assertIn(key, data)


# ---------------------------------------------------------------------------
# prediction_error_for + Cold_Start gating
# ---------------------------------------------------------------------------

class PredictionErrorForTests(unittest.TestCase):
    def test_cold_start_returns_undefined(self):
        sm = enabled_model(cold_start_min_percepts=5)
        sm.observe_and_update(make_frame(["code cortex"]))  # count=1 < 5
        res = sm.prediction_error_for(make_candidate("xem video"))
        self.assertFalse(res.defined)

    def test_defined_after_cold_start(self):
        sm = enabled_model(cold_start_min_percepts=1)
        sm.observe_and_update(make_frame(["code cortex"]))   # count=1 >= 1, sinh prediction
        sm.observe_and_update(make_frame(["code cortex"]))   # active prediction non-empty
        res = sm.prediction_error_for(make_candidate("xem video youtube"))
        self.assertTrue(res.defined)

    def test_disabled_returns_undefined(self):
        sm = SituationModel(SituationModelConfig(enabled=False))
        res = sm.prediction_error_for(make_candidate("x"))
        self.assertFalse(res.defined)


# ---------------------------------------------------------------------------
# Attention integration
# ---------------------------------------------------------------------------

class AttentionIntegrationTests(unittest.TestCase):
    def test_novelty_term_falls_back_when_disabled(self):
        engine = AttentionSalienceEngine()
        cand = make_candidate("code cortex")
        term = engine._novelty_term(cand, repeat_count=0, age_seconds=0.0)
        legacy = engine._novelty_score(cand, repeat_count=0, age_seconds=0.0)
        self.assertEqual(term, legacy)

    def test_novelty_term_uses_prediction_error(self):
        sm = enabled_model(cold_start_min_percepts=1)
        sm.observe_and_update(make_frame(["code cortex"]))
        sm.observe_and_update(make_frame(["code cortex"]))
        engine = AttentionSalienceEngine(situation_model=sm)
        cand = make_candidate("xem video youtube", tokens=("xem", "video"))
        pe = sm.prediction_error_for(cand)
        term = engine._novelty_term(cand, repeat_count=9, age_seconds=0.0)
        self.assertAlmostEqual(term, pe.value, places=6)

    def test_weighted_score_monotonic_in_novelty(self):
        engine = AttentionSalienceEngine()
        low = SalienceFactorBreakdown(novelty=0.2)
        high = SalienceFactorBreakdown(novelty=0.9)
        self.assertGreaterEqual(engine._weighted_score(high), engine._weighted_score(low))

    def test_public_signature_unchanged(self):
        import inspect
        sig = inspect.signature(AttentionSalienceEngine.evaluate)
        params = list(sig.parameters.keys())
        self.assertEqual(params[0], "self")
        self.assertEqual(params[1], "frame")

    def test_family_collision_floor(self):
        sm = enabled_model(cold_start_min_percepts=1, high_prediction_error_threshold=0.3, salience_floor=0.5)
        sm.observe_and_update(make_frame(["code cortex"]))
        sm.observe_and_update(make_frame(["code cortex"]))
        engine = AttentionSalienceEngine(situation_model=sm)
        cand = make_candidate("xem video youtube", tokens=("xem", "video"))
        floored = engine._apply_prediction_error_floor(cand, 0.1)
        self.assertGreaterEqual(floored, 0.5)


# ---------------------------------------------------------------------------
# Pipeline integration (Task 12.3)
# ---------------------------------------------------------------------------

class PipelineIntegrationTests(unittest.TestCase):
    def _pipeline(self, sm=None):
        from runtime.cognitive_pipeline import CognitivePipeline
        return CognitivePipeline(situation_model=sm) if sm else CognitivePipeline()

    def _signals(self, text):
        from core.evidence import RawSignal
        return [RawSignal.from_chat(text)]

    def test_pipeline_runs_with_situation_model_enabled(self):
        sm = enabled_model(cold_start_min_percepts=1)
        pipeline = self._pipeline(sm)
        result = pipeline.run_from_signals(self._signals("build cortex module"), channel="chat")
        self.assertEqual(result.frame.status, "closed")
        self.assertIn("situation", result.frame.metadata)

    def test_pipeline_default_runs(self):
        pipeline = self._pipeline()
        result = pipeline.run_from_signals(self._signals("xin chào"), channel="chat")
        self.assertEqual(result.frame.status, "closed")
        # Default bật -> snapshot situation có mặt trong metadata.
        self.assertIn("situation", result.frame.metadata)

    def test_pipeline_isolates_situation_model_error(self):
        class BoomModel(SituationModel):
            def observe_and_update(self, frame, *, now=None):
                raise RuntimeError("boom")

        sm = BoomModel(SituationModelConfig(enabled=True))
        pipeline = self._pipeline(sm)
        result = pipeline.run_from_signals(self._signals("test"), channel="chat")
        # Chu kỳ vẫn hoàn tất dù Situation Model lỗi, và có cảnh báo ghi nhận.
        self.assertEqual(result.frame.status, "closed")
        self.assertTrue(any("situation_model" in w for w in result.frame.warnings))


# ---------------------------------------------------------------------------
# Property-based tests (Task 13)
# ---------------------------------------------------------------------------

try:
    from hypothesis import given, settings, strategies as st
    _HAS_HYPOTHESIS = True
except Exception:  # pragma: no cover
    _HAS_HYPOTHESIS = False


if _HAS_HYPOTHESIS:

    class PropertyTests(unittest.TestCase):
        @settings(max_examples=80, deadline=None)
        @given(
            a=st.floats(min_value=-1.0, max_value=1.0),
            dim=st.integers(min_value=1, max_value=6),
        )
        def test_prediction_error_always_in_unit_interval(self, a, dim):
            from cortex.situation_model import PerceptView
            sm = SituationModel(SituationModelConfig(enabled=True))
            vec = tuple([a] * dim)
            pred = Prediction(description="x", embedding=vec, embedding_available=True)
            percept = PerceptView(text="y", tokens=("y",), embedding=vec)
            res = sm._compute_error(pred, percept)
            self.assertGreaterEqual(res.value, 0.0)
            self.assertLessEqual(res.value, 1.0)

        @settings(max_examples=60, deadline=None)
        @given(novelty=st.floats(min_value=0.0, max_value=1.0))
        def test_weighted_score_in_unit_interval(self, novelty):
            engine = AttentionSalienceEngine()
            score = engine._weighted_score(SalienceFactorBreakdown(novelty=novelty))
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

        @settings(max_examples=40, deadline=None)
        @given(
            claims=st.lists(
                st.sampled_from(["code cortex", "xem video", "nghe nhac", "build godot"]),
                min_size=1, max_size=5,
            )
        )
        def test_determinism_under_replay(self, claims):
            frames = [make_frame([c]) for c in claims]
            sm1 = SituationModel(SituationModelConfig(enabled=True), embedding_provider=WordEmbeddingProvider())
            sm2 = SituationModel(SituationModelConfig(enabled=True), embedding_provider=WordEmbeddingProvider())
            for f in frames:
                sm1.observe_and_update(f, now=42.0)
            for f in frames:
                sm2.observe_and_update(f, now=42.0)
            self.assertEqual(sm1.serialize(), sm2.serialize())


if __name__ == "__main__":
    unittest.main()
