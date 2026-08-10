# -*- coding: utf-8 -*-
"""Desktop semantic environment for autonomous cognition.

This layer sits *between* raw sensors (OCR/window/telemetry) and the autonomous
planner.  It does not claim to know the user's private intent.  Instead it
normalizes observable desktop changes into typed events, keeps a short in-RAM
activity timeline, and exposes a conservative ``UserSituation`` projection.

Design goals:
- raw OCR churn is not automatically a cognition-worthy event;
- app/window/navigation/idle transitions are explicit structured facts;
- semantic activity hints reuse BackgroundObserver / planner annotations rather
  than inventing intent from arbitrary screen words;
- private communication text is never copied into the timeline;
- no raw keystrokes are collected or persisted.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _stable_key(*parts: Any) -> str:
    raw = "|".join(_norm(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def _idle_bucket(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    if seconds < 8.0:
        return "active"
    if seconds < 45.0:
        return "recent"
    if seconds < 180.0:
        return "paused"
    return "away"


def _url_identity(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").rstrip("/")
        if host:
            # Keep path only as a short local hint; query/fragment can carry tokens.
            return _compact(f"{host}{path}", 180)
    except Exception:
        pass
    return _compact(raw.split("?", 1)[0].split("#", 1)[0], 180)


_CLOCK_RE = re.compile(r"^(?:\d{1,2}:\d{2}(?::\d{2})?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)$")
_NUMBERISH_RE = re.compile(r"^[\s\d.,:%+\-()/\\|]+$")
_PROGRESS_RE = re.compile(r"^(?:\d{1,3}\s*%|\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?)$")
_HEXISH_RE = re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")


def _text_shape(text: str) -> str:
    value = _norm(text)
    value = _HEXISH_RE.sub("<hex>", value)
    value = re.sub(r"\d+(?:[.,]\d+)?", "<n>", value)
    return _compact(value, 220)


def _numeric_fraction(text: str) -> float:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return 0.0
    return min(1.0, len(_DIGIT_RE.findall(compact)) / max(1, len(compact)))


def _looks_like_mechanical_item(text: str) -> bool:
    value = _compact(text, 320)
    normalized = value.strip()
    if not normalized:
        return True
    if _CLOCK_RE.fullmatch(normalized) or _PROGRESS_RE.fullmatch(normalized):
        return True
    if _NUMBERISH_RE.fullmatch(normalized) and _numeric_fraction(normalized) >= 0.35:
        return True
    # Short label + changing value, e.g. "CPU 31%", "FPS 144", "RAM 62".
    shape = _text_shape(normalized)
    if len(normalized) <= 48 and "<n>" in shape and _numeric_fraction(normalized) >= 0.20:
        return True
    return False


@dataclass(frozen=True, slots=True)
class DesktopSemanticEvent:
    timestamp: float
    kind: str
    category: str
    semantic: bool
    attention_level: int
    confidence: float
    novelty: float
    importance: float
    source: str
    app: str = ""
    object_ref: str = ""
    detail: str = ""
    evidence_refs: tuple[str, ...] = ()
    privacy_level: str = "normal"
    event_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(self.confidence, 3)
        payload["novelty"] = round(self.novelty, 3)
        payload["importance"] = round(self.importance, 3)
        return payload


@dataclass(frozen=True, slots=True)
class UserSituation:
    timestamp: float
    activity: str = "unknown"
    task_hint: str = "unknown"
    phase: str = "unknown"
    focused_app: str = ""
    focused_process: str = ""
    focused_object: str = ""
    last_action: str = "none"
    last_outcome: str = "unknown"
    attention_state: str = "unknown"
    interruption_cost: float = 0.0
    busy_score: float = 0.0
    confidence: float = 0.0
    semantic_delta: bool = False
    wake_recommended: bool = False
    max_attention_level: int = 0
    recent_events: tuple[DesktopSemanticEvent, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "activity": self.activity,
            "task_hint": self.task_hint,
            "phase": self.phase,
            "focused_app": self.focused_app,
            "focused_process": self.focused_process,
            "focused_object": self.focused_object,
            "last_action": self.last_action,
            "last_outcome": self.last_outcome,
            "attention_state": self.attention_state,
            "interruption_cost": round(self.interruption_cost, 3),
            "busy_score": round(self.busy_score, 3),
            "confidence": round(self.confidence, 3),
            "semantic_delta": bool(self.semantic_delta),
            "wake_recommended": bool(self.wake_recommended),
            "max_attention_level": int(self.max_attention_level),
            "recent_events": [event.to_dict() for event in self.recent_events[-8:]],
            "evidence_refs": list(self.evidence_refs),
            "epistemic_contract": (
                "activity/task/phase are conservative situation hints. Direct public claims still require "
                "grounded evidence. The timeline is in-memory and never stores raw keystrokes."
            ),
        }

    def prompt_context(self) -> str:
        lines = [
            "user_situation:",
            f"- activity={self.activity}; task_hint={self.task_hint}; phase={self.phase}; confidence={self.confidence:.2f}",
            f"- focused_app={self.focused_app or '<unknown>'}; process={self.focused_process or '<unknown>'}",
            f"- focused_object={self.focused_object or '<unknown>'}",
            f"- last_action={self.last_action}; last_outcome={self.last_outcome}",
            f"- attention={self.attention_state}; busy={self.busy_score:.2f}; interruption_cost={self.interruption_cost:.2f}",
            f"- semantic_delta={str(self.semantic_delta).lower()}; wake_recommended={str(self.wake_recommended).lower()}",
            "situation_contract:",
            "- Treat this as a private planning hint, not permission to narrate telemetry.",
            "- Do not claim exact user intent unless grounded by planner/observer evidence.",
            "- Prefer silence when interruption_cost is high and no important semantic event occurred.",
        ]
        if self.recent_events:
            lines.append("- recent_environment_events:")
            for event in self.recent_events[-5:]:
                lines.append(
                    f"  - {event.kind} level={event.attention_level} conf={event.confidence:.2f} detail={event.detail or '<none>'}"
                )
        return "\n".join(lines)


class DesktopSemanticRuntime:
    """Fuse telemetry + screen delta + observer state into a short activity timeline."""

    def __init__(self, *, max_events: int = 64, history_window_seconds: float = 45.0) -> None:
        self._events: deque[DesktopSemanticEvent] = deque(maxlen=max(16, int(max_events)))
        self._recent_event_keys: deque[str] = deque(maxlen=96)
        self._last_surface_key = ""
        self._last_url = ""
        self._last_idle_bucket = ""
        self._last_media_state = ""
        self._shape_history: dict[str, deque[tuple[float, str, str]]] = {}
        self._history_window_seconds = max(10.0, float(history_window_seconds))

    def observe(
        self,
        screen_context: Any,
        *,
        telemetry: Mapping[str, Any] | None = None,
        observer_frame: Any = None,
        rolling_context: Any = None,
        activity_session: Any = None,
        now: float | None = None,
    ) -> UserSituation:
        now = time.time() if now is None else float(now)
        telemetry = telemetry if isinstance(telemetry, Mapping) else {}
        content_meta = telemetry.get("content_metadata", {})
        content_meta = content_meta if isinstance(content_meta, Mapping) else {}

        title = _compact(
            getattr(screen_context, "window_title", "")
            or telemetry.get("active_window_title", "")
            or telemetry.get("active_app", ""),
            220,
        )
        process = _compact(
            getattr(screen_context, "process_name", "")
            or telemetry.get("active_process", "")
            or telemetry.get("process_name", ""),
            120,
        )
        app = process or _compact(telemetry.get("active_app", "") or title, 120)
        window_class = _compact(telemetry.get("window_class", ""), 100)
        surface_key = _stable_key(process or app, title, window_class)
        privacy_blocked = bool(getattr(screen_context, "privacy_blocked", False))
        privacy_level = "private" if privacy_blocked else str(content_meta.get("privacy_level", "normal") or "normal")
        if privacy_level in {"private", "sensitive"}:
            privacy_blocked = True

        evidence_refs = tuple(getattr(screen_context, "evidence_refs", ()) or ())
        events_this_tick: list[DesktopSemanticEvent] = []

        def emit(
            kind: str,
            *,
            category: str,
            semantic: bool,
            level: int,
            confidence: float,
            novelty: float,
            importance: float,
            source: str,
            detail: str = "",
            object_ref: str = "",
            refs: Sequence[str] = (),
            identity: str = "",
        ) -> None:
            event_key = identity or _stable_key(kind, source, surface_key, object_ref, detail)
            # The same stable fact on consecutive ticks should not flood the timeline.
            if event_key in self._recent_event_keys:
                return
            event = DesktopSemanticEvent(
                timestamp=now,
                kind=kind,
                category=category,
                semantic=bool(semantic),
                attention_level=max(0, min(4, int(level))),
                confidence=_clamp01(confidence),
                novelty=_clamp01(novelty),
                importance=_clamp01(importance),
                source=source,
                app=app,
                object_ref="" if privacy_blocked else _compact(object_ref, 220),
                detail="" if privacy_blocked else _compact(detail, 260),
                evidence_refs=tuple(dict.fromkeys(str(ref) for ref in refs if str(ref).strip()))[:8],
                privacy_level=privacy_level,
                event_key=event_key,
            )
            self._events.append(event)
            self._recent_event_keys.append(event_key)
            events_this_tick.append(event)

        focus_changed = bool(telemetry.get("focus_changed", False))
        surface_changed = bool(self._last_surface_key and surface_key and surface_key != self._last_surface_key)
        if surface_changed or focus_changed or bool(getattr(screen_context, "window_changed", False)):
            emit(
                "surface_changed",
                category="ui_state",
                semantic=True,
                level=1,
                confidence=0.98,
                novelty=0.72,
                importance=0.24,
                source="window_telemetry",
                detail=title,
                object_ref=process or app,
                refs=("telemetry:foreground_window",),
                identity=f"surface:{surface_key}",
            )

        idle_seconds = float(telemetry.get("idle_seconds", 0.0) or 0.0)
        idle_bucket = _idle_bucket(idle_seconds)
        if self._last_idle_bucket and idle_bucket != self._last_idle_bucket:
            kind = "user_resumed" if idle_bucket in {"active", "recent"} and self._last_idle_bucket in {"paused", "away"} else "idle_state_changed"
            emit(
                kind,
                category="user_presence",
                semantic=True,
                level=1,
                confidence=0.95,
                novelty=0.55,
                importance=0.20,
                source="input_idle_telemetry",
                detail=f"{self._last_idle_bucket}->{idle_bucket}",
                refs=("telemetry:last_input",),
                identity=f"idle:{self._last_idle_bucket}->{idle_bucket}:{int(now // 5)}",
            )

        browser_url = _url_identity(str(telemetry.get("browser_url", "") or content_meta.get("url", "") or ""))
        if browser_url and self._last_url and browser_url != self._last_url:
            emit(
                "navigation_changed",
                category="ui_state",
                semantic=True,
                level=2,
                confidence=0.90,
                novelty=0.72,
                importance=0.34,
                source="browser_telemetry",
                detail=browser_url,
                object_ref=browser_url,
                refs=("telemetry:browser_url",),
                identity=f"url:{_stable_key(browser_url)}",
            )

        media_state = _norm(content_meta.get("media_state", ""))
        if media_state and media_state != "unknown" and self._last_media_state and media_state != self._last_media_state:
            emit(
                "media_state_changed",
                category="ui_state",
                semantic=True,
                level=1,
                confidence=_clamp01(content_meta.get("confidence", 0.65), 0.65),
                novelty=0.50,
                importance=0.18,
                source=str(content_meta.get("source", "content_metadata") or "content_metadata"),
                detail=f"{self._last_media_state}->{media_state}",
                refs=("telemetry:content_metadata",),
                identity=f"media:{surface_key}:{media_state}",
            )

        changed_text = tuple(str(item) for item in (getattr(screen_context, "changed_text", ()) or ()) if str(item).strip())
        content_changed = bool(getattr(screen_context, "content_changed", False))
        changed_ratio = _clamp01(getattr(screen_context, "changed_ratio", 0.0))
        if content_changed or changed_text:
            mechanical, mechanical_conf = self._classify_screen_delta(
                surface_key=surface_key,
                changed_text=changed_text,
                changed_ratio=changed_ratio,
                now=now,
            )
            if privacy_blocked:
                emit(
                    "private_surface_changed",
                    category="privacy",
                    semantic=False,
                    level=0,
                    confidence=1.0,
                    novelty=0.0,
                    importance=0.0,
                    source="screen_privacy_guard",
                    refs=evidence_refs,
                    identity=f"private:{surface_key}:{int(getattr(screen_context, 'revision', 0) or 0)}",
                )
            elif mechanical:
                emit(
                    "mechanical_screen_delta",
                    category="mechanical",
                    semantic=False,
                    level=0,
                    confidence=mechanical_conf,
                    novelty=max(0.02, changed_ratio * 0.25),
                    importance=0.02,
                    source="screen_delta_classifier",
                    detail="periodic/numeric OCR churn",
                    refs=evidence_refs,
                    identity=f"mechanical:{surface_key}:{int(getattr(screen_context, 'revision', 0) or 0)}",
                )
            else:
                possible_error = _clamp01(getattr(observer_frame, "possible_error", 0.0))
                if possible_error >= 0.72:
                    emit(
                        "possible_error_visible",
                        category="important",
                        semantic=True,
                        level=3,
                        confidence=max(0.70, possible_error),
                        novelty=max(0.55, changed_ratio),
                        importance=max(0.74, possible_error),
                        source="observer_screen_fusion",
                        detail=_compact(changed_text[0], 180) if changed_text else "screen content changed near an error signal",
                        refs=evidence_refs,
                        identity=f"error:{surface_key}:{int(getattr(screen_context, 'revision', 0) or 0)}",
                    )
                else:
                    emit(
                        "screen_content_changed",
                        category="content",
                        semantic=True,
                        level=2,
                        confidence=max(0.58, _clamp01(getattr(screen_context, "scene_confidence", 0.0))),
                        novelty=max(0.30, min(0.82, changed_ratio * 2.5 + (0.12 if changed_text else 0.0))),
                        importance=min(0.62, 0.24 + changed_ratio * 1.6),
                        source="screen_delta_classifier",
                        detail=_compact(changed_text[0], 180) if changed_text else "stable screen content changed",
                        refs=evidence_refs,
                        identity=f"content:{surface_key}:{int(getattr(screen_context, 'revision', 0) or 0)}",
                    )

        # Main planner ActivitySemantics is stronger than sensor-side guesses.
        if activity_session is not None:
            new_keys = tuple(getattr(activity_session, "new_event_keys", ()) or ())
            recent_activity_events = tuple(getattr(activity_session, "recent_events", ()) or ())
            for event in recent_activity_events:
                key = str(getattr(event, "event_key", "") or "")
                if not key.startswith("semantic:") or key not in new_keys:
                    continue
                emit(
                    "planner_activity_event",
                    category="activity",
                    semantic=True,
                    level=3,
                    confidence=_clamp01(getattr(event, "confidence", 0.0)),
                    novelty=0.88,
                    importance=0.72,
                    source="main_planner_activity_semantics",
                    detail=str(getattr(event, "detail", "") or ""),
                    refs=tuple(getattr(event, "evidence_refs", ()) or ()),
                    identity=key,
                )

        activity, activity_confidence = self._resolve_activity(observer_frame, activity_session, telemetry)
        phase = self._resolve_phase(observer_frame, activity_session, idle_bucket)
        focused_object = self._focused_object(telemetry, content_meta, title, privacy_blocked)
        task_hint = self._task_hint(activity, phase, focused_object, activity_session)

        busy_score = _clamp01(getattr(rolling_context, "busy_score", 0.0))
        interruption_cost = _clamp01(getattr(rolling_context, "interrupt_cost", 0.0))
        if rolling_context is None:
            busy_score = 0.82 if idle_bucket == "active" and activity in {"debugging", "designing", "coding", "game"} else 0.42 if idle_bucket == "active" else 0.12
            interruption_cost = min(1.0, 0.18 + busy_score * 0.62)

        if idle_bucket == "away":
            attention_state = "away"
        elif busy_score >= 0.72 or interruption_cost >= 0.72:
            attention_state = "focused"
        elif idle_bucket == "paused":
            attention_state = "paused"
        else:
            attention_state = "active"

        significant = [event for event in events_this_tick if event.semantic and event.attention_level >= 2]
        max_level = max((event.attention_level for event in events_this_tick), default=0)
        semantic_delta = bool(significant)
        wake_recommended = any(event.semantic and event.attention_level >= 3 for event in events_this_tick)
        last_action = self._last_action(events_this_tick)
        last_outcome = self._last_outcome(events_this_tick, activity_session)
        combined_conf = max(
            activity_confidence,
            max((event.confidence for event in events_this_tick if event.semantic), default=0.0),
            0.48 if surface_key else 0.0,
        )

        recent_events = tuple(self._events)[-10:]
        all_refs: list[str] = []
        for event in recent_events[-6:]:
            all_refs.extend(event.evidence_refs)

        self._last_surface_key = surface_key or self._last_surface_key
        self._last_url = browser_url or self._last_url
        self._last_idle_bucket = idle_bucket
        if media_state and media_state != "unknown":
            self._last_media_state = media_state

        return UserSituation(
            timestamp=now,
            activity=activity,
            task_hint=task_hint,
            phase=phase,
            focused_app=app,
            focused_process=process,
            focused_object=focused_object,
            last_action=last_action,
            last_outcome=last_outcome,
            attention_state=attention_state,
            interruption_cost=interruption_cost,
            busy_score=busy_score,
            confidence=combined_conf,
            semantic_delta=semantic_delta,
            wake_recommended=wake_recommended,
            max_attention_level=max_level,
            recent_events=recent_events,
            evidence_refs=tuple(dict.fromkeys(all_refs))[:12],
        )

    def _classify_screen_delta(
        self,
        *,
        surface_key: str,
        changed_text: tuple[str, ...],
        changed_ratio: float,
        now: float,
    ) -> tuple[bool, float]:
        if not changed_text:
            return (changed_ratio < 0.035, 0.78 if changed_ratio < 0.035 else 0.45)
        if all(_looks_like_mechanical_item(item) for item in changed_text):
            return True, 0.93

        joined = " | ".join(changed_text[:5])
        shape = _text_shape(joined)
        history = self._shape_history.setdefault(surface_key or "unknown", deque(maxlen=8))
        while history and now - history[0][0] > self._history_window_seconds:
            history.popleft()

        mechanical = False
        confidence = 0.0
        if shape:
            for ts, old_shape, old_text in reversed(history):
                if now - ts > 18.0:
                    break
                if old_shape == shape and _norm(old_text) != _norm(joined):
                    numeric = max(_numeric_fraction(old_text), _numeric_fraction(joined))
                    if numeric >= 0.12:
                        mechanical = True
                        confidence = min(0.96, 0.78 + numeric * 0.35)
                        break
        history.append((now, shape, joined))
        return mechanical, confidence

    @staticmethod
    def _resolve_activity(observer_frame: Any, activity_session: Any, telemetry: Mapping[str, Any]) -> tuple[str, float]:
        planner_kind = str(getattr(activity_session, "activity_kind", "") or "")
        planner_conf = _clamp01(getattr(activity_session, "semantic_confidence", 0.0))
        if planner_kind and planner_kind != "unknown" and planner_conf >= 0.55:
            return planner_kind, planner_conf

        observed = str(getattr(observer_frame, "activity_intent", "") or "")
        observer_conf = _clamp01(getattr(observer_frame, "confidence", 0.0), 0.0)
        if observed and observed != "unknown":
            return observed, max(0.56, min(0.82, observer_conf or 0.62))

        kind = str(telemetry.get("active_window_kind", "") or "")
        fallback = {
            "coding": "coding",
            "documentation": "reading",
            "communication": "communicating",
            "entertainment": "media_or_entertainment",
            "focus_aid_media": "background_media",
        }.get(kind, "unknown")
        return fallback, 0.48 if fallback != "unknown" else 0.0

    @staticmethod
    def _resolve_phase(observer_frame: Any, activity_session: Any, idle_bucket: str) -> str:
        phase = str(getattr(activity_session, "phase", "") or "")
        if phase and phase != "unknown":
            return phase
        if idle_bucket == "away":
            return "paused"
        possible_error = _clamp01(getattr(observer_frame, "possible_error", 0.0))
        activity = str(getattr(observer_frame, "activity_intent", "") or "")
        if possible_error >= 0.72 and activity == "debugging":
            return "investigating_problem"
        return "active" if idle_bucket in {"active", "recent"} else "holding"

    @staticmethod
    def _focused_object(
        telemetry: Mapping[str, Any],
        content_meta: Mapping[str, Any],
        title: str,
        privacy_blocked: bool,
    ) -> str:
        if privacy_blocked:
            return "private_surface"
        for key in ("selected_file", "active_file", "current_file", "file_path"):
            value = _compact(telemetry.get(key, ""), 220)
            if value:
                return value
        content_title = _compact(content_meta.get("title", ""), 220)
        if content_title:
            return content_title
        url = _url_identity(str(telemetry.get("browser_url", "") or content_meta.get("url", "") or ""))
        if url:
            return url
        return _compact(title, 220)

    @staticmethod
    def _task_hint(activity: str, phase: str, focused_object: str, activity_session: Any) -> str:
        if activity_session is not None:
            planner_kind = str(getattr(activity_session, "activity_kind", "") or "")
            planner_phase = str(getattr(activity_session, "phase", "") or "")
            if planner_kind and planner_kind != "unknown":
                return _compact(f"{planner_kind}:{planner_phase or phase}", 160)
        if activity != "unknown" and focused_object:
            return _compact(f"{activity} · {focused_object}", 180)
        return activity if activity != "unknown" else "unknown"

    @staticmethod
    def _last_action(events: Sequence[DesktopSemanticEvent]) -> str:
        for event in reversed(tuple(events)):
            if event.kind == "surface_changed":
                return "switched_surface"
            if event.kind == "navigation_changed":
                return "navigated"
            if event.kind == "screen_content_changed":
                return "screen_content_changed"
            if event.kind == "possible_error_visible":
                return "error_became_visible"
            if event.kind == "planner_activity_event":
                return "activity_event"
            if event.kind == "user_resumed":
                return "resumed_activity"
        return "none"

    @staticmethod
    def _last_outcome(events: Sequence[DesktopSemanticEvent], activity_session: Any) -> str:
        for event in reversed(tuple(events)):
            if event.kind == "possible_error_visible":
                return "possible_problem"
            if event.kind == "planner_activity_event" and event.detail:
                return _compact(event.detail, 160)
        if activity_session is not None:
            recent = tuple(getattr(activity_session, "recent_events", ()) or ())
            for event in reversed(recent):
                key = str(getattr(event, "event_key", "") or "")
                if key.startswith("semantic:") and str(getattr(event, "detail", "") or ""):
                    return _compact(getattr(event, "detail", ""), 160)
        return "unknown"


__all__ = ["DesktopSemanticEvent", "DesktopSemanticRuntime", "UserSituation"]
