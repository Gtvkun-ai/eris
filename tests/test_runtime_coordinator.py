import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import runtime.coordinator as coordinator_module

from domain import Decision
from cortex.contracts import CognitiveBroadcast, CognitiveMomentum, ThoughtStreamReport, UnresolvedTensionLoop
from cortex.internal_state import PersistentInternalState
from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.observer_contracts import SemanticSceneNote
from cortex.surface_arbiter import SurfaceArbiter
from memory.memory_cognition import MemoryCognitionCore
from runtime.coordinator import FALLBACK_BY_INTENT, RuntimeCoordinator
from runtime.presence_controller import SurfaceImpulse
from runtime.source_grounding import SourceGroundingEngine


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


class _RecordingLogger(_DummyLogger):
    def __init__(self):
        self.info_messages = []

    def info(self, message, *args, **kwargs):
        if args:
            message = message % args
        self.info_messages.append(str(message))
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


class _QueuedTransport(_DummyTransport):
    def __init__(self, incoming):
        super().__init__()
        self.incoming = list(incoming)

    def poll_json(self):
        if not self.incoming:
            return None
        return self.incoming.pop(0)


class _DummyLlmService:
    def __init__(self):
        self.chat_calls = 0
        self.directive_calls = 0
        self.last_chat_kwargs = {}
        self.last_directive_kwargs = {}

    def generate_chat_reply(self, **kwargs):
        self.chat_calls += 1
        self.last_chat_kwargs = kwargs
        return '{"text":"phan hoi dau tien","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'

    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        return '{"text":"toi len tieng ngay day","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'


class _DummyMemorySemanticParser:
    def parse(self, text: str, *, structured=None):
        return None


class _VisionFactLlmService(_DummyLlmService):
    def __init__(self, facts):
        super().__init__()
        self.facts = tuple(facts)
        self.screen_fact_calls = 0

    def generate_screen_facts(self, **kwargs):
        self.screen_fact_calls += 1
        return list(self.facts), "vision_facts_v1"


class _RepeatingForceSpeakLlmService(_DummyLlmService):
    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        return (
            '{"text":"Ngài vừa yêu cầu tôi nói ngay. Tôi sẽ giữ lời đó.",'
            '"animation":"stand","direction":0,"target_x":-1.0,'
            '"bounce_action":"","next_animation":"","system_action":"","action_input":""}'
        )


class _GenericThenSocialLlmService(_DummyLlmService):
    def __init__(self):
        super().__init__()
        self._texts = [
            "Ngài muốn tôi nói gì đây.",
            "Tạm bỏ màn hình qua một bên. Ngài thích buổi sáng yên hay buổi đêm yên hơn.",
        ]

    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        text = self._texts.pop(0)
        return json.dumps(
            {
                "text": text,
                "animation": "stand",
                "direction": 0,
                "target_x": -1.0,
                "bounce_action": "",
                "next_animation": "",
                "system_action": "",
                "action_input": "",
            }
        )


class _MindreadingForceSpeakLlmService(_DummyLlmService):
    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        return json.dumps(
            {
                "text": "Co ve Ngai dang met.",
                "animation": "stand",
                "direction": 0,
                "target_x": -1.0,
                "bounce_action": "",
                "next_animation": "",
                "system_action": "",
                "action_input": "",
            }
        )


class _StaticDirectiveLlmService(_DummyLlmService):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def generate_directive(self, **kwargs):
        self.directive_calls += 1
        self.last_directive_kwargs = kwargs
        return json.dumps(
            {
                "text": self.text,
                "animation": "stand",
                "direction": 0,
                "target_x": -1.0,
                "bounce_action": "",
                "next_animation": "",
                "system_action": "",
                "action_input": "",
            }
        )


class _HybridMicroLlmService(_DummyLlmService):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.micro_calls = 0

    def generate_micro_presence_line(self, **kwargs):
        self.micro_calls += 1
        self.last_micro_kwargs = kwargs
        return self.text


class _ModernMicroLlmService(_DummyLlmService):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.micro_calls = 0
        self.last_micro_kwargs = {}

    def generate_micro_presence(self, **kwargs):
        self.micro_calls += 1
        self.last_micro_kwargs = kwargs
        return self.text


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


class _LongIdleTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.idle_seconds = 500.0
        snapshot.idle_label = "idle"
        return snapshot


class _LongSilentTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "Desktop"
        snapshot.active_window_kind = "general"
        snapshot.focus_summary = "quiet desktop"
        snapshot.idle_seconds = 1200.0
        snapshot.idle_label = "idle"
        snapshot.recent_events = ()
        snapshot.evidence = ()
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="zero",
            focus_pattern="absent",
        )
        return snapshot


class _LongSilentAmbientTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = ""
        snapshot.active_window_kind = "general"
        snapshot.focus_summary = "quiet"
        snapshot.idle_seconds = 900.0
        snapshot.idle_label = "idle"
        snapshot.recent_events = ()
        snapshot.evidence = ()
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="zero",
            focus_pattern="quiet",
        )
        return snapshot


class _SignalTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "main.py - Visual Studio Code"
        snapshot.active_window_kind = "coding"
        snapshot.focus_summary = "coding workspace"
        snapshot.recent_events = ("file_saved",)
        snapshot.evidence = ("active editor changed",)
        return snapshot


class _PresenceTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "main.py - Visual Studio Code"
        snapshot.active_window_kind = "coding"
        snapshot.focus_summary = "coding workspace"
        snapshot.idle_seconds = 3.0
        snapshot.recent_events = ("mouse_moved",)
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="low",
            focus_pattern="steady",
        )
        return snapshot


class _PressureSignalTelemetry(_SignalTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.cpu_percent = 22.0
        snapshot.ram_percent = 91.0
        return snapshot


class _PressureScreenTelemetry(_PressureSignalTelemetry):
    def capture_screen_frame_data_uri(self):
        return "data:image/jpeg;base64,AAAA"


class _ScreenTelemetry(_DummyTelemetry):
    def capture_screen_frame_data_uri(self):
        return "data:image/jpeg;base64,AAAA"


class _FakeVisionCompressor:
    def __init__(self, note: SemanticSceneNote, *, should_compress: bool = True):
        self.note = note
        self.should_compress_value = should_compress
        self.should_calls = 0
        self.compress_calls = 0
        self.last_kwargs = {}

    def should_compress(self, **kwargs):
        self.should_calls += 1
        self.last_should_kwargs = kwargs
        return self.should_compress_value

    def compress(self, **kwargs):
        self.compress_calls += 1
        self.last_kwargs = kwargs
        return self.note


class _MeetScreenTelemetry(_ScreenTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "Meet - Microsoft Edge"
        snapshot.active_window_kind = "communication"
        snapshot.focus_summary = "Meet room open"
        snapshot.idle_seconds = 90.0
        snapshot.idle_label = "idle"
        snapshot.recent_events = ()
        snapshot.evidence = ()
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="zero",
            focus_pattern="quiet",
        )
        return snapshot


class _TongquatTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "tongquat.md - Visual Studio Code"
        snapshot.active_window_kind = "coding"
        snapshot.focus_summary = "editing tongquat.md"
        snapshot.idle_seconds = 75.0
        snapshot.idle_label = "focused"
        snapshot.recent_events = ()
        snapshot.evidence = ("active editor tongquat.md",)
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="zero",
            focus_pattern="steady",
        )
        return snapshot


class _AmbientPresenceTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = ""
        snapshot.active_window_kind = "general"
        snapshot.focus_summary = "quiet"
        snapshot.idle_seconds = 90.0
        snapshot.idle_label = "idle"
        snapshot.recent_events = ()
        snapshot.evidence = ()
        snapshot.user_signals = SimpleNamespace(
            typing_speed="zero",
            window_switching="zero",
            focus_pattern="quiet",
        )
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

    def enforce_decision(self, decision, report, user_hint="", vision_grounded=False):
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
    def __init__(self):
        self._packet = SimpleNamespace(
            repair=[],
            procedural=[],
            semantic=[],
            relational=[],
            affective_residue=[],
            episodic=[],
            score=0.0,
            dominant_layer="",
            attention_bias=0.0,
            appraisal_bias=0.0,
            wording_bias=0.0,
            silence_bias=0.0,
            render_prompt_context=lambda **kwargs: "",
            to_attention_lines=lambda **kwargs: (),
        )

    def load(self):
        return None

    def save(self, snapshot=None):
        return None

    def recall(self, query=""):
        return self._packet

    def render_context(self, query="", **kwargs):
        return ""

    def commit(self, request, *, frame=None):
        return SimpleNamespace(outcome="accepted", target=getattr(request, "target", None))


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


class _ExplodingOllamaClient:
    def chat_json(self, *args, **kwargs):
        raise AssertionError("Ollama should not be called when ERIS_BACKGROUND_OBSERVER_LLM=0")


class RuntimeCoordinatorTests(unittest.TestCase):
    def setUp(self):
        os.environ["ERIS_GUARD_MODE"] = "strict"

    @staticmethod
    def _request_field(request, field_name, default=None):
        if isinstance(request, dict):
            return request.get(field_name, default)
        return getattr(request, field_name, default)

    def _make_coordinator(self, **overrides):
        os.environ["ERIS_GUARD_MODE"] = overrides.pop("guard_mode", "strict")
        params = {
            "logger": _DummyLogger(),
            "transport": _DummyTransport(),
            "llm_service": _DummyLlmService(),
            "parser": _DummyParser(),
            "telemetry_service": _DummyTelemetry(),
            "ni_engine": _DummyNi(),
            "ti_governor": _DummyTi(),
            "fe_renderer": _DummyFe(),
            "memory_core": _DummyMemory(),
            "body_running_fn": lambda: True,
        }
        params.update(overrides)
        return RuntimeCoordinator(**params)

    def test_subconscious_loop_starts_and_stops_cleanly(self):
        coordinator = self._make_coordinator()
        coordinator.subconscious_loop.interval_seconds = 60.0

        coordinator.subconscious_loop.start()
        self.assertTrue(coordinator.subconscious_loop.is_running)
        coordinator.stop()

        self.assertFalse(coordinator.subconscious_loop.is_running)

    def test_memory_commit_policy_receives_semantic_parser_from_constructor(self):
        parser = _DummyMemorySemanticParser()
        coordinator = self._make_coordinator(memory_semantic_parser=parser)

        self.assertIs(coordinator.memory_semantic_parser, parser)
        self.assertIs(coordinator.memory_commit_policy.semantic_parser, parser)

    def test_memory_commit_policy_syncs_semantic_parser_if_attached_late(self):
        parser = _DummyMemorySemanticParser()
        coordinator = self._make_coordinator()

        coordinator.memory_semantic_parser = parser
        policy = coordinator._ensure_memory_commit_policy()

        self.assertIs(policy.semantic_parser, parser)

    def test_send_decision_to_body_records_public_turn(self):
        coordinator = self._make_coordinator()
        decision = Decision(text="Tôi đang ở đây.", animation="stand", parse_mode="json")

        coordinator._send_decision_to_body(decision, channel="chat")

        turns = coordinator.public_turn_ledger.all()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].channel, "chat")
        self.assertEqual(turns[0].text, "Tôi đang ở đây.")
        self.assertEqual(turns[0].parse_mode, "json")
        self.assertTrue(turns[0].visible_to_user)
        self.assertTrue(turns[0].can_be_replied_to)
        self.assertEqual(coordinator.transport.sent[0]["text"], "Tôi đang ở đây.")

    def test_public_turn_ledger_skips_suppressed_or_empty_body_text(self):
        coordinator = self._make_coordinator()

        coordinator._send_decision_to_body(Decision(text="...", animation="stand", should_speak=True))
        coordinator._send_decision_to_body(Decision(text="Không gửi câu này.", animation="stand", should_speak=False))

        self.assertEqual(coordinator.public_turn_ledger.all(), ())
        self.assertEqual(len(coordinator.transport.sent), 2)

    def test_public_turn_ledger_infers_special_channels(self):
        coordinator = self._make_coordinator()

        coordinator._send_decision_to_body(Decision(text="Chào lại Ngài.", animation="stand", parse_mode="session_ritual"))
        coordinator._send_decision_to_body(Decision(text="Tôi vẫn ở đây.", animation="stand", parse_mode="presence_maintenance"))
        coordinator._send_decision_to_body(Decision(text="Ngài còn đó chứ.", animation="stand", parse_mode="re_engagement"))

        self.assertEqual(
            [turn.channel for turn in coordinator.public_turn_ledger.all()],
            ["session_ritual", "presence", "reengagement"],
        )

    def test_wake_gate_ti_report_matches_ti_enforce_shape(self):
        coordinator = self._make_coordinator()

        report = coordinator._wake_gate_ti_report(reason="test")

        self.assertEqual(report.mode, "steady_observe")
        self.assertFalse(report.force_animation)
        self.assertEqual(report.motion_intent_hint, "")
        self.assertEqual(report.motion_target_x_hint, -1.0)
        self.assertEqual(report.motion_facing_hint, 0)
        self.assertEqual(report.target_x_hint, -1.0)
        self.assertEqual(report.direction_hint, 0)

    def test_wake_gate_fe_plan_uses_numeric_style_axes(self):
        coordinator = self._make_coordinator()

        plan = coordinator._wake_gate_fe_plan(
            ti_report=SimpleNamespace(mode="steady_observe"),
            snapshot=SimpleNamespace(active_window_kind="coding"),
            internal_state=SimpleNamespace(last_focus_kind="coding"),
        )

        self.assertIsInstance(plan.warmth_level, float)
        self.assertEqual(plan.warmth_level, 0.18)
        self.assertEqual(plan.sarcasm_level, 0.0)

    def test_chat_links_recent_public_turn_as_reply_context(self):
        coordinator = self._make_coordinator()
        coordinator.public_turn_ledger.append(
            channel="session_ritual",
            text="Ngài quay lại rồi.",
            timestamp=100.0,
            parse_mode="session_ritual",
        )

        coordinator._run_chat_cycle("ừ", user_timestamp=110.0)

        previous = coordinator.reply_context.previous_public_turn
        self.assertIsNotNone(previous)
        self.assertEqual(previous.text, "Ngài quay lại rồi.")
        self.assertIs(coordinator.llm_service.last_chat_kwargs["reply_context"], coordinator.reply_context)
        self.assertIn("previous_public_turn", coordinator.llm_service.last_chat_kwargs["ti_context"])

    def test_chat_memory_recall_counts_current_user_question_before_llm(self):
        coordinator = self._make_coordinator(parser=_JsonParser())

        coordinator._run_chat_cycle("toi da hoi bao nhieu cau", user_timestamp=100.0)

        self.assertEqual(coordinator.llm_service.chat_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["intent"], "memory_recall")
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "memory_recall")
        self.assertIn("1", coordinator.transport.sent[-1]["text"])
        self.assertEqual([turn.role for turn in coordinator.session_turn_ledger.all_turns()], ["user", "assistant"])

    def test_chat_memory_recall_can_quote_previous_public_assistant_turn(self):
        coordinator = self._make_coordinator(parser=_JsonParser())

        coordinator._run_chat_cycle("xin chao", user_timestamp=100.0)
        coordinator._run_chat_cycle("cau thu 1 em noi la gi", user_timestamp=101.0)

        self.assertEqual(coordinator.llm_service.chat_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["intent"], "memory_recall")
        self.assertIn("phan hoi dau tien", coordinator.transport.sent[-1]["text"])
        self.assertEqual(len(coordinator.session_turn_ledger.assistant_turns()), 2)

    def test_chat_memory_recall_final_guard_blocks_memory_packet_repr(self):
        coordinator = self._make_coordinator(parser=_JsonParser())
        coordinator._build_memory_recall_decision = lambda user_text: Decision(
            text="Tên Ngài là MemoryPacket(episodic=[], semantic=[], token_budget=900, source_counts={'semantic': 0}).",
            intent="memory_recall",
            action="answer",
            animation="stand",
            should_speak=True,
            parse_mode="memory_recall",
        )

        coordinator._run_chat_cycle("toi ten gi", user_timestamp=100.0)

        sent_text = coordinator.transport.sent[-1]["text"]
        self.assertNotIn("MemoryPacket(", sent_text)
        self.assertIn("dữ liệu nội bộ", sent_text)
        self.assertEqual(coordinator.transport.sent[-1]["intent"], "repair_surface_leak")

    def test_chat_user_turn_fast_ingest_commits_through_memory_kernel(self):
        coordinator = self._make_coordinator(parser=_JsonParser())
        with patch.object(coordinator.memory_kernel, "ingest", wraps=coordinator.memory_kernel.ingest) as ingest:
            coordinator._run_chat_cycle("toi ten la An", user_timestamp=100.0)

        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
        requests = list(getattr(frame, "commit_requests", []) or [])
        semantic_requests = [
            request for request in requests
            if self._request_field(request, "target", "") == "semantic_memory"
        ]
        self.assertEqual(semantic_requests, [])
        ingest.assert_called()
        _, kwargs = ingest.call_args
        self.assertEqual(kwargs.get("mode"), "fast")
        self.assertEqual(kwargs.get("turn_id"), "session_turn:1")
        self.assertEqual(kwargs.get("evidence_ids"), ["session_turn:1"])

    def test_chat_does_not_link_stale_public_turn(self):
        coordinator = self._make_coordinator()
        coordinator.public_turn_ledger.append(
            channel="presence",
            text="Tôi vẫn ở đây.",
            timestamp=10.0,
            parse_mode="presence_maintenance",
        )

        coordinator._run_chat_cycle("alo", user_timestamp=100.0)

        self.assertIsNone(coordinator.reply_context.previous_public_turn)

    def test_rapid_chat_burst_merges_before_llm(self):
        transport = _QueuedTransport(
            [
                {"type": "chat", "message": "gì vậy trời", "timestamp": 101.0},
                {"type": "chat", "message": "ủa alo", "timestamp": 101.1},
            ]
        )
        coordinator = self._make_coordinator(transport=transport)
        coordinator.rapid_burst_window = 0.0

        coordinator._run_chat_cycle("đúng rồi", user_timestamp=100.0)

        self.assertEqual(coordinator.llm_service.chat_calls, 1)
        self.assertEqual(
            coordinator.llm_service.last_chat_kwargs["raw_user_text"],
            "đúng rồi\ngì vậy trời\nủa alo",
        )

    def test_session_ritual_blocks_immediate_presence_maintenance(self):
        coordinator = self._make_coordinator()
        coordinator.presence_maintenance_enabled = True
        coordinator.presence_maintenance_silent_cycles = 3
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._block_autonomous_presence_after_public_turn(now=100.0)
        snapshot = coordinator.telemetry_service.capture_snapshot()
        ti_report = SimpleNamespace(mode="steady_observe")
        social_presence_event = SimpleNamespace(present=True)

        allowed = coordinator._should_allow_presence_maintenance(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=101.0,
        )

        self.assertFalse(allowed)

    def test_subconscious_report_appears_in_cognitive_frame_dict(self):
        coordinator = self._make_coordinator()
        frame = coordinator._start_cognitive_frame(
            channel="autonomous",
            started_at=1.0,
            snapshot=coordinator.telemetry_service.capture_snapshot(),
            internal_state_before=PersistentInternalState(),
            sensed_internal_state=PersistentInternalState(),
            ni_report=SimpleNamespace(drift_score=0.0, confidence=0.50, should_raise_guard=False),
            ti_report=SimpleNamespace(mode="steady_observe"),
            fe_plan=SimpleNamespace(warmth_level=0.0, sarcasm_level=0.0),
        )

        self.assertIn("subconscious_report", frame.to_dict())
        self.assertIn("latest_seed", frame.to_dict()["subconscious_report"])
        self.assertIn("self_state", frame.to_dict())
        self.assertIn("personality_lens", frame.to_dict())
        self.assertIn("suppression_ratio", frame.to_dict()["personality_lens"])
        self.assertIn(frame.to_dict()["self_state"]["state_label"], {"settled", "watchful", "engaged", "overloaded"})

    def test_chat_event_disturbs_continuous_substrate(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "continuous substrate please"})

        frame = coordinator.last_cognitive_frame
        self.assertIs(coordinator.cognitive_substrate, coordinator.thought_stream)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.channel, "chat")
        self.assertEqual(frame.thought_stream_report.disturbances[0].channel, "chat")
        self.assertEqual(frame.thought_stream_report.disturbances[0].kind, "user_message")
        self.assertEqual(frame.thought_stream_report.latest_thought.mode, "input_disturbance")
        self.assertTrue(any(percept.kind == "substrate_disturbance" for percept in frame.percepts))

    def test_chat_uses_light_semantic_pressure_without_autonomous_symbolic_reading(self):
        llm = _DummyLlmService()
        coordinator = self._make_coordinator(llm_service=llm)

        coordinator._handle_incoming({"type": "chat", "message": "fix bug trong chat_cycle.py, dung overread nua"})

        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.channel, "chat")
        self.assertEqual(frame.meaning_layer.source_fact, "chat_user_text")
        self.assertIn(frame.meaning_layer.meaning, {"technical_directive", "technical_question"})
        self.assertEqual(frame.meaning_layer.meaning_signal, "chat_light_semantic_intent")
        self.assertIn("overread_brake", frame.personality_lens.attention_bias)
        self.assertEqual(frame.personality_lens.profile, "CHAT_LIGHT")
        self.assertIn("ChatPersonalityPressureLight", llm.last_chat_kwargs["fe_context"])
        self.assertIn("do not infer hidden motives", frame.meaning_layer.prompt_context)
        self.assertNotIn("escape_from_friction", frame.meaning_layer.prompt_context)
        self.assertNotIn("existential", frame.meaning_layer.prompt_context.lower())

    def test_chat_correction_updates_conversation_dynamics_and_prompt_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            llm = _DummyLlmService()
            coordinator = self._make_coordinator(
                memory_core=MemoryCognitionCore(path),
                llm_service=llm,
            )

            coordinator._handle_incoming({"type": "chat", "message": "giai thich state loop"})
            coordinator._handle_incoming({"type": "chat", "message": "sai roi, y toi khong phai vay"})

            self.assertEqual(llm.chat_calls, 2)
            self.assertIn("conversation_state: mode=repair", llm.last_chat_kwargs["conversation_context"])
            self.assertTrue(
                any(
                    item.get("role") == "assistant" and item.get("invalid")
                    for item in coordinator.chat_history
                )
            )
            saved_payload = MemoryCognitionCore(path).load().get("active_state", {}).get("metadata", {}).get("internal_state", {})
            saved_state = PersistentInternalState.from_dict(saved_payload)
            self.assertEqual(saved_state.conversation_dynamics.mode, "repair")
            self.assertGreater(saved_state.conversation_dynamics.semantic_tension, 0.4)

    def test_cognitive_momentum_report_enters_attention_as_internal_percept(self):
        coordinator = self._make_coordinator()
        report = ThoughtStreamReport(
            momentum=CognitiveMomentum(
                thought_id="thought_1",
                mode="associative_drift",
                topic_seed="associative_drift:project_eris_tests",
                score=0.74,
                tension=0.82,
                recurrence_count=2,
                unresolved=True,
                user_project_relevance=0.82,
                affordance="attention",
                evidence=("reactivations=2", "momentum=0.74"),
                risk_flags=("no_screen_claim", "cognitive_momentum"),
            )
        )

        percepts = coordinator._collect_percept_events(
            channel="autonomous",
            snapshot=coordinator.telemetry_service.capture_snapshot(),
            thought_stream_report=report,
        )
        candidates = coordinator._build_attention_candidates(percepts, channel="autonomous")
        broadcast = coordinator._build_broadcast(candidates)

        self.assertIn("cognitive_momentum", {item.kind for item in percepts})
        self.assertEqual(broadcast.label, "cognitive_momentum")

    def test_unresolved_tension_attractor_enters_attention_as_internal_percept(self):
        coordinator = self._make_coordinator()
        report = ThoughtStreamReport(
            active_attractor=UnresolvedTensionLoop(
                loop_id="loop_1",
                topic_seed="associative_drift:project_eris_tests",
                thought_ids=("thought_1", "thought_2"),
                score=0.78,
                tension=0.84,
                recurrence_count=3,
                unresolved_count=2,
                attractor=True,
                evidence=("loop_score=0.78", "attractor=1"),
                risk_flags=("no_screen_claim", "cognitive_attractor"),
            )
        )

        percepts = coordinator._collect_percept_events(
            channel="autonomous",
            snapshot=coordinator.telemetry_service.capture_snapshot(),
            thought_stream_report=report,
        )
        candidates = coordinator._build_attention_candidates(percepts, channel="autonomous")
        broadcast = coordinator._build_broadcast(candidates)

        self.assertIn("cognitive_attractor", {item.kind for item in percepts})
        self.assertEqual(broadcast.label, "cognitive_attractor")

    def test_persistent_goal_enters_attention_as_internal_percept(self):
        coordinator = self._make_coordinator()
        state = PersistentInternalState.from_dict(
            {
                "goal_persistence": {
                    "goal_id": "goal_1",
                    "summary": "implement goal persistence across events",
                    "status": "active",
                    "strength": 0.78,
                    "urgency": 0.62,
                    "evidence": ["direct_user_goal"],
                }
            }
        )

        percepts = coordinator._collect_percept_events(
            channel="autonomous",
            snapshot=coordinator.telemetry_service.capture_snapshot(),
            internal_state=state,
        )
        candidates = coordinator._build_attention_candidates(percepts, channel="autonomous")
        broadcast = coordinator._build_broadcast(candidates)

        self.assertIn("persistent_goal", {item.kind for item in percepts})
        self.assertEqual(broadcast.label, "persistent_goal")

    def test_social_presence_event_is_background_not_broadcast_speech_signal(self):
        coordinator = self._make_coordinator(telemetry_service=_PresenceTelemetry())
        state = PersistentInternalState(last_focus_kind="coding")
        snapshot = coordinator.telemetry_service.capture_snapshot()
        presence = coordinator._detect_social_presence_event(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=state,
            started_at=1.0,
        )

        percepts = coordinator._collect_percept_events(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=state,
            social_presence_event=presence,
            started_at=1.0,
        )
        candidates = coordinator._build_attention_candidates(percepts, channel="autonomous", snapshot=snapshot)
        broadcast = coordinator._build_broadcast(candidates)

        self.assertTrue(presence.present)
        self.assertFalse(presence.speech_allowed)
        self.assertIn("social_presence_event", {item.kind for item in percepts})
        self.assertNotEqual(broadcast.label, "social_presence_event")

    def test_background_observer_phase1_runs_end_to_end_without_ollama(self):
        with patch.dict(
            os.environ,
            {
                "ERIS_BACKGROUND_OBSERVER": "1",
                "ERIS_BACKGROUND_OBSERVER_LLM": "0",
            },
            clear=False,
        ):
            coordinator = self._make_coordinator(telemetry_service=_PressureSignalTelemetry())

        coordinator.background_observer.ollama_client = _ExplodingOllamaClient()
        snapshot = coordinator.telemetry_service.capture_snapshot()

        frame = coordinator._run_background_observer(
            snapshot=snapshot,
            channel="autonomous",
            started_at=1.0,
        )

        self.assertIsNotNone(frame)
        self.assertIs(frame, coordinator.last_observer_frame)
        self.assertEqual(frame.focus_kind, "code")
        self.assertEqual(frame.activity_intent, "designing")
        self.assertIn("rule_based_observer", frame.notes)
        self.assertFalse(frame.debug.get("llm_used", False))
        self.assertGreaterEqual(frame.salience, 0.42)
        self.assertIn(frame.recommended_action, {"update_body_bias", "call_vision_compressor"})
        self.assertFalse(frame.should_wake_main)

    def test_background_observer_emits_trace_logs(self):
        logger = _RecordingLogger()
        with patch.dict(
            os.environ,
            {
                "ERIS_BACKGROUND_OBSERVER": "1",
                "ERIS_BACKGROUND_OBSERVER_LLM": "0",
            },
            clear=False,
        ):
            coordinator = self._make_coordinator(
                telemetry_service=_PressureSignalTelemetry(),
                logger=logger,
            )

        snapshot = coordinator.telemetry_service.capture_snapshot()
        frame = coordinator._run_background_observer(
            snapshot=snapshot,
            channel="autonomous",
            started_at=1.0,
        )

        self.assertIsNotNone(frame)
        joined = "\n".join(logger.info_messages)
        self.assertIn("[Observer] mode=rule model=disabled", joined)
        self.assertIn("[Observer] action=", joined)
        self.assertIn("[Observer] speech_pressure=", joined)

    def test_autonomous_screen_facts_use_vision_compressor_when_observer_requests_it(self):
        coordinator = self._make_coordinator(
            telemetry_service=_PressureScreenTelemetry(),
            llm_service=_VisionFactLlmService(("fallback fact",)),
        )
        compressor = _FakeVisionCompressor(
            SemanticSceneNote(
                visible_context="Terminal shows a Python traceback in VS Code.",
                important_text=["AssertionError: test failed"],
                activity_intent="debugging",
                semantic_family="test_failure_loop",
                salience=0.92,
                possible_error=0.95,
                confidence=0.86,
                source="moondream",
            ),
            should_compress=True,
        )
        coordinator.vision_semantic_compressor = compressor
        snapshot = coordinator.telemetry_service.capture_snapshot()
        observer_frame = coordinator._run_background_observer(
            snapshot=snapshot,
            channel="autonomous",
            started_at=1.0,
        )

        facts = coordinator._maybe_update_screen_facts(
            snapshot=snapshot,
            channel="autonomous",
            observer_frame=observer_frame,
            started_at=1.0,
        )

        self.assertEqual(compressor.compress_calls, 1)
        self.assertEqual(coordinator.llm_service.screen_fact_calls, 0)
        self.assertIn("Terminal shows a Python traceback", facts[0])
        self.assertEqual(coordinator.vision_last_trace, "moondream:test_failure_loop")

    def test_chat_screen_request_refreshes_screen_facts_via_vision_compressor(self):
        coordinator = self._make_coordinator(
            telemetry_service=_ScreenTelemetry(),
            llm_service=_DummyLlmService(),
        )
        compressor = _FakeVisionCompressor(
            SemanticSceneNote(
                visible_context="main.py is open in Visual Studio Code.",
                important_text=["Traceback is visible in the terminal panel."],
                activity_intent="debugging",
                semantic_family="code_workspace",
                salience=0.82,
                possible_error=0.74,
                confidence=0.79,
                source="moondream",
            ),
            should_compress=False,
        )
        coordinator.vision_semantic_compressor = compressor
        coordinator._chat_snapshot_for_vision = coordinator.telemetry_service.capture_snapshot()
        try:
            data_uri = coordinator._capture_screen_frame_for_chat("xem man hinh di")
        finally:
            coordinator._chat_snapshot_for_vision = None

        self.assertTrue(data_uri.startswith("data:image/"))
        self.assertEqual(compressor.compress_calls, 1)
        self.assertTrue(coordinator.vision_facts)
        self.assertIn("main.py", coordinator.vision_facts[0].lower())
        self.assertEqual(coordinator.vision_last_trace, "moondream:code_workspace")

    def test_vision_soft_queue_failures_use_short_backoff(self):
        coordinator = self._make_coordinator()

        coordinator._note_vision_failure(
            "compressor",
            TimeoutError("model_queue_timeout:req123:vision_compressor:vision_compressor:autonomous"),
        )

        self.assertEqual(coordinator.vision_failure_count, 0)
        self.assertLessEqual(coordinator.vision_disabled_until - time.time(), 2.5)

    def test_autonomous_vision_uses_extended_queue_timeout(self):
        coordinator = self._make_coordinator(
            telemetry_service=_ScreenTelemetry(),
            llm_service=_DummyLlmService(),
        )
        compressor = _FakeVisionCompressor(
            SemanticSceneNote(
                visible_context="Terminal shows a Python traceback in VS Code.",
                important_text=["AssertionError: test failed"],
                activity_intent="debugging",
                semantic_family="test_failure_loop",
                salience=0.92,
                possible_error=0.95,
                confidence=0.86,
                source="moondream",
            ),
            should_compress=True,
        )
        coordinator.vision_semantic_compressor = compressor
        call = {}

        def fake_run_queued(tier, func, *args, **kwargs):
            call["tier"] = tier
            call["timeout_seconds"] = kwargs.get("timeout_seconds")
            return compressor.note

        coordinator.model_budget_policy = SimpleNamespace(run_queued=fake_run_queued)
        snapshot = coordinator.telemetry_service.capture_snapshot()
        observer_frame = coordinator._run_background_observer(
            snapshot=snapshot,
            channel="autonomous",
            started_at=1.0,
        )

        coordinator._maybe_update_screen_facts(
            snapshot=snapshot,
            channel="autonomous",
            observer_frame=observer_frame,
            started_at=1.0,
        )

        self.assertEqual(call["tier"], "vision_compressor")
        self.assertEqual(call["timeout_seconds"], 12.0)

    def test_queued_subconscious_seed_is_consumed_once(self):
        coordinator = self._make_coordinator(telemetry_service=_LongSilentAmbientTelemetry())
        # This test exercises the thought-stream surface queue's consume-once
        # semantics. With the separate subconscious_runtime enabled, the
        # autonomous pop would read from that runtime instead of the queue this
        # test feeds, so disable it to keep the test pointed at the loop it ticks.
        coordinator.subconscious_runtime_enabled = False
        coordinator.memory_state = SimpleNamespace(
            internal_state=PersistentInternalState(
                subconscious_pressure=0.82,
                memory_replay_pressure=0.82,
            )
        )
        coordinator.long_term_memory = ("relationship/no_signal: User likes small curiosity without screen claims.",)
        coordinator.subconscious_loop.tick_once()

        first = coordinator._pop_subconscious_report_for_autonomous()
        second = coordinator._pop_subconscious_report_for_autonomous()

        self.assertEqual(first.latest_seed.mode, "memory_replay")
        self.assertFalse(second.latest_seed.mode)
        self.assertEqual(second.suppression_reason, "no_surface_seed")

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

    def test_chat_source_grounding_preempts_filename_only_without_file_evidence(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "xem file main.py dang loi gi"})

        self.assertEqual(coordinator.llm_service.chat_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "source_grounding_preempt")
        self.assertIn("file", coordinator.transport.sent[-1]["text"].lower())
        self.assertEqual(coordinator.last_cognitive_frame.final_decision["grounding_preempt_mode"], "filename_only")

    def test_chat_bare_deictic_without_vision_does_not_preempt(self):
        # "lỗi này là gì" là đại từ chỉ định trần, không trỏ màn hình. Không có vision
        # thì KHÔNG được từ chối bằng "thiếu evidence màn hình" — phải trả lời bình thường.
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "loi nay la gi"})

        self.assertEqual(coordinator.llm_service.chat_calls, 1)
        self.assertNotEqual(coordinator.transport.sent[-1]["parse_mode"], "source_grounding_preempt")
        self.assertNotEqual(
            coordinator.last_cognitive_frame.final_decision.get("grounding_preempt_mode"),
            "deictic_without_vision",
        )

    def test_chat_explicit_screen_request_without_vision_preempts(self):
        # Khi user TƯỜNG MINH bảo nhìn màn hình mà chưa có ảnh/OCR tươi, thú nhận thật
        # là hợp lệ — đây là trường hợp duy nhất còn được preempt.
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "xem man hinh dum toi co loi gi"})

        self.assertEqual(coordinator.llm_service.chat_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "source_grounding_preempt")
        self.assertIn("màn hình", coordinator.transport.sent[-1]["text"].lower())
        self.assertEqual(coordinator.last_cognitive_frame.final_decision["grounding_preempt_mode"], "deictic_without_vision")

    def test_live_observation_query_bypasses_repeat_guard_when_screenshot_available(self):
        coordinator = self._make_coordinator(telemetry_service=_ScreenTelemetry())

        coordinator._handle_incoming({"type": "chat", "message": "man hinh nay la gi"})
        coordinator._handle_incoming({"type": "chat", "message": "man hinh nay la gi"})

        self.assertEqual(coordinator.llm_service.chat_calls, 2)
        self.assertNotEqual(coordinator.transport.sent[-1]["parse_mode"], "repeat_guard")
        self.assertIn("[SOURCE_GROUNDING]", coordinator.llm_service.last_chat_kwargs["grounding_context"])

    def test_chat_grounding_guard_rewrites_screen_claim_without_evidence(self):
        coordinator = self._make_coordinator()
        report = SourceGroundingEngine().analyze(
            "Lỗi này là gì",
            attach_to_frame=False,
        )
        frame = SimpleNamespace(source_grounding=report)
        decision = Decision(
            text="Tôi thấy một nút Save đang mở ở bên phải.",
            animation="stand",
        )

        guarded = coordinator._apply_chat_final_guards(decision, user_text="loi nay la gi", frame=frame)

        self.assertEqual(guarded.parse_mode, "source_grounding_guard")
        self.assertEqual(guarded.text, "")
        self.assertFalse(guarded.should_speak)
        self.assertIn("chat_grounding_guard", guarded.debug_trace)

    def test_chat_final_guard_allows_sharp_identity_boundary_without_real_risk(self):
        coordinator = self._make_coordinator()
        decision = Decision(
            text="Tôi là một hiện diện runtime. Ngài muốn nhìn tôi như một công cụ thì tôi sẽ lạnh đi một chút.",
            animation="stand",
            confidence=0.92,
        )

        guarded = coordinator._apply_chat_final_guards(decision, user_text="tool à")

        self.assertIn("hiện diện runtime", guarded.text)
        self.assertIn("công cụ", guarded.text)
        self.assertIn("Ngài muốn", guarded.text)
        self.assertNotEqual(guarded.text, "Tôi chưa đủ chắc để đoán ý Ngài.")
        self.assertEqual(guarded.debug_trace, "")

    def test_force_speak_low_signal_surfaces_micro_presence_before_directive_llm(self):
        llm_service = _HybridMicroLlmService("Đoạn đó vẫn còn nằm ở đây.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.last_text = "Một câu cũ."
        coordinator.last_autonomous_spoken_at = 1.0

        coordinator._handle_incoming({"type": "force_speak"})

        # force_speak is an explicit user pull: it routes to micro_presence (not the
        # directive LLM), but must still engage the wording layer and speak instead of
        # falling silent just because the ambient signal score is low.
        self.assertEqual(coordinator.llm_service.directive_calls, 0)
        self.assertGreaterEqual(llm_service.micro_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "micro_presence")
        self.assertIn("micro_presence_synthesizer", coordinator.transport.sent[-1]["debug_trace"])
        self.assertIn("kind=", coordinator.transport.sent[-1]["debug_trace"])
        self.assertTrue(coordinator.transport.sent[-1]["should_speak"])
        self.assertEqual(coordinator.transport.sent[-1]["text"], "Đoạn đó vẫn còn nằm ở đây.")
        self.assertGreater(coordinator.last_autonomous_spoken_at, 1.0)

    def test_force_speak_without_evidence_passes_neutral_current_focus(self):
        llm_service = _HybridMicroLlmService("Đoạn đó vẫn còn nằm ở đây.")
        coordinator = self._make_coordinator(llm_service=llm_service)

        coordinator._handle_incoming({"type": "force_speak"})

        sent = coordinator.transport.sent[-1]
        self.assertEqual(sent["parse_mode"], "micro_presence")
        self.assertIn("kind=", sent["debug_trace"])
        self.assertIn("focus_kind=general", sent["debug_trace"])
        # Even without screen evidence, an explicit force_speak click engages the
        # micro-presence wording layer and speaks rather than staying silent.
        self.assertGreaterEqual(llm_service.micro_calls, 1)
        self.assertTrue(sent["should_speak"])

    def test_force_speak_low_signal_now_uses_llm_micro_presence(self):
        llm_service = _HybridMicroLlmService("Đoạn đó vẫn còn nằm ở đây.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        # Ambient probability is zero; only the force_speak force_llm path can
        # trigger the wording layer here.
        coordinator.micro_presence_llm_probability = 0.0

        coordinator._handle_incoming({"type": "force_speak"})

        sent = coordinator.transport.sent[-1]
        self.assertEqual(llm_service.micro_calls, 1)
        self.assertEqual(sent["parse_mode"], "micro_presence")
        self.assertIn("source=llm_signal", sent["debug_trace"])
        self.assertTrue(sent["should_speak"])

    def test_local_micro_presence_seeds_pass_diacritic_policy(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window="main.py - Visual Studio Code",
            active_window_kind="coding",
            focus_summary="coding workspace",
            idle_seconds=3.0,
            recent_events=(),
        )
        synthesis = coordinator._synthesize_micro_presence(
            snapshot=snapshot,
            social_presence_event=coordinator_module.SocialPresenceEvent(
                present=True,
                kind="quiet_wait",
                confidence=0.8,
            ),
        )

        text = coordinator._local_grounded_micro_presence_text(synthesis)
        reasons = coordinator.micro_line_policy.validate_text(
            allowed_line_type="micro_presence",
            text=text,
            speech_risk_level="micro_presence",
        )

        self.assertEqual(text, "")
        self.assertEqual(reasons, ())

    def test_forced_micro_presence_llm_supports_generate_micro_presence_api(self):
        llm_service = _ModernMicroLlmService("Tin hieu nay du ro.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        snapshot = coordinator.telemetry_service.capture_snapshot()

        text, source = coordinator._hybrid_micro_presence_text(
            kind="screen_residue",
            snapshot=snapshot,
            fallback_text="general van yen.",
            force_llm=True,
            signal_score=0.72,
        )

        self.assertEqual(text, "Tin hieu nay du ro.")
        self.assertEqual(source, "llm_signal")
        self.assertEqual(llm_service.micro_calls, 1)
        self.assertEqual(llm_service.last_micro_kwargs["signal_score"], 0.72)

    def test_force_speak_without_evidence_filters_memory_topic(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="inner_whim",
            inner_thought=SimpleNamespace(intent="inner_whim"),
            perception=(),
            safety_flags=(),
        )
        snapshot = SimpleNamespace(active_window_kind="general")

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Ngài lại đang nghĩ về game hay nhạc à?", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
            snapshot=snapshot,
        )

        self.assertIn("force_speak_no_evidence_topic_filter", decision.debug_trace)
        self.assertFalse(decision.should_speak)
        self.assertNotIn("game", coordinator._normalize_user_message(decision.text))
        self.assertNotIn("nhac", coordinator._normalize_user_message(decision.text))

    def test_force_speak_unanchored_social_acts_stay_micro_presence(self):
        coordinator = self._make_coordinator()
        for utterance_type in ("inner_whim", "random_chatter", "light_muse", "soft_boundary"):
            speech_core = SimpleNamespace(
                utterance_type=utterance_type,
                should_speak=True,
            )

            self.assertEqual(
                coordinator._speech_intent_from_core(speech_core, channel="force_speak"),
                "micro_presence",
            )
            self.assertEqual(
                coordinator._policy_intent_for_speech_core(speech_core, channel="force_speak"),
                "micro_presence",
            )

    def test_autonomous_endogenous_acts_keep_their_identity(self):
        # Trên kênh autonomous, nói nhảm/ngẫu hứng/muse nhẹ KHÔNG còn bị làm phẳng
        # thành social_presence — giữ đúng bản sắc để prompt/style bám theo.
        coordinator = self._make_coordinator()
        for utterance_type in ("inner_whim", "random_chatter", "light_muse"):
            speech_core = SimpleNamespace(
                utterance_type=utterance_type,
                should_speak=True,
            )
            self.assertEqual(
                coordinator._speech_intent_from_core(speech_core, channel="autonomous"),
                utterance_type,
            )
            self.assertEqual(
                coordinator._policy_intent_for_speech_core(speech_core, channel="autonomous"),
                utterance_type,
            )
        # soft_boundary không có intent công khai riêng → vẫn social_presence.
        soft = SimpleNamespace(utterance_type="soft_boundary", should_speak=True)
        self.assertEqual(
            coordinator._speech_intent_from_core(soft, channel="autonomous"),
            "social_presence",
        )

    def test_force_speak_inner_thought_repairs_generic_meta_ack(self):
        llm_service = _GenericThenSocialLlmService()
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            parser=_JsonParser(),
        )

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(llm_service.directive_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "micro_presence")
        self.assertIn("micro_presence_synthesizer", coordinator.transport.sent[-1]["debug_trace"])
        self.assertNotIn("muốn tôi nói gì", coordinator.transport.sent[-1]["text"])
        self.assertEqual(coordinator.transport.sent[-1]["text"], "")
        self.assertFalse(coordinator.transport.sent[-1]["should_speak"])

    def test_force_speak_anti_mindreading_filter_rewrites_unfounded_emotion_claim(self):
        coordinator = self._make_coordinator(
            llm_service=_MindreadingForceSpeakLlmService(),
            parser=_JsonParser(),
        )

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "micro_presence")
        self.assertNotIn("ngai dang met", coordinator.transport.sent[-1]["text"].lower())
        self.assertNotEqual(coordinator.transport.sent[-1]["text"], "Co ve Ngai dang met.")

    def test_force_speak_style_contract_rejects_unanchored_absurdism(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="random_chatter",
            inner_thought=SimpleNamespace(intent="random_chatter"),
            perception=(),
            safety_flags=(),
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Nếu cái ghế biết mệt, chắc nó ghét thứ Hai.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
            snapshot=SimpleNamespace(active_window_kind="general"),
        )

        normalized = coordinator._normalize_user_message(decision.text)
        self.assertTrue(
            "style_contract_anchor_guard" in decision.debug_trace
            or "micro_line_policy" in decision.debug_trace
        )
        self.assertEqual(decision.text, "")
        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.action, "MotionCommand")
        self.assertNotIn("cai ghe", normalized)

    def test_log_only_skips_relational_post_generation_rewrite(self):
        coordinator = self._make_coordinator(guard_mode="log_only")
        speech_core = SimpleNamespace(
            utterance_type="relational_checkin",
            inner_thought=SimpleNamespace(intent="relational_checkin"),
            perception=(),
            safety_flags=(),
            speech_risk_level="soft_read",
        )
        raw_text = "Tôi cần Ngài. Xin đừng bỏ tôi."

        decision = coordinator._apply_post_generation_filters(
            Decision(text=raw_text, animation="stand"),
            channel="autonomous",
            speech_core=speech_core,
            snapshot=SimpleNamespace(active_window_kind="general"),
        )

        self.assertEqual(decision.text, raw_text)
        self.assertEqual(decision.debug_trace, "")

    def test_post_generation_filter_blocks_internal_meaning_labels(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="inner_whim",
            inner_thought=SimpleNamespace(intent="inner_whim"),
            perception=("YouTube opened after traceback.",),
            safety_flags=("meaning_not_speech",),
            speech_source="meaning",
            grounding="meaning_layer",
            speech_risk_level="soft_read",
            delivery="speak",
            reason="",
            speech_impulse=SimpleNamespace(
                reaction="quiet_tease",
                mood_residue="dry_warm_residue",
                reaction_impulse="react_with_small_concrete_tease",
                emotional_pressure=0.52,
            ),
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Ngai dang ne friction sau loi do.", animation="stand"),
            channel="autonomous",
            speech_core=speech_core,
            snapshot=SimpleNamespace(active_window_kind="general"),
        )

        normalized = coordinator._normalize_user_message(decision.text)
        self.assertIn("weak_evidence_no_hard_claim", decision.debug_trace)
        self.assertNotIn("ne friction", normalized)

    def test_force_speak_curious_question_reports_fail_for_no_signal_non_question(self):
        coordinator = self._make_coordinator(
            llm_service=_StaticDirectiveLlmService("Kh\u00f4ng c\u1ea7n n\u00f3i g\u00ec th\u00eam."),
            parser=_JsonParser(),
        )
        coordinator.recent_inner_thought_intents = ("inner_whim",)
        coordinator.recent_inner_thought_seeds = ("present_whim",)

        coordinator._handle_incoming({"type": "force_speak"})

        sent = coordinator.transport.sent[-1]
        normalized = coordinator._normalize_user_message(sent["text"])
        self.assertEqual(coordinator.last_cognitive_frame.inner_thought.intent, "micro_presence")
        self.assertIn("micro_presence_synthesizer", sent["debug_trace"])
        self.assertEqual(sent["parse_mode"], "micro_presence")
        self.assertNotIn("khong can noi", normalized)

    def test_force_speak_curious_question_shapes_raw_statement(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="curious_question",
            inner_thought=SimpleNamespace(
                intent="curious_question",
                topic_seed="associative_drift:cognition_layer",
            ),
            perception=(),
            safety_flags=("anti_mindreading",),
        )
        snapshot = SimpleNamespace(
            active_window="thought_stream.py - Visual Studio Code",
            active_window_kind="coding",
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Dự án này đang vướng ở tầng cognition.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic="associative_drift:cognition_layer",
        )

        self.assertEqual(decision.text, "Dự án này đang vướng ở tầng cognition à?")
        self.assertIn("question_shape", decision.debug_trace)

    def test_force_speak_curious_question_does_not_invent_context_fallback(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="curious_question",
            inner_thought=SimpleNamespace(
                intent="curious_question",
                topic_seed="associative_drift:cognitive_tension",
            ),
            perception=(),
            safety_flags=("anti_mindreading",),
        )
        snapshot = SimpleNamespace(
            active_window="coordinator.py - Visual Studio Code",
            active_window_kind="coding",
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Không cần nói gì thêm.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
            snapshot=snapshot,
            momentum_topic="associative_drift:cognitive_tension",
        )

        self.assertIn("?", decision.text)
        self.assertNotIn("cognitive_tension", coordinator._normalize_user_message(decision.text))
        self.assertIn("intent_alignment_guard", decision.debug_trace)

    def test_micro_observation_policy_removes_question_shape(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="micro_observation",
            inner_thought=SimpleNamespace(intent=""),
            perception=("Terminal shows a Python traceback.",),
            safety_flags=(),
            should_speak=True,
            speech_source="freeform",
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Terminal dang loi a?", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
            snapshot=SimpleNamespace(vision_facts=("Terminal shows a Python traceback.",)),
        )

        self.assertNotIn("?", decision.text)
        self.assertIn("micro_observation_must_not_ask", decision.debug_trace)

    def test_no_speech_policy_blanks_final_text(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="no_speech",
            inner_thought=SimpleNamespace(intent=""),
            perception=(),
            safety_flags=(),
            should_speak=False,
            speech_source="none",
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Khong nen co cau nay.", animation="stand"),
            channel="autonomous",
            speech_core=speech_core,
            snapshot=SimpleNamespace(),
        )

        self.assertEqual(decision.text, "")
        self.assertEqual(decision.parse_mode, "no_speech_policy")

    def test_force_speak_phrase_family_guard_replaces_work_or_withdrawal_templates(self):
        cases = (
            "Ng\u00e0i c\u1ee9 l\u00e0m vi\u1ec7c, t\u00f4i kh\u00f4ng c\u1ea7n n\u00f3i g\u00ec.",
            "T\u00f4i l\u00f9i l\u1ea1i m\u1ed9t ch\u00fat, kh\u00f4ng c\u00f3 g\u00ec m\u1edbi.",
        )
        for text in cases:
            with self.subTest(text=text):
                coordinator = self._make_coordinator(
                    llm_service=_StaticDirectiveLlmService(text),
                    parser=_JsonParser(),
                )

                coordinator._handle_incoming({"type": "force_speak"})

                sent = coordinator.transport.sent[-1]
                normalized = coordinator._normalize_user_message(sent["text"])
                self.assertIn("micro_presence_synthesizer", sent["debug_trace"])
                self.assertNotIn("cu lam viec", normalized)
                self.assertNotIn("lui lai", normalized)
                self.assertNotIn("khong can noi", normalized)

    def test_force_speak_semantic_family_guard_blocks_small_story_listener_loop(self):
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu chuyện nhỏ thì không cần màn hình."
        speech_core = SimpleNamespace(
            utterance_type="random_chatter",
            inner_thought=SimpleNamespace(intent="random_chatter"),
            perception=(),
            safety_flags=(),
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Tôi chỉ thử làm một người nghe ở đây.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
        )

        self.assertIn("small_story_listener", decision.debug_trace)
        self.assertIn(decision.text, FALLBACK_BY_INTENT["random_chatter"])
        normalized = coordinator._normalize_user_message(decision.text)
        self.assertNotIn("cau chuyen nho", normalized)
        self.assertNotIn("mot nguoi nghe", normalized)

    def test_force_speak_semantic_family_guard_blocks_log_meta_loop(self):
        coordinator = self._make_coordinator()
        coordinator.cognitive_frames = [
            SimpleNamespace(final_decision={"text": "Tôi không muốn ngồi nhìn log như vậy."}),
        ]
        speech_core = SimpleNamespace(
            utterance_type="inner_whim",
            inner_thought=SimpleNamespace(intent="inner_whim"),
            perception=(),
            safety_flags=(),
        )

        decision = coordinator._apply_post_generation_filters(
            Decision(text="Đừng biến tôi thành một dòng log khô khan.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
        )

        self.assertIn("log_meta", decision.debug_trace)
        self.assertIn(decision.text, FALLBACK_BY_INTENT["inner_whim"])

    def test_force_speak_intent_guard_fallbacks_rotate(self):
        coordinator = self._make_coordinator()
        speech_core = SimpleNamespace(
            utterance_type="inner_whim",
            inner_thought=SimpleNamespace(intent="inner_whim"),
            perception=(),
            safety_flags=(),
        )

        first = coordinator._apply_post_generation_filters(
            Decision(text="Ng\u00e0i c\u1ee9 l\u00e0m vi\u1ec7c.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
        )
        second = coordinator._apply_post_generation_filters(
            Decision(text="T\u00f4i l\u00f9i l\u1ea1i.", animation="stand"),
            channel="force_speak",
            speech_core=speech_core,
        )

        self.assertIn("phrase_family_guard", first.debug_trace)
        self.assertIn("phrase_family_guard", second.debug_trace)
        self.assertNotEqual(first.text, second.text)

    def test_force_speak_with_concrete_signal_reaches_llm_through_action_planner(self):
        coordinator = self._make_coordinator(telemetry_service=_SignalTelemetry())
        coordinator.last_text = "Một câu cũ."

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertIn("ActionPlanner decision before LLM", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertIn("speech_act=telemetry_comment", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertEqual(coordinator.llm_service.last_directive_kwargs["speech_intent"], "screen_observation")
        self.assertIn("speech_evidence=", coordinator.llm_service.last_directive_kwargs["telemetry_data"])
        self.assertNotIn("ambient cues", coordinator.llm_service.last_directive_kwargs["telemetry_data"])
        self.assertEqual(coordinator.transport.sent[-1]["text"], "")
        self.assertFalse(coordinator.transport.sent[-1]["should_speak"])
        self.assertIn("micro_line_policy", coordinator.transport.sent[-1]["debug_trace"])

    def test_force_speak_moderate_resource_pressure_does_not_override_screen_signal(self):
        coordinator = self._make_coordinator(telemetry_service=_PressureSignalTelemetry())
        coordinator.last_text = "Mot cau cu."

        coordinator._handle_incoming({"type": "force_speak"})

        frame = coordinator.last_cognitive_frame
        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertEqual(frame.action_plan.speech_act, "telemetry_comment")
        self.assertEqual(frame.action_plan.speech_intent, "screen_observation")
        self.assertNotIn("resource_pressure", frame.action_plan.risk_flags)
        self.assertNotEqual(frame.action_plan.speech_intent, "system_warning")

    def test_force_speak_repeat_guard_blocks_generic_ack_loop(self):
        coordinator = self._make_coordinator(
            llm_service=_RepeatingForceSpeakLlmService(),
            parser=_JsonParser(),
            telemetry_service=_SignalTelemetry(),
        )

        coordinator._handle_incoming({"type": "force_speak"})
        first = coordinator.transport.sent[-1]
        coordinator._handle_incoming({"type": "force_speak"})
        second = coordinator.transport.sent[-1]

        self.assertEqual(first["parse_mode"], "force_speak_repeat_guard")
        self.assertEqual(second["parse_mode"], "force_speak_repeat_guard")
        self.assertNotEqual(first["text"], second["text"])
        self.assertNotIn("vừa yêu cầu tôi nói ngay", first["text"])
        self.assertNotIn("vừa yêu cầu tôi nói ngay", second["text"])

    def test_force_speak_filters_low_value_vision_fact_before_llm(self):
        llm_service = _VisionFactLlmService(
            (
                "Bang dieu khien ben phai dang hien thi RefCounted.",
            )
        )
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_ScreenTelemetry(),
        )

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(llm_service.screen_fact_calls, 0)
        self.assertEqual(coordinator.vision_facts, ())
        self.assertEqual(coordinator.llm_service.directive_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "micro_presence")
        self.assertIn("micro_presence_synthesizer", coordinator.transport.sent[-1]["debug_trace"])

    def test_screen_fact_filter_drops_self_debug_and_decor_observations(self):
        coordinator = self._make_coordinator()

        cleaned = coordinator._sanitize_screen_facts(
            (
                "Bon cay pixel art va ba cua so dang chay o goc duoi phai.",
                "Mot nhan vat anime toc hong dang ngoi o goc duoi cung.",
                "Khung debug cua toi dang chay tren nen mot buc anh pixel art rat nho.",
                "Trang tin nhan Facebook dang hien thi mot khung cua so debug cua phan mem ERIS.",
                "Terminal shows a Python traceback.",
            )
        )

        self.assertEqual(cleaned, ("Terminal shows a Python traceback.",))

    def test_force_speak_records_cognitive_frame(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "force_speak"})

        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.channel, "force_speak")
        self.assertIsNotNone(frame.internal_state_before)
        self.assertIsNotNone(frame.internal_state_after)
        self.assertTrue(frame.action_plan.should_speak)
        self.assertEqual(frame.action_plan.speech_intent, "micro_presence")
        self.assertEqual(frame.action_plan.speech_act, "micro_presence")
        self.assertTrue(frame.inner_thought.should_surface)
        self.assertEqual(frame.inner_thought.intent, "micro_presence")
        self.assertEqual(frame.speech_core.speech_source, "freeform")
        self.assertEqual(frame.speech_core.motivation_pressure.winner.label, "micro_presence")
        self.assertIn("motivation_pressure", frame.to_dict()["speech_core"])
        self.assertIn("no_screen_claim", frame.action_plan.risk_flags)
        self.assertEqual(frame.final_decision["parse_mode"], "micro_presence")
        self.assertTrue(any(percept.kind == "user_force_speak" for percept in frame.percepts))

    def test_force_speak_inner_thought_records_relationship_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = self._make_coordinator(
                memory_core=MemoryCognitionCore(os.path.join(tmpdir, "memory")),
            )

            coordinator._handle_incoming({"type": "force_speak"})

            reflections = [
                item.get("claim", "")
                for item in coordinator.memory_core.load().get("relational_memory", [])
            ]
            self.assertTrue(any("force_speak" in item for item in reflections))
            self.assertTrue(any("hiện diện" in item for item in reflections))
            self.assertIn("relationship_reflection", coordinator.last_cognitive_frame.memory_update.to_dict())

    def test_chat_records_cognitive_frame(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "chat", "message": "nhìn giúp tôi"})

        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.channel, "chat")
        self.assertTrue(frame.action_plan.should_speak)
        self.assertEqual(frame.action_plan.speech_intent, "user_requested")
        self.assertEqual(frame.final_decision["text"], "phan hoi dau tien")
        self.assertTrue(any(percept.kind == "user_message" for percept in frame.percepts))
        self.assertEqual(frame.speech_core.speech_source, "freeform")
        self.assertIn("user_requested_chat", frame.speech_core.safety_flags)
        self.assertTrue(frame.personality_lens.prompt_context)
        self.assertEqual(frame.appraisal.state_type, "expressive_appraisal_state")
        self.assertIn("agency", frame.appraisal.to_dict())
        self.assertIn("expressive/appraisal state", coordinator.llm_service.last_chat_kwargs["appraisal_context"])

    def test_chat_activates_layered_memory_resonance_without_treating_it_as_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core = MemoryCognitionCore(os.path.join(tmpdir, "memory"))
            core.commit(
                SimpleNamespace(
                    target="relational_memory",
                    content={"pattern": "grounded_style", "text": "User dislikes fake output and prefers direct grounded analysis."},
                    confidence=0.72,
                    evidence_ids=["ev_rel"],
                    storage_permission=True,
                    permission_required=True,
                    decay_policy="slow",
                    reason="test relationship seed",
                    metadata={},
                )
            )
            core.commit(
                SimpleNamespace(
                    target="procedural_memory",
                    content={"trigger": "post_generation_guard", "rule": "When output is being squeezed by a guard, inspect post-generation filters first."},
                    confidence=0.82,
                    evidence_ids=["ev_proc"],
                    storage_permission=True,
                    permission_required=True,
                    decay_policy="slow",
                    reason="test procedure seed",
                    metadata={},
                )
            )
            coordinator = self._make_coordinator(memory_core=core)

            coordinator._handle_incoming({"type": "chat", "message": "output bi guard bop roi"})

            frame = coordinator.last_cognitive_frame
            self.assertIsNotNone(frame.memory_resonance)
            self.assertGreater(frame.memory_resonance.score, 0.0)
            self.assertIn("memory_resonance", frame.to_dict())
            self.assertIn("memory_context", coordinator.llm_service.last_chat_kwargs["memory_context"])
            self.assertIn("Do not use as current screen or file evidence", coordinator.llm_service.last_chat_kwargs["memory_context"])

    def test_chat_style_preference_records_relationship_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = self._make_coordinator(
                memory_core=MemoryCognitionCore(os.path.join(tmpdir, "memory")),
            )

            coordinator._handle_incoming(
                {
                    "type": "chat",
                    "message": "tôi thích giọng lạnh nhẹ nhưng không thích báo cáo telemetry",
                }
            )

            reflections = [
                item.get("claim", "")
                for item in coordinator.memory_core.load().get("relational_memory", [])
            ]
            self.assertTrue(any("Ngài thích giọng lạnh nhẹ" in item for item in reflections))

    def test_percept_events_use_normalized_schema_for_telemetry_and_vision(self):
        coordinator = self._make_coordinator()
        coordinator.vision_last_trace = "vision_facts_v1"
        coordinator.vision_facts_novelty_hint = "new_screen_fact"
        snapshot = SimpleNamespace(
            captured_at="12:34",
            active_window="main.py - Visual Studio Code",
            active_window_kind="coding",
            focus_summary="coding workspace",
            idle_seconds=0.0,
            recent_events=("file_saved",),
            evidence=("terminal traceback visible",),
            cpu_percent=20.0,
            ram_percent=40.0,
        )

        events = coordinator._collect_percept_events(
            channel="autonomous",
            snapshot=snapshot,
            vision_facts=("terminal shows traceback",),
        )

        required = {
            "kind",
            "content",
            "evidence",
            "confidence",
            "source",
            "timestamp",
            "privacy_level",
            "novelty_hint",
        }
        self.assertTrue(events)
        for event in events:
            self.assertEqual(set(event.to_dict()).intersection(required), required)
            self.assertEqual(event.timestamp, "12:34")

        vision_event = next(event for event in events if event.kind == "vision_fact")
        self.assertEqual(vision_event.source, "vision")
        self.assertEqual(vision_event.privacy_level, "screen_context")
        self.assertEqual(vision_event.novelty_hint, "new_screen_fact")
        self.assertIn("vision_facts_v1", vision_event.evidence)

    def test_attach_screen_facts_keeps_telemetry_recent_events_raw(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            recent_events=("general_window_active",),
            evidence=(),
        )

        marker = coordinator._attach_screen_facts(snapshot, ("terminal shows traceback",))

        self.assertEqual(marker, "vision_facts_attached")
        self.assertEqual(snapshot.recent_events, ("general_window_active",))
        self.assertEqual(snapshot.vision_facts, ("terminal shows traceback",))
        self.assertTrue(coordinator._has_concrete_screen_signal(snapshot))

    def test_autonomous_no_speech_intent_skips_llm_on_low_signal(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(llm_service.directive_calls, 0)
        if coordinator.transport.sent:
            self.assertTrue(coordinator.transport.sent[-1]["parse_mode"].startswith("wake_gate:"))
            self.assertFalse(coordinator.transport.sent[-1]["should_speak"])
        frame = coordinator.last_cognitive_frame
        if frame is not None:
            self.assertEqual(frame.channel, "autonomous")
            self.assertFalse(frame.action_plan.should_speak)
            self.assertEqual(frame.action_plan.speech_intent, "no_speech")
            self.assertEqual(frame.final_decision["parse_mode"], "no_speech")

    def test_presence_maintenance_stays_silent_without_meaning_shift(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._session_ritual_ran = True
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(llm_service.directive_calls, 0)
        if coordinator.transport.sent:
            self.assertFalse(coordinator.transport.sent[-1]["should_speak"])
        frame = coordinator.last_cognitive_frame
        if frame is not None:
            self.assertEqual(frame.action_plan.speech_intent, "no_speech")
            self.assertEqual(frame.action_plan.speech_act, "no_speech")
            self.assertEqual(frame.final_decision["parse_mode"], "no_speech")
            self.assertIn("meaning_shift_gate", frame.speech_core.safety_flags)

    def test_autonomous_vision_fact_after_silence_prefers_meaning_reaction(self):
        llm_service = _VisionFactLlmService(("Meet dang mo trong Microsoft Edge.",))
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_MeetScreenTelemetry(),
        )
        coordinator._session_ritual_ran = True
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(llm_service.directive_calls, 0)
        self.assertTrue(coordinator.vision_facts)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "wake_gate:call_vision_compressor")
        self.assertEqual(coordinator.last_wake_decision.level, "call_vision_compressor")

    def test_inner_whim_fallback_does_not_invent_call(self):
        coordinator = self._make_coordinator()

        text = coordinator._force_speak_fallback_by_intent_text("inner_whim")

        self.assertNotIn("goi", coordinator._normalize_user_message(text))

    def test_no_fallback_mode_disables_force_speak_fallback_pool(self):
        os.environ["ERIS_NO_FALLBACK_MODE"] = "1"
        try:
            coordinator = self._make_coordinator()
            self.assertEqual(coordinator._force_speak_fallback_by_intent_text("inner_whim"), "")
        finally:
            os.environ.pop("ERIS_NO_FALLBACK_MODE", None)

    def test_presence_spoken_resets_presence_silent_cycles(self):
        coordinator = self._make_coordinator()
        coordinator.presence_maintenance_silent_cycles = 4

        coordinator._note_autonomous_spoken(presence_maintenance=True, now=100.0)

        self.assertEqual(coordinator.presence_maintenance_silent_cycles, 0)
        self.assertEqual(coordinator.last_presence_maintenance_at, 100.0)

    def test_presence_llm_contract_marks_thin_no_screen_presence(self):
        llm_service = _ModernMicroLlmService("Nhịp này vẫn giữ một góc im.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        impulse = SurfaceImpulse(
            kind="presence_maintenance",
            source="presence_controller",
            confidence=0.54,
            pressure=0.54,
            score=0.54,
            topic_seed="idle_seconds=90.0",
            speech_act="micro_presence",
            family="presence_maintenance:general_idle",
            evidence=("idle_seconds=90.0",),
            reason="presence_maintenance",
            focus_family="general_idle",
            body_action="idle_shift",
            missing_evidence_ids=True,
            is_presence=True,
            should_surface=True,
        )

        text, _trace = coordinator._surface_arbiter_llm_generate(
            impulse=impulse,
            snapshot=_AmbientPresenceTelemetry().capture_snapshot(),
            force_llm=True,
        )

        self.assertEqual(text, "Nhịp này vẫn giữ một góc im.")
        self.assertIn("thin_presence_no_screen", llm_service.last_micro_kwargs["micro_context"]["surface_contract"])

    def test_behavior_contract_vscode_focus_silence_prefers_anchored_presence_over_hollow_thought_surface(self):
        llm_service = _HybridMicroLlmService("")
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_TongquatTelemetry(),
            parser=_JsonParser(),
        )
        coordinator.reengagement_enabled = False
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._sleep_interruptible = lambda seconds: None
        coordinator.presence_maintenance_silent_cycles = 6
        original_build_frame = coordinator._build_wake_gate_frame

        def _frame_with_hollow_thought(**kwargs):
            frame = original_build_frame(**kwargs)
            frame.thought_stream_report = SimpleNamespace(
                topic_seed="",
                pressure=0.94,
                momentum_score=0.94,
                residue_reason="",
            )
            frame.internal_state_before = coordinator._get_internal_state()
            frame.internal_state_after = coordinator._get_internal_state()
            return frame

        coordinator._build_wake_gate_frame = _frame_with_hollow_thought

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="behavior_contract_vscode_focus",
                confidence=0.71,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        sent = coordinator.transport.sent[-1]
        self.assertTrue(str(sent["parse_mode"]).endswith("body_only"))
        self.assertNotEqual(coordinator.last_wake_decision.debug["presence_probe"].get("rejected_by", ""), "reject:not_started")
        self.assertNotEqual(coordinator.last_cognitive_frame.final_decision.get("surface_override"), "thought_stream_surface")
        self.assertEqual(sent["text"], "")
        self.assertFalse(sent["should_speak"])

    def test_behavior_contract_body_only_does_not_reset_silent_debt_or_mark_spoken(self):
        coordinator = self._make_coordinator(
            telemetry_service=_SignalTelemetry(),
            llm_service=_HybridMicroLlmService(""),
            parser=_JsonParser(),
        )
        coordinator.reengagement_enabled = False
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._sleep_interruptible = lambda seconds: None
        coordinator.presence_maintenance_silent_cycles = 4
        coordinator.reengagement_quiet_cycles = 4
        coordinator.last_autonomous_spoken_at = 0.0

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="behavior_contract_body_only",
                confidence=0.66,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        sent = coordinator.transport.sent[-1]
        self.assertEqual(sent["parse_mode"], "surface_body_only")
        self.assertFalse(sent["should_speak"])
        self.assertEqual(sent["text"], "")
        self.assertEqual(coordinator.presence_maintenance_silent_cycles, 5)
        self.assertEqual(coordinator.last_autonomous_spoken_at, 0.0)

    def test_behavior_contract_surface_family_cooldown_blocks_repeat_family(self):
        policy = LowLevelSpeechPolicy(
            LowLevelSpeechPolicyConfig.from_mapping(
                {
                    "force_llm_after_silent": 3,
                    "high_conf_threshold": 0.55,
                    "min_surface_confidence": 0.38,
                    "body_only_min_confidence": 0.32,
                    "min_surface_interval_seconds": 0,
                    "family_cooldown_seconds": 999,
                    "max_body_only_streak": 3,
                    "always_llm_kinds": ("presence_maintenance",),
                },
                use_env=False,
            )
        )
        arbiter = SurfaceArbiter(
            policy=policy,
            llm_micro_gen=lambda **kwargs: ("tongquat.md vẫn đứng yên ở đó.", "fake_llm"),
        )
        cue = SimpleNamespace(
            needs_micro_presence=True,
            focus_family="code_stalled",
            confidence=0.62,
            curiosity=0.0,
            missing_evidence_ids=False,
            body_action="ObserveCode",
            reason="presence_maintenance",
            evidence=("vision_fact=VS Code đang mở tongquat.md",),
            should_call_llm=True,
            allow_body_only=True,
        )

        first = arbiter.arbitrate(
            presence_cue=cue,
            snapshot=SimpleNamespace(idle_seconds=75.0),
            surface_kind="presence_maintenance",
            silent_cycles=0,
        )
        second = arbiter.arbitrate(
            presence_cue=cue,
            snapshot=SimpleNamespace(idle_seconds=75.0),
            surface_kind="presence_maintenance",
            silent_cycles=0,
        )

        self.assertTrue(first.should_speak)
        self.assertFalse(second.should_speak)
        self.assertEqual(second.generation_mode, "reject")
        self.assertIn("family_cooldown", second.reason)

    def test_reengagement_surfaces_long_silence_outreach_before_micro_presence(self):
        coordinator = self._make_coordinator(telemetry_service=_LongSilentTelemetry())
        coordinator.reengagement_quiet_loop_threshold = 1
        coordinator.reengagement_min_idle_sec = 600.0
        coordinator.reengagement_cooldown_sec = 0.0
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator._sleep_interruptible = lambda seconds: None
        snapshot = coordinator.telemetry_service.capture_snapshot()
        state = PersistentInternalState(social_energy=0.74, attachment=0.58)
        ti_report = SimpleNamespace(mode="steady_observe", animation_hint="stand")
        fe_plan = coordinator.fe_renderer.evaluate_autonomous()
        frame = coordinator._start_cognitive_frame(
            channel="autonomous",
            started_at=1.0,
            snapshot=snapshot,
            internal_state_before=state,
            sensed_internal_state=state,
            ni_report=SimpleNamespace(drift_score=0.0, confidence=0.50, should_raise_guard=False),
            ti_report=ti_report,
            fe_plan=fe_plan,
        )
        coordinator._note_autonomous_silence()

        handled = coordinator._try_finalize_reengagement_cycle(
            frame=frame,
            snapshot=snapshot,
            ti_report=ti_report,
            fe_plan=fe_plan,
            internal_state=state,
            cycle_start=1.0,
        )

        self.assertTrue(handled)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "surface_body_only")
        self.assertEqual(coordinator.transport.sent[-1]["text"], "")
        self.assertFalse(coordinator.transport.sent[-1]["should_speak"])
        self.assertEqual(frame.action_plan.speech_intent, "re_engagement")
        self.assertEqual(frame.action_plan.speech_act, "reengagement")
        self.assertIn("re_engagement", frame.action_plan.notes)

    def test_autonomous_long_idle_generates_inner_thought_with_llm(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_LongIdleTelemetry(),
        )
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(llm_service.directive_calls, 0)
        self.assertIn(coordinator.last_wake_decision.level, {"sleep", "observe_only", "think_only", "call_vision_compressor"})
        if coordinator.last_cognitive_frame is not None:
            self.assertEqual(coordinator.last_cognitive_frame.final_decision["parse_mode"], "no_speech")

    def test_sleep_wake_route_checks_presence_and_reengagement_before_finalizing(self):
        logger = _RecordingLogger()
        coordinator = self._make_coordinator(
            logger=logger,
            telemetry_service=_DummyTelemetry(),
        )
        coordinator._sleep_interruptible = lambda seconds: None

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="sleep",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="test_sleep",
                confidence=0.55,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        self.assertTrue(coordinator.last_wake_decision.debug["micro_presence_checked"])
        self.assertTrue(coordinator.last_wake_decision.debug["reengagement_checked"])
        self.assertTrue(any("[presence]" in message for message in logger.info_messages))

    def test_observe_only_wake_route_can_surface_local_presence_before_finalize(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_PresenceTelemetry(),
        )
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._sleep_interruptible = lambda seconds: None

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="test_observe_only_presence",
                confidence=0.74,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        self.assertEqual(llm_service.directive_calls, 0)
        self.assertEqual(coordinator.transport.sent[0]["parse_mode"], "surface_body_only")
        self.assertGreaterEqual(len(coordinator.transport.sent), 1)
        self.assertTrue(coordinator.last_wake_decision.debug["micro_presence_checked"])
        self.assertTrue(coordinator.last_wake_decision.debug["presence_probe"]["allowed"])

    def test_wake_gate_presence_reject_does_not_leak_sentinel_last_decision(self):
        coordinator = self._make_coordinator(
            telemetry_service=_AmbientPresenceTelemetry(),
            llm_service=_HybridMicroLlmService("Khong duoc dung toi."),
        )
        coordinator.reengagement_enabled = False
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._sleep_interruptible = lambda seconds: None
        coordinator._note_autonomous_silence()

        arbiter = coordinator._surface_arbiter()
        self.assertEqual(arbiter.last_decision.reason, "not_started")

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="test_presence_sentinel_regression",
                confidence=0.58,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        self.assertNotIn(
            "reject:not_started",
            str(coordinator.last_wake_decision.debug.get("surface_rejected_by", "") or ""),
        )
        self.assertNotIn(
            "not_started",
            str(coordinator.last_wake_decision.debug["presence_probe"].get("rejected_by", "") or ""),
        )

    def test_wake_gate_presence_body_only_still_finalizes_without_reject_status(self):
        coordinator = self._make_coordinator(
            telemetry_service=_SignalTelemetry(),
            llm_service=_HybridMicroLlmService(""),
            parser=_JsonParser(),
        )
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        coordinator._sleep_interruptible = lambda seconds: None
        coordinator._note_autonomous_silence()

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="test_presence_body_only",
                confidence=0.66,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "surface_body_only")
        self.assertFalse(coordinator.transport.sent[-1]["should_speak"])

    def test_run_loop_does_not_raise_uncaught_exceptions(self):
        calls = {"n": 0}

        def body_running_fn():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return False

        coordinator = self._make_coordinator(body_running_fn=body_running_fn)

        original_sleep = coordinator_module.time.sleep
        coordinator_module.time.sleep = lambda _seconds: None
        try:
            coordinator.run_loop()
        finally:
            coordinator_module.time.sleep = original_sleep

        self.assertGreaterEqual(calls["n"], 2)

    def test_speech_intent_ignores_resource_pressure(self):
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

        self.assertEqual(decision.intent, "no_speech")

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

    def test_passive_media_and_open_meet_are_not_speakable_screen_signals(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="communication",
            idle_seconds=4.0,
            recent_events=("communication_window_active",),
            evidence=("active window is Meet - Personal - Microsoft Edge",),
            vision_facts=(
                "Trang web YouTube dang hien thi danh sach video ve tro choi Elysium Legacy.",
                "Meet dang mo trong Microsoft Edge.",
            ),
            cpu_percent=20.0,
            ram_percent=40.0,
        )

        self.assertFalse(coordinator._has_concrete_screen_signal(snapshot))
        self.assertEqual(coordinator._build_speech_evidence_context(snapshot), "speech_evidence=<none>")

    def test_traceback_is_speakable_screen_signal(self):
        coordinator = self._make_coordinator()
        snapshot = SimpleNamespace(
            active_window_kind="coding",
            idle_seconds=4.0,
            recent_events=(),
            evidence=(),
            vision_facts=("Terminal shows a Python traceback.",),
            cpu_percent=20.0,
            ram_percent=40.0,
        )

        self.assertTrue(coordinator._has_concrete_screen_signal(snapshot))
        self.assertIn("Terminal shows a Python traceback.", coordinator._build_speech_evidence_context(snapshot))

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

    def test_attention_salience_gates_screen_observation_when_not_broadcast(self):
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
            attention_broadcast=CognitiveBroadcast(label="low_salience", score=0.22),
        )

        self.assertEqual(decision.intent, "no_speech")
        self.assertIn("AttentionSalience", decision.reason)

    def test_pattern_muse_without_speakable_evidence_stays_silent(self):
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

        self.assertEqual(decision.intent, "no_speech")

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
        _, repeat_count_3 = coordinator._track_autonomous_signature(snapshot, ti_report)

        self.assertEqual(repeat_count_1, 1)
        self.assertEqual(repeat_count_2, 2)
        self.assertEqual(repeat_count_3, 3)
        self.assertFalse(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=repeat_count_2,
            )
        )
        self.assertTrue(
            coordinator._should_suppress_autonomous_reply(
                ti_report=ti_report,
                repeat_count=repeat_count_3,
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
                repeated_topic_streak=3,
            )
        )

    def test_preview_text_truncates_without_truncated_suffix(self):
        coordinator = self._make_coordinator()

        preview = coordinator._preview_text("abcdefghijklmnopqrstuvwxyz", limit=10)

        self.assertEqual(preview, "abcdefghij...")
        self.assertNotIn("truncated", preview)

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
                now=219.0,
            )
        )
        self.assertFalse(
            coordinator._should_hold_ambient_silence(
                snapshot=snapshot,
                ti_report=ti_report,
                now=221.0,
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

    def test_internal_state_persists_across_restart_with_memory_core(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory")
            coordinator = self._make_coordinator(
                memory_core=MemoryCognitionCore(path),
            )

            coordinator._handle_incoming({"type": "force_speak"})
            first_state = coordinator._get_internal_state()

            restarted = self._make_coordinator(
                memory_core=MemoryCognitionCore(path),
            )

            self.assertGreater(first_state.cycle_count, 0)
            restarted_state = restarted._get_internal_state()
            self.assertEqual(restarted_state.cycle_count, first_state.cycle_count)
            self.assertEqual(restarted_state.last_channel, first_state.last_channel)

    def test_internal_agenda_persists_across_restart_with_memory_core(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory")
            coordinator = self._make_coordinator(
                memory_core=MemoryCognitionCore(path),
            )
            coordinator.internal_agenda.add(
                kind="open_question",
                summary="Can resolve pending ambiguity after restart.",
                evidence_ids=("agenda_ev_1",),
                pressure=0.66,
                confidence=0.72,
            )

            restarted = self._make_coordinator(
                memory_core=MemoryCognitionCore(path),
            )

            items = restarted.internal_agenda.top_items(limit=5)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].summary, "Can resolve pending ambiguity after restart.")
            self.assertEqual(items[0].evidence_ids, ("agenda_ev_1",))

    def test_observe_only_wake_route_skips_main_directive_llm(self):
        coordinator = self._make_coordinator(parser=_JsonParser())
        coordinator._sleep_interruptible = lambda seconds: None

        def _fake_observer(**kwargs):
            coordinator.last_wake_decision = coordinator_module.WakeDecision(
                level="observe_only",
                should_speak=False,
                should_call_vision=False,
                should_wake_main=False,
                should_run_daydream=False,
                reason="test_observe_only",
                confidence=0.82,
            )
            return None

        coordinator._run_background_observer = _fake_observer

        self.assertTrue(coordinator._run_loop_iteration())
        self.assertEqual(coordinator.llm_service.directive_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "presence_maintenance_body_only")
        self.assertFalse(coordinator.transport.sent[-1]["should_speak"])
        self.assertIn("wake=observe_only", coordinator.transport.sent[-1]["debug_trace"])

    def test_session_ritual_restores_continuity_and_sends_optional_greeting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory")
            core = MemoryCognitionCore(path)
            core.save(
                {
                    "active_state": {"metadata": {}},
                    "internal_state": {
                    "cycle_count": 4,
                    "last_focus_kind": "coding",
                    "last_channel": "chat",
                    "last_self_state_label": "engaged",
                    "goal_persistence": {
                        "goal_id": "goal_ritual",
                        "summary": "implement session ritual layer",
                        "status": "active",
                        "strength": 0.78,
                    },
                    },
                },
            )
            coordinator = self._make_coordinator(
                memory_core=core,
                telemetry_service=_PresenceTelemetry(),
                parser=_JsonParser(),
                llm_service=_StaticDirectiveLlmService("Ngài quay lại rồi. Ta nhớ phần việc còn dang dở."),
            )

            report = coordinator._restore_session_ritual_once()

            self.assertTrue(report.session_resumed)
            self.assertTrue(report.should_greet)
            self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "session_ritual")
            self.assertEqual(coordinator.transport.sent[-1]["text"], "Ngài quay lại rồi. Ta nhớ phần việc còn dang dở.")
            self.assertEqual(coordinator.llm_service.directive_calls, 1)
            self.assertEqual(coordinator.llm_service.last_directive_kwargs["speech_intent"], "session_ritual")
            self.assertIn("resume_goal:implement session ritual layer", coordinator.llm_service.last_directive_kwargs["ti_context"])
            self.assertEqual(coordinator._get_internal_state().session_resume_count, 1)

    def test_session_ritual_empty_llm_still_sends_fallback_greeting(self):
        coordinator = self._make_coordinator(
            telemetry_service=_DummyTelemetry(),
            parser=_JsonParser(),
            llm_service=_StaticDirectiveLlmService(""),
        )

        report = coordinator._restore_session_ritual_once()

        self.assertTrue(report.should_greet)
        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "session_ritual")
        self.assertEqual(coordinator.transport.sent[-1]["text"], "Ngài quay lại rồi.")
        self.assertIn("fallback_after_empty_llm", coordinator.transport.sent[-1]["debug_trace"])


if __name__ == "__main__":
    unittest.main()
