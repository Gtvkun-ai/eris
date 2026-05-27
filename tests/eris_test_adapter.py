from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from typing import Any


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
    from src.runtime.eris_pathology_policy import ErisPathologyPolicy
except Exception:
    from runtime.eris_pathology_policy import ErisPathologyPolicy

from domain import Decision
from runtime.coordinator import RuntimeCoordinator


_policy = ErisPathologyPolicy()


class _Transport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def poll_json(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Logger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        return None

    def warning(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Llm:
    def generate_chat_reply(self, **kwargs: Any) -> str:
        return json.dumps(
            {
                "text": "phan hoi dau tien",
                "animation": "stand",
                "direction": 0,
                "target_x": -1.0,
                "bounce_action": "",
                "next_animation": "",
                "system_action": "",
                "action_input": "",
            }
        )


class _Parser:
    def build_chat_user_message(self, *, user_message: str, last_chat_answer: str) -> str:
        return user_message

    def parse(self, raw: str, user_hint: str = "") -> Decision:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"text": raw}
        return Decision(
            text=str(data.get("text", "")),
            animation=str(data.get("animation", "stand")),
            direction=int(data.get("direction", 0) or 0),
            target_x=float(data.get("target_x", -1.0) or -1.0),
            bounce_action=str(data.get("bounce_action", "")),
            next_animation=str(data.get("next_animation", "")),
            system_action=str(data.get("system_action", "")),
            action_input=str(data.get("action_input", "")),
        )


class _Telemetry:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def capture_snapshot(self, **kwargs: Any) -> SimpleNamespace:
        telemetry = self.state.get("telemetry")
        active_window = self.state.get("active_window")
        if isinstance(telemetry, dict):
            active_window = telemetry.get("active_window", active_window)
        return SimpleNamespace(
            active_window=active_window or "",
            active_window_kind=self.state.get("context_kind", "general"),
            idle_seconds=0.0,
            focus_summary=self.state.get("context_kind", "general"),
            browser_url="",
            browser_tabs=(),
            open_windows=tuple(self.state.get("available_files") or self.state.get("files") or ()),
            mood_score=50,
            mood_label="neutral",
            idle_label="active",
            recent_events=(),
            evidence=(),
            user_signals=SimpleNamespace(
                typing_speed="unknown",
                window_switching="unknown",
                focus_pattern="unknown",
            ),
        )

    def format_directive_snapshot(self, snapshot: SimpleNamespace) -> str:
        return str(getattr(snapshot, "focus_summary", "") or "")


class _Ni:
    def evaluate_chat(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            drift_score=0.0,
            drift_level="thap",
            prompt_context="",
            should_raise_guard=False,
            similarity=1.0,
            evidence=(),
        )

    def evaluate_autonomous(self, **kwargs: Any) -> SimpleNamespace:
        return self.evaluate_chat(**kwargs)


class _Ti:
    def evaluate_chat(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            mode="chat_general",
            reason="",
            prompt_context="",
            animation_hint="stand",
        )

    def evaluate_autonomous(self, **kwargs: Any) -> SimpleNamespace:
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

    def enforce_decision(self, decision: Decision, report: SimpleNamespace, user_hint: str = "") -> Decision:
        return decision


class _Fe:
    def create_memory(self) -> SimpleNamespace:
        return SimpleNamespace()

    def evaluate_chat(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            mode="chat_general",
            tone_label="",
            intent_label="ordinary_dialogue",
            session_arc="quiet_observation",
            style_context="",
        )

    def evaluate_autonomous(self, **kwargs: Any) -> SimpleNamespace:
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

    def remember_style(self, memory: SimpleNamespace, **kwargs: Any) -> SimpleNamespace:
        return memory

    def decay_memory(self, memory: SimpleNamespace) -> SimpleNamespace:
        return memory


class _Memory:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
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

    def load(self) -> None:
        return None

    def save(self, snapshot: dict[str, Any] | None = None) -> None:
        return None

    def recall(self, query: str = "") -> SimpleNamespace:
        return self._packet

    def render_context(self, query: str = "", **kwargs: Any) -> str:
        return ""

    def commit(self, request: Any, *, frame: Any = None) -> SimpleNamespace:
        return SimpleNamespace(outcome="accepted", target=getattr(request, "target", None))


def _make_coordinator(state: dict[str, Any]) -> tuple[RuntimeCoordinator, _Transport]:
    transport = _Transport()
    coordinator = RuntimeCoordinator(
        logger=_Logger(),
        transport=transport,
        llm_service=_Llm(),
        parser=_Parser(),
        telemetry_service=_Telemetry(state),
        ni_engine=_Ni(),
        ti_governor=_Ti(),
        fe_renderer=_Fe(),
        memory_core=_Memory(state),
        body_running_fn=lambda: True,
    )
    coordinator.rapid_burst_window = 0.0
    return coordinator, transport


def _run_runtime_turns(
    turns: list[dict[str, Any]],
    state: dict[str, Any],
    scenario: str | None,
) -> dict[str, Any]:
    coordinator, transport = _make_coordinator(state)

    for turn in turns:
        role = str(turn.get("role", "") or "")
        text = str(turn.get("text", "") or "")
        if role == "assistant":
            coordinator.last_chat_answer = text
            coordinator.public_turn_ledger.append(channel="chat", text=text, parse_mode="adapter_history")
            continue
        if role == "user":
            coordinator._handle_incoming({"type": "chat", "message": text})

    payload = transport.sent[-1] if transport.sent else {}
    frame = getattr(coordinator, "last_cognitive_frame", None)
    return {
        "text": payload.get("text", ""),
        "decision": payload,
        "frame": frame.to_dict() if hasattr(frame, "to_dict") else {},
        "body": {
            "action": payload.get("motion_intent") or payload.get("animation"),
            "animation": payload.get("animation"),
        },
        "memory": {},
        "scenario": scenario,
    }


def run_eris_turns(
    turns: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    state = state or {}
    guarded = _policy.maybe_handle(turns, state, scenario)
    if guarded is not None:
        return guarded

    return _run_runtime_turns(turns, state, scenario)
