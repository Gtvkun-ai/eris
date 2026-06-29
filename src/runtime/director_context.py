# -*- coding: utf-8 -*-
"""director_context.py - contract nho cho lop dao dien san khau.

DirectorContext la "anh gac cong" giua cognition va stage: no gom scene,
audience, machine state, evidence va budget noi thanh mot goi on dinh.  LLM
co the sang tao cau chu, nhung khong duoc tu doan san khau hoac quyen claim.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping


EvidenceLevel = Literal["observed", "tool", "inferred", "remembered", "forbidden"]
AudienceMode = Literal["private", "stream", "recording", "unknown"]
RelationBand = Literal["distant", "neutral", "warm", "close_restrained", "unknown"]
DecisionMode = Literal["suppress", "body_only", "short", "repair", "full"]


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    key: str
    level: EvidenceLevel
    value: Any
    confidence: float
    source: str
    observed_at_ms: int
    expires_at_ms: int | None = None
    public_ok: bool = True
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MachineState:
    active_app: str = "unknown"
    window_title: str = ""
    focus_kind: str = "unknown"
    idle_ms: int = 0
    typing_rate: str = "unknown"
    tts_playing: bool = False
    mic_active: bool = False
    fullscreen: bool = False
    audio_output_active: bool = False

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SceneMode:
    name: str
    confidence: float
    reasons: tuple[str, ...] = ()
    policy_tags: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DirectorContext:
    session_id: str
    trace_id: str
    audience_mode: AudienceMode
    relation_band: RelationBand
    scene_mode: SceneMode
    machine_state: MachineState
    world_state: dict[str, Any] = field(default_factory=dict)
    recent_text_turns: tuple[str, ...] = ()
    evidence: tuple[EvidenceClaim, ...] = ()
    allowed_claim_levels: tuple[EvidenceLevel, ...] = ("observed", "tool")
    forbidden_claims: tuple[str, ...] = ()
    speak_budget_words: int = 16
    speak_budget_ms: int = 2500
    interruption_state: str = "none"

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "audience_mode": self.audience_mode,
            "relation_band": self.relation_band,
            "scene_mode": self.scene_mode.to_payload(),
            "machine_state": self.machine_state.to_payload(),
            "world_state": dict(self.world_state),
            "recent_text_turns": list(self.recent_text_turns),
            "evidence": [claim.to_payload() for claim in self.evidence],
            "allowed_claim_levels": list(self.allowed_claim_levels),
            "forbidden_claims": list(self.forbidden_claims),
            "speak_budget_words": self.speak_budget_words,
            "speak_budget_ms": self.speak_budget_ms,
            "interruption_state": self.interruption_state,
        }

    def compact_payload(self) -> dict[str, Any]:
        """Payload ngan gan gui UI/debug, tranh phinh UDP body."""
        return {
            "trace_id": self.trace_id,
            "audience": self.audience_mode,
            "relation": self.relation_band,
            "scene": self.scene_mode.to_payload(),
            "machine": self.machine_state.to_payload(),
            "allowed_claim_levels": list(self.allowed_claim_levels),
            "forbidden_claims": list(self.forbidden_claims),
            "budget_words": self.speak_budget_words,
            "interruption_state": self.interruption_state,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _get_mapping_path(data: Mapping[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _snapshot_from_frame(frame: Any) -> Any:
    if frame is None:
        return None
    for attr in ("snapshot", "signal_snapshot", "observer_snapshot"):
        value = getattr(frame, attr, None)
        if value is not None:
            return value
    return None


def _attr_any(obj: Any, *names: str, default: Any = "") -> Any:
    if obj is None:
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return default


class SceneModeClassifier:
    """Phan loai scene tu machine state va channel hien tai.

    Rule uu tien scene cu the hon.  Coding/docs can giu im hon private idle;
    stream/recording se duoc tach rieng de sau nay gan moderation/publicity.
    """

    CODE_TOKENS = ("code", "coding", "ide", "vscode", "visual studio", "python", "debug", "godot")
    DOC_TOKENS = ("docs", "documentation", "browser", "reference", "pdf")
    COMM_TOKENS = ("chat", "discord", "zalo", "message", "slack")
    MEDIA_TOKENS = ("media", "youtube", "music", "game", "entertainment")

    def classify(self, machine: MachineState, *, channel: str = "", audience_mode: str = "private") -> SceneMode:
        haystack = " ".join(
            (
                machine.focus_kind,
                machine.active_app,
                machine.window_title,
                channel,
                audience_mode,
            )
        ).lower()
        if audience_mode in {"stream", "recording"}:
            return SceneMode("stream_host", 0.82, ("audience_not_private",), ("public_safe",))
        if any(token in haystack for token in self.CODE_TOKENS):
            return SceneMode("coding_partner", 0.86, ("focus_kind_code",), ("protect_focus", "technical"))
        if any(token in haystack for token in self.DOC_TOKENS):
            return SceneMode("study_partner", 0.74, ("focus_kind_docs",), ("protect_focus",))
        if any(token in haystack for token in self.COMM_TOKENS):
            return SceneMode("social_sidecar", 0.70, ("communication_context",), ("low_intrusion",))
        if any(token in haystack for token in self.MEDIA_TOKENS):
            return SceneMode("media_companion", 0.66, ("media_context",), ("light_banter_ok",))
        if machine.idle_ms >= 20000:
            return SceneMode("private_idle", 0.68, ("idle_window",), ("micro_presence_ok",))
        return SceneMode("private_general", 0.55, ("default_private",), ("low_intrusion",))


class DirectorContextBuilder:
    """Build DirectorContext tu payload/frame ma khong bat coordinator biet chi tiet."""

    def __init__(self, *, session_id: str | None = None, scene_classifier: SceneModeClassifier | None = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self.scene_classifier = scene_classifier or SceneModeClassifier()

    def build(
        self,
        *,
        payload: Mapping[str, Any],
        frame: Any = None,
        channel: str | None = None,
        user_text: str = "",
    ) -> DirectorContext:
        now = _now_ms()
        snapshot = _snapshot_from_frame(frame)
        machine = self._machine_state(payload=payload, snapshot=snapshot)
        audience = self._audience_mode(payload=payload, channel=channel)
        relation = self._relation_band(payload=payload)
        scene = self.scene_classifier.classify(machine, channel=channel or "", audience_mode=audience)
        evidence = self._evidence(payload=payload, snapshot=snapshot, machine=machine, now=now)
        forbidden = self._forbidden_claims(payload=payload, machine=machine)
        return DirectorContext(
            session_id=self.session_id,
            trace_id=uuid.uuid4().hex[:12],
            audience_mode=audience,
            relation_band=relation,
            scene_mode=scene,
            machine_state=machine,
            evidence=tuple(evidence),
            forbidden_claims=tuple(forbidden),
            speak_budget_words=self._budget_words(scene, channel=channel, user_text=user_text),
            speak_budget_ms=2500 if scene.name != "coding_partner" else 1800,
            interruption_state=self._interruption_state(payload),
        )

    def _machine_state(self, *, payload: Mapping[str, Any], snapshot: Any) -> MachineState:
        depth = payload.get("depth_v2") if isinstance(payload.get("depth_v2"), Mapping) else {}
        focus = _clean(_attr_any(snapshot, "active_window_kind", "focus_kind_hint", "focus_kind"))
        active_app = _clean(_attr_any(snapshot, "active_app", "active_window"), "unknown")
        title = _clean(_attr_any(snapshot, "active_window_title", "active_window"))
        idle_seconds = _safe_float(_attr_any(snapshot, "idle_seconds", "idle_s", default=0.0), 0.0)
        if not focus:
            focus = _clean(_get_mapping_path(depth, "status", "focus_mode"), "unknown")
        return MachineState(
            active_app=active_app,
            window_title=title,
            focus_kind=focus or "unknown",
            idle_ms=max(0, int(idle_seconds * 1000)),
            tts_playing=bool(payload.get("tts_playing", False)),
            mic_active=bool(payload.get("mic_active", False)),
            fullscreen=bool(_attr_any(snapshot, "fullscreen", default=False)),
            audio_output_active=bool(payload.get("audio_output_active", False)),
        )

    def _audience_mode(self, *, payload: Mapping[str, Any], channel: str | None) -> AudienceMode:
        raw = _clean(payload.get("audience_mode") or payload.get("publicity") or channel).lower()
        if raw in {"stream", "broadcast", "live"}:
            return "stream"
        if raw in {"recording", "video"}:
            return "recording"
        if raw in {"chat", "assistant_output", "autonomous", "force_speak", "private", ""}:
            return "private"
        return "unknown"

    def _relation_band(self, *, payload: Mapping[str, Any]) -> RelationBand:
        depth = payload.get("depth_v2") if isinstance(payload.get("depth_v2"), Mapping) else {}
        raw = _clean(
            payload.get("relation_band")
            or _get_mapping_path(depth, "tom", "relationship")
            or _get_mapping_path(depth, "anchor", "relation_band")
        ).lower()
        if "close" in raw or "near" in raw or "restrained" in raw:
            return "close_restrained"
        if "warm" in raw or "soft" in raw:
            return "warm"
        if "distant" in raw or "cold" in raw:
            return "distant"
        if raw:
            return "neutral"
        return "unknown"

    def _evidence(
        self,
        *,
        payload: Mapping[str, Any],
        snapshot: Any,
        machine: MachineState,
        now: int,
    ) -> list[EvidenceClaim]:
        evidence: list[EvidenceClaim] = [
            EvidenceClaim("active_app", "observed", machine.active_app, 0.90, "machine_state", now, expires_at_ms=now + 5000),
            EvidenceClaim("focus_kind", "observed", machine.focus_kind, 0.82, "machine_state", now, expires_at_ms=now + 5000),
            EvidenceClaim("idle_ms", "observed", machine.idle_ms, 0.80, "machine_state", now, expires_at_ms=now + 5000),
        ]
        if machine.window_title:
            evidence.append(EvidenceClaim("window_title", "observed", machine.window_title, 0.70, "machine_state", now, expires_at_ms=now + 5000, public_ok=False))
        if isinstance(payload.get("emotion_debug"), Mapping):
            evidence.append(EvidenceClaim("affect_summary", "inferred", payload.get("emotion_debug"), 0.55, "internal_state", now, public_ok=False))
        if snapshot is not None:
            screen_text = _clean(_attr_any(snapshot, "screen_text", "ocr_text", "focus_summary"))
            if screen_text:
                evidence.append(EvidenceClaim("screen_summary", "observed", screen_text[:240], 0.64, "vision_or_focus", now, expires_at_ms=now + 5000))
        return evidence

    def _forbidden_claims(self, *, payload: Mapping[str, Any], machine: MachineState) -> list[str]:
        forbidden = ["hearing_user_breath", "emotion_as_fact", "system_action_without_tool"]
        has_screen = bool(machine.window_title or any(str(claim).strip() for claim in (payload.get("screen_facts"), payload.get("vision_facts"))))
        if not has_screen:
            forbidden.append("screen_claim_without_sensor")
        return forbidden

    def _budget_words(self, scene: SceneMode, *, channel: str | None, user_text: str) -> int:
        if str(channel or "").lower() == "chat" and str(user_text or "").strip():
            return 60
        if scene.name == "coding_partner":
            return 18
        if scene.name == "private_idle":
            return 14
        if scene.name == "stream_host":
            return 22
        return 16

    def _interruption_state(self, payload: Mapping[str, Any]) -> str:
        stage = payload.get("stage")
        if isinstance(stage, Mapping) and stage.get("interrupted"):
            return "interrupted"
        if payload.get("interrupt_event"):
            return "interrupted"
        return "none"


__all__ = [
    "AudienceMode",
    "DecisionMode",
    "DirectorContext",
    "DirectorContextBuilder",
    "EvidenceClaim",
    "EvidenceLevel",
    "MachineState",
    "RelationBand",
    "SceneMode",
    "SceneModeClassifier",
]
