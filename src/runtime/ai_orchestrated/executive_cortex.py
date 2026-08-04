# -*- coding: utf-8 -*-
"""Gemma Executive Cortex between DeepSeek cognition and runtime mechanics.

DeepSeek workers keep their existing ownership: Observer interprets, Inner
reflects, Seed proposes premises and Surface writes public wording.  This layer
chooses the next cognitive move, may inspect one read-only runtime affordance,
and returns a semantic target.  It never commits speech or executes side-effect
operations by itself.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from .executive_tools import ExecutiveTool, build_live_executive_tool_catalog, catalog_index


EXECUTIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action", "candidate_index", "semantic_target", "speech_act", "tone",
        "tool_name", "tool_input", "reply_baton", "reason", "confidence", "intrusion_risk",
    ],
    "properties": {
        "action": {
            "type": "string",
            "enum": ["silence", "body_only", "use_candidate", "call_tool", "speak_from_tool"],
        },
        "candidate_index": {"type": "integer", "minimum": -1, "maximum": 15},
        "semantic_target": {"type": "string"},
        "speech_act": {"type": "string"},
        "tone": {"type": "string"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "string"},
        "reply_baton": {"type": "string", "enum": ["preserve", "release_optional"]},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "intrusion_risk": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _compact(value: Any, limit: int = 800) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    action: str = "silence"
    candidate_index: int = -1
    semantic_target: str = ""
    speech_act: str = ""
    tone: str = ""
    tool_name: str = ""
    tool_input: str = ""
    reply_baton: str = "preserve"
    reason: str = "executive_silence"
    confidence: float = 0.0
    intrusion_risk: float = 0.0
    tool_result: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ExecutiveDecision":
        data = value or {}
        action = str(data.get("action", "silence") or "silence").strip().lower()
        if action not in {"silence", "body_only", "use_candidate", "call_tool", "speak_from_tool"}:
            action = "silence"
        try:
            index = int(data.get("candidate_index", -1))
        except (TypeError, ValueError):
            index = -1
        return cls(
            action=action,
            candidate_index=max(-1, min(15, index)),
            semantic_target=_compact(data.get("semantic_target", ""), 1200),
            speech_act=_compact(data.get("speech_act", ""), 80).lower(),
            tone=_compact(data.get("tone", ""), 80).lower(),
            tool_name=_compact(data.get("tool_name", ""), 100),
            tool_input=_compact(data.get("tool_input", ""), 1200),
            reply_baton=(
                "release_optional"
                if str(data.get("reply_baton", "preserve") or "preserve").strip().lower() == "release_optional"
                else "preserve"
            ),
            reason=_compact(data.get("reason", "executive_decision"), 300) or "executive_decision",
            confidence=_clamp01(data.get("confidence", 0.0)),
            intrusion_risk=_clamp01(data.get("intrusion_risk", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.executive_decision.v1",
            "action": self.action,
            "candidate_index": self.candidate_index,
            "semantic_target": self.semantic_target,
            "speech_act": self.speech_act,
            "tone": self.tone,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "reply_baton": self.reply_baton,
            "reason": self.reason,
            "confidence": self.confidence,
            "intrusion_risk": self.intrusion_risk,
            "tool_result": dict(self.tool_result or {}),
        }


def may_release_optional_reply_baton(
    blackboard: Any,
    candidate: Any | None,
    decision: ExecutiveDecision,
) -> bool:
    """Allow Gemma to release only a weak social baton for this turn.

    The runtime still owns hard task, safety and structured-engagement batons.
    This helper deliberately uses typed candidate/state fields rather than user
    phrase markers.
    """

    return bool(
        decision.reply_baton == "release_optional"
        and bool(getattr(blackboard, "reply_expected", False))
        and candidate is not None
        and str(getattr(candidate, "kind", "") or "")
        in {"random_chat", "casual_curiosity", "playful_prompt", "social_check_in"}
        and not bool(getattr(blackboard, "engagement_active", False))
        and not bool(getattr(blackboard, "engagement_required", False))
        and decision.confidence >= 0.60
        and decision.intrusion_risk <= 0.35
    )


@dataclass(frozen=True, slots=True)
class ExecutiveOutcome:
    candidate: Any | None
    action: str
    reason: str
    decision: ExecutiveDecision


class ExecutiveCortex:
    """Sparse Gemma policy layer for autonomous conversational trajectory."""

    def __init__(
        self,
        owner: Any,
        client: Any,
        *,
        invoke_structured: Any,
        logger: Any | None = None,
    ) -> None:
        self.owner = owner
        self.client = client
        self.invoke_structured = invoke_structured
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(_flag("ERIS_EXECUTIVE_CORTEX_ENABLED", True) and self.client is not None)

    @staticmethod
    def _system_prompt(*, after_tool: bool = False) -> str:
        tail = (
            "A verified tool result is supplied. Do not call another tool. Choose silence, body_only, use_candidate, or speak_from_tool."
            if after_tool
            else "You may call at most one tool, and only when auto_callable=true."
        )
        return (
            "You are ERIS Executive Cortex. DeepSeek workers already own observation, private reflection, premise generation and public wording. "
            "You own only the next conversational trajectory. Choose whether ERIS should remain silent, use body presence, advance one supplied candidate, "
            "or inspect one live read-only runtime tool before deciding. Silence is a first-class action. Do not reward speaking merely because a candidate exists. "
            "Treat optional conversational invitations as weak evidence, not a user debt. Set reply_baton=release_optional only when recent public history shows a socially optional invitation or a closed topic; preserve it for explicit task questions, required parameters, safety confirmation, or active engagement. Prefer reversible low-pressure moves under social ambiguity. "
            "Never claim a tool succeeded without a verified tool_result. Never select unavailable or non-auto-callable tools. "
            "semantic_target is a meaning brief for DeepSeek Surface, never final public wording. "
            + tail
            + " Return one JSON object only."
        )

    def deliberate(
        self,
        blackboard: Any,
        candidates: Sequence[Any],
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> ExecutiveOutcome:
        candidates = tuple(item for item in candidates if item is not None)
        if not self.enabled:
            candidate = candidates[0] if candidates else None
            return ExecutiveOutcome(candidate, "legacy", "executive_disabled", ExecutiveDecision(action="use_candidate" if candidate else "silence"))

        catalog = build_live_executive_tool_catalog(self.owner, include_unavailable=True, max_items=64, refresh=True)
        decision = self._decide(blackboard, candidates, catalog, snapshot=snapshot, tool_result=None)
        if decision.action == "call_tool":
            result = self._execute_read_only_tool(decision, catalog)
            if result is None:
                return ExecutiveOutcome(None, "silence", "executive_tool_rejected", replace(decision, action="silence"))
            decision = self._decide(
                blackboard,
                candidates,
                catalog,
                snapshot=snapshot,
                tool_result=result,
            )
            decision = replace(decision, tool_result=result)

        if decision.action == "body_only":
            return ExecutiveOutcome(None, "body_only", decision.reason, decision)
        if decision.action == "silence":
            return ExecutiveOutcome(None, "silence", decision.reason, decision)
        if decision.action == "speak_from_tool":
            candidate = self._candidate_from_tool(decision)
            if candidate is None:
                return ExecutiveOutcome(None, "silence", "executive_tool_result_not_grounded", replace(decision, action="silence"))
            return ExecutiveOutcome(candidate, "use_candidate", decision.reason, decision)

        if not candidates:
            return ExecutiveOutcome(None, "silence", "executive_no_candidate", replace(decision, action="silence"))
        index = decision.candidate_index
        if index < 0 or index >= len(candidates):
            index = 0
        candidate = candidates[index]
        candidate = self._rewrite_candidate(candidate, decision)
        return ExecutiveOutcome(candidate, "use_candidate", decision.reason, decision)

    def _decide(
        self,
        blackboard: Any,
        candidates: Sequence[Any],
        catalog: tuple[ExecutiveTool, ...],
        *,
        snapshot: Mapping[str, Any] | None,
        tool_result: Mapping[str, Any] | None,
    ) -> ExecutiveDecision:
        public_view = blackboard.public_view() if callable(getattr(blackboard, "public_view", None)) else {}
        source = snapshot or {}
        payload = {
            "blackboard": public_view,
            "candidate_cards": [self._candidate_card(item, index) for index, item in enumerate(candidates)],
            "recent_public_history": list(source.get("recent_public_history", ()))[-8:],
            "deepseek_lane_digests": {
                "observer": source.get("observer_frame", source.get("last_observer_frame", {})),
                "inner": source.get("self_context", {}),
                "relationship": source.get("relationship", {}),
                "recent_self_turn_semantics": list(source.get("recent_self_turn_semantics", ()))[-6:],
                "shared_semantic_context": source.get("shared_semantic_context", {}),
            },
            "live_tools": [item.to_dict() for item in catalog],
            "verified_tool_result": dict(tool_result or {}),
            "contract": {
                "authority": "trajectory_and_semantic_target_only",
                "surface_owner": "deepseek_surface",
                "runtime_owner": "tool_execution_permission_concurrency",
                "tool_calls_remaining": 0 if tool_result else 1,
            },
        }
        try:
            raw = self.invoke_structured(
                self.client,
                system=self._system_prompt(after_tool=bool(tool_result)),
                payload=payload,
                schema=EXECUTIVE_SCHEMA,
                name="eris_gemma_executive_cortex",
                max_tokens=320,
                reasoning_effort="medium",
                inference_tier="main_cognition",
                priority=58,
                timeout_seconds=float(os.getenv("ERIS_EXECUTIVE_TIMEOUT_S", "18") or 18),
            )
        except Exception as exc:
            self._log("warning", "[executive] model call failed: %s", exc)
            return ExecutiveDecision(reason="executive_model_failure")
        decision = ExecutiveDecision.from_mapping(raw)
        self._log(
            "info",
            "[executive] action=%s candidate=%d tool=%s confidence=%.2f risk=%.2f reason=%s",
            decision.action,
            decision.candidate_index,
            decision.tool_name or "none",
            decision.confidence,
            decision.intrusion_risk,
            decision.reason,
        )
        return decision

    @staticmethod
    def _candidate_card(candidate: Any, index: int) -> dict[str, Any]:
        return {
            "index": index,
            "kind": str(getattr(candidate, "kind", "") or ""),
            "semantic_target": _compact(getattr(candidate, "topic", ""), 1200),
            "speech_act": str(getattr(candidate, "speech_act", "") or ""),
            "anchor_type": str(getattr(candidate, "anchor_type", "") or ""),
            "anchor_id": str(getattr(candidate, "anchor_id", "") or ""),
            "source": str(getattr(candidate, "source", "") or ""),
            "reason": _compact(getattr(candidate, "reason", ""), 320),
            "confidence": _clamp01(getattr(candidate, "confidence", 0.0)),
            "relevance": _clamp01(getattr(candidate, "relevance", 0.0)),
            "urgency": _clamp01(getattr(candidate, "urgency", 0.0)),
            "intrusion_risk": _clamp01(getattr(candidate, "seed_intrusion_risk", 0.0)),
            "evidence_refs": list(getattr(candidate, "evidence_refs", ()) or ()),
        }

    def _execute_read_only_tool(
        self,
        decision: ExecutiveDecision,
        catalog: tuple[ExecutiveTool, ...],
    ) -> Mapping[str, Any] | None:
        tool = catalog_index(catalog).get(decision.tool_name)
        if tool is None or not tool.auto_callable:
            self._log("warning", "[executive] rejected tool=%s auto_callable=0", decision.tool_name)
            return None
        executor = getattr(self.owner, "action_executor", None)
        if executor is None or not callable(getattr(executor, "execute", None)):
            return None
        try:
            result = executor.execute(tool.name, decision.tool_input)
        except Exception as exc:
            self._log("warning", "[executive] tool=%s failed: %s", tool.name, exc)
            return None
        recorder = getattr(self.owner, "_record_tool_grounding", None)
        if callable(recorder):
            try:
                recorder(result, action_name=tool.name)
            except Exception:
                pass
        return {
            "tool_name": tool.name,
            "success": bool(getattr(result, "success", False)),
            "observed": bool(getattr(result, "observed", False)),
            "status": str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", "")) or ""),
            "message": _compact(getattr(result, "message", ""), 1200),
            "data": dict(getattr(result, "data", {}) or {}),
            "evidence": list(getattr(result, "evidence", ()) or ()),
            "error_kind": str(getattr(result, "error_kind", "") or ""),
        }

    @staticmethod
    def _rewrite_candidate(candidate: Any, decision: ExecutiveDecision) -> Any:
        changes: dict[str, Any] = {}
        if decision.semantic_target:
            changes["topic"] = decision.semantic_target
        if decision.speech_act:
            changes["speech_act"] = decision.speech_act
        if decision.tone:
            changes["tone"] = decision.tone
        changes["reason"] = _compact(f"gemma_executive:{decision.reason}; upstream={getattr(candidate, 'reason', '')}", 240)
        changes["source"] = f"gemma_executive:{getattr(candidate, 'source', 'candidate')}"
        try:
            return replace(candidate, **changes)
        except Exception:
            for key, value in changes.items():
                try:
                    setattr(candidate, key, value)
                except Exception:
                    pass
            return candidate

    @staticmethod
    def _candidate_from_tool(decision: ExecutiveDecision) -> Any | None:
        result = decision.tool_result or {}
        if not bool(result.get("success")) or not bool(result.get("observed")):
            return None
        target = decision.semantic_target or str(result.get("message", "") or "")
        if not target:
            return None
        try:
            from .social_initiative import SocialSpeechCandidate

            tool_name = str(result.get("tool_name", "") or "runtime_tool")
            return SocialSpeechCandidate(
                decision="candidate",
                kind="random_chat",
                topic=target,
                speech_act=decision.speech_act or "share_grounded_runtime_finding",
                anchor_type="idle",
                anchor_id=f"executive_tool:{tool_name}",
                evidence_refs=tuple(str(item) for item in result.get("evidence", ()) if str(item or "").strip()),
                requires_grounding=False,
                confidence=max(0.45, decision.confidence),
                relevance=max(0.45, 1.0 - decision.intrusion_risk),
                urgency=0.2,
                tone=decision.tone or "matter_of_fact_warm",
                reason=f"gemma_executive:verified_tool:{tool_name}:{decision.reason}",
                source="gemma_executive_tool",
            )
        except Exception:
            return None

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = [
    "EXECUTIVE_SCHEMA",
    "ExecutiveCortex",
    "ExecutiveDecision",
    "ExecutiveOutcome",
    "may_release_optional_reply_baton",
]
