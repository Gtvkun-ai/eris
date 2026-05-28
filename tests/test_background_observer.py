import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.background_observer import BackgroundObserver, BackgroundObserverConfig
from cortex.observer_contracts import SignalDiff, SignalSnapshot
from llm.ollama_client import OllamaClient, OllamaResult


class _FakeOllamaClient:
    def __init__(self, result: OllamaResult | None = None):
        self.result = result or OllamaResult(ok=False, error="no_result")
        self.calls: list[dict[str, object]] = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return self.result


class BackgroundObserverConfigTests(unittest.TestCase):
    def test_rule_based_rollout_env_keeps_llm_off(self):
        with patch.dict(
            os.environ,
            {
                "ERIS_BACKGROUND_OBSERVER": "1",
                "ERIS_BACKGROUND_OBSERVER_LLM": "0",
            },
            clear=False,
        ):
            config = BackgroundObserverConfig()

        self.assertTrue(config.enabled)
        self.assertFalse(config.llm_enabled)
        self.assertEqual(config.ollama_model, "qwen3:0.6b")
        self.assertEqual(config.keep_alive, "30m")

    def test_llm_rollout_env_reads_observer_model_settings(self):
        with patch.dict(
            os.environ,
            {
                "ERIS_BACKGROUND_OBSERVER": "1",
                "ERIS_BACKGROUND_OBSERVER_LLM": "1",
                "ERIS_OBSERVER_MODEL": "qwen3:0.6b",
                "ERIS_OBSERVER_KEEP_ALIVE": "30m",
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            },
            clear=False,
        ):
            config = BackgroundObserverConfig()
            client = OllamaClient()

        self.assertTrue(config.enabled)
        self.assertTrue(config.llm_enabled)
        self.assertEqual(config.ollama_model, "qwen3:0.6b")
        self.assertEqual(config.keep_alive, "30m")
        self.assertEqual(client.base_url, "http://127.0.0.1:11434/api")


class BackgroundObserverRuntimeTests(unittest.TestCase):
    def _snapshot(self) -> SignalSnapshot:
        return SignalSnapshot(
            active_window_title="pytest failure in VSCode",
            active_app="Code",
            focus_kind_hint="code",
            recent_events=["keyboard_input", "terminal_command"],
            ocr_text="Traceback AssertionError test failed",
            idle_seconds=2.0,
        )

    def _diff(self) -> SignalDiff:
        return SignalDiff(
            ocr_changed=True,
            event_changed=True,
            diff_score=0.42,
            novelty=0.36,
            repetition=0.08,
            reason=["ocr_changed", "event_changed"],
        )

    def test_rule_based_mode_does_not_call_ollama(self):
        fake_client = _FakeOllamaClient(
            OllamaResult(
                ok=True,
                parsed={
                    "focus_kind": "browser",
                    "activity_intent": "reading",
                    "salience": 0.2,
                    "novelty": 0.2,
                    "repetition": 0.1,
                    "ambiguity": 0.1,
                    "possible_error": 0.1,
                    "user_presence": 0.2,
                    "recommended_action": "observe_only",
                    "confidence": 0.5,
                },
            )
        )
        observer = BackgroundObserver(
            BackgroundObserverConfig(enabled=True, llm_enabled=False),
            ollama_client=fake_client,
        )

        frame = observer.observe(self._snapshot(), self._diff(), recent_summary="recent summary")

        self.assertEqual(fake_client.calls, [])
        self.assertIn("rule_based_observer", frame.notes)
        self.assertNotIn("llm_observer", frame.notes)
        self.assertFalse(frame.debug.get("llm_used", False))

    def test_llm_mode_uses_ollama_only_when_enabled(self):
        fake_client = _FakeOllamaClient(
            OllamaResult(
                ok=True,
                parsed={
                    "focus_kind": "code",
                    "activity_intent": "debugging",
                    "salience": 0.74,
                    "novelty": 0.61,
                    "repetition": 0.11,
                    "ambiguity": 0.12,
                    "possible_error": 0.81,
                    "user_presence": 0.72,
                    "recommended_action": "update_body_bias",
                    "confidence": 0.77,
                    "notes": ["llm_debug_signal"],
                },
            )
        )
        observer = BackgroundObserver(
            BackgroundObserverConfig(
                enabled=True,
                llm_enabled=True,
                ollama_model="qwen3:0.6b",
                keep_alive="30m",
                llm_cooldown_seconds=0.0,
            ),
            ollama_client=fake_client,
        )

        frame = observer.observe(self._snapshot(), self._diff(), recent_summary="recent summary")

        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(fake_client.calls[0]["model"], "qwen3:0.6b")
        self.assertEqual(fake_client.calls[0]["kwargs"]["keep_alive"], "30m")
        self.assertTrue(frame.debug.get("llm_used"))
        self.assertIn("rule_based_observer", frame.notes)
        self.assertIn("llm_observer", frame.notes)
        self.assertEqual(frame.focus_kind, "code")
        self.assertEqual(frame.activity_intent, "debugging")


if __name__ == "__main__":
    unittest.main()
