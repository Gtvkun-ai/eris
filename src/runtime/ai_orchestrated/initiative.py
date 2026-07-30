# -*- coding: utf-8 -*-
"""Deterministic Initiative Controller cho self-initiated public turn.

V17 giao controller hai trách nhiệm có thể kiểm chứng bằng code:

- đọc ``TypedCognitiveBlackboard`` và chọn NO_OP / BODY_ONLY / SPEECH;
- áp cooldown, ngân sách và semantic-repeat trước khi gọi Surface Worker.

Controller không đọc câu tự nhiên, không dò keyword từ OCR, không gọi model và
không viết lời public. Surface Worker chỉ nhận SpeechIntent sau khi policy đã
duyệt. Như vậy một provider chậm không còn được quyền trì hoãn cả quyết định im
hay nói, một đặc quyền trước đây được trao khá hào phóng.
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
from .contracts import IntentionPlan
from .cognitive_blackboard import CognitiveAnchor, TypedCognitiveBlackboard
from .semantic_contracts import TurnSemantics


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


class InitiativeController:
    def __init__(self, *, state_path: Path | None = None, logger: Any | None = None) -> None:
        self.logger = logger
        self._path = state_path or (default_eris_home() / "state" / "initiative_state.json")
        self._lock = threading.RLock()
        self._state = self._load()
        self._dirty = False
        self._last_persist_at = 0.0
        self._persist_debounce_seconds = max(2.0, _as_float(_setting("persist_debounce_seconds", 12.0), 12.0))

    def decide(self, blackboard: TypedCognitiveBlackboard) -> InitiativeDecision:
        """Quyết định initiative bằng code thường, không gọi model.

        Thứ tự authority:
        1. hard mechanical boundaries;
        2. chọn một typed anchor có provenance;
        3. dựng IntentionPlan local;
        4. áp cooldown/budget/duplicate gate;
        5. trả đúng một trong NO_OP, BODY_ONLY hoặc SPEECH.

        Hàm này phải chạy ở mức mili-giây. Nếu nó cần internet để biết có nên
        nói hay không thì kiến trúc đã tự viết đơn xin treo.
        """

        silence = IntentionPlan.silence(channel="autonomous", reason="initiative_no_op")
        has_delta = bool(blackboard.mechanical_delta or blackboard.activity_event)

        if not _as_bool(_setting("enabled", True), True):
            return InitiativeDecision(InitiativeAction.NO_OP, "initiative_disabled", silence)
        if blackboard.reply_expected:
            action = InitiativeAction.BODY_ONLY if has_delta and not blackboard.privacy_blocked else InitiativeAction.NO_OP
            return InitiativeDecision(action, "waiting_for_user_reply", silence, body_motion="quiet_presence")
        if blackboard.user_busy:
            action = InitiativeAction.BODY_ONLY if has_delta and not blackboard.privacy_blocked else InitiativeAction.NO_OP
            return InitiativeDecision(action, "user_busy", silence, body_motion="small_acknowledge")

        anchor = self._select_anchor(blackboard)
        if anchor is None:
            if has_delta and not blackboard.privacy_blocked:
                return InitiativeDecision(
                    InitiativeAction.BODY_ONLY,
                    "mechanical_delta_without_speech_anchor",
                    silence,
                    body_motion="curious_glance",
                )
            return InitiativeDecision(InitiativeAction.NO_OP, "no_public_anchor", silence)

        plan, mode, motion = self._plan_for_anchor(anchor, blackboard)
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
            anchor_type=anchor.kind,
            anchor_id=anchor.anchor_id,
            evidence_refs=anchor.evidence_refs,
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
    def _select_anchor(blackboard: TypedCognitiveBlackboard) -> CognitiveAnchor | None:
        """Chọn neo cao nhất nhưng vẫn tuân thủ privacy/provenance."""

        for anchor in blackboard.anchors:
            if anchor.kind in {"screen", "activity"} and blackboard.privacy_blocked:
                continue
            if anchor.kind == "screen" and not (blackboard.screen_fresh or blackboard.screen_title):
                continue
            if anchor.kind == "conversation" and blackboard.reply_expected:
                continue
            return anchor
        return None

    @staticmethod
    def _plan_for_anchor(
        anchor: CognitiveAnchor,
        blackboard: TypedCognitiveBlackboard,
    ) -> tuple[IntentionPlan, str, str]:
        """Dựng semantic plan local từ một anchor typed.

        Đây là policy mapping, không phải text generation. ``topic`` mô tả mục
        tiêu giao tiếp để Surface Worker viết câu sau đó.
        """

        kind = anchor.kind
        refs = list(anchor.evidence_refs[:5])
        common = {
            "speak": True,
            "importance": max(0.45, min(0.92, anchor.priority)),
            "intrusion_risk": 0.10 if blackboard.commentary_required else 0.16,
            "confidence": max(0.45, min(0.95, anchor.confidence)),
            "tool_intent": "",
            "tool_input": "",
            "evidence_refs": refs,
            "activity": {
                "activity_kind": "unknown", "phase": "unknown", "event": "",
                "event_key": "none", "confidence": 0.0, "evidence_refs": refs,
            },
        }
        mapping: dict[str, Any]
        mode: str
        motion: str
        if kind == "conversation":
            mode, motion = "continuation", "soft"
            mapping = {
                **common,
                "motive": "useful_followup",
                "strategy": "continue_public_thread",
                "value_focus": "continuity",
                "topic": f"Continue the real open public thread: {anchor.topic_seed}",
                "performance_hint": "soft",
                "semantics": {
                    "turn_kind": "continuation", "speech_act": "carry_open_thread",
                    "subject_key": anchor.anchor_id or blackboard.thread_key,
                    "evidence_scope": "conversation",
                    "continuation_key": blackboard.thread_key or anchor.anchor_id or "current_thread",
                },
            }
        elif kind == "task":
            mode, motion = "task_followup", "focused"
            mapping = {
                **common,
                "motive": "engagement_followup",
                "strategy": "preserve_active_engagement",
                "value_focus": "task_continuity",
                "topic": f"Follow up the active {blackboard.engagement_kind or 'engagement'} without unrelated banter: {anchor.topic_seed}",
                "performance_hint": "focused",
                "semantics": {
                    "turn_kind": "activity_event", "speech_act": "task_followup",
                    "subject_key": anchor.anchor_id or "active_engagement",
                    "evidence_scope": "engagement_runtime", "continuation_key": "none",
                },
            }
        elif kind == "discovery":
            mode, motion = "discovery_share", "curious"
            mapping = {
                **common,
                "motive": "share_verified_discovery",
                "strategy": "share_discovery",
                "value_focus": "curiosity",
                "topic": f"Share one concise verified discovery from this artifact: {anchor.topic_seed}",
                "performance_hint": "curious",
                "semantics": {
                    "turn_kind": "discovery", "speech_act": "share_discovery",
                    "subject_key": anchor.anchor_id or "verified_discovery",
                    "evidence_scope": "discovery_artifact", "continuation_key": "none",
                },
            }
        elif kind in {"screen", "activity"}:
            mode, motion = "screen_comment", "curious"
            mapping = {
                **common,
                "motive": "meaningful_environment_change",
                "strategy": "grounded_curiosity",
                "value_focus": "shared_attention",
                "topic": (
                    f"Make one low-risk comment or question about the literal current app/window anchor: {anchor.topic_seed}. "
                    "Do not infer user intent or unseen content."
                ),
                "performance_hint": "curious",
                "semantics": {
                    "turn_kind": "environment" if kind == "screen" else "activity_event",
                    "speech_act": "comment_current_surface",
                    "subject_key": anchor.anchor_id or "current_surface",
                    "evidence_scope": "screen_delta" if anchor.evidence_refs else "runtime_window",
                    "continuation_key": "none",
                },
            }
        elif kind == "memory":
            mode, motion = "memory_callback", "soft"
            mapping = {
                **common,
                "motive": "memory_resonance",
                "strategy": "share_grounded_memory_callback",
                "value_focus": "continuity",
                "topic": f"Share one brief memory callback using only the approved memory seed and evidence: {anchor.topic_seed}",
                "performance_hint": "soft",
                "semantics": {
                    "turn_kind": "internal", "speech_act": "memory_callback",
                    "subject_key": anchor.anchor_id or "grounded_memory",
                    "evidence_scope": "memory", "continuation_key": "none",
                },
            }
        elif kind == "self":
            mode, motion = "inner_thought", "quiet_presence"
            mapping = {
                **common,
                "motive": "private_mind_surface",
                "strategy": "share_public_safe_thought",
                "value_focus": "self_authorship",
                "topic": f"Surface one brief public-safe thought from the approved seed: {anchor.topic_seed}",
                "performance_hint": "quiet_presence",
                "semantics": {
                    "turn_kind": "internal", "speech_act": "share_public_safe_thought",
                    "subject_key": anchor.anchor_id or "public_self_seed",
                    "evidence_scope": "self_context", "continuation_key": "none",
                },
            }
        else:
            mode, motion = "small_talk", "soft"
            mapping = {
                **common,
                "motive": "internal_agenda",
                "strategy": "companion_presence",
                "value_focus": "relational_presence",
                "topic": "Offer one brief warm-guarded companion line or question grounded only in the current public context.",
                "performance_hint": "soft",
                "semantics": {
                    "turn_kind": "presence", "speech_act": "warm_companion_presence",
                    "subject_key": anchor.anchor_id or "shared_quiet",
                    "evidence_scope": "persona", "continuation_key": "none",
                },
            }
        mapping["notes"] = f"deterministic_initiative anchor={kind}"
        return IntentionPlan.from_mapping(mapping, channel="autonomous"), mode, motion

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
        if signature and profile.duplicate_window_seconds > 0.0:
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
