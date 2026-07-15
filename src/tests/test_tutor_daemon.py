# -*- coding: utf-8 -*-
"""tests/test_tutor_daemon.py

Integration cho TutorDaemon + StageEmitter + hook dự đoán SituationModel.
Backend dùng FakeTutorBackend (không online).
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.tutor.config import TutorConfig, TutorLogger, TutorRiskGuard
from cortex.tutor.contracts import KnowledgeGap, TutorQuestion
from cortex.tutor.gap_collector import GapCollector
from cortex.tutor.curiosity_gate import CuriosityGate
from cortex.tutor.question_formulator import QuestionFormulator
from cortex.tutor.claim_digest import ClaimDigest
from cortex.tutor.share_impulse import LearningShareImpulse
from llm.tutor_backend import FakeTutorBackend
from runtime.tutor_daemon import TutorDaemon, TutorStageEmitter
from cortex.situation_model import SituationModel


class _Transport:
    def __init__(self):
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)


class _Sink:
    def __init__(self):
        self.items = []

    def push_share_impulse(self, highlight, *, priority):
        self.items.append(highlight)


def build_daemon(*, enabled=True, backend=None, ingest=None, transport=None, sink=None,
                 risk_guard=None):
    cfg = TutorConfig(enabled=enabled, min_seconds_between_episodes=0.0,
                      share_window_s=0.0, curiosity_threshold=0.1).normalized()
    collector = GapCollector(cfg)
    gate = CuriosityGate(cfg)
    formulator = QuestionFormulator(cfg)
    backend = backend or FakeTutorBackend(answer_text="Pytest là framework test cho Python.")
    digest = ClaimDigest(cfg, ingest_fn=ingest or (lambda *a, **k: 2))
    share = LearningShareImpulse(cfg, formulator=formulator, thought_sink=sink or _Sink(),
                                 novelty_fn=lambda h: 1.0)
    emitter = TutorStageEmitter(transport=transport, logger=TutorLogger())
    daemon = TutorDaemon(
        cfg, collector=collector, gate=gate, formulator=formulator, backend=backend,
        digest=digest, share_impulse=share, emitter=emitter,
        risk_guard=risk_guard or TutorRiskGuard(cfg), logger=TutorLogger(),
    )
    return daemon, collector


class TestTutorDaemon(unittest.TestCase):
    def test_disabled_returns_none(self):
        daemon, collector = build_daemon(enabled=False)
        collector.push(KnowledgeGap(description="loi gi do", stake_relevance=0.9, prediction_error=0.9))
        self.assertIsNone(daemon.run_once(idle=True, now=1000.0))

    def test_full_episode_commits_and_shares(self):
        sink = _Sink()
        transport = _Transport()
        daemon, collector = build_daemon(transport=transport, sink=sink)
        collector.push(KnowledgeGap(description="loi gi do", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertIsNotNone(ep)
        self.assertEqual(ep.stage, "done")
        self.assertGreater(ep.claims_committed, 0)
        self.assertTrue(ep.shared)
        self.assertGreaterEqual(len(sink.items), 1)
        # Stage flow xuất hiện qua popup events.
        stages = [p["tutor"]["stage"] for p in transport.sent]
        for s in ("forming", "asking", "reading", "digesting", "done"):
            self.assertIn(s, stages)
        # Không lộ PII trong payload, đúng parse_mode.
        for p in transport.sent:
            self.assertEqual(p["parse_mode"], "tutor_event")
            self.assertFalse(p["should_speak"])

    def test_not_idle_no_episode(self):
        daemon, collector = build_daemon()
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        self.assertIsNone(daemon.run_once(idle=False, now=1000.0))

    def test_backend_error_isolated(self):
        backend = FakeTutorBackend(raise_exc=RuntimeError("boom"))
        daemon, collector = build_daemon(backend=backend)
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)  # không được ném
        self.assertEqual(ep.stage, "failed")
        self.assertEqual(ep.fail_reason, "network_error")

    def test_captcha_pauses(self):
        cfg = TutorConfig(enabled=True, min_seconds_between_episodes=0.0, curiosity_threshold=0.1,
                          captcha_pause_s=3600.0).normalized()
        guard = TutorRiskGuard(cfg)
        backend = FakeTutorBackend(fail_reason="captcha_or_expired")
        daemon, collector = build_daemon(backend=backend, risk_guard=guard)
        daemon.config = cfg
        daemon.risk_guard = guard
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.fail_reason, "captcha_or_expired")
        self.assertTrue(guard.is_paused(1001.0))

    def test_consecutive_failures_cooldown(self):
        cfg = TutorConfig(enabled=True, min_seconds_between_episodes=0.0, curiosity_threshold=0.1,
                          max_consecutive_failures=2, failure_cooldown_s=1800.0).normalized()
        guard = TutorRiskGuard(cfg)
        backend = FakeTutorBackend(fail_reason="empty_answer")
        daemon, collector = build_daemon(backend=backend, risk_guard=guard)
        daemon.config = cfg
        daemon.risk_guard = guard
        for i in range(2):
            collector.push(KnowledgeGap(description=f"loi {i}", stake_relevance=0.9, prediction_error=0.9))
            daemon.run_once(idle=True, now=1000.0 + i)
        self.assertTrue(guard.is_paused(1003.0))

    def test_formulation_failure_no_backend_call(self):
        backend = FakeTutorBackend(answer_text="x")
        cfg = TutorConfig(enabled=True, min_seconds_between_episodes=0.0, curiosity_threshold=0.1).normalized()
        collector = GapCollector(cfg)

        class _BadFormulator:
            def formulate(self, gap):
                return None

        daemon = TutorDaemon(
            cfg, collector=collector, gate=CuriosityGate(cfg), formulator=_BadFormulator(),
            backend=backend, digest=ClaimDigest(cfg, ingest_fn=lambda *a, **k: 1),
        )
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.fail_reason, "formulation_failed")
        self.assertEqual(backend.ask_calls, 0)


# ---------------------------------------------------------------------------
# Task 10 — hook làm giàu dự đoán
# ---------------------------------------------------------------------------

def make_frame(claims, timestamp=1000.0):
    evidence = [
        SimpleNamespace(claim=c, source="active_window", confidence=0.8,
                        reliability=0.8, timestamp=timestamp)
        for c in claims
    ]
    return SimpleNamespace(evidence=evidence, timestamp=timestamp)


class _Provider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def enrich(self, *, content_thread, percept_text):
        self.calls += 1
        return self.text


class TestPredictionHook(unittest.TestCase):
    def test_enrich_used_when_provider_present(self):
        provider = _Provider("bạn sắp chạy test sau khi sửa code")
        sm = SituationModel(knowledge_provider=provider)
        sm.observe_and_update(make_frame(["đang sửa code cortex"]), now=1.0)
        self.assertGreater(provider.calls, 0)
        self.assertIn("test", sm.state.last_prediction.description.lower())

    def test_baseline_deterministic_without_provider(self):
        frames = [make_frame(["đang code"], timestamp=float(i)) for i in range(4)]

        def run():
            sm = SituationModel()
            for f in frames:
                sm.observe_and_update(f, now=f.timestamp)
            return sm.serialize()

        self.assertEqual(run(), run())

    def test_provider_none_keeps_heuristic(self):
        sm = SituationModel()
        sm.observe_and_update(make_frame(["đang xem video"]), now=1.0)
        self.assertTrue(sm.state.last_prediction.description.startswith("bạn tiếp tục"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Task 11.3 — ingest claim (có embedding) + KnowledgeProvider
# ---------------------------------------------------------------------------

from cortex.tutor.knowledge_provider import KnowledgeProvider
from runtime.tutor_wiring import _build_ingest_fn


class _FakeCore:
    def __init__(self, outcome="accepted", stored_id="sem_1"):
        self.committed = []
        self._outcome = outcome
        self._stored = stored_id

    def commit(self, request):
        self.committed.append(request)
        return SimpleNamespace(outcome=self._outcome, stored_id=self._stored)


class _FakeRuntime:
    def __init__(self, core):
        self.memory_core = core
        self.logger = None


class TestTutorIngest(unittest.TestCase):
    def test_ingest_commits_semantic_with_tutor_tags(self):
        core = _FakeCore()
        fn = _build_ingest_fn(_FakeRuntime(core), None, None)
        self.assertIsNotNone(fn)
        n = fn("Pytest là framework test cho Python.", source="tutor", gap_id="g1")
        self.assertEqual(n, 1)
        req = core.committed[0]
        self.assertEqual(req["target"], "semantic_memory")
        self.assertIn("tutor", req["tags"])
        self.assertTrue(req["storage_permission"])
        self.assertEqual(req["evidence_ids"], ["g1"])

    def test_ingest_zero_when_rejected(self):
        core = _FakeCore(outcome="rejected", stored_id="")
        fn = _build_ingest_fn(_FakeRuntime(core), None, None)
        self.assertEqual(fn("abc", gap_id="g"), 0)

    def test_ingest_none_without_commit_path(self):
        class _Bare:
            logger = None
        self.assertIsNone(_build_ingest_fn(_Bare(), None, None))


class TestKnowledgeProvider(unittest.TestCase):
    def test_enrich_uses_tutor_claim(self):
        item = SimpleNamespace(claim="Pytest dùng fixtures và assert rewriting", tags=("tutor", "learned"))
        prov = KnowledgeProvider(lambda q: [item])
        out = prov.enrich(content_thread="đang code", percept_text="đang sửa test")
        self.assertIn("điều đã học", out)
        self.assertIn("fixtures", out)
        self.assertLessEqual(len(out), 280)

    def test_enrich_skips_non_tutor(self):
        item = SimpleNamespace(claim="x", tags=("commit",))
        prov = KnowledgeProvider(lambda q: [item])
        self.assertEqual(prov.enrich(percept_text="abc"), "")

    def test_enrich_empty_query(self):
        prov = KnowledgeProvider(lambda q: [SimpleNamespace(claim="x", tags=("tutor",))])
        self.assertEqual(prov.enrich(), "")

    def test_situation_model_uses_knowledge_provider(self):
        item = SimpleNamespace(claim="test thường chạy sau khi sửa code", tags=("tutor",))
        provider = KnowledgeProvider(lambda q: [item])
        sm = SituationModel()
        sm.set_knowledge_provider(provider)
        sm.observe_and_update(make_frame(["đang sửa code cortex"]), now=1.0)
        self.assertIn("điều đã học", sm.state.last_prediction.description)


# ---------------------------------------------------------------------------
# Knowledge classification + routing + on-demand lookup
# ---------------------------------------------------------------------------

from cortex.tutor.knowledge_classifier import KnowledgeClassifier


class _FixedClassifier:
    def __init__(self, kind):
        self.kind = kind

    def classify(self, q, a, *, gap_source="", kind_hint=""):
        return self.kind


def build_daemon_kind(kind, *, ingest_calls):
    cfg = TutorConfig(enabled=True, min_seconds_between_episodes=0.0, share_window_s=0.0,
                      curiosity_threshold=0.1).normalized()
    collector = GapCollector(cfg)
    formulator = QuestionFormulator(cfg)
    backend = FakeTutorBackend(answer_text="Một câu trả lời nào đó từ gia sư.")

    def ingest(*a, **k):
        ingest_calls.append(1)
        return 2

    sink = _Sink()
    share = LearningShareImpulse(cfg, formulator=formulator, thought_sink=sink, novelty_fn=lambda h: 1.0)
    daemon = TutorDaemon(
        cfg, collector=collector, gate=CuriosityGate(cfg), formulator=formulator,
        backend=backend, digest=ClaimDigest(cfg, ingest_fn=ingest), share_impulse=share,
        classifier=_FixedClassifier(kind), risk_guard=TutorRiskGuard(cfg), logger=TutorLogger(),
    )
    return daemon, collector, sink


class TestKnowledgeRouting(unittest.TestCase):
    def test_durable_stores(self):
        calls = []
        daemon, collector, sink = build_daemon_kind("durable", ingest_calls=calls)
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.stage, "done")
        self.assertEqual(len(calls), 1)            # đã commit (embedding)
        self.assertGreater(ep.claims_committed, 0)

    def test_context_not_stored_but_remarks(self):
        calls = []
        daemon, collector, sink = build_daemon_kind("context", ingest_calls=calls)
        collector.push(KnowledgeGap(description="đoán ngữ cảnh", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.stage, "done")
        self.assertEqual(len(calls), 0)            # KHÔNG lưu trí nhớ dài hạn
        self.assertGreaterEqual(len(sink.items), 1)

    def test_banter_not_stored_but_remarks(self):
        calls = []
        daemon, collector, sink = build_daemon_kind("banter", ingest_calls=calls)
        collector.push(KnowledgeGap(description="chuyện vui", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(len(calls), 0)
        self.assertGreaterEqual(len(sink.items), 1)


class TestForcedAndUncertainty(unittest.TestCase):
    def test_forced_gap_runs_even_when_busy(self):
        # idle=False ⇒ select() trả None; nhưng gap force phải chạy.
        calls = []
        daemon, collector, sink = build_daemon_kind("durable", ingest_calls=calls)
        gap = collector.collect_from_uncertainty("X là gì?", stake=0.8, now=1000.0, force=True)
        collector.push(gap)
        ep = daemon.run_once(idle=False, now=1000.0)
        self.assertIsNotNone(ep)
        self.assertEqual(ep.stage, "done")

    def test_non_forced_skipped_when_busy(self):
        calls = []
        daemon, collector, sink = build_daemon_kind("durable", ingest_calls=calls)
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9, force=False))
        self.assertIsNone(daemon.run_once(idle=False, now=1000.0))

    def test_uncertainty_gap_fields(self):
        gc = GapCollector()
        gap = gc.collect_from_uncertainty("asyncio là gì", stake=0.7, now=5.0, kind_hint="durable")
        self.assertEqual(gap.source, "epistemic_uncertainty")
        self.assertTrue(gap.force)
        self.assertEqual(gap.kind_hint, "durable")


class TestClassifier(unittest.TestCase):
    def test_observer_unknown_is_context(self):
        c = KnowledgeClassifier()
        self.assertEqual(c.classify("q", "a", gap_source="observer_unknown"), "context")

    def test_kind_hint_respected(self):
        c = KnowledgeClassifier()
        self.assertEqual(c.classify("q", "a", gap_source="epistemic_uncertainty", kind_hint="banter"), "banter")

    def test_default_durable(self):
        c = KnowledgeClassifier()
        self.assertEqual(c.classify("q", "a"), "durable")

    def test_llm_override(self):
        c = KnowledgeClassifier(generate_fn=lambda p: '{"kind": "banter"}')
        self.assertEqual(c.classify("q", "a", gap_source="expectation_violation"), "banter")


# ---------------------------------------------------------------------------
# CuriosityRouter + ask_user / skip routing (cho nó khôn ra)
# ---------------------------------------------------------------------------

from cortex.tutor.curiosity_router import CuriosityRouter


class TestCuriosityRouter(unittest.TestCase):
    def test_skip_when_already_known(self):
        r = CuriosityRouter(already_known_fn=lambda t: True)
        action, reason = r.route(KnowledgeGap(description="x", source="observer_unknown"))
        self.assertEqual(action, "skip")
        self.assertEqual(reason, "already_known")

    def test_violation_defaults_ask_user(self):
        r = CuriosityRouter()  # no LLM, no known-fn
        action, _ = r.route(KnowledgeGap(description="bạn đổi việc", source="expectation_violation"))
        self.assertEqual(action, "ask_user")

    def test_observer_defaults_ask_gemini(self):
        r = CuriosityRouter()
        action, _ = r.route(KnowledgeGap(description="app lạ", source="observer_unknown"))
        self.assertEqual(action, "ask_gemini")

    def test_hint_overrides(self):
        r = CuriosityRouter()
        gap = KnowledgeGap(description="x", source="observer_unknown", kind_hint="ask_user")
        action, reason = r.route(gap)
        self.assertEqual(action, "ask_user")
        self.assertEqual(reason, "hint")

    def test_llm_route(self):
        r = CuriosityRouter(generate_fn=lambda p: '{"route": "ask_gemini"}')
        action, reason = r.route(KnowledgeGap(description="pytest là gì", source="epistemic_uncertainty"))
        self.assertEqual(action, "ask_gemini")
        self.assertEqual(reason, "llm")


def build_daemon_router(route_action, *, ingest_calls, backend=None, route_reason="test"):
    cfg = TutorConfig(enabled=True, min_seconds_between_episodes=0.0, share_window_s=0.0,
                      curiosity_threshold=0.1).normalized()
    collector = GapCollector(cfg)
    formulator = QuestionFormulator(cfg)
    backend = backend or FakeTutorBackend(answer_text="kiến thức gì đó")

    def ingest(*a, **k):
        ingest_calls.append(1)
        return 1

    sink = _Sink()
    share = LearningShareImpulse(cfg, formulator=formulator, thought_sink=sink, novelty_fn=lambda h: 1.0)

    class _FixedRouter:
        def route(self, gap):
            return (route_action, route_reason)

    daemon = TutorDaemon(
        cfg, collector=collector, gate=CuriosityGate(cfg), formulator=formulator,
        backend=backend, digest=ClaimDigest(cfg, ingest_fn=ingest), share_impulse=share,
        router=_FixedRouter(), risk_guard=TutorRiskGuard(cfg), logger=TutorLogger(),
    )
    return daemon, collector, sink, backend


class TestRoutedDaemon(unittest.TestCase):
    def test_skip_no_browser(self):
        calls = []
        daemon, collector, sink, backend = build_daemon_router("skip", ingest_calls=calls)
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.fail_reason, "gate_rejected_trivial")
        self.assertEqual(backend.ask_calls, 0)
        self.assertEqual(len(calls), 0)

    def test_skip_known_reason(self):
        calls = []
        daemon, collector, sink, backend = build_daemon_router(
            "skip", ingest_calls=calls, route_reason="already_known")
        collector.push(KnowledgeGap(description="x", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.fail_reason, "gate_rejected_known")
        self.assertEqual(backend.ask_calls, 0)
        self.assertEqual(len(calls), 0)

    def test_ask_user_speaks_no_browser(self):
        calls = []
        daemon, collector, sink, backend = build_daemon_router("ask_user", ingest_calls=calls)
        collector.push(KnowledgeGap(description="ý bạn là gì", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.stage, "done")
        self.assertEqual(backend.ask_calls, 0)       # KHÔNG mở Gemini
        self.assertEqual(len(calls), 0)              # KHÔNG lưu
        self.assertGreaterEqual(len(sink.items), 1)  # đã đẩy câu hỏi cho bạn

    def test_ask_gemini_opens_and_stores(self):
        calls = []
        daemon, collector, sink, backend = build_daemon_router("ask_gemini", ingest_calls=calls)
        collector.push(KnowledgeGap(description="pytest là gì", stake_relevance=0.9, prediction_error=0.9))
        ep = daemon.run_once(idle=True, now=1000.0)
        self.assertEqual(ep.stage, "done")
        self.assertGreater(backend.ask_calls, 0)     # có mở Gemini
        self.assertGreater(len(calls), 0)            # có lưu (embedding)
