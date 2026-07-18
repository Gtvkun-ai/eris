# -*- coding: utf-8 -*-
"""Canonical wording adapter for ERIS V3.

The LLM provider remains an adapter. V3 owns the request packet, constraints,
and the interpretation of the provider result. That distinction matters: using
an existing LLM client is not the same thing as delegating cognition to the old
runtime, despite the impressive human habit of confusing plumbing with agency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from runtime.canonical_cognition import LLMWordingResult


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


@dataclass(slots=True)
class WordingRequest:
    frame_id: str
    prompt_context: str
    speech_act: str
    tone: str
    must_include: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    max_intensity: float = 0.5
    output_format: str = "Decision JSON"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "prompt_context": self.prompt_context,
            "speech_act": self.speech_act,
            "tone": self.tone,
            "must_include": list(self.must_include),
            "must_avoid": list(self.must_avoid),
            "max_intensity": float(self.max_intensity),
            "output_format": self.output_format,
        }


class V3WordingEngine:
    module_name = "llm_wording"
    HIDDEN_STATE_MARKERS = (
        "v3_cognitive_plan", "global workspace", "theory of mind", "permission engine",
        "cognitive arbitration", "hidden state", "module report", "system prompt",
    )

    def prepare(self, frame: Any, *, prompt_context: str = "") -> tuple[WordingRequest, LLMWordingResult]:
        speech = _get(frame, "speech_plan", None)
        permission = _get(frame, "permission", None)
        request = WordingRequest(
            frame_id=str(_get(frame, "frame_id", "") or ""),
            prompt_context=str(prompt_context or ""),
            speech_act=str(_get(speech, "speech_act", "answer") or "answer"),
            tone=str(_get(speech, "tone", "cold_soft") or "cold_soft"),
            must_include=[str(x) for x in (_get(speech, "must_include", []) or [])],
            must_avoid=[str(x) for x in (_get(speech, "must_avoid", []) or [])],
            max_intensity=float(_get(permission, "max_intensity", 0.5) or 0.5),
        )
        result = LLMWordingResult(raw_text="", parsed_text=None, parser_ok=True, violations=[], deferred=True)
        return request, result

    def capture(self, frame: Any, decision: Any = None, *, raw_response: str = "", external_violations: list[str] | None = None) -> LLMWordingResult:
        text = str(_get(decision, "text", "") or "")
        raw = str(raw_response or text)
        violations = [str(x) for x in (external_violations or []) if str(x).strip()]
        lowered = text.lower()
        for marker in self.HIDDEN_STATE_MARKERS:
            if marker in lowered:
                violations.append(f"hidden_state_leak:{marker}")
        if re.search(r"<think>|</think>|```json\s*\{", raw, flags=re.I):
            violations.append("reasoning_or_wrapper_leak")
        should_speak = bool(_get(decision, "should_speak", bool(text)))
        if should_speak and not text.strip():
            violations.append("empty_surface_text")
        parser_mode = str(_get(decision, "parse_mode", "") or "")
        parser_trace = str(_get(decision, "parser_trace", "") or "")
        if "fail" in parser_mode.lower():
            violations.append("parser_failure")
        return LLMWordingResult(
            raw_text=raw,
            parsed_text=text or None,
            parser_ok=not violations,
            violations=list(dict.fromkeys(violations)),
            deferred=False,
        )


__all__ = ["WordingRequest", "V3WordingEngine"]
