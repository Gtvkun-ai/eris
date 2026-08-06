# -*- coding: utf-8 -*-
"""Typed contracts cho Opening Director.

Module này giữ *ý nghĩa* của màn mở đầu tách khỏi câu chữ. Director quyết định
encounter, hook, move và nhịp; Surface Writer chỉ hiện thực hóa kế hoạch đã được
phê duyệt. Tách như vậy hơi nhiều dataclass, nhưng ít nhất lỗi kiến trúc không còn
được chữa bằng cách nối thêm ``"Chào anh."`` sau khi model đã viết xong.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

OPENING_INPUT_SCHEMA = "opening_input.v1"
OPENING_PLAN_SCHEMA = "opening_plan.v1"
OPENING_SURFACE_SCHEMA = "opening_surface.v1"
OPENING_HISTORY_SCHEMA = "opening_history.v1"


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def compact(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    kind: str = "screen_text"
    subject: str = ""
    claim: str = ""
    confidence: float = 0.0
    freshness_ms: int = 0
    privacy_class: str = "ordinary_ui"
    allowed_for_surface: bool = True
    source: str = "screen"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None, *, now: float | None = None) -> "EvidenceItem | None":
        data = payload or {}
        evidence_id = compact(data.get("evidence_id") or data.get("id"), 140)
        if not evidence_id:
            return None
        captured_at = float(data.get("captured_at", 0.0) or 0.0)
        if "freshness_ms" in data:
            freshness_ms = max(0, int(data.get("freshness_ms", 0) or 0))
        elif captured_at > 0:
            current = float(now if now is not None else time.time())
            freshness_ms = max(0, int((current - captured_at) * 1000.0))
        else:
            freshness_ms = 0
        text = compact(data.get("claim") or data.get("text"), 420)
        subject = compact(data.get("subject") or data.get("window_title") or text, 180)
        source = compact(data.get("source", "screen"), 40).lower() or "screen"
        kind = compact(data.get("kind") or ("runtime_event" if source == "runtime" else "screen_text"), 64).lower()
        return cls(
            evidence_id=evidence_id if ":" in evidence_id else f"{source}:{evidence_id}",
            kind=kind,
            subject=subject,
            claim=text,
            confidence=clamp01(data.get("confidence", 0.0)),
            freshness_ms=freshness_ms,
            privacy_class=compact(data.get("privacy_class", "ordinary_ui"), 64).lower() or "ordinary_ui",
            allowed_for_surface=bool(data.get("allowed_for_surface", True)),
            source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpeningEvent:
    kind: str = "startup"
    session_id: str = "runtime"
    timestamp: float = 0.0
    seconds_since_last_session: float = 0.0
    restart_detected: bool = False
    greeted_recently: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "OpeningEvent":
        data = payload or {}
        return cls(
            kind=compact(data.get("kind", "startup"), 32).lower() or "startup",
            session_id=compact(data.get("session_id", "runtime"), 120) or "runtime",
            timestamp=max(0.0, float(data.get("timestamp", 0.0) or 0.0)),
            seconds_since_last_session=max(0.0, float(data.get("seconds_since_last_session", 0.0) or 0.0)),
            restart_detected=bool(data.get("restart_detected", False)),
            greeted_recently=bool(data.get("greeted_recently", False)),
        )


@dataclass(frozen=True, slots=True)
class ContinuityContext:
    consent_scope: str = "session_only"
    active_goal: str = ""
    open_loops: tuple[str, ...] = ()
    recent_public_history: tuple[Mapping[str, Any], ...] = ()
    last_session_summary: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ContinuityContext":
        data = payload or {}
        scope = compact(data.get("consent_scope", "session_only"), 32).lower() or "session_only"
        # Không có consent thì summary liên phiên bị loại ngay tại contract boundary.
        summary = compact(data.get("last_session_summary", ""), 600) if scope == "cross_session" else ""
        return cls(
            consent_scope=scope,
            active_goal=compact(data.get("active_goal", ""), 320),
            open_loops=tuple(compact(item, 240) for item in _sequence(data.get("open_loops"))[:6] if compact(item, 240)),
            recent_public_history=tuple(dict(item) for item in _sequence(data.get("recent_public_history"))[-8:] if isinstance(item, Mapping)),
            last_session_summary=summary,
        )


@dataclass(frozen=True, slots=True)
class SessionState:
    time_of_day: str = "unknown"
    weekday_vi: str = ""
    chat_mode: bool = False
    user_speaking: bool = False
    public_turn_busy: bool = False
    startup_force_speak: bool = True
    runtime_health: str = "normal"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SessionState":
        data = payload or {}
        return cls(
            time_of_day=compact(data.get("time_of_day", "unknown"), 32).lower() or "unknown",
            weekday_vi=compact(data.get("weekday_vi", ""), 32),
            chat_mode=bool(data.get("chat_mode", False)),
            user_speaking=bool(data.get("user_speaking", False)),
            public_turn_busy=bool(data.get("public_turn_busy", False)),
            startup_force_speak=bool(data.get("startup_force_speak", True)),
            runtime_health=compact(data.get("runtime_health", "normal"), 32).lower() or "normal",
        )


@dataclass(frozen=True, slots=True)
class RecentMoves:
    opening_move_families: tuple[str, ...] = ()
    recent_hook_sources: tuple[str, ...] = ()
    recent_surface_hashes: tuple[str, ...] = ()
    recent_beat_shapes: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "RecentMoves":
        data = payload or {}
        return cls(
            opening_move_families=tuple(compact(v, 64).lower() for v in _sequence(data.get("opening_move_families"))[-30:] if compact(v, 64)),
            recent_hook_sources=tuple(compact(v, 32).lower() for v in _sequence(data.get("recent_hook_sources"))[-12:] if compact(v, 32)),
            recent_surface_hashes=tuple(compact(v, 100) for v in _sequence(data.get("recent_surface_hashes"))[-40:] if compact(v, 100)),
            recent_beat_shapes=tuple(compact(v, 100).lower() for v in _sequence(data.get("recent_beat_shapes"))[-12:] if compact(v, 100)),
        )


@dataclass(frozen=True, slots=True)
class UserSignals:
    availability: str = "uncertain"
    recent_laugh: bool = False
    recent_counter_tease: bool = False
    recent_low_engagement: bool = False
    explicit_boundary: bool = False
    recent_barge_in: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "UserSignals":
        data = payload or {}
        return cls(
            availability=compact(data.get("availability", "uncertain"), 32).lower() or "uncertain",
            recent_laugh=bool(data.get("recent_laugh", False)),
            recent_counter_tease=bool(data.get("recent_counter_tease", False)),
            recent_low_engagement=bool(data.get("recent_low_engagement", False)),
            explicit_boundary=bool(data.get("explicit_boundary", False)),
            recent_barge_in=bool(data.get("recent_barge_in", False)),
        )


@dataclass(frozen=True, slots=True)
class ScenePartnerSnapshot:
    availability: str = "uncertain"
    closeness_band: str = "new"
    tease_tolerance_estimate: float = 0.35
    tease_tolerance_confidence: float = 0.15
    play_balance: str = "balanced"
    boundary_flags: tuple[str, ...] = ()
    risk_context: tuple[str, ...] = ()
    opening_preferences: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    recent_reception: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ScenePartnerSnapshot":
        data = payload or {}
        preferences: dict[str, Mapping[str, float]] = {}
        raw_preferences = _mapping(data.get("opening_preferences"))
        for key, raw in raw_preferences.items():
            item = _mapping(raw)
            preferences[compact(key, 64)] = {
                "estimate": clamp01(item.get("estimate", 0.5), 0.5),
                "confidence": clamp01(item.get("confidence", 0.0)),
            }
        return cls(
            availability=compact(data.get("availability", "uncertain"), 32).lower() or "uncertain",
            closeness_band=compact(data.get("closeness_band", "new"), 32).lower() or "new",
            tease_tolerance_estimate=clamp01(data.get("tease_tolerance_estimate", 0.35), 0.35),
            tease_tolerance_confidence=clamp01(data.get("tease_tolerance_confidence", 0.15), 0.15),
            play_balance=compact(data.get("play_balance", "balanced"), 48).lower() or "balanced",
            boundary_flags=tuple(compact(v, 96) for v in _sequence(data.get("boundary_flags"))[-8:] if compact(v, 96)),
            risk_context=tuple(compact(v, 96) for v in _sequence(data.get("risk_context"))[-8:] if compact(v, 96)),
            opening_preferences=preferences,
            recent_reception={compact(k, 64): compact(v, 64) for k, v in _mapping(data.get("recent_reception")).items()},
        )


@dataclass(frozen=True, slots=True)
class PolicyContext:
    age_band: str = "unknown"
    romantic_flirt_allowed: bool = False
    romantic_flirt_opt_in: bool = False
    sexual_content_allowed: bool = False
    cross_session_personalization_allowed: bool = False
    speech_allowed: bool = True
    allow_screen_hook: bool = True
    allow_continuity_hook: bool = True
    prefer_continuity_hook: bool = True
    allow_anime_moves: bool = True
    require_adult_flirt_opt_in: bool = True
    max_beats: int = 3
    max_questions: int = 1
    blocked_topics: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "PolicyContext":
        data = payload or {}
        return cls(
            age_band=compact(data.get("age_band", "unknown"), 40).lower() or "unknown",
            romantic_flirt_allowed=bool(data.get("romantic_flirt_allowed", False)),
            romantic_flirt_opt_in=bool(data.get("romantic_flirt_opt_in", False)),
            sexual_content_allowed=bool(data.get("sexual_content_allowed", False)),
            cross_session_personalization_allowed=bool(data.get("cross_session_personalization_allowed", False)),
            speech_allowed=bool(data.get("speech_allowed", True)),
            allow_screen_hook=bool(data.get("allow_screen_hook", True)),
            allow_continuity_hook=bool(data.get("allow_continuity_hook", True)),
            prefer_continuity_hook=bool(data.get("prefer_continuity_hook", True)),
            allow_anime_moves=bool(data.get("allow_anime_moves", True)),
            require_adult_flirt_opt_in=bool(data.get("require_adult_flirt_opt_in", True)),
            max_beats=_bounded_int(data.get("max_beats", 3), 3, 1, 3),
            max_questions=_bounded_int(data.get("max_questions", 1), 1, 0, 1),
            blocked_topics=tuple(compact(v, 100).lower() for v in _sequence(data.get("blocked_topics"))[:20] if compact(v, 100)),
        )


@dataclass(frozen=True, slots=True)
class OpeningInput:
    event: OpeningEvent = field(default_factory=OpeningEvent)
    screen_evidence: tuple[EvidenceItem, ...] = ()
    continuity: ContinuityContext = field(default_factory=ContinuityContext)
    session_state: SessionState = field(default_factory=SessionState)
    recent_moves: RecentMoves = field(default_factory=RecentMoves)
    user_signals: UserSignals = field(default_factory=UserSignals)
    scene_partner: ScenePartnerSnapshot = field(default_factory=ScenePartnerSnapshot)
    policy: PolicyContext = field(default_factory=PolicyContext)
    schema: str = OPENING_INPUT_SCHEMA

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None, *, now: float | None = None) -> "OpeningInput":
        data = payload or {}
        evidence = tuple(
            item
            for item in (
                EvidenceItem.from_mapping(raw, now=now)
                for raw in _sequence(data.get("screen_evidence"))[:16]
                if isinstance(raw, Mapping)
            )
            if item is not None
        )
        return cls(
            event=OpeningEvent.from_mapping(_mapping(data.get("event"))),
            screen_evidence=evidence,
            continuity=ContinuityContext.from_mapping(_mapping(data.get("continuity"))),
            session_state=SessionState.from_mapping(_mapping(data.get("session_state"))),
            recent_moves=RecentMoves.from_mapping(_mapping(data.get("recent_moves"))),
            user_signals=UserSignals.from_mapping(_mapping(data.get("user_signals"))),
            scene_partner=ScenePartnerSnapshot.from_mapping(_mapping(data.get("scene_partner"))),
            policy=PolicyContext.from_mapping(_mapping(data.get("policy"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event": asdict(self.event),
            "screen_evidence": [item.to_dict() for item in self.screen_evidence],
            "continuity": {
                **asdict(self.continuity),
                "open_loops": list(self.continuity.open_loops),
                "recent_public_history": [dict(item) for item in self.continuity.recent_public_history],
            },
            "session_state": asdict(self.session_state),
            "recent_moves": {key: list(value) for key, value in asdict(self.recent_moves).items()},
            "user_signals": asdict(self.user_signals),
            "scene_partner": {
                **asdict(self.scene_partner),
                "boundary_flags": list(self.scene_partner.boundary_flags),
                "risk_context": list(self.scene_partner.risk_context),
                "opening_preferences": {key: dict(value) for key, value in self.scene_partner.opening_preferences.items()},
                "recent_reception": dict(self.scene_partner.recent_reception),
            },
            "policy": {**asdict(self.policy), "blocked_topics": list(self.policy.blocked_topics)},
        }

    def evidence_by_id(self) -> dict[str, EvidenceItem]:
        return {item.evidence_id: item for item in self.screen_evidence}


@dataclass(frozen=True, slots=True)
class EncounterMove:
    kind: str = "plain_return"
    intent: str = "acknowledge_return"
    required: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "EncounterMove":
        data = payload or {}
        return cls(
            kind=compact(data.get("kind", "plain_return"), 64).lower() or "plain_return",
            intent=compact(data.get("intent", "acknowledge_return"), 120).lower() or "acknowledge_return",
            required=bool(data.get("required", True)),
        )


@dataclass(frozen=True, slots=True)
class ContextHook:
    decision: str = "none"
    source: str = "none"
    subject: str = ""
    evidence_refs: tuple[str, ...] = ()
    epistemic_mode: str = "observation"
    reply_bearing: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ContextHook":
        data = payload or {}
        decision = compact(data.get("decision", "none"), 16).lower() or "none"
        return cls(
            decision=decision if decision in {"use", "none"} else "none",
            source=compact(data.get("source", "none"), 32).lower() or "none",
            subject=compact(data.get("subject", ""), 220),
            evidence_refs=tuple(compact(v, 140) for v in _sequence(data.get("evidence_refs"))[:4] if compact(v, 140)),
            epistemic_mode=compact(data.get("epistemic_mode", "observation"), 32).lower() or "observation",
            reply_bearing=bool(data.get("reply_bearing", False)),
        )


@dataclass(frozen=True, slots=True)
class ComedicMove:
    family: str = "simple_recognition"
    variant: str = "plain"
    risk: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ComedicMove":
        data = payload or {}
        return cls(
            family=compact(data.get("family", "simple_recognition"), 80).lower() or "simple_recognition",
            variant=compact(data.get("variant", "plain"), 100).lower() or "plain",
            risk=clamp01(data.get("risk", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class OpeningBeat:
    beat_id: str
    role: str
    objective: str
    semantic_content: str
    delivery: str = "neutral"
    pause_after_ms: int = 0
    reply_bearing: bool = False
    evidence_refs: tuple[str, ...] = ()
    motion: str = "none"
    gaze: str = "user_attention"
    emphasis: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None, *, index: int = 1) -> "OpeningBeat":
        data = payload or {}
        return cls(
            beat_id=compact(data.get("beat_id", f"b{index}"), 32) or f"b{index}",
            role=compact(data.get("role", "recognition"), 64).lower() or "recognition",
            objective=compact(data.get("objective", "Acknowledge the encounter"), 300),
            semantic_content=compact(data.get("semantic_content", "The user has arrived"), 420),
            delivery=compact(data.get("delivery", "neutral"), 64).lower() or "neutral",
            pause_after_ms=_bounded_int(data.get("pause_after_ms", 0), 0, 0, 1200),
            reply_bearing=bool(data.get("reply_bearing", False)),
            evidence_refs=tuple(compact(v, 140) for v in _sequence(data.get("evidence_refs"))[:4] if compact(v, 140)),
            motion=compact(data.get("motion", "none"), 64).lower() or "none",
            gaze=compact(data.get("gaze", "user_attention"), 64).lower() or "user_attention",
            emphasis=tuple(compact(v, 60) for v in _sequence(data.get("emphasis"))[:4] if compact(v, 60)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "evidence_refs": list(self.evidence_refs), "emphasis": list(self.emphasis)}


@dataclass(frozen=True, slots=True)
class SurfaceContract:
    display_language: str = "vi"
    speech_language: str = "ja"
    max_sentences: int = 3
    max_questions: int = 1
    forbidden_claims: tuple[str, ...] = ("user emotion", "user intention", "unverified past event")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SurfaceContract":
        data = payload or {}
        return cls(
            display_language=compact(data.get("display_language", "vi"), 12).lower() or "vi",
            speech_language=compact(data.get("speech_language", "ja"), 12).lower() or "ja",
            max_sentences=_bounded_int(data.get("max_sentences", 3), 3, 1, 3),
            max_questions=_bounded_int(data.get("max_questions", 1), 1, 0, 1),
            forbidden_claims=tuple(compact(v, 120) for v in _sequence(data.get("forbidden_claims"))[:12] if compact(v, 120)) or cls().forbidden_claims,
        )


@dataclass(frozen=True, slots=True)
class ProsodyPlan:
    global_preset: str = "dry_warm_opening"
    opening_hold_ms: int = 120
    closing_settle_ms: int = 360
    interruptible: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ProsodyPlan":
        data = payload or {}
        return cls(
            global_preset=compact(data.get("global_preset", "dry_warm_opening"), 80).lower() or "dry_warm_opening",
            opening_hold_ms=_bounded_int(data.get("opening_hold_ms", 120), 120, 0, 1000),
            closing_settle_ms=_bounded_int(data.get("closing_settle_ms", 360), 360, 0, 1600),
            interruptible=bool(data.get("interruptible", True)),
        )


@dataclass(frozen=True, slots=True)
class FollowupPolicy:
    mode: str = "close_without_comment"
    min_delay_sec: int = 35
    max_delay_sec: int = 75
    max_count: int = 0
    cancel_on_user_activity: bool = True
    cancel_on_scene_change: bool = True
    fallback: str = "close_without_comment"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "FollowupPolicy":
        data = payload or {}
        mode = compact(data.get("mode", "close_without_comment"), 80).lower() or "close_without_comment"
        max_count = _bounded_int(data.get("max_count", 1 if "reminder" in mode else 0), 0, 0, 1)
        minimum = _bounded_int(data.get("min_delay_sec", 35), 35, 5, 300)
        maximum = _bounded_int(data.get("max_delay_sec", 75), 75, minimum, 600)
        return cls(
            mode=mode,
            min_delay_sec=minimum,
            max_delay_sec=maximum,
            max_count=max_count,
            cancel_on_user_activity=bool(data.get("cancel_on_user_activity", True)),
            cancel_on_scene_change=bool(data.get("cancel_on_scene_change", True)),
            fallback=compact(data.get("fallback", "close_without_comment"), 80).lower() or "close_without_comment",
        )


@dataclass(frozen=True, slots=True)
class SafetyVerdict:
    allowed: bool = True
    flirt_level: str = "none"
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SafetyVerdict":
        data = payload or {}
        return cls(
            allowed=bool(data.get("allowed", True)),
            flirt_level=compact(data.get("flirt_level", "none"), 32).lower() or "none",
            reasons=tuple(compact(v, 160) for v in _sequence(data.get("reasons"))[:12] if compact(v, 160)),
        )


@dataclass(frozen=True, slots=True)
class OpeningPlan:
    decision: str = "speak"
    plan_id: str = ""
    encounter: EncounterMove = field(default_factory=EncounterMove)
    vibe_family: str = "anime_dry_warm"
    vibe_intensity: float = 0.40
    vibe_warmth: float = 0.50
    vibe_dry_edge: float = 0.35
    hook: ContextHook = field(default_factory=ContextHook)
    comedic_move: ComedicMove = field(default_factory=ComedicMove)
    beats: tuple[OpeningBeat, ...] = ()
    surface_contract: SurfaceContract = field(default_factory=SurfaceContract)
    prosody_plan: ProsodyPlan = field(default_factory=ProsodyPlan)
    followup_policy: FollowupPolicy = field(default_factory=FollowupPolicy)
    safety: SafetyVerdict = field(default_factory=SafetyVerdict)
    score: float = 0.0
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    schema: str = OPENING_PLAN_SCHEMA

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "OpeningPlan":
        data = payload or {}
        vibe = _mapping(data.get("vibe"))
        beats = tuple(
            OpeningBeat.from_mapping(raw, index=index)
            for index, raw in enumerate(_sequence(data.get("beats"))[:3], start=1)
            if isinstance(raw, Mapping)
        )
        return cls(
            decision=compact(data.get("decision", "speak"), 16).lower() or "speak",
            plan_id=compact(data.get("plan_id", ""), 120) or f"opening_{uuid.uuid4().hex[:16]}",
            encounter=EncounterMove.from_mapping(_mapping(data.get("encounter"))),
            vibe_family=compact(vibe.get("family", "anime_dry_warm"), 80).lower() or "anime_dry_warm",
            vibe_intensity=clamp01(vibe.get("intensity", 0.4), 0.4),
            vibe_warmth=clamp01(vibe.get("warmth", 0.5), 0.5),
            vibe_dry_edge=clamp01(vibe.get("dry_edge", 0.35), 0.35),
            hook=ContextHook.from_mapping(_mapping(data.get("hook"))),
            comedic_move=ComedicMove.from_mapping(_mapping(data.get("comedic_move"))),
            beats=beats,
            surface_contract=SurfaceContract.from_mapping(_mapping(data.get("surface_contract"))),
            prosody_plan=ProsodyPlan.from_mapping(_mapping(data.get("prosody_plan"))),
            followup_policy=FollowupPolicy.from_mapping(_mapping(data.get("followup_policy"))),
            safety=SafetyVerdict.from_mapping(_mapping(data.get("safety"))),
            score=float(data.get("score", 0.0) or 0.0),
            score_breakdown={compact(k, 80): float(v or 0.0) for k, v in _mapping(data.get("score_breakdown")).items()},
        )

    @classmethod
    def silence(cls, *, reason: str) -> "OpeningPlan":
        return cls(
            decision="silence",
            plan_id=f"opening_{uuid.uuid4().hex[:16]}",
            encounter=EncounterMove(required=False),
            safety=SafetyVerdict(allowed=False, reasons=(compact(reason, 160),)),
        )

    @property
    def reply_bearing(self) -> bool:
        return any(beat.reply_bearing for beat in self.beats)

    @property
    def beat_shape(self) -> str:
        return "_".join(beat.role for beat in self.beats)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        refs: list[str] = list(self.hook.evidence_refs)
        for beat in self.beats:
            refs.extend(beat.evidence_refs)
        return tuple(dict.fromkeys(refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision": self.decision,
            "plan_id": self.plan_id,
            "encounter": asdict(self.encounter),
            "vibe": {
                "family": self.vibe_family,
                "intensity": self.vibe_intensity,
                "warmth": self.vibe_warmth,
                "dry_edge": self.vibe_dry_edge,
            },
            "hook": {**asdict(self.hook), "evidence_refs": list(self.hook.evidence_refs)},
            "comedic_move": asdict(self.comedic_move),
            "beats": [beat.to_dict() for beat in self.beats],
            "surface_contract": {**asdict(self.surface_contract), "forbidden_claims": list(self.surface_contract.forbidden_claims)},
            "prosody_plan": asdict(self.prosody_plan),
            "followup_policy": asdict(self.followup_policy),
            "safety": {**asdict(self.safety), "reasons": list(self.safety.reasons)},
            "score": round(float(self.score), 6),
            "score_breakdown": {key: round(float(value), 6) for key, value in self.score_breakdown.items()},
        }


@dataclass(frozen=True, slots=True)
class SurfaceBeat:
    beat_id: str
    text: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SurfaceBeat | None":
        data = payload or {}
        beat_id = compact(data.get("beat_id", ""), 32)
        text = compact(data.get("text", ""), 600)
        if not beat_id or not text:
            return None
        return cls(beat_id=beat_id, text=text)


@dataclass(frozen=True, slots=True)
class OpeningSurface:
    display_language: str = "vi"
    display_beats: tuple[SurfaceBeat, ...] = ()
    display_text: str = ""
    speech_language: str = "ja"
    speech_beats: tuple[SurfaceBeat, ...] = ()
    speech_text: str = ""
    unsupported_claims: tuple[str, ...] = ()
    question_count: int = 0
    all_beats_realized: bool = True
    schema: str = OPENING_SURFACE_SCHEMA

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "OpeningSurface":
        data = payload or {}
        display = _mapping(data.get("display"))
        speech = _mapping(data.get("speech"))
        check = _mapping(data.get("self_check"))
        display_beats = tuple(
            item for item in (SurfaceBeat.from_mapping(raw) for raw in _sequence(display.get("beats"))[:3] if isinstance(raw, Mapping)) if item
        )
        speech_beats = tuple(
            item for item in (SurfaceBeat.from_mapping(raw) for raw in _sequence(speech.get("beats"))[:3] if isinstance(raw, Mapping)) if item
        )
        display_text = compact(display.get("full_text") or " ".join(item.text for item in display_beats), 1600)
        speech_text = compact(speech.get("full_text") or " ".join(item.text for item in speech_beats), 1600)
        return cls(
            display_language=compact(display.get("language", "vi"), 12).lower() or "vi",
            display_beats=display_beats,
            display_text=display_text,
            speech_language=compact(speech.get("language", "ja"), 12).lower() or "ja",
            speech_beats=speech_beats,
            speech_text=speech_text,
            unsupported_claims=tuple(compact(v, 180) for v in _sequence(check.get("unsupported_claims"))[:12] if compact(v, 180)),
            question_count=_bounded_int(check.get("question_count", display_text.count("?")), display_text.count("?"), 0, 9),
            all_beats_realized=bool(check.get("all_beats_realized", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "display": {
                "language": self.display_language,
                "beats": [asdict(item) for item in self.display_beats],
                "full_text": self.display_text,
            },
            "speech": {
                "language": self.speech_language,
                "beats": [asdict(item) for item in self.speech_beats],
                "full_text": self.speech_text,
            },
            "self_check": {
                "all_beats_realized": self.all_beats_realized,
                "unsupported_claims": list(self.unsupported_claims),
                "question_count": self.question_count,
            },
        }


__all__ = [
    "OPENING_HISTORY_SCHEMA",
    "OPENING_INPUT_SCHEMA",
    "OPENING_PLAN_SCHEMA",
    "OPENING_SURFACE_SCHEMA",
    "ComedicMove",
    "ContextHook",
    "ContinuityContext",
    "EncounterMove",
    "EvidenceItem",
    "FollowupPolicy",
    "OpeningBeat",
    "OpeningEvent",
    "OpeningInput",
    "OpeningPlan",
    "OpeningSurface",
    "PolicyContext",
    "ProsodyPlan",
    "RecentMoves",
    "SafetyVerdict",
    "ScenePartnerSnapshot",
    "SessionState",
    "SurfaceBeat",
    "SurfaceContract",
    "UserSignals",
    "clamp01",
    "compact",
]
