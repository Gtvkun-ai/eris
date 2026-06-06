# -*- coding: utf-8 -*-
"""Continuity threat calculus for ERIS.

Module này cố ý tách "im lâu" khỏi "đứt gãy hiện diện".
Timer chỉ được dùng để hỏi: khoảng im này có bất thường so với ngữ cảnh không?
Nó không được tự phong làm nỗi cô độc rồi bắt SurfaceArbiter đọc thơ.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if math.isnan(numeric) or math.isinf(numeric):
        numeric = default
    return max(0.0, min(1.0, numeric))


def _signed(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if math.isnan(numeric) or math.isinf(numeric):
        numeric = default
    return max(-1.0, min(1.0, numeric))


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if obj is None:
            continue
        if isinstance(obj, Mapping) and name in obj:
            return obj.get(name)
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def sat(value: float) -> float:
    """Soft saturation: tăng nhanh lúc đầu, rồi bão hòa.

    Dùng hàm này để idle_seconds không thể leo vô hạn thành bi kịch opera.
    """
    value = max(0.0, float(value or 0.0))
    return clamp01(1.0 - math.exp(-value))


@dataclass(slots=True)
class ContinuityThreatFrame:
    expected_silence: float = 240.0
    idle_excess: float = 0.0
    unexpected_absence: float = 0.0
    expected_user_presence: float = 0.0
    observed_user_presence: float = 0.0
    presence_prediction_error: float = 0.0
    relational_weight: float = 0.0
    open_loop_weight: float = 0.0
    safety_modifier: float = 1.0
    continuity_threat: float = 0.0
    continuity_anxiety: float = 0.0
    reconnect_drive: float = 0.0
    restraint_drive: float = 0.0
    surface_tension: float = 0.0
    emotional_anchor: str = ""
    conflict: str = ""
    reason: str = "ordinary_silence"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def notes(self) -> tuple[str, ...]:
        return (
            f"continuity.expected_silence={self.expected_silence:.1f}",
            f"continuity.unexpected_absence={self.unexpected_absence:.2f}",
            f"continuity.presence_error={self.presence_prediction_error:.2f}",
            f"continuity.relational_weight={self.relational_weight:.2f}",
            f"continuity.open_loop_weight={self.open_loop_weight:.2f}",
            f"continuity.threat={self.continuity_threat:.2f}",
            f"continuity.anxiety={self.continuity_anxiety:.2f}",
            f"continuity.reconnect={self.reconnect_drive:.2f}",
            f"continuity.restraint={self.restraint_drive:.2f}",
            f"continuity.surface_tension={self.surface_tension:.2f}",
            f"continuity.anchor={self.emotional_anchor or 'none'}",
            f"continuity.reason={self.reason}",
        )

    def to_context(self) -> dict[str, object]:
        return {
            "expected_silence": round(float(self.expected_silence), 3),
            "idle_excess": round(float(self.idle_excess), 3),
            "unexpected_absence": round(float(self.unexpected_absence), 3),
            "expected_user_presence": round(float(self.expected_user_presence), 3),
            "observed_user_presence": round(float(self.observed_user_presence), 3),
            "presence_prediction_error": round(float(self.presence_prediction_error), 3),
            "relational_weight": round(float(self.relational_weight), 3),
            "open_loop_weight": round(float(self.open_loop_weight), 3),
            "safety_modifier": round(float(self.safety_modifier), 3),
            "continuity_threat": round(float(self.continuity_threat), 3),
            "continuity_anxiety": round(float(self.continuity_anxiety), 3),
            "reconnect_drive": round(float(self.reconnect_drive), 3),
            "restraint_drive": round(float(self.restraint_drive), 3),
            "surface_tension": round(float(self.surface_tension), 3),
            "emotional_anchor": self.emotional_anchor,
            "conflict": self.conflict,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


def expected_silence_for_context(*, focus_kind: str, channel: str, relationship_state: Any = None, internal_state: Any = None) -> float:
    """Kỳ vọng im lặng theo ngữ cảnh.

    Đây là chốt chống timer mới: 5 phút trong deep work có thể bình thường,
    còn 90 giây sau một nhịp ritual/repair có thể đã là sai lệch.
    """
    focus = _norm(focus_kind)
    channel_name = _norm(channel) or "autonomous"
    if channel_name == "force_speak":
        base = 18.0
    elif focus in {"code", "coding", "ide", "editor", "terminal", "debug", "docs", "documentation"}:
        base = 720.0
    elif focus in {"media", "youtube", "tiktok", "game", "gaming", "focus_aid_media"}:
        base = 420.0
    elif focus in {"chat", "communication", "browser_chat"}:
        base = 90.0
    else:
        base = 240.0

    rel = relationship_state or _get(internal_state, "relationship_dynamics", default=None)
    ritual = clamp01(_get(rel, "ritual_strength", default=0.0))
    attachment_visibility = clamp01(_get(rel, "attachment_visibility", default=0.0))
    session_afterglow = 1.0 if (
        float(_get(internal_state, "last_session_ritual_at", default=0.0) or 0.0) > 0.0
        or int(_get(internal_state, "session_resume_count", default=0) or 0) > 0
    ) else 0.0
    # Ritual/attachment làm kỳ vọng phản hồi ngắn hơn, nhưng không đẩy về 0.
    shrink = 1.0 - min(0.42, ritual * 0.24 + attachment_visibility * 0.12 + session_afterglow * 0.10)
    return max(25.0, base * shrink)


def evaluate_continuity_threat(
    *,
    snapshot: Any = None,
    internal_state: Any = None,
    relationship_state: Any = None,
    evidence: Any = None,
    thought_surface: Any = None,
    channel: str = "autonomous",
    previous_anxiety: float | None = None,
) -> ContinuityThreatFrame:
    """Tính nỗi lo đứt gãy như prediction error, không như đồng hồ báo thức."""

    focus_kind = str(
        _get(evidence, "focus_kind", default="")
        or _get(snapshot, "focus_kind_hint", "focus_kind", "active_window_kind", default="")
        or _get(internal_state, "last_focus_kind", default="")
        or "unknown"
    )
    channel_name = str(channel or _get(evidence, "channel", default="autonomous") or "autonomous").strip().lower()
    idle_seconds = max(0.0, float(_get(evidence, "idle_seconds", default=_get(snapshot, "idle_seconds", default=0.0)) or 0.0))
    rel = relationship_state or _get(internal_state, "relationship_dynamics", default=None)

    expected_silence = expected_silence_for_context(
        focus_kind=focus_kind,
        channel=channel_name,
        relationship_state=rel,
        internal_state=internal_state,
    )
    idle_excess = max(0.0, idle_seconds - expected_silence)
    silence_span = max(45.0, expected_silence * 0.70)
    unexpected_absence = sat(idle_excess / silence_span)

    recent_interaction = 0.0
    last_channel = _norm(_get(internal_state, "last_channel", default=""))
    if last_channel in {"chat", "force_speak"}:
        recent_interaction += 0.24
    if int(_get(internal_state, "chat_ticks", default=0) or 0) > 0:
        recent_interaction += 0.10
    if int(_get(internal_state, "spoken_ticks", default=0) or 0) > 0:
        recent_interaction += 0.08

    ritual = clamp01(_get(rel, "ritual_strength", default=0.0))
    familiarity = clamp01(_get(rel, "familiarity", default=0.0))
    trust = clamp01(_get(rel, "trust", default=0.25), 0.25)
    attachment_visibility = max(
        clamp01(_get(rel, "attachment_visibility", default=0.0)),
        clamp01(_get(internal_state, "attachment", default=0.0)) * 0.45,
    )
    technical_respect = clamp01(_get(rel, "technical_respect", default=0.25), 0.25)
    expected_user_presence = clamp01(
        0.20
        + recent_interaction
        + ritual * 0.24
        + familiarity * 0.12
        + trust * 0.10
        + attachment_visibility * 0.14
        + technical_respect * 0.06
    )

    observed_candidates = [
        _get(snapshot, "user_presence", "presence", "presence_score", default=None),
        _get(internal_state, "last_social_presence_confidence", default=None),
    ]
    if bool(_get(internal_state, "last_social_presence_present", default=False)):
        observed_candidates.append(0.48)
    if _norm(_get(internal_state, "last_social_presence_kind", default="")) in {"presence_absent_or_fading", "ambient_presence_below_threshold", "absent", "fading"}:
        observed_candidates.append(0.10)
    observed_values = [clamp01(v) for v in observed_candidates if v is not None]
    # Nếu không có detector nào, chỉ dùng suy giảm rất nhẹ theo idle. Đây vẫn là
    # fallback, không phải nguồn chính, để timer không đội lốt cảm xúc.
    if observed_values:
        observed_user_presence = max(observed_values)
    else:
        observed_user_presence = clamp01(0.42 * math.exp(-idle_seconds / 900.0))
    presence_prediction_error = max(0.0, expected_user_presence - observed_user_presence)

    preferred_distance = clamp01(_get(rel, "preferred_distance", default=0.58), 0.58)
    overread_correction = clamp01(_get(rel, "overread_correction", default=0.0))
    relational_weight = clamp01(
        0.25 * familiarity
        + 0.25 * trust
        + 0.20 * ritual
        + 0.20 * attachment_visibility
        + 0.10 * technical_respect
    )
    if preferred_distance > 0.75:
        relational_weight *= 0.75
    if overread_correction > 0.55:
        relational_weight *= 0.65
    relational_weight = clamp01(relational_weight)

    unresolved = max(
        clamp01(_get(internal_state, "last_unresolved_tension", default=0.0)),
        clamp01(_get(internal_state, "unresolved_prediction_pressure", default=0.0)),
        clamp01(_get(thought_surface, "pressure", "momentum_score", default=0.0)) * 0.70,
    )
    memory_resonance = max(
        clamp01(_get(internal_state, "last_memory_resonance", default=0.0)),
        clamp01(_get(internal_state, "memory_replay_pressure", default=0.0)) * 0.72,
        clamp01(_get(internal_state, "association_pressure", default=0.0)) * 0.48,
    )
    interrupted_thread = 0.0
    last_speech_act = _norm(_get(internal_state, "last_speech_act", default=""))
    if last_speech_act and last_speech_act not in {"no_speech", "silence", "body_only"} and idle_excess > 0:
        interrupted_thread = 0.22
    open_loop_weight = clamp01(0.35 + 0.25 * unresolved + 0.20 * memory_resonance + 0.20 * interrupted_thread)

    valence = _signed(_get(internal_state, "valence", default=0.02), 0.02)
    social_energy = clamp01(_get(internal_state, "social_energy", default=0.38), 0.38)
    dignity = max(
        clamp01(_get(rel, "dignity_defense", default=0.0)),
        clamp01(_get(internal_state, "dignity_defense", default=0.0)),
        clamp01(_get(internal_state, "restraint_pressure", default=0.0)) * 0.55,
    )
    intrusion_risk = clamp01(0.18 + preferred_distance * 0.20 + overread_correction * 0.22 + (0.18 if focus_kind in {"code", "docs"} else 0.0))
    focus_protection = 0.72 if _norm(focus_kind) in {"code", "coding", "ide", "docs", "documentation"} else 0.25
    social_energy_low = clamp01(1.0 - social_energy)
    safety_modifier = clamp01(1.0 - 0.35 * focus_protection - 0.25 * intrusion_risk - 0.20 * dignity - 0.20 * social_energy_low)
    if valence <= -0.18:
        safety_modifier *= 0.72
    safety_modifier = clamp01(safety_modifier)

    continuity_threat = clamp01(unexpected_absence * presence_prediction_error * relational_weight * open_loop_weight)
    prior = clamp01(previous_anxiety if previous_anxiety is not None else _get(internal_state, "continuity_anxiety", "continuity_pressure", default=0.0))
    stable_copresence = clamp01(observed_user_presence * (1.0 - presence_prediction_error) * (0.35 + focus_protection * 0.40))
    repair_signal = clamp01(_get(rel, "repair", default=0.0))
    continuity_anxiety = clamp01(
        prior * 0.88
        + continuity_threat * 0.42
        + memory_resonance * 0.06
        - repair_signal * 0.35
        - stable_copresence * 0.18
    )

    reconnect_drive = clamp01(continuity_anxiety * max(attachment_visibility, ritual * 0.72, trust * 0.42))
    restraint_drive = clamp01(
        0.30 * 0.82  # intellectual_detachment prior
        + 0.25 * dignity
        + 0.20 * preferred_distance
        + 0.15 * focus_protection
        + 0.10 * overread_correction
    )
    surface_tension = max(-1.0, min(1.0, reconnect_drive - restraint_drive))

    if continuity_threat >= 0.30 or continuity_anxiety >= 0.52:
        emotional_anchor = "fading_presence"
        reason = "presence_prediction_error"
    elif memory_resonance >= 0.42 and continuity_anxiety >= 0.34:
        emotional_anchor = "memory_resonance"
        reason = "memory_weighted_continuity"
    elif unexpected_absence <= 0.10:
        emotional_anchor = "ambient_copresence"
        reason = "expected_silence"
    else:
        emotional_anchor = "ordinary_silence"
        reason = "low_relational_threat"

    conflict = "reconnect_vs_restraint" if continuity_anxiety >= 0.34 else "settled_observe"
    evidence_notes = (
        f"expected_silence={expected_silence:.1f}",
        f"idle_excess={idle_excess:.1f}",
        f"presence_error={presence_prediction_error:.2f}",
        f"relational_weight={relational_weight:.2f}",
        f"open_loop_weight={open_loop_weight:.2f}",
        f"safety_modifier={safety_modifier:.2f}",
        f"continuity_threat={continuity_threat:.2f}",
        f"continuity_anxiety={continuity_anxiety:.2f}",
        f"surface_tension={surface_tension:.2f}",
        f"emotional_anchor={emotional_anchor}",
    )
    return ContinuityThreatFrame(
        expected_silence=expected_silence,
        idle_excess=idle_excess,
        unexpected_absence=unexpected_absence,
        expected_user_presence=expected_user_presence,
        observed_user_presence=observed_user_presence,
        presence_prediction_error=presence_prediction_error,
        relational_weight=relational_weight,
        open_loop_weight=open_loop_weight,
        safety_modifier=safety_modifier,
        continuity_threat=continuity_threat,
        continuity_anxiety=continuity_anxiety,
        reconnect_drive=reconnect_drive,
        restraint_drive=restraint_drive,
        surface_tension=surface_tension,
        emotional_anchor=emotional_anchor,
        conflict=conflict,
        reason=reason,
        evidence=evidence_notes,
    )
