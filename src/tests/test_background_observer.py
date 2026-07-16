import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.background_observer import BackgroundObserver, BackgroundObserverConfig
from cortex.observer_contracts import SignalDiff, SignalSnapshot


class _FakeObserverAdapter:
    def __init__(self, data=None):
        self.data = data or {}
        self.calls = []

    def observe(self, **kwargs):
        self.calls.append(kwargs)
        return self.data


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

    def test_injected_adapter_flag_enables_llm_path(self):
        with patch.dict(
            os.environ,
            {
                "ERIS_BACKGROUND_OBSERVER": "1",
                "ERIS_BACKGROUND_OBSERVER_LLM": "1",
            },
            clear=False,
        ):
            config = BackgroundObserverConfig()

        self.assertTrue(config.enabled)
        self.assertTrue(config.llm_enabled)


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

    def test_rule_based_mode_does_not_call_adapter(self):
        adapter = _FakeObserverAdapter(
            {
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
            }
        )
        observer = BackgroundObserver(
            BackgroundObserverConfig(enabled=True, llm_enabled=False),
            sensory_adapter=adapter,
        )

        frame = observer.observe(self._snapshot(), self._diff(), recent_summary="recent summary")

        self.assertEqual(adapter.calls, [])
        self.assertIn("rule_based_observer", frame.notes)
        self.assertNotIn("llm_observer", frame.notes)
        self.assertFalse(frame.debug.get("llm_used", False))

    def test_llm_mode_uses_injected_adapter_only_when_enabled(self):
        adapter = _FakeObserverAdapter(
            {
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
                "notes": ["adapter_debug_signal"],
            }
        )
        observer = BackgroundObserver(
            BackgroundObserverConfig(
                enabled=True,
                llm_enabled=True,
                llm_cooldown_seconds=0.0,
            ),
            sensory_adapter=adapter,
        )

        frame = observer.observe(self._snapshot(), self._diff(), recent_summary="recent summary")

        self.assertEqual(len(adapter.calls), 1)
        self.assertTrue(frame.debug.get("llm_used"))
        self.assertIn("rule_based_observer", frame.notes)
        self.assertIn("llm_observer", frame.notes)
        self.assertEqual(frame.focus_kind, "code")
        self.assertEqual(frame.activity_intent, "debugging")


if __name__ == "__main__":
    unittest.main()
