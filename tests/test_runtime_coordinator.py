import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from domain import Decision
from runtime.coordinator import RuntimeCoordinator


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


class _DummyTransport:
    def __init__(self):
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)

    def close(self):
        return None

    def poll_json(self):
        return None


class _DummyLlmService:
    def __init__(self):
        self.chat_calls = 0

    def generate_chat_reply(self, **kwargs):
        self.chat_calls += 1
        return '{"text":"phan hoi dau tien","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'


class _DummyParser:
    def build_chat_user_message(self, *, user_message, last_chat_answer):
        return user_message

    def parse(self, raw, user_hint=""):
        return Decision(text="phan hoi dau tien", animation="stand")


class _DummyTelemetry:
    def capture_snapshot(self, **kwargs):
        return SimpleNamespace(
            active_window="",
            active_window_kind="general",
            idle_seconds=0.0,
            focus_summary="general",
            browser_url="",
            browser_tabs=(),
            open_windows=(),
            mood_score=50,
            mood_label="neutral",
            idle_label="active",
        )


class _CommunicationTelemetry:
    def capture_snapshot(self, **kwargs):
        return SimpleNamespace(
            active_window="Zalo",
            active_window_kind="communication",
            idle_seconds=120.0,
            focus_summary="communication",
            browser_url="",
            browser_tabs=(),
            open_windows=("Zalo",),
            mood_score=50,
            mood_label="neutral",
            idle_label="active",
        )


class _DummyNi:
    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(
            drift_score=0.0,
            drift_level="thap",
            prompt_context="",
            should_raise_guard=False,
            similarity=1.0,
            evidence=(),
        )


class _LowDriftNi:
    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(
            drift_score=0.2,
            drift_level="thap",
            prompt_context="",
            should_raise_guard=False,
            similarity=0.8,
            evidence=(),
        )


class _MetaLlmService(_DummyLlmService):
    def run_ni_meta_critic(self, **kwargs):
        return (
            '{"drift_score":1.0,"drift_level":"nghiem trong",'
            '"explanation":"meta overreact"}'
        )


class _DummyTi:
    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(
            mode="chat_general",
            reason="",
            prompt_context="",
            animation_hint="stand",
        )

    def enforce_decision(self, decision, report, user_hint=""):
        return decision


class _DummyFe:
    def create_memory(self):
        return SimpleNamespace()

    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(
            mode="chat_general",
            tone_label="",
            intent_label="ordinary_dialogue",
            session_arc="quiet_observation",
            style_context="",
        )

    def remember_style(self, memory, **kwargs):
        return memory

    def decay_memory(self, memory):
        return memory


class _DummyMemory:
    def append_fact(self, memory, fact):
        return memory


class _DummyActionRouter:
    def route_chat(self, user_text, *, last_action=""):
        lowered = (user_text or "").lower()
        if any(token in lowered for token in ("bài", "bai", "nhạc", "nhac")):
            return "get_now_playing", ""
        return None


class _DummyActionExecutor:
    def execute(self, action_name, action_input):
        return SimpleNamespace(
            action_name=action_name,
            action_input=action_input,
            success=True,
            message="",
            data={"title": "demo song", "artist": "demo artist"},
        )


class RuntimeCoordinatorTests(unittest.TestCase):
    def _make_coordinator(self, **overrides):
        params = {
            "logger": _DummyLogger(),
            "transport": _DummyTransport(),
            "llm_service": _DummyLlmService(),
            "parser": _DummyParser(),
            "telemetry_service": _DummyTelemetry(),
            "ni_engine": _DummyNi(),
            "ti_governor": _DummyTi(),
            "fe_renderer": _DummyFe(),
            "memory_store": _DummyMemory(),
            "body_running_fn": lambda: True,
        }
        params.update(overrides)
        return RuntimeCoordinator(**params)

    def test_repeated_chat_message_triggers_repeat_guard(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "xin chào"})
        coordinator._handle_incoming({"type": "chat", "message": "xin chào"})

        self.assertEqual(coordinator.llm_service.chat_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "repeat_guard")
        self.assertIn("lặp lại", coordinator.transport.sent[-1]["text"].lower())

    def test_near_duplicate_chat_message_triggers_repeat_guard(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "xin chào"})
        coordinator._handle_incoming({"type": "chat", "message": "xin chào nhé"})

        self.assertEqual(coordinator.llm_service.chat_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "repeat_guard")
        self.assertIn("lặp lại", coordinator.transport.sent[-1]["text"].lower())

    def test_near_duplicate_direct_action_gets_repeat_prefix(self):
        coordinator = self._make_coordinator(
            action_router=_DummyActionRouter(),
            action_executor=_DummyActionExecutor(),
        )

        coordinator._handle_incoming({"type": "chat", "message": "tên bài đó"})
        coordinator._handle_incoming({"type": "chat", "message": "bài đó là gì"})

        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "direct_action")
        self.assertIn("hỏi lại cùng một ý", coordinator.transport.sent[-1]["text"].lower())

    def test_chat_ni_meta_softens_low_signal_message(self):
        coordinator = self._make_coordinator(
            llm_service=_MetaLlmService(),
            ni_engine=_LowDriftNi(),
        )

        snapshot = coordinator.telemetry_service.capture_snapshot()
        report = coordinator.ni_engine.evaluate_chat()
        report = coordinator._maybe_apply_ni_meta_critic(
            mode="chat",
            snapshot=snapshot,
            base_report=report,
            telemetry_text=coordinator._build_ni_telemetry_summary(snapshot),
            user_text="xin chào",
        )

        self.assertLessEqual(report.drift_score, 0.45)
        self.assertEqual(report.drift_level, "vừa")
        self.assertFalse(report.should_raise_guard)


    def test_autonomous_ni_meta_softens_communication_overreaction(self):
        coordinator = self._make_coordinator(
            llm_service=_MetaLlmService(),
            telemetry_service=_CommunicationTelemetry(),
        )
        coordinator.ni_meta_auto_enabled = True

        snapshot = coordinator.telemetry_service.capture_snapshot()
        report = SimpleNamespace(
            drift_score=0.76,
            drift_level="cao",
            prompt_context="local context",
            should_raise_guard=True,
            evidence=(),
        )
        report = coordinator._maybe_apply_ni_meta_critic(
            mode="autonomous",
            snapshot=snapshot,
            base_report=report,
            telemetry_text=coordinator._build_ni_telemetry_summary(snapshot),
            last_text="",
        )

        self.assertLessEqual(report.drift_score, 0.72)
        self.assertNotIn("meta overreact", report.prompt_context)

    def test_chat_ni_state_isolated_from_autonomous_history(self):
        coordinator = self._make_coordinator()
        snapshot = coordinator.telemetry_service.capture_snapshot()
        high_drift = SimpleNamespace(drift_score=1.0)

        for _ in range(5):
            coordinator.autonomous_ni_state.update(snapshot=snapshot, report=high_drift)

        self.assertEqual(coordinator.autonomous_ni_state.current_state, "OFF_GOAL")

        coordinator._handle_incoming({"type": "chat", "message": "xin chao"})

        self.assertEqual(coordinator.chat_ni_state.current_state, "ON_GOAL")
        self.assertEqual(coordinator.chat_ni_state.streak_length, 1)
        self.assertEqual(coordinator.autonomous_ni_state.current_state, "OFF_GOAL")


if __name__ == "__main__":
    unittest.main()
