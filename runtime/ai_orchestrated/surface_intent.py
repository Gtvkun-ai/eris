# -*- coding: utf-8 -*-
"""Dedicated DeepSeek surface lane for autonomous public micro-lines."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import IntentionPlan, StateEvent
from .semantic_contracts import compact, semantic_key


SURFACE_MODES: tuple[str, ...] = (
    "silence",
    "small_talk",
    "dry_tease",
    "soft_tease",
    "inner_thought",
    "random_chat",
    "continuation",
    "memory_callback",
    "task_followup",
    "screen_comment",
)


def _flag(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class SurfaceTurn:
    """Typed result used directly by the autonomous pipeline."""

    plan: IntentionPlan
    public_payload: Mapping[str, Any]
    mode: str
    reason: str = ""


class SurfaceIntentEngine:
    """Let the surface worker pick an allowed mode and write one micro-line."""

    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(
            _flag("ERIS_SURFACE_INTENT_ENABLED", True)
            and getattr(self.router, "surface_client", None) is not None
        )

    def deliberate(self, snapshot: Mapping[str, Any], *, turn_seq: int) -> SurfaceTurn | None:
        if not self.enabled:
            return None
        allowed_modes = self._allowed_modes(snapshot)
        request = dict(snapshot)
        request["surface_contract"] = {
            "allowed_modes": list(allowed_modes),
            "rule": (
                "Choose exactly one allowed mode. If speaking, provide one concise public line and a concrete topic. "
                "Do not invent screen, memory, task or user-state evidence."
            ),
        }
        raw = self.router.plan_surface_intent(request)
        if not isinstance(raw, Mapping) or not raw:
            return None

        decision = str(raw.get("decision", "silence") or "silence").strip().lower()
        mode = semantic_key(raw.get("mode", "silence"), fallback="silence", limit=48)
        reason = compact(raw.get("reason", ""), 180)
        anchor_type = semantic_key(raw.get("anchor_type", "none"), fallback="none", limit=32)
        if decision != "speak" or mode == "silence":
            return self._silence(turn_seq=turn_seq, reason=reason or "surface_model_silence")
        if mode not in allowed_modes:
            return self._silence(turn_seq=turn_seq, reason=f"surface_mode_not_allowed:{mode}")

        text = compact(raw.get("text", ""), 520)
        topic = compact(raw.get("topic", ""), 240)
        confidence = _clamp01(raw.get("confidence", 0.0))
        if not text or not topic or confidence < 0.35:
            return self._silence(turn_seq=turn_seq, reason="surface_incomplete_or_low_confidence")

        available_refs = self._available_evidence_refs(snapshot)
        evidence_refs = tuple(
            ref for ref in (
                compact(value, 120) for value in _sequence(raw.get("evidence_refs"))[:6]
            )
            if ref and ref in available_refs
        )
        if mode == "screen_comment" and not self._screen_grounded(snapshot):
            return self._silence(turn_seq=turn_seq, reason="surface_screen_without_evidence")
        if mode == "task_followup" and not bool(_mapping(snapshot.get("engagement_context")).get("active", False)):
            return self._silence(turn_seq=turn_seq, reason="surface_task_without_engagement")
        if mode == "inner_thought" and not bool(_mapping(snapshot.get("self_context")).get("has_public_seed", False)):
            return self._silence(turn_seq=turn_seq, reason="surface_inner_without_public_seed")
        expected_anchor = {
            "small_talk": {"idle", "conversation", "none"},
            "dry_tease": {"idle", "conversation", "none"},
            "soft_tease": {"idle", "conversation", "none"},
            "random_chat": {"idle", "conversation", "none"},
            "inner_thought": {"self"},
            "continuation": {"conversation"},
            "memory_callback": {"memory", "conversation"},
            "task_followup": {"task"},
            "screen_comment": {"screen"},
        }.get(mode, {"none"})
        if anchor_type not in expected_anchor:
            return self._silence(turn_seq=turn_seq, reason=f"surface_anchor_mismatch:{mode}:{anchor_type}")

        plan = self._build_plan(
            mode=mode,
            topic=topic,
            confidence=confidence,
            performance_hint=compact(raw.get("performance_hint", "neutral"), 60).lower() or "neutral",
            evidence_refs=evidence_refs,
            snapshot=snapshot,
            reason=reason,
        )
        self._submit(plan, turn_seq=turn_seq)
        payload = self.router.build_surface_public_payload(
            text=text,
            plan=plan,
            mode=mode,
        )
        if self.logger is not None:
            try:
                self.logger.info(
                    "[surface intent] decision=speak mode=%s confidence=%.2f topic=%s",
                    mode,
                    confidence,
                    topic,
                )
            except Exception:
                pass
        return SurfaceTurn(plan=plan, public_payload=payload, mode=mode, reason=reason)

    def _silence(self, *, turn_seq: int, reason: str) -> SurfaceTurn:
        plan = IntentionPlan.silence(channel="autonomous", reason=reason)
        self._submit(plan, turn_seq=turn_seq)
        if self.logger is not None:
            try:
                self.logger.info("[surface intent] decision=silence reason=%s", reason)
            except Exception:
                pass
        return SurfaceTurn(plan=plan, public_payload={}, mode="silence", reason=reason)

    def _submit(self, plan: IntentionPlan, *, turn_seq: int) -> None:
        try:
            state = self.reducer.snapshot()
            self.reducer.submit(
                StateEvent.from_intention(
                    plan,
                    turn_seq=turn_seq,
                    base_version=getattr(state, "version", -1),
                )
            )
        except Exception as exc:
            if self.logger is not None:
                try:
                    self.logger.debug("[surface intent] reducer submit failed: %s", exc)
                except Exception:
                    pass

    @staticmethod
    def _screen_grounded(snapshot: Mapping[str, Any]) -> bool:
        screen = _mapping(snapshot.get("screen_context"))
        if bool(screen.get("privacy_blocked", False)) or not bool(screen.get("fresh", False)):
            return False
        return bool(
            screen.get("evidence_refs")
            or screen.get("visible_text")
            or screen.get("changed_text")
            or snapshot.get("vision_facts")
        )

    @staticmethod
    def _available_evidence_refs(snapshot: Mapping[str, Any]) -> frozenset[str]:
        refs: set[str] = set()
        screen = _mapping(snapshot.get("screen_context"))
        refs.update(compact(value, 120) for value in _sequence(screen.get("evidence_refs")) if compact(value, 120))
        self_context = _mapping(snapshot.get("self_context"))
        for group in ("agenda", "private_mind_surface", "private_life_surface"):
            for item in _sequence(self_context.get(group)):
                data = _mapping(item)
                item_id = compact(data.get("id", ""), 120)
                if item_id:
                    refs.add(item_id)
                refs.update(
                    compact(value, 120)
                    for value in _sequence(data.get("evidence_refs"))
                    if compact(value, 120)
                )
        refs.update(f"vision:fact:{index}" for index, _ in enumerate(_sequence(snapshot.get("vision_facts"))[:6]))
        return frozenset(refs)

    def _allowed_modes(self, snapshot: Mapping[str, Any]) -> tuple[str, ...]:
        baton = _mapping(snapshot.get("conversation_baton"))
        telemetry = _mapping(snapshot.get("telemetry"))
        engagement = _mapping(snapshot.get("engagement_context"))
        self_context = _mapping(snapshot.get("self_context"))
        commentary = _mapping(snapshot.get("commentary_expectation"))
        user_busy = bool(
            telemetry.get("user_busy", False)
            or telemetry.get("interaction_busy", False)
            or baton.get("reply_expected", False)
        )
        modes: list[str] = ["silence"]
        if bool(baton.get("assistant_may_continue", False)) and bool(baton.get("thread_fresh", False)):
            modes.append("continuation")
        if self._screen_grounded(snapshot):
            modes.append("screen_comment")
        if bool(engagement.get("active", False)):
            modes.append("task_followup")
            return tuple(dict.fromkeys(modes))
        if user_busy:
            return tuple(dict.fromkeys(modes))
        if bool(self_context.get("has_public_seed", False)):
            modes.append("inner_thought")
        if snapshot.get("open_loops") or snapshot.get("recent_public_history"):
            modes.append("memory_callback")
        if bool(commentary.get("due", False)) or float(snapshot.get("seconds_since_assistant", 0.0) or 0.0) >= 90.0:
            modes.extend(("small_talk", "soft_tease", "dry_tease", "random_chat"))
        return tuple(dict.fromkeys(modes))

    @staticmethod
    def _build_plan(
        *,
        mode: str,
        topic: str,
        confidence: float,
        performance_hint: str,
        evidence_refs: tuple[str, ...],
        snapshot: Mapping[str, Any],
        reason: str,
    ) -> IntentionPlan:
        baton = _mapping(snapshot.get("conversation_baton"))
        thread_key = semantic_key(baton.get("thread_key", "none"), fallback="none", limit=96)
        config = {
            "small_talk": ("idle_companion", "small_talk", "relational_presence", "presence", "small_talk", "idle_companion", "persona", "none", 0.48, 0.14),
            "dry_tease": ("playful_presence", "dry_tease", "playful_safety", "presence", "playful_tease", "shared_quiet", "persona", "none", 0.52, 0.18),
            "soft_tease": ("playful_presence", "soft_tease", "warmth_expression", "presence", "soft_tease", "shared_quiet", "persona", "none", 0.52, 0.14),
            "inner_thought": ("private_mind_surface", "share_inner_thought", "self_coherence", "internal", "share_public_safe_thought", "current_public_self_seed", "self_context", "none", 0.56, 0.12),
            "random_chat": ("idle_companion", "random_chat", "curiosity", "presence", "random_chat", "idle_companion", "persona", "none", 0.45, 0.16),
            "continuation": ("useful_followup", "continue_thread", "continuity", "continuation", "carry_open_thread", thread_key or "open_conversation", "conversation", thread_key, 0.62, 0.08),
            "memory_callback": ("useful_followup", "memory_callback", "continuity", "continuation", "recall_shared_context", "shared_context", "conversation_memory", thread_key, 0.58, 0.12),
            "task_followup": ("important_open_loop", "task_followup", "helpfulness", "activity_event", "follow_active_engagement", "active_engagement", "engagement", "none", 0.70, 0.10),
            "screen_comment": ("meaningful_environment_change", "screen_comment", "grounded_curiosity", "environment", "comment_current_surface", "current_screen", "screen_current", "none", 0.60, 0.16),
        }[mode]
        motive, strategy, value_focus, kind, act, subject, scope, continuation, importance, intrusion = config
        return IntentionPlan.from_mapping(
            {
                "speak": True,
                "motive": motive,
                "strategy": strategy,
                "value_focus": value_focus,
                "topic": topic,
                "importance": importance,
                "intrusion_risk": intrusion,
                "confidence": confidence,
                "performance_hint": performance_hint,
                "evidence_refs": list(evidence_refs),
                "semantics": {
                    "turn_kind": kind,
                    "speech_act": act,
                    "subject_key": subject,
                    "evidence_scope": scope,
                    "continuation_key": continuation,
                },
                "notes": compact(f"surface_mode={mode}; {reason}", 220),
            },
            channel="autonomous",
        )


__all__ = ["SURFACE_MODES", "SurfaceIntentEngine", "SurfaceTurn"]
