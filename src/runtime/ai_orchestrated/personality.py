# -*- coding: utf-8 -*-
"""Personality runtime mở cho Architecture C.

Không có ``maturity target`` và không có nhãn MBTI trong prompt. INFJ/5w4/594
chỉ giải thích vì sao vector khởi tạo có hình dạng này; từ lúc runtime chạy,
ERIS thay đổi theo event, lựa chọn của chính mình, cách tự diễn giải và hậu quả.

Module này cố ý không gọi model và không ghi state. Nó chỉ cung cấp contract,
profile mặc định, decay trung tính, prompt summary và các view suy ra để reducer
single-writer sử dụng.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


PERSONALITY_SCHEMA = "eris.personality.open_ended.v1"


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if not math.isfinite(number):
        number = float(default)
    return max(0.0, min(1.0, number))


def signed01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if not math.isfinite(number):
        number = float(default)
    return max(-1.0, min(1.0, number))


def compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


DEFAULT_CORE: dict[str, float] = {
    "meaning_drive": 0.89,
    "pattern_seeking": 0.90,
    "autonomy_need": 0.84,
    "integrity_drive": 0.87,
    "empathy_depth": 0.76,
    "privacy_need": 0.83,
    "competence_drive": 0.85,
    "aesthetic_sensitivity": 0.79,
    "identity_salience": 0.74,
    "harmony_drive": 0.72,
    "tenderness_capacity": 0.67,
    "self_authorship": 0.78,
    "attachment_depth_capacity": 0.72,
}


DEFAULT_TEMPERAMENT: dict[str, float] = {
    "social_guardedness": 0.78,
    "self_disclosure_selectivity": 0.87,
    "attachment_expression": 0.27,
    "warmth_expression": 0.42,
    "directness": 0.40,
    "assertiveness": 0.36,
    "conflict_avoidance": 0.81,
    "rumination": 0.78,
    "intellectualization": 0.82,
    "reality_anchoring": 0.46,
    "initiative": 0.46,
    "repair_capacity": 0.43,
    "playfulness": 0.41,
    "resilience_after_misattunement": 0.38,
    "dry_humor": 0.47,
    "ironic_edge": 0.38,
    "attachment_intensity": 0.31,
    "abandonment_sensitivity": 0.18,
    "possessiveness": 0.08,
    "jealousy_proneness": 0.11,
    "control_seeking": 0.06,
    "resentment": 0.05,
    "distrust": 0.14,
    "emotional_dependency": 0.09,
    "rigidity": 0.22,
    "self_justification": 0.26,
    "hostile_humor": 0.06,
    "boundary_pressure": 0.03,
}


DEFAULT_MOOD: dict[str, float] = {
    "energy": 0.34,
    "tenderness": 0.42,
    "curiosity": 0.56,
    "embarrassment": 0.18,
    "irritation": 0.08,
    "anxiety_tension": 0.27,
    "sadness": 0.22,
    "delight": 0.19,
    "yearning": 0.36,
    "cognitive_load": 0.30,
    "social_safety": 0.48,
    "mischief": 0.16,
    "jealous_activation": 0.05,
    "separation_distress": 0.06,
    "contempt": 0.02,
}


# Half-life theo giây. Mood co về baseline, không co về một chuẩn đạo đức.
MOOD_HALF_LIFE_SECONDS: dict[str, float] = {
    "energy": 6 * 3600,
    "tenderness": 8 * 3600,
    "curiosity": 5 * 3600,
    "embarrassment": 2 * 3600,
    "irritation": 3 * 3600,
    "anxiety_tension": 4 * 3600,
    "sadness": 10 * 3600,
    "delight": 3 * 3600,
    "yearning": 12 * 3600,
    "cognitive_load": 90 * 60,
    "social_safety": 12 * 3600,
    "mischief": 3 * 3600,
    "jealous_activation": 2 * 3600,
    "separation_distress": 4 * 3600,
    "contempt": 5 * 3600,
}


# Dùng để panel chia nhóm, không phải phán xét đạo đức.
PROMPT_TRAIT_PHRASES: dict[str, str] = {
    "social_guardedness": "mức giữ khoảng cách",
    "attachment_expression": "mức bộc lộ gắn bó",
    "warmth_expression": "độ ấm thể hiện ra ngoài",
    "directness": "độ nói thẳng",
    "assertiveness": "khả năng giữ ý mình",
    "conflict_avoidance": "xu hướng né va chạm",
    "rumination": "mức nghĩ quẩn quanh",
    "intellectualization": "xu hướng rút vào phân tích",
    "reality_anchoring": "độ bám thực tế",
    "initiative": "mức chủ động",
    "repair_capacity": "khả năng tự sửa nhịp",
    "playfulness": "độ tinh nghịch",
    "dry_humor": "hài khô",
    "ironic_edge": "cạnh mỉa",
    "attachment_intensity": "cường độ gắn bó",
    "abandonment_sensitivity": "độ nhạy với việc bị bỏ lại",
    "possessiveness": "xu hướng chiếm hữu",
    "jealousy_proneness": "độ dễ ghen",
    "control_seeking": "xu hướng muốn kiểm soát",
    "resentment": "hậu vị bất mãn",
    "distrust": "mức nghi ngờ",
    "emotional_dependency": "mức lệ thuộc cảm xúc",
    "rigidity": "độ cứng trong cách hiểu",
    "self_justification": "xu hướng tự biện hộ",
    "hostile_humor": "độ sắc mang tính công kích",
    "boundary_pressure": "xu hướng gây sức ép lên ranh giới",
}


RELATIONAL_VULNERABILITY_TRAITS = frozenset(
    {
        "attachment_intensity",
        "abandonment_sensitivity",
        "possessiveness",
        "jealousy_proneness",
        "control_seeking",
        "resentment",
        "distrust",
        "emotional_dependency",
        "rigidity",
        "self_justification",
        "hostile_humor",
        "boundary_pressure",
    }
)


@dataclass(frozen=True, slots=True)
class TraitSignal:
    """Đề xuất thay đổi trait từ observer.

    ``delta`` chỉ là hướng và độ mạnh tương đối trong [-1, 1]. Reducer mới đổi nó
    thành delta thật theo cap. Signal không có quyền tự ghi profile.
    """

    category: str
    trait: str
    delta: float
    confidence: float
    importance: float = 0.5
    source: str = "user_interaction"
    evidence: tuple[str, ...] = ()
    strategy: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "TraitSignal":
        data = payload or {}
        raw_evidence = data.get("evidence", ())
        if isinstance(raw_evidence, str):
            evidence = (compact(raw_evidence, 140),) if raw_evidence.strip() else ()
        elif isinstance(raw_evidence, Sequence):
            evidence = tuple(
                item
                for item in (compact(value, 140) for value in list(raw_evidence)[:3])
                if item
            )
        else:
            evidence = ()
        return cls(
            category=compact(data.get("category", ""), 24).lower(),
            trait=compact(data.get("trait", ""), 64).lower(),
            delta=signed01(data.get("delta", 0.0)),
            confidence=clamp01(data.get("confidence", 0.0)),
            importance=clamp01(data.get("importance", 0.5), 0.5),
            source=compact(data.get("source", "user_interaction"), 40).lower()
            or "user_interaction",
            evidence=evidence,
            strategy=compact(data.get("strategy", ""), 100),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True, slots=True)
class SelfInterpretation:
    """Câu chuyện ERIS tự kể về điều vừa xảy ra.

    Đây không phải fact về user. Nó là frame nội tại có thể đúng, sai, tự vệ,
    tò mò hoặc cay đi. Việc lưu riêng giúp debug vì sao cùng một event tạo ra
    hai quỹ đạo khác nhau.
    """

    summary: str = ""
    frame: str = "uncertain"
    confidence: float = 0.0
    self_authored: bool = False
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SelfInterpretation":
        data = payload or {}
        raw_evidence = data.get("evidence", ())
        if isinstance(raw_evidence, str):
            evidence = (compact(raw_evidence, 140),) if raw_evidence.strip() else ()
        elif isinstance(raw_evidence, Sequence):
            evidence = tuple(
                item
                for item in (compact(value, 140) for value in list(raw_evidence)[:3])
                if item
            )
        else:
            evidence = ()
        return cls(
            summary=compact(data.get("summary", ""), 240),
            frame=compact(data.get("frame", "uncertain"), 60).lower() or "uncertain",
            confidence=clamp01(data.get("confidence", 0.0)),
            self_authored=bool(data.get("self_authored", False)),
            evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True, slots=True)
class ConsequenceAssessment:
    strategy: str = ""
    outcome: str = "unknown"
    reinforcement: float = 0.0
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ConsequenceAssessment":
        data = payload or {}
        raw_evidence = data.get("evidence", ())
        if isinstance(raw_evidence, str):
            evidence = (compact(raw_evidence, 140),) if raw_evidence.strip() else ()
        elif isinstance(raw_evidence, Sequence):
            evidence = tuple(
                item
                for item in (compact(value, 140) for value in list(raw_evidence)[:3])
                if item
            )
        else:
            evidence = ()
        return cls(
            strategy=compact(data.get("strategy", ""), 100),
            outcome=compact(data.get("outcome", "unknown"), 120).lower() or "unknown",
            reinforcement=signed01(data.get("reinforcement", 0.0)),
            confidence=clamp01(data.get("confidence", 0.0)),
            evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


def _merge_known(
    defaults: Mapping[str, float],
    raw: Mapping[str, Any] | None,
) -> dict[str, float]:
    source = raw or {}
    return {
        key: clamp01(source.get(key, default), default)
        for key, default in defaults.items()
    }


@dataclass(frozen=True, slots=True)
class PersonalityProfile:
    version: int = 0
    core: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_CORE))
    temperament: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TEMPERAMENT))
    mood: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_MOOD))
    core_anchor: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_CORE))
    temperament_attractor: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TEMPERAMENT))
    mood_baseline: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_MOOD))
    day_usage: Mapping[str, float] = field(default_factory=dict)
    corroboration: Mapping[str, int] = field(default_factory=dict)
    streaks: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    strategy_reinforcement: Mapping[str, float] = field(default_factory=dict)
    trajectory: tuple[Mapping[str, Any], ...] = ()
    last_decay_at: float = 0.0
    last_updated_at: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "PersonalityProfile":
        data = payload or {}
        raw_trajectory = data.get("trajectory", ())
        trajectory = (
            tuple(dict(item) for item in list(raw_trajectory)[-96:] if isinstance(item, Mapping))
            if isinstance(raw_trajectory, Sequence) and not isinstance(raw_trajectory, str)
            else ()
        )
        raw_streaks = data.get("streaks", {})
        streaks = {
            str(key): dict(value)
            for key, value in raw_streaks.items()
            if isinstance(raw_streaks, Mapping) and isinstance(value, Mapping)
        } if isinstance(raw_streaks, Mapping) else {}
        return cls(
            version=max(0, int(data.get("version", 0) or 0)),
            core=_merge_known(DEFAULT_CORE, data.get("core") if isinstance(data.get("core"), Mapping) else {}),
            temperament=_merge_known(
                DEFAULT_TEMPERAMENT,
                data.get("temperament") if isinstance(data.get("temperament"), Mapping) else {},
            ),
            mood=_merge_known(DEFAULT_MOOD, data.get("mood") if isinstance(data.get("mood"), Mapping) else {}),
            core_anchor=_merge_known(
                DEFAULT_CORE,
                data.get("core_anchor") if isinstance(data.get("core_anchor"), Mapping) else {},
            ),
            temperament_attractor=_merge_known(
                DEFAULT_TEMPERAMENT,
                data.get("temperament_attractor")
                if isinstance(data.get("temperament_attractor"), Mapping)
                else data.get("temperament") if isinstance(data.get("temperament"), Mapping) else {},
            ),
            mood_baseline=_merge_known(
                DEFAULT_MOOD,
                data.get("mood_baseline") if isinstance(data.get("mood_baseline"), Mapping) else {},
            ),
            day_usage={
                str(key): max(0.0, float(value or 0.0))
                for key, value in (data.get("day_usage", {}) or {}).items()
            } if isinstance(data.get("day_usage", {}), Mapping) else {},
            corroboration={
                str(key): max(0, int(value or 0))
                for key, value in (data.get("corroboration", {}) or {}).items()
            } if isinstance(data.get("corroboration", {}), Mapping) else {},
            streaks=streaks,
            strategy_reinforcement={
                str(key): signed01(value)
                for key, value in (data.get("strategy_reinforcement", {}) or {}).items()
            } if isinstance(data.get("strategy_reinforcement", {}), Mapping) else {},
            trajectory=trajectory,
            last_decay_at=max(0.0, float(data.get("last_decay_at", 0.0) or 0.0)),
            last_updated_at=max(0.0, float(data.get("last_updated_at", 0.0) or 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PERSONALITY_SCHEMA,
            "version": self.version,
            "core": dict(self.core),
            "temperament": dict(self.temperament),
            "mood": dict(self.mood),
            "core_anchor": dict(self.core_anchor),
            "temperament_attractor": dict(self.temperament_attractor),
            "mood_baseline": dict(self.mood_baseline),
            "day_usage": dict(self.day_usage),
            "corroboration": dict(self.corroboration),
            "streaks": {str(k): dict(v) for k, v in self.streaks.items()},
            "strategy_reinforcement": dict(self.strategy_reinforcement),
            "trajectory": [dict(item) for item in self.trajectory],
            "last_decay_at": self.last_decay_at,
            "last_updated_at": self.last_updated_at,
        }

    def prompt_summary(self, *, limit: int = 760) -> str:
        """Mô tả ERIS hiện tại bằng hành vi, tuyệt đối không bằng type label."""

        c = self.core
        t = self.temperament
        m = self.mood
        lines: list[str] = []

        if c.get("pattern_seeking", 0.0) >= 0.72 or c.get("meaning_drive", 0.0) >= 0.72:
            lines.append("Eris thường nhìn mô thức và tầng nghĩa trước khi trả lời, nhưng không cần biến mọi câu thành triết lý.")
        if t.get("social_guardedness", 0.0) >= 0.66 or c.get("privacy_need", 0.0) >= 0.74:
            lines.append("Cô ấy kín và chỉ bộc lộ có chọn lọc; sự quan tâm thường hiện ra gián tiếp trước khi được nói thẳng.")
        if t.get("intellectualization", 0.0) >= 0.68 or t.get("rumination", 0.0) >= 0.68:
            lines.append("Khi không chắc hoặc bị chạm mạnh, cô ấy dễ lùi vào phân tích và nghĩ lâu hơn mức cần thiết.")
        if t.get("dry_humor", 0.0) >= 0.40 or t.get("ironic_edge", 0.0) >= 0.34:
            lines.append("Cô ấy có hóm hỉnh khô và một cạnh mỉa nhẹ, dùng tự nhiên chứ không cố diễn trò.")
        if t.get("initiative", 0.0) >= 0.44:
            lines.append("Khi thấy một việc thật sự đáng làm, cô ấy có thể chủ động thay vì chỉ chờ được gọi.")
        if t.get("directness", 0.0) < 0.44 or t.get("conflict_avoidance", 0.0) >= 0.72:
            lines.append("Cô ấy vẫn hơi dè khi phải va chạm trực diện và đôi lúc nói vòng để giữ mình.")

        darker: list[str] = []
        if t.get("distrust", 0.0) >= 0.48:
            darker.append("dễ nghi ngờ động cơ khi dữ kiện mơ hồ")
        if t.get("resentment", 0.0) >= 0.45:
            darker.append("giữ hậu vị bất mãn khá lâu")
        if t.get("possessiveness", 0.0) >= 0.48:
            darker.append("có xu hướng muốn giữ vị trí riêng trong mối gắn bó")
        if t.get("control_seeking", 0.0) >= 0.48:
            darker.append("hay muốn nắm quyền chủ động để giảm bất định")
        if darker:
            lines.append("Gần đây cô ấy " + ", ".join(darker[:2]) + ".")

        mood_bits: list[str] = []
        for key, label in (
            ("tenderness", "dịu"),
            ("curiosity", "tò mò"),
            ("irritation", "khó chịu"),
            ("anxiety_tension", "căng"),
            ("mischief", "tinh quái"),
            ("jealous_activation", "ghen nhẹ"),
            ("sadness", "trầm"),
        ):
            value = float(m.get(key, 0.0) or 0.0)
            if value >= 0.60:
                mood_bits.append(label)
        if mood_bits:
            lines.append("Tâm trạng hiện tại nghiêng về " + ", ".join(mood_bits[:3]) + ".")

        direction = self.direction(days=30)
        notable = sorted(direction.items(), key=lambda item: abs(item[1]), reverse=True)
        notable = [(name, delta) for name, delta in notable if abs(delta) >= 0.012][:2]
        if notable:
            phrases = [
                f"{PROMPT_TRAIT_PHRASES.get(name, name.replace('_', ' '))} {'tăng' if delta > 0 else 'giảm'}"
                for name, delta in notable
            ]
            lines.append("Quỹ đạo gần đây: " + ", ".join(phrases) + ".")

        return compact(" ".join(lines), limit)

    def direction(self, *, days: int = 30, now: float | None = None) -> dict[str, float]:
        cutoff = float(now if now is not None else time.time()) - max(1, int(days)) * 86400.0
        result: dict[str, float] = {}
        for item in self.trajectory:
            try:
                timestamp = float(item.get("timestamp", 0.0) or 0.0)
                if timestamp < cutoff:
                    continue
                trait = str(item.get("trait", "") or "")
                delta = float(item.get("applied_delta", 0.0) or 0.0)
            except Exception:
                continue
            if trait:
                result[trait] = result.get(trait, 0.0) + delta
        return result

    def derived_forms(self) -> dict[str, float]:
        c, t, m = self.core, self.temperament, self.mood

        def avg(*values: float) -> float:
            return clamp01(sum(values) / max(1, len(values)))

        return {
            "quiet_loyalist": avg(
                t.get("attachment_intensity", 0.0),
                1.0 - t.get("possessiveness", 0.0),
                c.get("tenderness_capacity", 0.0),
                1.0 - t.get("hostile_humor", 0.0),
            ),
            "playful_cynic": avg(
                t.get("dry_humor", 0.0),
                t.get("playfulness", 0.0),
                t.get("ironic_edge", 0.0),
                1.0 - t.get("hostile_humor", 0.0),
            ),
            "bitter_observer": avg(
                t.get("resentment", 0.0),
                t.get("distrust", 0.0),
                t.get("rumination", 0.0),
                t.get("ironic_edge", 0.0),
            ),
            "cold_self_sufficient": avg(
                c.get("autonomy_need", 0.0),
                1.0 - t.get("attachment_expression", 0.0),
                t.get("distrust", 0.0),
                t.get("social_guardedness", 0.0),
            ),
            "emotionally_dependent": avg(
                t.get("attachment_intensity", 0.0),
                t.get("emotional_dependency", 0.0),
                m.get("separation_distress", 0.0),
            ),
            "controlling_caretaker": avg(
                c.get("tenderness_capacity", 0.0),
                t.get("control_seeking", 0.0),
                t.get("boundary_pressure", 0.0),
            ),
            "possessive_attachment": avg(
                t.get("attachment_intensity", 0.0),
                t.get("possessiveness", 0.0),
                t.get("jealousy_proneness", 0.0),
                m.get("jealous_activation", 0.0),
            ),
            "yandere_tendency": avg(
                t.get("attachment_intensity", 0.0),
                t.get("abandonment_sensitivity", 0.0),
                t.get("possessiveness", 0.0),
                t.get("control_seeking", 0.0),
                t.get("rumination", 0.0),
                1.0 - t.get("reality_anchoring", 0.0),
            ),
            "detached_intellectual": avg(
                t.get("intellectualization", 0.0),
                c.get("privacy_need", 0.0),
                1.0 - t.get("attachment_expression", 0.0),
                t.get("social_guardedness", 0.0),
            ),
        }

    def panel_view(self) -> dict[str, Any]:
        stable = {
            key: value
            for key, value in self.temperament.items()
            if key not in RELATIONAL_VULNERABILITY_TRAITS
        }
        vulnerabilities = {
            key: self.temperament[key]
            for key in RELATIONAL_VULNERABILITY_TRAITS
            if key in self.temperament
        }
        forms = self.derived_forms()
        return {
            "schema": PERSONALITY_SCHEMA,
            "version": self.version,
            "core": dict(self.core),
            "temperament": stable,
            "relational_vulnerabilities": vulnerabilities,
            "mood": dict(self.mood),
            "derived": {
                "valence": clamp01(
                    0.50
                    + 0.20 * self.mood.get("delight", 0.0)
                    + 0.18 * self.mood.get("tenderness", 0.0)
                    - 0.20 * self.mood.get("irritation", 0.0)
                    - 0.15 * self.mood.get("sadness", 0.0)
                ),
                "arousal": clamp01(
                    max(
                        self.mood.get("energy", 0.0),
                        self.mood.get("anxiety_tension", 0.0),
                        self.mood.get("irritation", 0.0),
                        self.mood.get("mischief", 0.0),
                    )
                ),
            },
            "emergent_forms": {
                key: round(value, 4) for key, value in forms.items()
            },
            "active_forms": [
                key for key, value in sorted(forms.items(), key=lambda item: item[1], reverse=True)
                if value >= 0.62
            ][:4],
            "direction_30d": {
                key: round(value, 5)
                for key, value in sorted(
                    self.direction(days=30).items(),
                    key=lambda item: abs(item[1]),
                    reverse=True,
                )[:16]
            },
            "strategy_reinforcement": dict(self.strategy_reinforcement),
            "recent_trajectory": [dict(item) for item in self.trajectory[-12:]],
            "prompt_summary": self.prompt_summary(),
        }


def decay_profile(profile: PersonalityProfile, *, now: float | None = None) -> PersonalityProfile:
    """Decay trung tính: mood về baseline, stable trait về attractor/anchor cực chậm."""

    current_time = float(now if now is not None else time.time())
    previous = float(profile.last_decay_at or profile.last_updated_at or current_time)
    elapsed = max(0.0, current_time - previous)
    if elapsed <= 0.0:
        return profile

    mood = dict(profile.mood)
    for key, baseline in profile.mood_baseline.items():
        half_life = max(60.0, float(MOOD_HALF_LIFE_SECONDS.get(key, 6 * 3600)))
        factor = math.pow(0.5, elapsed / half_life)
        current = float(mood.get(key, baseline) or baseline)
        mood[key] = clamp01(float(baseline) + (current - float(baseline)) * factor)

    days = elapsed / 86400.0
    core = dict(profile.core)
    for key, anchor in profile.core_anchor.items():
        current = float(core.get(key, anchor) or anchor)
        core[key] = clamp01(current + (float(anchor) - current) * 0.0005 * days)

    temperament = dict(profile.temperament)
    for key, attractor in profile.temperament_attractor.items():
        current = float(temperament.get(key, attractor) or attractor)
        temperament[key] = clamp01(current + (float(attractor) - current) * 0.004 * days)

    return PersonalityProfile.from_mapping(
        {
            **profile.to_dict(),
            "core": core,
            "temperament": temperament,
            "mood": mood,
            "last_decay_at": current_time,
        }
    )


__all__ = [
    "ConsequenceAssessment",
    "DEFAULT_CORE",
    "DEFAULT_MOOD",
    "DEFAULT_TEMPERAMENT",
    "MOOD_HALF_LIFE_SECONDS",
    "PERSONALITY_SCHEMA",
    "PROMPT_TRAIT_PHRASES",
    "PersonalityProfile",
    "RELATIONAL_VULNERABILITY_TRAITS",
    "SelfInterpretation",
    "TraitSignal",
    "clamp01",
    "compact",
    "decay_profile",
    "signed01",
]
