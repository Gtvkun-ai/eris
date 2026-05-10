import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

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


class _SignalTelemetry(_DummyTelemetry):
    def capture_snapshot(self, **kwargs):
        snapshot = super().capture_snapshot(**kwargs)
        snapshot.active_window = "main.py - Visual Studio Code"
        snapshot.active_window_kind = "coding"
        snapshot.focus_summary = "coding workspace"
        snapshot.recent_events = ("file_saved",)
        snapshot.evidence = ("active editor changed",)
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

    def test_force_speak_low_signal_surfaces_inner_thought_before_llm(self):
        coordinator = self._make_coordinator()
        coordinator.last_text = "Một câu cũ."
        coordinator.last_autonomous_spoken_at = 1.0

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertIn("SpeechCore mode", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertIn("topic_seed=present_whim", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertIn("do not use canned phrases", coordinator.llm_service.last_directive_kwargs["ti_context"])
        self.assertEqual(coordinator.llm_service.last_directive_kwargs["avoid_text"], "Một câu cũ.")
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "inner_thought")
        self.assertEqual(coordinator.transport.sent[-1]["text"], "phan hoi dau tien")
        self.assertEqual(coordinator.last_text, coordinator.transport.sent[-1]["text"])
        self.assertGreater(coordinator.last_autonomous_spoken_at, 1.0)

    def test_force_speak_inner_thought_repairs_generic_meta_ack(self):
        llm_service = _GenericThenSocialLlmService()
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            parser=_JsonParser(),
        )

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(llm_service.directive_calls, 2)
        self.assertIn("SpeechCore repair", llm_service.last_directive_kwargs["ti_context"])
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "inner_thought")
        self.assertNotIn("muốn tôi nói gì", coordinator.transport.sent[-1]["text"])
        self.assertIn("buổi", coordinator.transport.sent[-1]["text"])

    def test_force_speak_anti_mindreading_filter_rewrites_unfounded_emotion_claim(self):
        coordinator = self._make_coordinator(
            llm_service=_MindreadingForceSpeakLlmService(),
            parser=_JsonParser(),
        )

        coordinator._handle_incoming({"type": "force_speak"})

        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "inner_thought")
        self.assertNotIn("ngai dang met", coordinator.transport.sent[-1]["text"].lower())
        self.assertNotEqual(coordinator.transport.sent[-1]["text"], "Co ve Ngai dang met.")

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
        self.assertEqual(coordinator.last_cognitive_frame.inner_thought.intent, "curious_question")
        self.assertIn("intent_alignment_guard", sent["debug_trace"])
        self.assertIn("semantic_repair_failed", sent["debug_trace"])
        self.assertEqual(sent["parse_mode"], "semantic_repair_failed")
        self.assertEqual(sent["text"], "")
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

        self.assertEqual(decision.text, "")
        self.assertEqual(decision.parse_mode, "semantic_repair_failed")
        self.assertIn("semantic_repair_failed", decision.debug_trace)

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
                self.assertIn("phrase_family_guard", sent["debug_trace"])
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
        self.assertEqual(coordinator.llm_service.last_directive_kwargs["avoid_text"], "Một câu cũ.")
        self.assertIn("speech_evidence=", coordinator.llm_service.last_directive_kwargs["telemetry_data"])
        self.assertNotIn("ambient cues", coordinator.llm_service.last_directive_kwargs["telemetry_data"])
        self.assertEqual(coordinator.transport.sent[-1]["text"], "phan hoi dau tien")

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
        self.assertEqual(coordinator.llm_service.directive_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "inner_thought")
        self.assertEqual(coordinator.transport.sent[-1]["text"], "phan hoi dau tien")

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
        self.assertEqual(frame.action_plan.speech_intent, "user_requested")
        self.assertEqual(frame.action_plan.speech_act, "inner_whim")
        self.assertTrue(frame.inner_thought.should_surface)
        self.assertEqual(frame.inner_thought.intent, "inner_whim")
        self.assertEqual(frame.speech_core.speech_source, "freeform")
        self.assertEqual(frame.speech_core.motivation_pressure.winner.label, "user_requested_presence")
        self.assertIn("motivation_pressure", frame.to_dict()["speech_core"])
        self.assertIn("no_screen_claim", frame.action_plan.risk_flags)
        self.assertEqual(frame.final_decision["parse_mode"], "inner_thought")
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

        self.assertEqual(coordinator.transport.sent, [])
        self.assertEqual(llm_service.directive_calls, 0)
        frame = coordinator.last_cognitive_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.channel, "autonomous")
        self.assertFalse(frame.action_plan.should_speak)
        self.assertEqual(frame.action_plan.speech_intent, "no_speech")
        self.assertEqual(frame.final_decision["parse_mode"], "no_speech")

    def test_autonomous_long_idle_generates_inner_thought_with_llm(self):
        llm_service = _DummyLlmService()
        coordinator = self._make_coordinator(
            llm_service=llm_service,
            telemetry_service=_LongIdleTelemetry(),
        )
        coordinator._sleep_interruptible = lambda seconds: coordinator.stop()

        coordinator.run_loop()

        self.assertEqual(llm_service.directive_calls, 1)
        self.assertEqual(coordinator.transport.sent[-1]["parse_mode"], "inner_thought")
        self.assertEqual(coordinator.last_cognitive_frame.action_plan.speech_act, "inner_whim")
        self.assertTrue(coordinator.last_cognitive_frame.inner_thought.should_surface)
        self.assertIn("no_screen_claim", coordinator.last_cognitive_frame.action_plan.risk_flags)
        self.assertIn("topic_seed=quiet_whim", llm_service.last_directive_kwargs["ti_context"])

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


if __name__ == "__main__":
    unittest.main()
