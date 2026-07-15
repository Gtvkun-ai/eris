# -*- coding: utf-8 -*-
"""Large runtime-level smoke tests for tutor wiring.

Run this file directly in the IDE, or with:

    pytest tests/test_tutor_wiring_runtime.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.situation_model import SituationModel
from llm.tutor_backend import FakeTutorBackend
from runtime.tutor_wiring import (
    _screen_context_from_snapshot,
    build_tutor_daemon_from_runtime,
    tutor_tick,
)


class _Logger:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, fmt, *args):
        self.infos.append(fmt % args if args else fmt)

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)


class _Transport:
    def __init__(self):
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)


class _SemanticStore:
    def __init__(self):
        self.items = []

    def add(self, claim, tags):
        self.items.append(SimpleNamespace(claim=claim, tags=tuple(tags)))

    def recall(self, query, limit=4, min_score=0.0):
        terms = [token for token in str(query or "").lower().split() if token]
        hits = []
        for item in self.items:
            haystack = str(item.claim).lower()
            if not terms or any(term in haystack for term in terms):
                hits.append(item)
            if len(hits) >= max(1, int(limit)):
                break
        return hits


class _MemoryCore:
    def __init__(self):
        self.semantic = _SemanticStore()
        self.committed = []

    def commit(self, request):
        self.committed.append(request)
        self.semantic.add(request.get("content", ""), request.get("tags", ()))
        return SimpleNamespace(outcome="accepted", stored_id=f"sem_{len(self.committed)}")


class _ActionExecutor:
    def __init__(self, result=None, raise_exc=None):
        self.result = result
        self.raise_exc = raise_exc
        self.calls = []

    def execute(self, action_name, action_input):
        self.calls.append((action_name, action_input))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class _Runtime:
    def __init__(self, *, action_executor=None):
        self.logger = _Logger()
        self.transport = _Transport()
        self.memory_core = _MemoryCore()
        self.action_executor = action_executor or _ActionExecutor()
        self.situation_model = SituationModel()
        self.chat_mode = False


class _CollectorSpy:
    def __init__(self):
        self.observer_calls = []
        self.violation_calls = []
        self.pushes = []

    def collect_from_observer(self, frame, *, now, screen_context=""):
        self.observer_calls.append((frame, now, screen_context))
        return "observer_gap"

    def collect_from_violation(self, violation, *, stake_relevance, now):
        self.violation_calls.append((violation, stake_relevance, now))
        return "violation_gap"

    def push(self, gap):
        self.pushes.append(gap)


class _DaemonSpy:
    def __init__(self):
        self.calls = []

    def run_once(self, *, idle, now):
        self.calls.append((idle, now))
        return None


class _SituationModelSpy:
    def __init__(self, violation=None):
        self._knowledge_provider = None
        self._violation = violation
        self.set_calls = []

    def set_knowledge_provider(self, provider):
        self._knowledge_provider = provider
        self.set_calls.append(provider)

    def expose_violation(self):
        return self._violation


class TestTutorWiringRuntime(unittest.TestCase):
    def _build_runtime(self, *, answer_text, action_result=None):
        runtime = _Runtime(action_executor=_ActionExecutor(result=action_result))
        with patch.dict(os.environ, {"ERIS_TUTOR_ENABLED": "1"}, clear=False):
            with patch("runtime.tutor_wiring._build_generate_fn", return_value=None):
                with patch("runtime.tutor_wiring._build_distill_fn", return_value=None):
                    with patch(
                        "llm.tutor_backend.GeminiWebBackend",
                        side_effect=lambda *a, **k: FakeTutorBackend(answer_text=answer_text),
                    ):
                        daemon = build_tutor_daemon_from_runtime(runtime)
        return runtime, daemon

    def test_build_disabled_returns_none(self):
        runtime = _Runtime()
        with patch.dict(os.environ, {"ERIS_TUTOR_ENABLED": "0"}, clear=False):
            daemon = build_tutor_daemon_from_runtime(runtime)
        self.assertIsNone(daemon)
        self.assertFalse(hasattr(runtime, "request_tutor_answer"))
        self.assertFalse(hasattr(runtime, "_tutor_collector"))

    def test_build_enabled_wires_runtime_and_learns_from_direct_answer(self):
        runtime, daemon = self._build_runtime(
            answer_text="Pytest la framework test cho Python, co fixtures va assert rewriting."
        )
        self.assertIsNotNone(daemon)
        self.assertTrue(callable(getattr(runtime, "request_tutor_answer", None)))
        self.assertTrue(callable(getattr(runtime, "request_tutor_lookup", None)))
        self.assertIsNotNone(getattr(runtime, "_tutor_collector", None))
        self.assertIs(runtime.situation_model._knowledge_provider, runtime.tutor_knowledge_provider)

        answer = runtime.request_tutor_answer("pytest la gi", context="dang doc file test")
        self.assertIn("Pytest", answer)
        self.assertEqual(len(runtime.memory_core.committed), 1)
        self.assertTrue(runtime.tutor_knowledge_provider.learned_claims("pytest"))

        stages = [payload["tutor"]["stage"] for payload in runtime.transport.sent]
        for stage in ("forming", "opening", "asking", "reading", "digesting", "done"):
            self.assertIn(stage, stages)

    def test_request_tutor_answer_falls_back_to_search_web(self):
        action_result = SimpleNamespace(
            success=True,
            data={
                "answer": "Pytest ho tro fixtures va co he thong assert rewriting.",
                "sources": "https://docs.pytest.org/",
            },
            message="",
        )
        runtime, daemon = self._build_runtime(answer_text="", action_result=action_result)
        self.assertIsNotNone(daemon)

        answer = runtime.request_tutor_answer("pytest fixtures")
        self.assertIn("fixtures", answer)
        self.assertIn("docs.pytest.org", answer)
        self.assertEqual(runtime.action_executor.calls, [("search_web", "pytest fixtures")])

    def test_request_tutor_lookup_runs_full_episode_and_commits_memory(self):
        runtime, daemon = self._build_runtime(
            answer_text="Assert rewriting giup thong bao loi assert ro hon khi test that bai."
        )
        self.assertIsNotNone(daemon)

        ok = runtime.request_tutor_lookup("assert rewriting", context="dang sua test fail")
        self.assertTrue(ok)
        self.assertGreaterEqual(len(runtime.memory_core.committed), 1)

        hits = runtime.memory_core.semantic.recall("assert rewriting", limit=2)
        self.assertTrue(hits)
        self.assertIn("tutor", runtime.memory_core.committed[0]["tags"])

    def test_tutor_tick_collects_observer_and_violation_and_lazy_attaches_provider(self):
        violation = SimpleNamespace(
            expected="ban tiep tuc viet test",
            observed="ban mo docs",
            prediction_error=0.83,
        )
        runtime = SimpleNamespace(
            logger=_Logger(),
            tutor_daemon=_DaemonSpy(),
            _tutor_collector=_CollectorSpy(),
            tutor_knowledge_provider=object(),
            situation_model=_SituationModelSpy(violation=violation),
            chat_mode=False,
        )
        observer_frame = SimpleNamespace(
            focus_kind="unknown",
            activity_intent="unknown",
            ambiguity=0.91,
            salience=0.72,
            evidence=["ocr"],
        )
        snapshot = SimpleNamespace(
            active_app="Code",
            active_window_title="tests/test_tutor_wiring_runtime.py",
            url_or_path_hint="",
            vision_facts=["pytest docs open"],
            ocr_text="active window is Code\nassert rewriting in pytest",
        )

        tutor_tick(runtime, observer_frame=observer_frame, channel="autonomous", snapshot=snapshot)

        self.assertEqual(len(runtime.situation_model.set_calls), 1)
        self.assertIs(runtime.situation_model._knowledge_provider, runtime.tutor_knowledge_provider)
        self.assertEqual(runtime._tutor_collector.pushes, ["observer_gap", "violation_gap"])
        self.assertEqual(len(runtime._tutor_collector.observer_calls), 1)
        self.assertIn("assert rewriting in pytest", runtime._tutor_collector.observer_calls[0][2])
        self.assertEqual(runtime._tutor_collector.violation_calls[0][1], 0.83)
        self.assertEqual(len(runtime.tutor_daemon.calls), 1)
        self.assertTrue(runtime.tutor_daemon.calls[0][0])

    def test_screen_context_filters_generic_telemetry_noise(self):
        cases = [
            (
                "generic_only",
                SimpleNamespace(
                    active_app="Code",
                    active_window_title="editor",
                    url_or_path_hint="",
                    vision_facts=[],
                    ocr_text="active window is Code\nthere has been no input for 5 seconds",
                ),
                "",
            ),
            (
                "real_ocr",
                SimpleNamespace(
                    active_app="Code",
                    active_window_title="editor",
                    url_or_path_hint="",
                    vision_facts=[],
                    ocr_text="active window is Code\npytest fixture scope docs",
                ),
                "pytest fixture scope docs",
            ),
            (
                "url_counts_as_real_content",
                SimpleNamespace(
                    active_app="Browser",
                    active_window_title="pytest docs",
                    url_or_path_hint="https://docs.pytest.org/en/stable/",
                    vision_facts=[],
                    ocr_text="",
                ),
                "docs.pytest.org",
            ),
        ]

        for name, snapshot, expected in cases:
            with self.subTest(case=name):
                context = _screen_context_from_snapshot(snapshot)
                if expected:
                    self.assertIn(expected, context)
                    self.assertNotIn("active window is", context.lower())
                else:
                    self.assertEqual(context, "")


if __name__ == "__main__":
    unittest.main()
