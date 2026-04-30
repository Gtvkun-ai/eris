import json
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
        self.directive_calls = 0
        self.last_directive_kwargs = {}

    def generate_chat_reply(self, **kwargs):
        self.chat_calls += 1
        return '{"text":"phan hoi dau tien","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'

    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        return '{"text":"toi len tieng ngay day","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'


class _DummyParser:
    def build_chat_user_message(self, *, user_message, last_chat_answer):
        return user_message

    def parse(self, raw, user_hint=""):
        return Decision(text="phan hoi dau tien", animation="stand")


class _JsonParser(_DummyParser):
    def parse(self, raw, user_hint=""):
        data = json.loads(raw)
        return Decision(
            text=data.get("text", ""),
            animation=data.get("animation", "stand"),
            extracted_fact=data.get("extracted_fact", ""),
            direction=int(data.get("direction", 0) or 0),
            target_x=float(data.get("target_x", -1.0) or -1.0),
            bounce_action=data.get("bounce_action", ""),
            debug_trace=data.get("debug_trace", ""),
            next_animation=data.get("next_animation", ""),
            system_action=data.get("system_action", ""),
            action_input=data.get("action_input", ""),
        )


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

    def format_directive_snapshot(self, snapshot):
        return "ambient cues"


class _SignalTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "main.py - Visual Studio Code"
        snapshot.active_window_kind = "coding"
        snapshot.focus_summary = "coding workspace"
        snapshot.recent_events = ("file_saved",)
        snapshot.evidence = ("active editor changed",)
        return snapshot


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
    def evaluate_autonomous(self, **kwargs):
        return SimpleNamespace(
            drift_score=0.0,
            drift_level="thap",
            prompt_context="",
            should_raise_guard=False,
            similarity=1.0,
            evidence=(),
        )

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
    def evaluate_autonomous(self, **kwargs):
        return SimpleNamespace(
            mode="steady_observe",
            reason="",
            prompt_context="Mode: steady_observe.",
            animation_hint="stand",
            force_animation=False,
            motion_intent_hint="",
            motion_target_x_hint=-1.0,
            motion_facing_hint=0,
            target_x_hint=-1.0,
            direction_hint=0,
        )

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

    def evaluate_autonomous(self, **kwargs):
        return SimpleNamespace(
            mode="grounded",
            tone_label="",
            intent_label="ordinary_dialogue",
            session_arc="quiet_observation",
            style_context="",
            sarcasm_level=0.0,
            warmth_level=0.0,
            brevity_bias="medium",
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


class _SearchActionExecutor:
    def execute(self, action_name, action_input):
        return SimpleNamespace(
            action_name=action_name,
            action_input=action_input,
            success=True,
            message="Một bài viết mới đang được bàn vì nó đặt lại câu hỏi về thói quen dùng AI.",
            data={
                "answer": "Một bài viết mới đang được bàn vì nó đặt lại câu hỏi về thói quen dùng AI.",
                "sources": "",
            },
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

    def test_force_speak_generates_immediate_directive_and_updates_cooldown(self):
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu cũ."
        coordinator.last_autonomous_spoken_at = 1.0

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertIn("force_speak", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertIn("Không có screen_facts mới", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertEqual(coordinator.llm_service.last_directive_kwargs["speech_intent"], "user_requested")
        self.assertEqual(coordinator.llm_service.last_directive_kwargs["avoid_text"], "Một câu cũ.")
        self.assertEqual(coordinator.transport.sent[-1]["text"], "phan hoi dau tien")
        self.assertEqual(coordinator.last_text, "phan hoi dau tien")
        self.assertGreater(coordinator.last_autonomous_spoken_at, 1.0)

    def test_autonomous_no_speech_intent_skips_llm_on_low_signal(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(coordinator.transport.sent, [])
        self.assertEqual(llm_service.directive_calls, 0)

    def test_speech_intent_selects_system_warning_for_resource_pressure(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="general",
            idle_seconds=4.0,
            recent_events=(),
            evidence=(),
            cpu_percent=94.0,
            ram_percent=60.0,
        )
        ti_report = SimpleNamespace(mode="steady_observe")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=1,
        )

        self.assertEqual(decision.intent, "system_warning")

    def test_generic_derived_telemetry_is_not_concrete_screen_signal(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="general",
            idle_seconds=4.0,
            recent_events=("general_window_active", "many_windows_open"),
            evidence=(
                "active window is Godot Engine",
                "focus kind is general",
                "there has been no input for 4 seconds",
                "10 windows are open",
                "recent events include general_window_active, many_windows_open",
            ),
            cpu_percent=20.0,
            ram_percent=40.0,
        )
        ti_report = SimpleNamespace(mode="steady_observe")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=1,
        )

        self.assertFalse(coordinator._has_concrete_screen_signal(snapshot))
        self.assertEqual(decision.intent, "no_speech")

    def test_explicit_runtime_event_counts_as_concrete_screen_signal(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="coding",
            idle_seconds=4.0,
            recent_events=("file_saved",),
            evidence=("active editor changed",),
            cpu_percent=20.0,
            ram_percent=40.0,
        )
        ti_report = SimpleNamespace(mode="steady_observe")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=1,
        )

        self.assertTrue(coordinator._has_concrete_screen_signal(snapshot))
        self.assertEqual(decision.intent, "screen_observation")
        self.assertIn("file_saved", decision.reason)

    def test_speech_intent_selects_playful_aside_for_pattern_muse(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="general",
            idle_seconds=800.0,
            recent_events=(),
            evidence=(),
            cpu_percent=20.0,
            ram_percent=40.0,
        )
        ti_report = SimpleNamespace(mode="pattern_muse")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=1,
        )

        self.assertEqual(decision.intent, "playful_aside")

    def test_idle_repeated_low_signal_stays_silent(self):
        coordinator = self._make_coordinator(action_executor=_DummyActionExecutor())
        snapshot = SimpleNamespace(
            active_window_kind="general",
            idle_seconds=220.0,
            recent_events=("general_window_active",),
            evidence=("active window is Desktop",),
            cpu_percent=20.0,
            ram_percent=40.0,
        )
        ti_report = SimpleNamespace(mode="steady_observe")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=2,
        )

        self.assertEqual(decision.intent, "no_speech")

    def test_idle_long_repeated_low_signal_stays_silent(self):
        coordinator = self._make_coordinator(action_executor=_DummyActionExecutor())
        snapshot = SimpleNamespace(
            active_window_kind="general",
            idle_seconds=500.0,
            recent_events=("general_window_active",),
            evidence=("active window is Desktop",),
            cpu_percent=20.0,
            ram_percent=40.0,
        )
        ti_report = SimpleNamespace(mode="steady_observe")

        decision = coordinator._choose_autonomous_speech_intent(
            snapshot=snapshot,
            ni_report=SimpleNamespace(drift_score=0.0),
            ti_report=ti_report,
            repeat_count=4,
        )

        self.assertEqual(decision.intent, "no_speech")

    def test_search_action_replaces_placeholder_text(self):
        coordinator = self._make_coordinator(action_executor=_SearchActionExecutor())
        decision = Decision(
            text="Tôi đi tìm một mẩu để bàn.",
            animation="read",
            system_action="search_web",
            action_input="recent AI culture article",
        )

        decision = coordinator._execute_system_action(
            decision,
            snapshot=SimpleNamespace(),
        )

        self.assertIn("thói quen dùng AI", decision.text)
        self.assertIn("action=search_web:ok", decision.debug_trace)

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
        self.assertEqual(report.drift_level, "thấp")
        self.assertGreaterEqual(report.confidence, 0.1)
        self.assertIn("chat_low_signal_cap", report.reason_span)
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

    def test_autonomous_repeat_guard_suppresses_quiet_modes(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window="Task Manager",
            active_window_kind="system",
            focus_summary="system monitoring",
            browser_url="",
            browser_tabs=(),
            open_windows=("Task Manager", "Visual Studio Code"),
            cpu_percent=91.0,
            ram_percent=93.0,
            idle_seconds=12.0,
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )
        ti_report = SimpleNamespace(mode="resource_guard")

        _, repeat_count_1 = coordinator._track_autonomous_signature(snapshot, ti_report)
        _, repeat_count_2 = coordinator._track_autonomous_signature(snapshot, ti_report)

        self.assertEqual(repeat_count_1, 1)
        self.assertEqual(repeat_count_2, 2)
        self.assertTrue(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=repeat_count_2,
            )
        )

    def test_autonomous_repeat_guard_resets_when_context_changes(self):
        coordinator = self._make_coordinator()
        ti_report = SimpleNamespace(mode="focus_guard")
        snapshot_a = SimpleNamespace(
            active_window="main.py - Visual Studio Code",
            active_window_kind="coding",
            focus_summary="coding workspace",
            browser_url="",
            browser_tabs=(),
            open_windows=("main.py - Visual Studio Code",),
            cpu_percent=35.0,
            ram_percent=58.0,
            idle_seconds=4.0,
            user_signals=SimpleNamespace(focus_pattern="deep_work"),
        )
        snapshot_b = SimpleNamespace(
            active_window="README.md - Visual Studio Code",
            active_window_kind="documentation",
            focus_summary="documentation reading",
            browser_url="",
            browser_tabs=(),
            open_windows=("README.md - Visual Studio Code",),
            cpu_percent=35.0,
            ram_percent=58.0,
            idle_seconds=4.0,
            user_signals=SimpleNamespace(focus_pattern="deep_work"),
        )

        signature_a, repeat_count_a = coordinator._track_autonomous_signature(snapshot_a, ti_report)
        signature_b, repeat_count_b = coordinator._track_autonomous_signature(snapshot_b, ti_report)

        self.assertNotEqual(signature_a, signature_b)
        self.assertEqual(repeat_count_a, 1)
        self.assertEqual(repeat_count_b, 1)
        self.assertFalse(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=repeat_count_b,
            )
        )

    def test_autonomous_signature_ignores_resource_pressure_changes(self):
        coordinator = self._make_coordinator()
        ti_report = SimpleNamespace(mode="steady_observe")
        snapshot = SimpleNamespace(
            active_window="Godot Engine",
            active_window_kind="general",
            focus_summary="general",
            browser_url="",
            browser_tabs=(),
            open_windows=("Godot Engine",),
            cpu_percent=35.0,
            ram_percent=58.0,
            idle_seconds=4.0,
            user_signals=SimpleNamespace(focus_pattern="steady"),
        )

        signature_normal = coordinator._build_autonomous_signature(snapshot, ti_report)
        snapshot.cpu_percent = 99.0
        snapshot.ram_percent = 98.0
        signature_hot = coordinator._build_autonomous_signature(snapshot, ti_report)

        self.assertEqual(signature_normal, signature_hot)
        self.assertNotIn("resource=", signature_hot)

    def test_focus_guard_suppresses_low_drift_on_goal_even_first_cycle(self):
        coordinator = self._make_coordinator()
        ti_report = SimpleNamespace(mode="focus_guard")
        ni_report = SimpleNamespace(drift_score=0.12)

        self.assertTrue(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=1,
                ni_report=ni_report,
                ni_state_label="ON_GOAL",
            )
        )

    def test_autonomous_repeat_guard_suppresses_repeated_topic_in_quiet_mode(self):
        coordinator = self._make_coordinator()
        ti_report = SimpleNamespace(mode="steady_observe")

        self.assertTrue(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=1,
                repeated_topic_tag="window_sprawl",
                repeated_topic_streak=2,
            )
        )

    def test_ambient_silence_holds_quiet_autonomous_modes_after_recent_line(self):
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu vừa nói xong."
        coordinator.last_autonomous_spoken_at = 100.0
        snapshot = SimpleNamespace(active_window_kind="coding")
        ti_report = SimpleNamespace(mode="steady_observe")

        self.assertTrue(
            coordinator._should_hold_ambient_silence(
                snapshot=snapshot,
                ti_report=ti_report,
                now=220.0,
            )
        )
        self.assertFalse(
            coordinator._should_hold_ambient_silence(
                snapshot=snapshot,
                ti_report=ti_report,
                now=330.0,
            )
        )

    def test_ambient_silence_does_not_hold_resource_guard(self):
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu vừa nói xong."
        coordinator.last_autonomous_spoken_at = 100.0
        snapshot = SimpleNamespace(active_window_kind="general")
        ti_report = SimpleNamespace(mode="resource_guard")

        self.assertFalse(
            coordinator._should_hold_ambient_silence(
                snapshot=snapshot,
                ti_report=ti_report,
                now=120.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
