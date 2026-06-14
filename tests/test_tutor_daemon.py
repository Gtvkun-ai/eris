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
        provider = _Provider("Ngài sắp chạy test sau khi sửa code")
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
        self.assertTrue(sm.state.last_prediction.description.startswith("Ngài tiếp tục"))


if __name__ == "__main__":
    unittest.main()
