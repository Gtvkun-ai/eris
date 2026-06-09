import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from domain import Decision
from llm import FormatViolationException
from runtime.coordinator import RuntimeCoordinator


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


class _DummyTransport:
    def __init__(self):
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)

    def poll_json(self):
        return None

    def close(self):
        return None


class _FormatFailingChatLlmService:
    def __init__(self):
        self.chat_calls = 0
        self.last_chat_kwargs = {}

    def generate_chat_reply(self, **kwargs):
        self.chat_calls += 1
        self.last_chat_kwargs = kwargs
        raise FormatViolationException(
            "LlmService local model.gguf also returned invalid chat JSON",
            channel="chat",
            raw_text='{"system_action":"none",',
        )

    def generate_directive(self, **kwargs):
        return '{"text":"noop","animation":"stand","direction":0,"target_x":-1.0,"bounce_action":"","next_animation":"","system_action":"","action_input":""}'


class _JsonParser:
    def build_chat_user_message(self, *, user_message, last_chat_answer):
        return user_message

    def parse(self, raw, user_hint=""):
        data = json.loads(raw)
        return Decision(
            text=data.get("text", ""),
            animation=data.get("animation", "stand"),
            intent=data.get("intent", ""),
            action=data.get("action", ""),
            reasoning_tags=tuple(data.get("reasoning_tags", ()) or ()),
            should_speak=bool(data.get("should_speak", True)),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            direction=int(data.get("direction", 0) or 0),
            target_x=float(data.get("target_x", -1.0) or -1.0),
            bounce_action=data.get("bounce_action", ""),
            debug_trace=data.get("debug_trace", ""),
            next_animation=data.get("next_animation", ""),
            system_action=data.get("system_action", ""),
            action_input=data.get("action_input", ""),
            parse_mode=data.get("parse_mode", "json"),
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


class _DummyNi:
    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(
            drift_score=0.0,
            drift_level="low",
            prompt_context="",
            should_raise_guard=False,
            similarity=1.0,
            evidence=(),
        )

    def evaluate_autonomous(self, **kwargs):
        return self.evaluate_chat(**kwargs)


class _DummyTi:
    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(mode="chat_general", reason="", prompt_context="", animation_hint="stand")

    def evaluate_autonomous(self, **kwargs):
        return SimpleNamespace(
            mode="steady_observe",
            reason="",
            prompt_context="",
            animation_hint="stand",
            force_animation=False,
            motion_intent_hint="",
            motion_target_x_hint=-1.0,
            motion_facing_hint=0,
            target_x_hint=-1.0,
            direction_hint=0,
        )

    def enforce_decision(self, decision, report, user_hint=""):
        return decision


class _DummyFe:
    def create_memory(self):
        return SimpleNamespace()

    def evaluate_chat(self, **kwargs):
        return SimpleNamespace(mode="chat_general", tone_label="", intent_label="ordinary_dialogue", session_arc="", style_context="")

    def evaluate_autonomous(self, **kwargs):
        return SimpleNamespace(
            mode="grounded",
            tone_label="",
            intent_label="ordinary_dialogue",
            session_arc="",
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


def test_chat_format_violation_tries_fallback_api_then_blocks():
    llm = _FormatFailingChatLlmService()
    coordinator = RuntimeCoordinator(
        logger=_DummyLogger(),
        transport=_DummyTransport(),
        llm_service=llm,
        parser=_JsonParser(),
        telemetry_service=_DummyTelemetry(),
        ni_engine=_DummyNi(),
        ti_governor=_DummyTi(),
        fe_renderer=_DummyFe(),
        memory_core=_DummyMemory(),
        body_running_fn=lambda: True,
    )

    coordinator._run_chat_cycle("xin chao", user_timestamp=100.0)

    sent = coordinator.transport.sent[-1]
    # 3 lượt remote (allow_local_fallback=False) + 1 lượt đổi API (allow_local_fallback=True)
    assert llm.chat_calls == 4
    # Always-block: cạn mọi đường thì chặn, không bịa câu trấn an.
    assert sent["intent"] == "no_fallback_block"
    assert sent["parse_mode"] == "no_fallback_block"
    assert "chặn lượt" in sent["text"]
    assert "format_violation_blocked" in sent["debug_trace"]
    # Lượt đổi API thật sự được gọi với allow_local_fallback=True.
    assert llm.last_chat_kwargs.get("allow_local_fallback") is True
def test_chat_format_violation_no_fallback_mode_blocks_instead_of_recovering():
    os.environ["ERIS_NO_FALLBACK_MODE"] = "1"
    try:
        llm = _FormatFailingChatLlmService()
        coordinator = RuntimeCoordinator(
            logger=_DummyLogger(),
            transport=_DummyTransport(),
            llm_service=llm,
            parser=_JsonParser(),
            telemetry_service=_DummyTelemetry(),
            ni_engine=_DummyNi(),
            ti_governor=_DummyTi(),
            fe_renderer=_DummyFe(),
            memory_core=_DummyMemory(),
            body_running_fn=lambda: True,
        )

        coordinator._run_chat_cycle("xin chao", user_timestamp=100.0)

        sent = coordinator.transport.sent[-1]
        assert llm.chat_calls == 3
        assert sent["intent"] == "no_fallback_block"
        assert sent["parse_mode"] == "no_fallback_block"
        assert "no-fallback mode" in sent["text"].lower()
    finally:
        os.environ.pop("ERIS_NO_FALLBACK_MODE", None)
