# -*- coding: utf-8 -*-
"""Endogenous speech pressure for ERIS.

Mô-đun này cung cấp cho ERIS một nguồn giọng nói nội bộ không bắt nguồn từ
sự thật về màn hình/đo từ xa. Nó không viết dòng công cộng. Nó chỉ đề xuất một
SpeechImpulse với một neo nội bộ, sau đó SpeechCore/ActionUtility quyết định
liệu xung lực đó có được phép nổi lên hay không."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .contracts import SpeechImpulse
from .internal_state import PersistentInternalState


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric != numeric:
        numeric = default
    return max(0.0, min(1.0, numeric))


def _clean(value: Any, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9_\s-]", " ", text)
    words = [word for word in text.split() if len(word) >= 2]
    return "_".join(words[:5])[:80] or "unanchored"


@dataclass(slots=True)
class SpontaneousLifeConfig:
    """Low-gain knobs for internal speech pressure."""

    autonomous_threshold: float = 0.50
    force_speak_threshold: float = 0.30
    hard_silence_after_speech_ticks: int = 1
    default_cooldown_seconds: float = 240.0
    min_idle_seconds_for_work_context: float = 180.0
    technical_focus_penalty: float = 0.18
    fatigue_penalty: float = 0.28
    exposure_penalty: float = 0.20


@dataclass(slots=True)
class SpontaneousLifeTrace:
    pressure: float = 0.0
    novelty: float = 0.0
    impulse_type: str = "none"
    family: str = ""
    blocked_reason: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "pressure": round(float(self.pressure), 3),
            "novelty": round(float(self.novelty), 3),
            "impulse_type": self.impulse_type,
            "family": self.family,
            "blocked_reason": self.blocked_reason,
            "evidence": list(self.evidence),
        }


class SpontaneousLifeEngine:
    """Tạo ra các xung giọng nói bên trong mà không cần đến màn hình. 

    Nó đọc áp lực thời gian chạy, dư lượng dòng suy nghĩ, khoảng cách mối quan hệ, 
    thời gian im lặng, mệt mỏi và lịch sử lời nói gần đây. Nó không bao giờ tuyên bố nhìn thấy 
    màn hình và nó không bao giờ trả về từ ngữ cuối cùng. Bài phát biểu trước công chúng vẫn thuộc về 
    tới SpeechCore + ActionPlanner + bảo vệ. Được cho là văn minh. 
    """

    def __init__(self, *, config: SpontaneousLifeConfig | None = None) -> None:
        self.config = config or SpontaneousLifeConfig()
        self._last_family_at: dict[str, float] = {}
        self.last_trace = SpontaneousLifeTrace()

    def evaluate(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state: PersistentInternalState | None = None,
        thought_surface=None,
        personality_lens=None,
        relationship_state=None,
        concrete_signals: tuple[str, ...] = (),
        recent_speech_acts: tuple[str, ...] = (),
        now: float | None = None,
    ) -> SpeechImpulse:
        now = time.monotonic() if now is None else float(now)
        channel_name = str(channel or "autonomous").strip().lower() or "autonomous"
        state = internal_state or PersistentInternalState()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)) if snapshot is not None else 0.0
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or getattr(state, "last_focus_kind", "") or "").strip().lower()
        ti_mode = str(getattr(state, "last_ti_mode", "") or "").strip().lower()

        thought_pressure = max(
            _clamp01(getattr(state, "thought_stream_pressure", 0.0)),
            _clamp01(getattr(state, "subconscious_pressure", 0.0)),
            _clamp01(getattr(thought_surface, "pressure", 0.0) if thought_surface is not None else 0.0),
            _clamp01(getattr(thought_surface, "momentum_score", 0.0) if thought_surface is not None else 0.0),
        )
        memory_residue = max(
            _clamp01(getattr(state, "memory_replay_pressure", 0.0)),
            _clamp01(getattr(state, "association_pressure", 0.0)) * 0.82,
            _clamp01(getattr(state, "last_memory_resonance", 0.0)) * 0.72,
        )
        silence = max(
            _clamp01(getattr(state, "silence_pressure", 0.0)),
            min(1.0, float(getattr(state, "silence_ticks", 0) or 0) / 7.0),
            min(1.0, idle_seconds / 420.0),
        )
        boredom = _clamp01(getattr(state, "boredom", 0.0))
        curiosity = max(_clamp01(getattr(state, "curiosity", 0.0)), _clamp01(getattr(state, "curiosity_pressure", 0.0)))
        attachment_visibility = _clamp01(getattr(getattr(state, "relationship_dynamics", None), "attachment_visibility", 0.0))
        if relationship_state is not None:
            attachment_visibility = max(attachment_visibility, _clamp01(getattr(relationship_state, "attachment_visibility", 0.0)))
        fatigue = max(_clamp01(getattr(state, "fatigue", 0.0)), _clamp01(getattr(state, "cognitive_tension", 0.0)) * 0.35)
        restraint = max(
            _clamp01(getattr(state, "restraint_pressure", 0.0)),
            _clamp01(getattr(personality_lens, "suppression_pressure", 0.0) if personality_lens is not None else 0.0),
        )

        technical_focus = focus_kind in {"coding", "code", "documentation", "docs", "ide"} or ti_mode in {
            "chat_code",
            "technical",
            "resource_guard",
            "goal_drift_alert",
            "focus_guard",
        }
        technical_penalty = self.config.technical_focus_penalty if technical_focus and idle_seconds < self.config.min_idle_seconds_for_work_context else 0.0
        recent_speech_penalty = 0.0
        if int(getattr(state, "silence_ticks", 0) or 0) <= self.config.hard_silence_after_speech_ticks:
            recent_speech_penalty = 0.22
        if recent_speech_acts and any(act in {"inner_whim", "random_chatter", "light_muse"} for act in tuple(recent_speech_acts)[-3:]):
            recent_speech_penalty = max(recent_speech_penalty, 0.18)

        pressure = (
            boredom * 0.22
            + curiosity * 0.16
            + silence * 0.24
            + thought_pressure * 0.26
            + memory_residue * 0.14
            + attachment_visibility * 0.06
            - fatigue * self.config.fatigue_penalty
            - restraint * self.config.exposure_penalty
            - technical_penalty
            - recent_speech_penalty
        )
        if thought_surface is not None and bool(getattr(thought_surface, "topic_seed", "")):
            pressure += 0.08
        if channel_name == "force_speak":
            pressure += 0.12
        pressure = _clamp01(pressure)

        novelty = _clamp01(
            max(
                getattr(thought_surface, "novelty", 0.0) if thought_surface is not None else 0.0,
                0.32 + curiosity * 0.20 + memory_residue * 0.12 + min(0.24, idle_seconds / 1800.0),
            )
        )
        impulse_type, speech_act, topic_seed = self._choose_impulse(
            state=state,
            thought_surface=thought_surface,
            boredom=boredom,
            curiosity=curiosity,
            silence=silence,
            memory_residue=memory_residue,
            attachment_visibility=attachment_visibility,
            technical_focus=technical_focus,
        )
        family = f"{impulse_type}:{_normalize_key(topic_seed)}"
        cooldown = self._cooldown_for(impulse_type=impulse_type, pressure=pressure)
        cooldown_left = self._cooldown_left(family, now=now, cooldown=cooldown)

        threshold = self.config.force_speak_threshold if channel_name == "force_speak" else self.config.autonomous_threshold
        blocked_reason = ""
        if channel_name not in {"autonomous", "force_speak"}:
            blocked_reason = "channel_not_endogenous"
        elif concrete_signals:
            blocked_reason = "external_signal_has_priority"
        elif pressure < threshold:
            blocked_reason = f"below_threshold:{pressure:.2f}/{threshold:.2f}"
        elif fatigue >= 0.74 and channel_name != "force_speak":
            blocked_reason = "fatigue_high"
        elif cooldown_left > 0 and channel_name != "force_speak":
            blocked_reason = f"family_cooldown:{cooldown_left:.0f}s"

        evidence = tuple(
            item
            for item in (
                f"endogenous_pressure={pressure:.2f}",
                f"silence={silence:.2f}",
                f"thought={thought_pressure:.2f}",
                f"memory_residue={memory_residue:.2f}",
                f"boredom={boredom:.2f}",
                f"focus={focus_kind or 'unknown'}",
                f"family={family}",
                f"blocked={blocked_reason}" if blocked_reason else "",
            )
            if item
        )
        self.last_trace = SpontaneousLifeTrace(
            pressure=pressure,
            novelty=novelty,
            impulse_type=impulse_type,
            family=family,
            blocked_reason=blocked_reason,
            evidence=evidence,
        )

        if blocked_reason:
            return SpeechImpulse(
                source="endogenous",
                source_layer="spontaneous_life",
                impulse_type=impulse_type,
                topic_seed=topic_seed,
                family=family,
                surface_pressure=pressure,
                novelty=novelty,
                risk="texture",
                needs_external_evidence=False,
                suggested_speech_act="no_speech",
                cooldown_seconds=cooldown,
                reason=blocked_reason,
                reaction="no_reaction",
                surface_intent="stay silent",
                semantic_family=family,
                evidence=evidence,
            )

        self._last_family_at[family] = now
        return SpeechImpulse(
            source="endogenous",
            source_layer="spontaneous_life",
            impulse_type=impulse_type,
            topic_seed=topic_seed,
            family=family,
            surface_pressure=pressure,
            novelty=novelty,
            risk="micro_presence" if speech_act in {"micro_presence", "companionship_ping"} else "texture",
            needs_external_evidence=False,
            suggested_speech_act=speech_act,
            cooldown_seconds=cooldown,
            reason="endogenous impulse cleared arbitration pre-threshold",
            meaning=topic_seed,
            reaction=speech_act,
            attitude="low_pressure_internal",
            surface_intent=speech_act,
            mood_residue=impulse_type,
            emotional_pressure=pressure,
            attention_bias=("endogenous", impulse_type),
            reaction_impulse=speech_act,
            semantic_family=family,
            source_fact="internal_state/thought_stream",
            evidence=evidence,
        )

    def _choose_impulse(
        self,
        *,
        state: PersistentInternalState,
        thought_surface,
        boredom: float,
        curiosity: float,
        silence: float,
        memory_residue: float,
        attachment_visibility: float,
        technical_focus: bool,
    ) -> tuple[str, str, str]:
        topic = _clean(getattr(thought_surface, "topic_seed", "") if thought_surface is not None else "", limit=80)
        if topic:
            return "inner_whim", "inner_whim", topic

        desire = getattr(state, "desire", None)
        unfinished = _clean(getattr(desire, "unfinished_thought", "") or getattr(state, "last_thought_seed", ""), limit=80)
        if unfinished and memory_residue >= 0.28:
            return "micro_story", "light_muse", unfinished

        if attachment_visibility >= 0.38 and silence >= 0.48 and boredom < 0.70:
            return "companionship_ping", "micro_presence", "quiet_co_presence"

        if boredom >= 0.52 and curiosity >= 0.30 and not technical_focus:
            return "random_chatter", "random_chatter", "small_absurd_observation"

        if technical_focus and silence >= 0.58:
            return "inner_whim", "inner_whim", "work_silence_residue"

        if memory_residue >= 0.42:
            return "micro_story", "light_muse", "memory_dust"

        return "inner_whim", "inner_whim", "quiet_whim"

    def _cooldown_for(self, *, impulse_type: str, pressure: float) -> float:
        base = {
            "companionship_ping": 300.0,
            "micro_story": 260.0,
            "random_chatter": 220.0,
            "inner_whim": 200.0,
        }.get(impulse_type, self.config.default_cooldown_seconds)
        if pressure >= 0.72:
            base *= 0.72
        return max(45.0, base)

    def _cooldown_left(self, family: str, *, now: float, cooldown: float) -> float:
        last = float(self._last_family_at.get(family, 0.0) or 0.0)
        if last <= 0.0:
            return 0.0
        elapsed = max(0.0, now - last)
        return max(0.0, cooldown - elapsed)
