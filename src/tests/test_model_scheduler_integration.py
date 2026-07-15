import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.coordinator import RuntimeCoordinator


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None


class _RecordingPolicy:
    def __init__(self):
        self.calls = []

    def run_queued(self, tier, func, *args, reason="", priority=0, **kwargs):
        self.calls.append(
            {
                "tier": tier,
                "reason": reason,
                "priority": priority,
                "args": args,
                "kwargs": kwargs,
            }
        )
        return func(*args, **kwargs)


class _FakeLlmService:
    def generate_chat_reply(self, **kwargs):
        return {"ok": True, "kind": "chat", "kwargs": kwargs}

    def generate_directive(self, **kwargs):
        return {"ok": True, "kind": "directive", "kwargs": kwargs}

    def generate_screen_facts(self, **kwargs):
        return (["fact"], "trace")


class _FakeSensoryAdapter:
    def __init__(self):
        self.calls = []

    def observe(self, **kwargs):
        self.calls.append(kwargs)
        return {"recommended_action": "observe_only"}


class ModelSchedulerIntegrationTests(unittest.TestCase):
    def test_install_model_inference_queue_wraps_sensory_adapter(self):
        coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
        coordinator.logger = _DummyLogger()
        coordinator.llm_service = _FakeLlmService()
        coordinator.sensory_model_adapter = _FakeSensoryAdapter()
        coordinator.model_budget_policy = _RecordingPolicy()

        RuntimeCoordinator._install_model_inference_queue(coordinator)

        result = coordinator.sensory_model_adapter.observe(snapshot="snap", diff="diff")

        self.assertEqual(result["recommended_action"], "observe_only")
        self.assertEqual(len(coordinator.model_budget_policy.calls), 1)
        self.assertEqual(coordinator.model_budget_policy.calls[0]["tier"], "sensory_0_6b")
        self.assertEqual(coordinator.model_budget_policy.calls[0]["priority"], 18)
        self.assertIn("observe", coordinator.model_budget_policy.calls[0]["reason"])


if __name__ == "__main__":
    unittest.main()
