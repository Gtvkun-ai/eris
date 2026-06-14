# -*- coding: utf-8 -*-
"""tests/test_curiosity_tutor.py

Bộ test đơn vị cho Curiosity Tutor. Ánh xạ tới acceptance criteria trong
.kiro/specs/curiosity-tutor. Backend web KHÔNG test online — dùng FakeTutorBackend
và PageSession giả.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.tutor.config import TutorConfig, TutorLogger, TutorRiskGuard, scrub_identity
from cortex.tutor.contracts import KnowledgeGap, TutorAnswer, TutorEpisode, TutorQuestion
from cortex.tutor.gap_collector import GapCollector
from cortex.tutor.curiosity_gate import CuriosityGate
from cortex.tutor.question_formulator import QuestionFormulator
from cortex.tutor.claim_digest import ClaimDigest
from cortex.tutor.share_impulse import LearningShareImpulse
from llm.tutor_backend import (
    FakeTutorBackend,
    GeminiWebBackend,
    CaptchaOrExpired,
)


def violation(expected="Ngài tiếp tục code", observed="Ngài mở youtube", pe=0.8):
    return SimpleNamespace(expected=expected, observed=observed, prediction_error=pe, cycle=3)


def observer_frame(focus="unknown", activity="unknown", ambiguity=0.7, salience=0.5):
    return SimpleNamespace(
        focus_kind=focus, activity_intent=activity, ambiguity=ambiguity,
        salience=salience, evidence=["alt_tab", "unknown_window"],
    )


# ---------------------------------------------------------------------------
# Task 1 — config + Master_Switch
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):
    def test_default_disabled(self):
        self.assertFalse(TutorConfig().enabled)

    def test_normalized_clamps(self):
        cfg = TutorConfig(curiosity_threshold=5.0, share_novelty_threshold=-1.0,
                          max_gap_queue=0, type_delay_ms_max=10, type_delay_ms_min=50).normalized()
        self.assertEqual(cfg.curiosity_threshold, 1.0)
        self.assertEqual(cfg.share_novelty_threshold, 0.0)
        self.assertGreaterEqual(cfg.max_gap_queue, 1)
        self.assertGreaterEqual(cfg.type_delay_ms_max, cfg.type_delay_ms_min)

    def test_invalid_flag_defaults_off(self):
        logger = TutorLogger()
        os.environ["ERIS_TUTOR_ENABLED"] = "maybe"
        try:
            cfg = TutorConfig.from_env(logger)
        finally:
            del os.environ["ERIS_TUTOR_ENABLED"]
        self.assertFalse(cfg.enabled)
        self.assertTrue(any(r.get("kind") == "warning" for r in logger.records))

    def test_scrub_identity(self):
        s = scrub_identity("liên hệ me@example.com cookie: abc123")
        self.assertNotIn("me@example.com", s)
        self.assertIn("[email]", s)


# ---------------------------------------------------------------------------
# Task 2 — GapCollector
# ---------------------------------------------------------------------------

class TestGapCollector(unittest.TestCase):
    def test_from_violation(self):
        gc = GapCollector()
        gap = gc.collect_from_violation(violation(), stake_relevance=0.6, now=10.0)
        self.assertIsNotNone(gap)
        self.assertEqual(gap.source, "expectation_violation")
        self.assertAlmostEqual(gap.stake_relevance, 0.6)
        self.assertGreater(gap.prediction_error, 0.0)

    def test_from_observer_unknown(self):
        gc = GapCollector()
        gap = gc.collect_from_observer(observer_frame(), now=10.0)
        self.assertIsNotNone(gap)
        self.assertEqual(gap.source, "observer_unknown")

    def test_observer_low_ambiguity_skipped(self):
        gc = GapCollector()
        self.assertIsNone(gc.collect_from_observer(observer_frame(ambiguity=0.1), now=10.0))

    def test_observer_known_skipped(self):
        gc = GapCollector()
        self.assertIsNone(gc.collect_from_observer(observer_frame(focus="code", activity="debugging"), now=10.0))

    def test_dedupe_semantic(self):
        gc = GapCollector()
        g1 = gc.collect_from_violation(violation(), stake_relevance=0.5, now=1.0)
        g2 = gc.collect_from_violation(violation(), stake_relevance=0.5, now=2.0)
        self.assertTrue(gc.push(g1))
        self.assertFalse(gc.push(g2))  # trùng -> không thêm
        self.assertEqual(gc.size, 1)

    def test_queue_cap(self):
        cfg = TutorConfig(max_gap_queue=5)
        gc = GapCollector(cfg)
        for i in range(20):
            gc.push(KnowledgeGap(description=f"loi khac nhau so {i}", stake_relevance=i / 20.0, updated_ts=float(i)))
        self.assertLessEqual(gc.size, 5)

    def test_resolve_removes(self):
        gc = GapCollector()
        g = KnowledgeGap(description="abc")
        gc.push(g)
        gc.resolve(g)
        self.assertEqual(len(gc.drain_candidates()), 0)


# ---------------------------------------------------------------------------
# Task 3 — CuriosityGate
# ---------------------------------------------------------------------------

class TestCuriosityGate(unittest.TestCase):
    def _gap(self, stake=0.9, pe=0.9):
        return KnowledgeGap(description="x", stake_relevance=stake, prediction_error=pe, updated_ts=1.0)

    def test_idle_only(self):
        gate = CuriosityGate()
        self.assertIsNone(gate.select([self._gap()], idle=False, now=1000.0))

    def test_threshold(self):
        gate = CuriosityGate(TutorConfig(curiosity_threshold=0.9))
        self.assertIsNone(gate.select([self._gap(stake=0.1, pe=0.1)], idle=True, now=1000.0))

    def test_rate_limit(self):
        gate = CuriosityGate(TutorConfig(min_seconds_between_episodes=120.0))
        g = self._gap()
        self.assertIsNotNone(gate.select([g], idle=True, now=1000.0))
        gate.note_started(1000.0)
        self.assertIsNone(gate.select([g], idle=True, now=1050.0))
        self.assertIsNotNone(gate.select([g], idle=True, now=1200.0))

    def test_hourly_cap(self):
        gate = CuriosityGate(TutorConfig(min_seconds_between_episodes=0.0, max_episodes_per_hour=2))
        g = self._gap()
        for t in (0.0, 1.0):
            self.assertIsNotNone(gate.select([g], idle=True, now=t))
            gate.note_started(t)
        self.assertIsNone(gate.select([g], idle=True, now=2.0))

    def test_priority_monotonic(self):
        gate = CuriosityGate()
        low = gate.priority(self._gap(stake=0.2, pe=0.5))
        high = gate.priority(self._gap(stake=0.8, pe=0.5))
        self.assertGreaterEqual(high, low)
        low_pe = gate.priority(self._gap(stake=0.5, pe=0.2))
        high_pe = gate.priority(self._gap(stake=0.5, pe=0.8))
        self.assertGreaterEqual(high_pe, low_pe)

    def test_drive_modulation(self):
        gate = CuriosityGate()
        full = gate.priority(self._gap(), drive_level=1.0)
        low = gate.priority(self._gap(), drive_level=0.0)
        self.assertGreater(full, low)


# ---------------------------------------------------------------------------
# Task 4 — QuestionFormulator
# ---------------------------------------------------------------------------

class TestQuestionFormulator(unittest.TestCase):
    def test_heuristic_when_no_llm(self):
        f = QuestionFormulator()
        q = f.formulate(KnowledgeGap(description="Tôi không hiểu cái này"))
        self.assertIsNotNone(q)
        self.assertTrue(q.is_valid)

    def test_llm_failure_fallback(self):
        def boom(prompt):
            raise RuntimeError("model down")
        f = QuestionFormulator(generate_fn=boom)
        q = f.formulate(KnowledgeGap(description="abc"))
        self.assertIsNotNone(q)  # fallback heuristic

    def test_pii_filtered(self):
        f = QuestionFormulator(generate_fn=lambda p: "Hỏi giúp me@example.com về cái này")
        q = f.formulate(KnowledgeGap(description="abc"))
        self.assertNotIn("@example.com", q.text)

    def test_length_capped(self):
        f = QuestionFormulator(generate_fn=lambda p: "x" * 999)
        q = f.formulate(KnowledgeGap(description="abc"))
        self.assertLessEqual(len(q.text), 400)

    def test_summarize_not_verbatim(self):
        answer = "Pytest là một framework test cho Python với fixtures và assert rewriting."
        ep = TutorEpisode(
            gap=KnowledgeGap(description="pytest là gì"),
            question=TutorQuestion(text="pytest là gì?"),
            answer=TutorAnswer(text=answer, ok=True),
        )
        # LLM trả về đúng nguyên văn answer -> phải bị thay bằng heuristic.
        f = QuestionFormulator(generate_fn=lambda p: answer)
        hi = f.summarize_learning(ep)
        self.assertTrue(hi)
        self.assertNotEqual(hi.strip().lower(), answer.strip().lower())
        self.assertLessEqual(len(hi), 200)


# ---------------------------------------------------------------------------
# Task 6 — ClaimDigest
# ---------------------------------------------------------------------------

class TestClaimDigest(unittest.TestCase):
    def test_commits_with_provenance(self):
        seen = {}

        def ingest(text, *, source, gap_id, citations):
            seen.update(text=text, source=source, gap_id=gap_id)
            return 2

        d = ClaimDigest(ingest_fn=ingest)
        ep = TutorEpisode(gap=KnowledgeGap(description="g"), answer=TutorAnswer(text="kiến thức", ok=True))
        n = d.digest(ep)
        self.assertEqual(n, 2)
        self.assertEqual(seen["source"], "tutor")

    def test_empty_answer_no_commit(self):
        called = {"n": 0}

        def ingest(text, **kw):
            called["n"] += 1
            return 1

        d = ClaimDigest(ingest_fn=ingest)
        ep = TutorEpisode(gap=KnowledgeGap(description="g"), answer=TutorAnswer(text="", ok=False))
        self.assertEqual(d.digest(ep), 0)
        self.assertEqual(called["n"], 0)

    def test_no_ingest_fn_returns_zero(self):
        d = ClaimDigest()
        ep = TutorEpisode(gap=KnowledgeGap(description="g"), answer=TutorAnswer(text="abc", ok=True))
        self.assertEqual(d.digest(ep), 0)


# ---------------------------------------------------------------------------
# Task 7 — LearningShareImpulse
# ---------------------------------------------------------------------------

class _Sink:
    def __init__(self):
        self.items = []

    def push_share_impulse(self, highlight, *, priority):
        self.items.append((highlight, priority))


def _episode(answer="Pytest là framework test.", stake=0.9):
    return TutorEpisode(
        gap=KnowledgeGap(description="pytest là gì", stake_relevance=stake),
        question=TutorQuestion(text="pytest?"),
        answer=TutorAnswer(text=answer, ok=True),
    )


class TestShareImpulse(unittest.TestCase):
    def _formulator(self):
        return QuestionFormulator()

    def test_disabled_no_share(self):
        sink = _Sink()
        s = LearningShareImpulse(TutorConfig(enabled=False), formulator=self._formulator(), thought_sink=sink)
        self.assertFalse(s.maybe_emit(_episode(), now=1000.0))
        self.assertEqual(len(sink.items), 0)

    def test_pushes_to_sink(self):
        sink = _Sink()
        s = LearningShareImpulse(TutorConfig(enabled=True), formulator=self._formulator(),
                                 thought_sink=sink, novelty_fn=lambda h: 1.0)
        self.assertTrue(s.maybe_emit(_episode(), now=1000.0))
        self.assertEqual(len(sink.items), 1)

    def test_skips_trivial(self):
        sink = _Sink()
        s = LearningShareImpulse(TutorConfig(enabled=True, share_novelty_threshold=0.5),
                                 formulator=self._formulator(), thought_sink=sink,
                                 novelty_fn=lambda h: 0.1)
        self.assertFalse(s.maybe_emit(_episode(stake=0.1), now=1000.0))

    def test_rate_limited(self):
        sink = _Sink()
        s = LearningShareImpulse(TutorConfig(enabled=True, share_window_s=600.0),
                                 formulator=self._formulator(), thought_sink=sink,
                                 novelty_fn=lambda h: 1.0)
        self.assertTrue(s.maybe_emit(_episode(), now=1000.0))
        self.assertFalse(s.maybe_emit(_episode(), now=1100.0))
        self.assertTrue(s.maybe_emit(_episode(), now=2000.0))


# ---------------------------------------------------------------------------
# Task 5 — GeminiWebBackend (qua PageSession giả)
# ---------------------------------------------------------------------------

class _FakePageSession:
    def __init__(self, *, answer="câu trả lời", blocked=False, timeout=False):
        self.answer = answer
        self.blocked = blocked
        self.timeout = timeout
        self.typed = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def goto(self, url):
        pass

    def is_blocked(self):
        return self.blocked

    def submit_question(self, text, *, delay_min_ms, delay_max_ms):
        self.typed = text

    def read_answer(self, *, stable_window_s, deadline):
        if self.timeout:
            raise TimeoutError("slow")
        return self.answer

    def citations(self):
        return ()


class TestGeminiWebBackend(unittest.TestCase):
    def test_disabled_no_network(self):
        called = {"n": 0}

        def factory():
            called["n"] += 1
            return _FakePageSession()

        b = GeminiWebBackend(TutorConfig(enabled=False), page_session_factory=factory)
        ans = b.ask(TutorQuestion(text="hi"))
        self.assertFalse(ans.ok)
        self.assertEqual(called["n"], 0)

    def test_happy_path(self):
        b = GeminiWebBackend(TutorConfig(enabled=True),
                             page_session_factory=lambda: _FakePageSession(answer="pytest là framework"))
        ans = b.ask(TutorQuestion(text="pytest?"))
        self.assertTrue(ans.ok)
        self.assertIn("pytest", ans.text)

    def test_captcha(self):
        b = GeminiWebBackend(TutorConfig(enabled=True),
                             page_session_factory=lambda: _FakePageSession(blocked=True))
        ans = b.ask(TutorQuestion(text="x"))
        self.assertFalse(ans.ok)
        self.assertEqual(ans.fail_reason, "captcha_or_expired")

    def test_timeout(self):
        b = GeminiWebBackend(TutorConfig(enabled=True),
                             page_session_factory=lambda: _FakePageSession(timeout=True))
        ans = b.ask(TutorQuestion(text="x"))
        self.assertFalse(ans.ok)
        self.assertEqual(ans.fail_reason, "timeout")

    def test_empty_answer(self):
        b = GeminiWebBackend(TutorConfig(enabled=True),
                             page_session_factory=lambda: _FakePageSession(answer=""))
        ans = b.ask(TutorQuestion(text="x"))
        self.assertFalse(ans.ok)
        self.assertEqual(ans.fail_reason, "empty_answer")


if __name__ == "__main__":
    unittest.main()
