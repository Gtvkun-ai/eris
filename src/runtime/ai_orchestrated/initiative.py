# -*- coding: utf-8 -*-
"""Runtime Initiative Governor cho self-initiated public turn.

V18 giao controller đúng một trách nhiệm: kiểm quyền phát cho một typed candidate
do Social Initiative Worker đề xuất. Controller không nghĩ topic, không đọc OCR
thô, không gọi model và không viết lời public. Nó chỉ áp user-busy, reply baton,
cooldown, budget, duplicate và provenance trước Surface Realizer.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from runtime.workspace_manager import default_eris_home
from runtime.chess.surface import ChessSurfaceState
from .contracts import IntentionPlan
from .cognitive_blackboard import TypedCognitiveBlackboard
from .semantic_contracts import TurnSemantics
from .social_initiative import SocialSpeechCandidate


def _setting(name: str, default: Any) -> Any:
    try:
        from runtime.runtime_settings_store import runtime_setting
        return runtime_setting("initiative", name, default=default)
    except Exception:
        return os.getenv("ERIS_INITIATIVE_" + name.upper(), default)


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "bật", "bat"}


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return number if number == number else default


def _plan_semantics(plan: Any) -> TurnSemantics:
    value = getattr(plan, "semantics", None)
    if isinstance(value, TurnSemantics):
        return value
    if isinstance(value, Mapping):
        return TurnSemantics.from_mapping(value)
    return TurnSemantics()


@dataclass(frozen=True, slots=True)
class InitiativeProfile:
    kind: str
    cooldown_seconds: float
    minimum_user_silence_seconds: float
    hourly_budget: int
    duplicate_window_seconds: float


_PROFILES: dict[str, InitiativeProfile] = {
    "continuation": InitiativeProfile("continuation", 20.0, 8.0, 20, 180.0),
    "environment": InitiativeProfile("environment", 32.0, 12.0, 24, 180.0),
    "activity_event": InitiativeProfile("activity_event", 12.0, 6.0, 24, 120.0),
    "discovery": InitiativeProfile("discovery", 1800.0, 90.0, 2, 7200.0),
    "internal": InitiativeProfile("internal", 150.0, 30.0, 10, 300.0),
    "presence": InitiativeProfile("presence", 55.0, 12.0, 24, 90.0),
    "startup": InitiativeProfile("startup", 0.0, 0.0, 2, 0.0),
    "force_speak": InitiativeProfile("force_speak", 0.0, 0.0, 20, 300.0),
    "other": InitiativeProfile("other", 120.0, 25.0, 8, 300.0),
}


def profile_for_plan(plan: Any) -> InitiativeProfile:
    """Chọn profile từ key typed, không suy từ câu public."""
    kind = _plan_semantics(plan).turn_kind
    return _PROFILES.get(kind, _PROFILES["other"])


class InitiativeAction(str, Enum):
    """Ba kết quả duy nhất của deterministic initiative policy."""

    NO_OP = "no_op"
    BODY_ONLY = "body_only"
    SPEECH = "speech"


@dataclass(frozen=True, slots=True)
class SpeechIntent:
    """Ý định đã được policy duyệt để Surface Worker chỉ việc viết câu.

    Surface Worker không được đổi action, topic owner hay evidence scope. Nó chỉ
    hiện thực hóa lời nói theo contract này.
    """

    plan: IntentionPlan
    mode: str
    anchor_type: str
    anchor_id: str
    evidence_refs: tuple[str, ...] = ()
    max_sentences: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.speech_intent.v1",
            "mode": self.mode,
            "anchor_type": self.anchor_type,
            "anchor_id": self.anchor_id,
            "evidence_refs": list(self.evidence_refs),
            "max_sentences": self.max_sentences,
            "plan": self.plan.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class InitiativeDecision:
    action: InitiativeAction
    reason: str
    plan: IntentionPlan
    speech_intent: SpeechIntent | None = None
    body_motion: str = "quiet_presence"

    @property
    def should_speak(self) -> bool:
        return self.action is InitiativeAction.SPEECH and self.speech_intent is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.initiative_decision.v1",
            "action": self.action.value,
            "reason": self.reason,
            "body_motion": self.body_motion,
            "plan": self.plan.to_dict(),
            "speech_intent": self.speech_intent.to_dict() if self.speech_intent else None,
        }


@dataclass(frozen=True, slots=True)
class InitiativeEvent:
    timestamp: float
    channel: str
    importance: float
    kind: str = "other"
    semantic_signature: str = ""
    speech_act: str = "unspecified"
    subject_key: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InitiativeState:
    version: int = 0
    events: tuple[InitiativeEvent, ...] = ()
    last_decision: Mapping[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "InitiativeState":
        data = payload or {}
        events: list[InitiativeEvent] = []
        raw = data.get("events", ())
        if isinstance(raw, (list, tuple)):
            for item in raw[-96:]:
                if not isinstance(item, Mapping):
                    continue
                # Migration: state V2 cũ không có signature typed. Không dựng lại
                # signature từ topic vì đó chính là heuristic cần xóa.
                events.append(InitiativeEvent(
                    timestamp=max(0.0, _as_float(item.get("timestamp"), 0.0)),
                    channel=str(item.get("channel", "autonomous") or "autonomous")[:40],
                    importance=max(0.0, min(1.0, _as_float(item.get("importance"), 0.0))),
                    kind=str(item.get("kind", "other") or "other")[:40],
                    semantic_signature=str(item.get("semantic_signature", "") or "")[:320],
                    speech_act=str(item.get("speech_act", "unspecified") or "unspecified")[:64],
                    subject_key=str(item.get("subject_key", "unknown") or "unknown")[:96],
                ))
        return cls(
            version=max(0, int(data.get("version", 0) or 0)),
            events=tuple(events),
            last_decision=dict(data.get("last_decision", {})) if isinstance(data.get("last_decision"), Mapping) else {},
            updated_at=max(0.0, _as_float(data.get("updated_at"), 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "eris.initiative.v3",
            "version": self.version,
            "events": [item.to_dict() for item in self.events],
            "last_decision": dict(self.last_decision),
            "updated_at": self.updated_at,
        }


_CANDIDATE_UNSET = object()


class InitiativeController:
    def __init__(self, *, state_path: Path | None = None, logger: Any | None = None) -> None:
        self.logger = logger
        self._path = state_path or (default_eris_home() / "state" / "initiative_state.json")
        self._lock = threading.RLock()
        self._state = self._load()
        self._dirty = False
        self._last_persist_at = 0.0
        self._persist_debounce_seconds = max(2.0, _as_float(_setting("persist_debounce_seconds", 12.0), 12.0))

    def decide(
        self,
        blackboard: TypedCognitiveBlackboard,
        candidate: SocialSpeechCandidate | None | object = _CANDIDATE_UNSET,
    ) -> InitiativeDecision:
        """Governor thuần timing/quyền phát cho một model-owned candidate.

        V18 không còn bắt runtime tự nghĩ topic. Social Initiative Worker sở hữu
        ``candidate.topic`` và ``candidate.speech_act``; governor chỉ kiểm hard
        boundaries, cooldown, budget, duplicate và provenance. Nếu không có
        candidate, kết quả là NO_OP hoặc BODY_ONLY chứ không tự bịa small talk.
        """

        silence = IntentionPlan.silence(channel="autonomous", reason="initiative_no_op")
        has_delta = bool(blackboard.mechanical_delta or blackboard.activity_event)
        # Compatibility cho test/caller cũ gọi decide(board) trực tiếp. Production
        # luôn truyền candidate (kể cả None), nên nhánh này không trao lại quyền
        # nghĩ topic cho runtime self-turn.
        compatibility_call = candidate is _CANDIDATE_UNSET
        if compatibility_call:
            candidate = self._compat_candidate_from_blackboard(blackboard)

        if not _as_bool(_setting("enabled", True), True):
            return InitiativeDecision(InitiativeAction.NO_OP, "initiative_disabled", silence)
        chess_event_override = bool(
            blackboard.engagement_active
            and (blackboard.engagement_due or blackboard.engagement_required)
            and str(blackboard.engagement_kind or "").lower() == "chess"
            and any(anchor.kind == "task" for anchor in blackboard.anchors)
        )
        reminder_override = bool(
            blackboard.followup_reminder_due
            and blackboard.followup_reminder_count <= 0
            and candidate is not None
            and getattr(candidate, "kind", "") == "followup_reminder"
        )
        if blackboard.reply_expected and not chess_event_override and not reminder_override:
            action = InitiativeAction.BODY_ONLY if has_delta and not blackboard.privacy_blocked else InitiativeAction.NO_OP
            return InitiativeDecision(action, "waiting_for_user_reply", silence, body_motion="quiet_presence")
        if blackboard.user_busy:
            action = InitiativeAction.BODY_ONLY if has_delta and not blackboard.privacy_blocked else InitiativeAction.NO_OP
            return InitiativeDecision(action, "user_busy", silence, body_motion="small_acknowledge")
        if candidate is None or not candidate.available:
            if has_delta and not blackboard.privacy_blocked:
                return InitiativeDecision(
                    InitiativeAction.BODY_ONLY,
                    "mechanical_delta_without_candidate",
                    silence,
                    body_motion="curious_glance",
                )
            return InitiativeDecision(
                InitiativeAction.NO_OP,
                "no_public_anchor" if compatibility_call else "no_speech_candidate",
                silence,
            )

        plan, mode, motion, anchor_type, anchor_id, refs = self._plan_for_candidate(candidate, blackboard)
        allowed, reason = self.evaluate(
            plan,
            now=blackboard.now,
            user_busy=False,
            seconds_since_user=blackboard.seconds_since_user,
        )
        if not allowed:
            if has_delta and not blackboard.privacy_blocked and self.should_body_only(reason, has_perception_delta=True):
                return InitiativeDecision(InitiativeAction.BODY_ONLY, reason, plan, body_motion=motion)
            return InitiativeDecision(InitiativeAction.NO_OP, reason, plan)

        speech_intent = SpeechIntent(
            plan=plan,
            mode=mode,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            evidence_refs=refs,
            max_sentences=2,
        )
        return InitiativeDecision(
            InitiativeAction.SPEECH,
            "allowed",
            plan,
            speech_intent=speech_intent,
            body_motion=motion,
        )

    @staticmethod
    def _compat_candidate_from_blackboard(
        blackboard: TypedCognitiveBlackboard,
    ) -> SocialSpeechCandidate | None:
        """Adapter rollout-only cho API V17; không dùng trong production V18."""

        anchor = blackboard.strongest_anchor()
        if anchor is None:
            return None
        mapping = {
            "conversation": ("continuation", "carry_open_thread", False),
            "task": ("task_followup", "task_followup", False),
            "discovery": ("discovery_share", "share_discovery", bool(anchor.evidence_refs)),
            "screen": ("screen_comment", "comment_current_surface", True),
            "activity": ("screen_comment", "comment_current_surface", True),
            "semantic_scene": ("semantic_scene", "develop_semantic_context", False),
            "memory": ("memory_callback", "memory_callback", True),
            "self": ("inner_thought", "share_public_safe_thought", False),
            "presence": ("social_check_in", "warm_companion_presence", False),
        }
        kind, act, needs_grounding = mapping.get(anchor.kind, ("random_chat", "social_check_in", False))
        return SocialSpeechCandidate(
            decision="candidate",
            kind=kind,
            topic=anchor.topic_seed,
            speech_act=act,
            anchor_type="idle" if anchor.kind == "presence" else anchor.kind,
            anchor_id=anchor.anchor_id,
            evidence_refs=anchor.evidence_refs,
            requires_grounding=needs_grounding,
            confidence=anchor.confidence,
            relevance=anchor.priority,
            urgency=0.15,
            tone="soft",
            reason="v17_direct_call_compatibility",
            source="compatibility_adapter",
        )

    @staticmethod
    def _plan_for_candidate(
        candidate: SocialSpeechCandidate,
        blackboard: TypedCognitiveBlackboard,
    ) -> tuple[IntentionPlan, str, str, str, str, tuple[str, ...]]:
        """Đóng candidate model-owned thành plan typed, không viết lại topic."""

        kind = candidate.kind
        refs = tuple(candidate.evidence_refs[:5])
        mode_map = {
            "continuation": ("continuation", "soft", "continuation", "conversation"),
            "followup_reminder": ("continuation", "gentle_reminder", "continuation", "conversation"),
            "task_followup": ("task_followup", "focused", "activity_event", "task"),
            "discovery_share": ("discovery_share", "curious", "discovery", "discovery"),
            "screen_comment": ("screen_comment", "curious", "environment", "screen"),
            "semantic_scene": ("semantic_scene", "curious", "semantic_context", "semantic_scene"),
            "memory_callback": ("memory_callback", "soft", "internal", "memory"),
            "inner_thought": ("inner_thought", "quiet_presence", "internal", "self"),
            "social_check_in": ("small_talk", "soft", "presence", "idle"),
            "casual_curiosity": ("random_chat", "curious", "presence", "idle"),
            "playful_prompt": ("soft_tease", "playful", "presence", "idle"),
            "random_chat": ("random_chat", "soft", "presence", "idle"),
            "force_speak": ("random_chat", "focused", "force_speak", "presence"),
        }
        mode, motion, turn_kind, default_anchor = mode_map.get(
            kind, ("random_chat", "soft", "presence", "idle")
        )
        evidence_scope = {
            "screen_comment": "screen_grounded_claim",
            "semantic_scene": "shared_semantic_context",
            "memory_callback": "memory",
            "discovery_share": "discovery_artifact",
            "task_followup": "engagement_runtime",
            "continuation": "conversation",
            "followup_reminder": "conversation",
            "inner_thought": "self_context",
        }.get(kind, "social_context")
        strategy = {
            "continuation": "continue_public_thread",
            "followup_reminder": "gentle_followup_reminder",
            "task_followup": "preserve_active_engagement",
            "discovery_share": "share_discovery",
            "screen_comment": "grounded_curiosity",
            "semantic_scene": "develop_shared_semantic_context",
            "memory_callback": "share_grounded_memory_callback",
            "inner_thought": "share_public_safe_thought",
            "social_check_in": "social_check_in",
            "casual_curiosity": "casual_curiosity",
            "playful_prompt": "playful_prompt",
            "random_chat": "companion_presence",
        }.get(kind, "companion_presence")
        importance = max(0.42, min(0.94, 0.48 + 0.30 * candidate.relevance + 0.16 * candidate.urgency))
        intrusion = max(0.05, min(0.60, 0.24 - 0.12 * candidate.relevance + 0.10 * candidate.urgency))
        anchor_type = candidate.anchor_type or default_anchor
        anchor_id = candidate.anchor_id or "shared_quiet"
        subject_key = anchor_id
        activity_payload = {
            "activity_kind": "unknown", "phase": "unknown", "event": "",
            "event_key": "none", "confidence": 0.0, "evidence_refs": list(refs),
        }
        if kind == "task_followup" and blackboard.engagement_kind == "chess":
            # Dedupe theo position/event thật. Hai nước khác nhau không được coi
            # là lặp chỉ vì cùng mang nhãn task_followup.
            state = ChessSurfaceState.from_mapping(blackboard.engagement_state)
            event_key = state.event_fingerprint(blackboard.engagement_last_event_kind)
            subject_key = f"{anchor_id}:{event_key}"
            activity_payload = {
                "activity_kind": "chess",
                "phase": state.phase or "unknown",
                "event": blackboard.engagement_last_event_kind,
                "event_key": event_key,
                "confidence": 1.0 if state.meaningful else 0.0,
                "evidence_refs": list(refs),
            }
        mapping = {
            "speak": True,
            "motive": kind,
            "strategy": strategy,
            "value_focus": "relational_presence" if turn_kind == "presence" else "continuity",
            # Candidate topic is model-owned. Runtime only carries it; it does
            # not decorate it with a new hidden agenda.
            "topic": candidate.topic,
            "importance": importance,
            "intrusion_risk": intrusion,
            "confidence": max(0.40, min(0.96, candidate.confidence)),
            "performance_hint": candidate.tone or motion,
            "tool_intent": "",
            "tool_input": "",
            "evidence_refs": list(refs),
            "activity": activity_payload,
            "semantics": {
                "turn_kind": turn_kind,
                "speech_act": candidate.speech_act or kind,
                "subject_key": subject_key,
                "evidence_scope": evidence_scope,
                "continuation_key": blackboard.thread_key if kind in {"continuation", "followup_reminder"} else "none",
            },
            "notes": f"social_candidate source={candidate.source} reason={candidate.reason}",
        }
        return (
            IntentionPlan.from_mapping(mapping, channel="autonomous"),
            mode,
            motion,
            anchor_type,
            anchor_id,
            refs,
        )

    def evaluate(
        self,
        plan: Any,
        *,
        now: float | None = None,
        user_busy: bool = False,
        seconds_since_user: float = 0.0,
        **_: Any,
    ) -> tuple[bool, str]:
        now = float(now if now is not None else time.time())
        semantics = _plan_semantics(plan)
        profile = profile_for_plan(plan)
        if not _as_bool(_setting("enabled", True), True):
            return self._remember(False, "initiative_disabled", plan, now, profile=profile)

        importance = max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0)))
        if user_busy and importance < 0.90:
            return self._remember(False, "user_busy", plan, now, profile=profile)
        if seconds_since_user > 0.0 and seconds_since_user < profile.minimum_user_silence_seconds and importance < 0.84:
            return self._remember(False, "user_recently_active", plan, now, profile=profile)

        with self._lock:
            events = tuple(item for item in self._state.events if now - item.timestamp <= 3600.0)
        # Companion-commentary là chế độ nghe ERIS sống cùng màn hình, không phải
        # một thông báo hệ thống mỗi sáu phút. Budget vẫn hữu hạn để chống spam,
        # nhưng mặc định đủ rộng cho nhịp 1-2 phút/lần.
        global_budget = max(1, int(_as_float(_setting("global_hourly_budget", 40), 40)))
        if len(events) >= global_budget:
            return self._remember(False, "global_hourly_budget_exhausted", plan, now, profile=profile)
        same_kind = tuple(item for item in events if item.kind == profile.kind)
        if len(same_kind) >= profile.hourly_budget:
            return self._remember(False, "kind_hourly_budget_exhausted", plan, now, profile=profile)
        if same_kind and now - same_kind[-1].timestamp < profile.cooldown_seconds:
            return self._remember(False, "kind_cooldown", plan, now, profile=profile)

        signature = semantics.signature if semantics.complete else ""
        # force_speak là lệnh tường minh từ user; không bao giờ bị duplicate/repeat
        # chặn bất kể signature hay window.
        if profile.kind != "force_speak" and signature and profile.duplicate_window_seconds > 0.0:
            for item in reversed(events):
                if now - item.timestamp > profile.duplicate_window_seconds:
                    break
                if item.semantic_signature == signature:
                    return self._remember(False, "semantic_repeat", plan, now, profile=profile)
        return self._remember(True, "allowed", plan, now, profile=profile)

    def should_body_only(self, reason: str, *, has_perception_delta: bool = False, **_: Any) -> bool:
        """Body-only dựa trên event cơ học, không dựa scene keyword."""
        return bool(
            has_perception_delta
            and reason in {"user_busy", "user_recently_active", "kind_cooldown", "semantic_repeat"}
        )

    def record_spoken(self, plan: Any, *, now: float | None = None, channel: str = "autonomous", **_: Any) -> None:
        now = float(now if now is not None else time.time())
        semantics = _plan_semantics(plan)
        profile = profile_for_plan(plan)
        event = InitiativeEvent(
            timestamp=now,
            channel=str(channel or "autonomous")[:40],
            importance=max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0))),
            kind=profile.kind,
            semantic_signature=semantics.signature if semantics.complete else "",
            speech_act=semantics.speech_act,
            subject_key=semantics.subject_key,
        )
        with self._lock:
            events = [item for item in self._state.events if now - item.timestamp <= 24 * 3600.0]
            events.append(event)
            self._state = replace(self._state, version=self._state.version + 1, events=tuple(events[-96:]), updated_at=now)
            self._dirty = True
            self._persist_locked(force=True)

    def panel_view(self, *, now: float | None = None) -> dict[str, Any]:
        now = float(now if now is not None else time.time())
        with self._lock:
            self._persist_locked(force=False)
            state = self._state
            recent_hour = [item for item in state.events if now - item.timestamp <= 3600.0]
            last = state.events[-1].to_dict() if state.events else {}
            hourly_budget = max(1, int(_as_float(_setting("global_hourly_budget", 40), 40)))
            profile = _PROFILES.get(str(last.get("kind", "other") or "other"), _PROFILES["other"])
            next_allowed_at = float(last.get("timestamp", 0.0) or 0.0) + profile.cooldown_seconds if last else 0.0
            return {
                "schema": "eris.initiative.v3",
                "enabled": _as_bool(_setting("enabled", True), True),
                "hourly_budget": hourly_budget,
                "used_last_hour": len(recent_hour),
                "remaining_budget": max(0, hourly_budget - len(recent_hour)),
                "minimum_interval_seconds": profile.cooldown_seconds,
                "next_allowed_at": next_allowed_at,
                "last_spoken": last,
                "last_decision": dict(state.last_decision),
                "profiles": {key: asdict(value) for key, value in _PROFILES.items()},
                "recent_events": [item.to_dict() for item in state.events[-12:]][::-1],
                "version": state.version,
            }

    def reset(self) -> None:
        with self._lock:
            self._state = InitiativeState(version=self._state.version + 1, updated_at=time.time())
            self._dirty = True
            self._persist_locked(force=True)

    def flush(self) -> None:
        with self._lock:
            self._persist_locked(force=True)

    def _remember(self, allowed: bool, reason: str, plan: Any, now: float, *, profile: InitiativeProfile) -> tuple[bool, str]:
        semantics = _plan_semantics(plan)
        payload = {
            "allowed": bool(allowed),
            "reason": reason,
            "kind": profile.kind,
            "semantic_signature": semantics.signature if semantics.complete else "",
            "at": now,
            "importance": max(0.0, min(1.0, _as_float(getattr(plan, "importance", 0.0), 0.0))),
            "intrusion_risk": max(0.0, min(1.0, _as_float(getattr(plan, "intrusion_risk", 0.0), 0.0))),
        }
        with self._lock:
            self._state = replace(self._state, version=self._state.version + 1, last_decision=payload, updated_at=now)
            self._dirty = True
            self._persist_locked(force=False)
        return allowed, reason

    def _load(self) -> InitiativeState:
        try:
            if self._path.exists():
                return InitiativeState.from_mapping(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception as exc:
            self._log("warning", "[initiative] load failed: %s", exc)
        return InitiativeState()

    def _persist_locked(self, *, force: bool) -> None:
        if not self._dirty:
            return
        now = time.time()
        if not force and now - self._last_persist_at < self._persist_debounce_seconds:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix(self._path.suffix + ".tmp")
            temp.write_text(json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self._path)
            self._dirty = False
            self._last_persist_at = now
        except Exception as exc:
            self._log("warning", "[initiative] persist failed: %s", exc)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = [
    "InitiativeAction", "InitiativeController", "InitiativeDecision",
    "InitiativeEvent", "InitiativeProfile", "InitiativeState",
    "SpeechIntent", "profile_for_plan",
]
