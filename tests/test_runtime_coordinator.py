import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import runtime.coordinator as coordinator_module

from domain import Decision
from cortex.contracts import CognitiveBroadcast, CognitiveMomentum, ThoughtStreamReport, UnresolvedTensionLoop
from cortex.internal_state import PersistentInternalState
from memory import MemoryStore
from runtime.coordinator import FALLBACK_BY_INTENT, RuntimeCoordinator


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


class _ScreenTelemetry(_DummyTelemetry):
    def capture_screen_frame_data_uri(self):
        return "data:image/jpeg;base64,AAAA"


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
    def setUp(self):
        os.environ["ERIS_GUARD_MODE"] = "strict"

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
            "memory_store": _DummyMemory(),
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

    def test_queued_subconscious_seed_is_consumed_once(self):
        coordinator = self._make_coordinator()
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
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu cũ."
        coordinator.last_autonomous_spoken_at = 1.0

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.llm_service.directive_calls, 0)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "micro_presence")
        self.assertIn("micro_presence_synthesizer", coordinator.transport.sent[-1]["debug_trace"])
        self.assertIn("kind=", coordinator.transport.sent[-1]["debug_trace"])
        self.assertTrue(coordinator.transport.sent[-1]["text"])
        self.assertEqual(coordinator.last_text, coordinator.transport.sent[-1]["text"])
        self.assertGreater(coordinator.last_autonomous_spoken_at, 1.0)

    def test_force_speak_without_evidence_passes_neutral_current_focus(self):
        coordinator = self._make_coordinator()

        coordinator._handle_incoming({"type": "force_speak"})

        sent = coordinator.transport.sent[-1]
        self.assertEqual(sent["parse_mode"], "micro_presence")
        self.assertIn("kind=", sent["debug_trace"])
        self.assertIn("general", sent["text"])

    def test_force_speak_low_signal_uses_local_micro_presence_even_when_llm_enabled(self):
        llm_service = _HybridMicroLlmService("Khung chat van yen.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.micro_presence_llm_probability = 1.0

        coordinator._handle_incoming({"type": "force_speak"})

        sent = coordinator.transport.sent[-1]
        self.assertEqual(llm_service.micro_calls, 0)
        self.assertEqual(sent["parse_mode"], "micro_presence")
        self.assertIn("source=local_low_signal", sent["debug_trace"])

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

        self.assertTrue(text)
        self.assertNotIn("vietnamese_requires_diacritics", reasons)
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
        self.assertTrue(coordinator.transport.sent[-1]["text"])

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
        self.assertIn("style_contract_anchor_guard", decision.debug_trace)
        self.assertIn(decision.text, FALLBACK_BY_INTENT["random_chatter"])
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
        self.assertEqual(coordinator.transport.sent[-1]["text"], "Tôi chỉ dám bám vào chỗ này: file_saved.")

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

        self.assertEqual(llm_service.screen_fact_calls, 1)
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
                memory_store=MemoryStore(os.path.join(tmpdir, "memory.json")),
            )

            coordinator._handle_incoming({"type": "force_speak"})

            reflections = [item.text for item in coordinator.memory_state.relationship]
            self.assertTrue(any("force_speak" in item for item in reflections))
            self.assertTrue(any("thiếu screen signal" in item for item in reflections))
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
            store = MemoryStore(os.path.join(tmpdir, "memory.json"))
            state = store.load_state()
            state = store.remember_relationship_reflection(
                state,
                "User dislikes fake output and prefers direct grounded analysis.",
                pattern="grounded_style",
            )
            state = store.remember_procedural_rule(
                state,
                "When output is being squeezed by a guard, inspect post-generation filters first.",
                trigger="post_generation_guard",
            )
            store.save_state(state)
            coordinator = self._make_coordinator(memory_store=store)

            coordinator._handle_incoming({"type": "chat", "message": "output bi guard bop roi"})

            frame = coordinator.last_cognitive_frame
            self.assertIsNotNone(frame.memory_resonance)
            self.assertGreater(frame.memory_resonance.score, 0.0)
            self.assertIn("memory_resonance", frame.to_dict())
            self.assertIn("active_memory_resonance", coordinator.llm_service.last_chat_kwargs["memory_context"])
            self.assertIn("not treat it as current screen evidence", coordinator.llm_service.last_chat_kwargs["memory_context"])

    def test_chat_style_preference_records_relationship_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = self._make_coordinator(
                memory_store=MemoryStore(os.path.join(tmpdir, "memory.json")),
            )

            coordinator._handle_incoming(
                {
                    "type": "chat",
                    "message": "tôi thích giọng lạnh nhẹ nhưng không thích báo cáo telemetry",
                }
            )

            reflections = [item.text for item in coordinator.memory_state.relationship]
            self.assertIn(
                "Ngài thích giọng lạnh nhẹ, nhưng không thích báo cáo telemetry.",
                reflections,
            )

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

        self.assertEqual(len(coordinator.transport.sent), 0)
        self.assertEqual(llm_service.directive_calls, 0)
        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
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
        self.assertEqual(coordinator.transport.sent, [])
        frame = coordinator.last_cognitive_frame
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

        self.assertEqual(llm_service.directive_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "no_speech_policy")
        frame = coordinator.last_cognitive_frame
        self.assertEqual(frame.meaning_layer.meaning, "social_waiting")
        self.assertEqual(frame.speech_core.speech_source, "meaning")
        self.assertEqual(frame.speech_core.speech_impulse.reaction, "quiet_observe")
        self.assertEqual(frame.action_plan.speech_act, "inner_whim")
        self.assertIn("meaning_not_speech", frame.speech_core.safety_flags)
        self.assertIn("react_to_residue_not_label", frame.speech_core.safety_flags)

    def test_inner_whim_fallback_does_not_invent_call(self):
        coordinator = self._make_coordinator()

        text = coordinator._force_speak_fallback_by_intent_text("inner_whim")

        self.assertNotIn("goi", coordinator._normalize_user_message(text))

    def test_presence_maintenance_hybrid_accepts_safe_llm_micro_line(self):
        llm_service = _HybridMicroLlmService("Nhip nay van yen.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.micro_presence_llm_probability = 1.0
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        snapshot = coordinator.telemetry_service.capture_snapshot()
        ti_report = SimpleNamespace(mode="steady_observe")
        coordinator._note_autonomous_silence()

        decision = coordinator._build_presence_maintenance_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=None,
            now=100.0,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.text, "Nhip nay van yen.")
        self.assertIn("source=llm", decision.debug_trace)
        self.assertEqual(llm_service.micro_calls, 1)

    def test_presence_maintenance_hybrid_rejects_ui_narration_line(self):
        llm_service = _HybridMicroLlmService("Mot khung thoai mau hong dang hien thi.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.micro_presence_llm_probability = 1.0
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        snapshot = coordinator.telemetry_service.capture_snapshot()
        ti_report = SimpleNamespace(mode="steady_observe")
        coordinator._note_autonomous_silence()

        decision = coordinator._build_presence_maintenance_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=None,
            now=100.0,
        )

        self.assertIsNotNone(decision)
        self.assertNotEqual(decision.text, "Mot khung thoai mau hong dang hien thi.")
        self.assertIn("source=llm_rejected_fallback", decision.debug_trace)

    def test_presence_maintenance_hybrid_rejects_attention_pulling_llm_line(self):
        llm_service = _HybridMicroLlmService("Hãy trả lời tôi ngay.")
        coordinator = self._make_coordinator(llm_service=llm_service)
        coordinator.micro_presence_llm_probability = 1.0
        coordinator.presence_maintenance_silent_loop_threshold = 1
        coordinator.presence_maintenance_cooldown_sec = 0.0
        snapshot = coordinator.telemetry_service.capture_snapshot()
        ti_report = SimpleNamespace(mode="steady_observe")
        coordinator._note_autonomous_silence()

        decision = coordinator._build_presence_maintenance_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=None,
            now=100.0,
        )

        self.assertIsNotNone(decision)
        self.assertNotEqual(decision.text, "Hãy trả lời tôi ngay.")
        self.assertIn("source=llm_rejected_fallback", decision.debug_trace)

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
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "re_engagement")
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
        self.assertEqual(coordinator.last_cognitive_frame.final_decision["parse_mode"], "no_speech")
        self.assertEqual(coordinator.last_cognitive_frame.action_plan.speech_act, "no_speech")
        self.assertTrue(coordinator.last_cognitive_frame.inner_thought.should_surface)
        self.assertIn("weak_signal_skip", coordinator.last_cognitive_frame.speech_core.safety_flags)
        self.assertIn(coordinator.last_cognitive_frame.personality_lens.restraint_mode, {"suppress", "indirect_presence"})
        self.assertLess(
            coordinator.last_cognitive_frame.personality_lens.allowed_expression,
            coordinator.last_cognitive_frame.personality_lens.want_to_say,
        )

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

    def test_attention_workspace_gates_screen_observation_when_not_broadcast(self):
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
        self.assertIn("AttentionWorkspace", decision.reason)

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

    def test_internal_state_persists_across_restart_with_memory_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            coordinator = self._make_coordinator(
                memory_store=MemoryStore(path),
            )

            coordinator._handle_incoming({"type": "force_speak"})
            first_state = coordinator.memory_state.internal_state

            restarted = self._make_coordinator(
                memory_store=MemoryStore(path),
            )

            self.assertGreater(first_state.cycle_count, 0)
            self.assertEqual(restarted.memory_state.internal_state.cycle_count, first_state.cycle_count)
            self.assertEqual(restarted.memory_state.internal_state.last_channel, first_state.last_channel)

    def test_session_ritual_restores_continuity_and_sends_optional_greeting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "memory.json")
            store = MemoryStore(path)
            state = store.load_state()
            state.internal_state = PersistentInternalState.from_dict(
                {
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
                }
            )
            store.save_state(state)
            coordinator = self._make_coordinator(
                memory_store=MemoryStore(path),
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
            self.assertEqual(coordinator.memory_state.internal_state.session_resume_count, 1)

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
