# -*- coding: utf-8 -*-
"""Projection duy nhất từ mood sống sang giọng public của ERIS.

V39 sửa một lỗi kiến trúc khá ngớ ngẩn nhưng dễ mắc: personality từng vô tình
được dùng như một *nhiệt độ giọng cố định* (ấm kín / lạnh / restrained). Trong
khi đó runtime đã có mood duy trì thật ở ``PersistentInternalState`` và mood
quỹ đạo trong ``PersonalityProfile``. Kết quả là state có thay đổi nhưng writer
lại bị prompt kéo về cùng một giọng nền.

Module này không tạo mood mới và không quyết định speak/silence. Nó chỉ chiếu
state đã tồn tại thành một ``AffectiveVoiceState`` dùng CHUNG cho direct chat
và autonomous Surface:

    mood sống + mood dài hạn + quan hệ + personality shape
                         ↓
                 AffectiveVoiceState
                    ↙            ↘
             direct chat       Surface

Nguyên tắc quan trọng:
- affect hiện tại quyết định hướng/cường độ cảm xúc;
- personality chỉ định hình cách biểu hiện (độ tự bộc lộ, directness, humor...);
- relationship điều biến bandwidth thân mật/trêu đùa;
- grounding/capability không bị nới bởi voice state.

Tracker chỉ giữ snapshot trước để tính trajectory biểu đạt. Nó không persistence
riêng xuống đĩa và không trở thành một mood system thứ ba.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


AFFECTIVE_VOICE_VERSION = "eris.affective_voice.v39.state_authority"


def _clamp01(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if number != number:
        number = float(default)
    return max(0.0, min(1.0, number))


def _signed(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if number != number:
        number = float(default)
    return max(-1.0, min(1.0, number))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _attr(state: object | None, name: str, default: float = 0.0) -> float:
    if state is None:
        return float(default)
    return _clamp01(getattr(state, name, default), default)


@dataclass(frozen=True, slots=True)
class AffectiveVoiceState:
    """Snapshot public-safe của state biểu đạt hiện tại.

    Không field nào là bằng chứng về thế giới bên ngoài hoặc trạng thái user.
    ``trajectory`` chỉ nói ERIS vừa đổi thế nào so với sample trước.
    """

    version: str = AFFECTIVE_VOICE_VERSION
    channel: str = "chat"
    sampled_at: float = 0.0

    # Affect sống. valence signed, còn lại 0..1.
    valence: float = 0.0
    arousal: float = 0.0
    curiosity: float = 0.0
    social_energy: float = 0.0
    attachment: float = 0.0
    tenderness: float = 0.0
    irritation: float = 0.0
    fatigue: float = 0.0
    delight: float = 0.0
    sadness: float = 0.0
    anxiety: float = 0.0
    playfulness: float = 0.0
    yearning: float = 0.0
    restraint: float = 0.0

    # Personality chỉ là shape, không phải affect target.
    disclosure_selectivity: float = 0.0
    social_guardedness: float = 0.0
    directness_trait: float = 0.0
    dry_humor_trait: float = 0.0
    playfulness_trait: float = 0.0

    # Relationship chỉ điều biến bandwidth biểu đạt.
    familiarity: float = 0.0
    closeness: float = 0.0
    playful_safety: float = 0.0
    boundary_safety: float = 0.0
    rupture: float = 0.0

    # Derived knobs để writer đọc dễ hơn; vẫn chỉ là voice, không là semantic authority.
    expressive_drive: float = 0.0
    affiliation: float = 0.0
    withdrawal: float = 0.0

    # Delta so với lần project trước của cùng runtime host.
    trajectory: Mapping[str, float] = field(default_factory=dict)
    trajectory_strength: float = 0.0
    stable_for_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trajectory"] = {
            str(key): round(float(value), 4)
            for key, value in self.trajectory.items()
        }
        for key, value in list(payload.items()):
            if isinstance(value, float):
                payload[key] = round(value, 4)
        return payload

    def prompt_context(self) -> str:
        """Render compact, dương tính và không gắn nhãn mood bằng adjective preset."""

        current = (
            f"valence={self.valence:+.2f}, arousal={self.arousal:.2f}, curiosity={self.curiosity:.2f}, "
            f"social_energy={self.social_energy:.2f}, delight={self.delight:.2f}, playfulness={self.playfulness:.2f}, "
            f"tenderness={self.tenderness:.2f}, attachment={self.attachment:.2f}, irritation={self.irritation:.2f}, "
            f"sadness={self.sadness:.2f}, anxiety={self.anxiety:.2f}, fatigue={self.fatigue:.2f}, restraint={self.restraint:.2f}"
        )
        shape = (
            f"disclosure_selectivity={self.disclosure_selectivity:.2f}, social_guardedness={self.social_guardedness:.2f}, "
            f"directness_trait={self.directness_trait:.2f}, dry_humor_trait={self.dry_humor_trait:.2f}, "
            f"playfulness_trait={self.playfulness_trait:.2f}"
        )
        relation = (
            f"familiarity={self.familiarity:.2f}, closeness={self.closeness:.2f}, "
            f"playful_safety={self.playful_safety:.2f}, boundary_safety={self.boundary_safety:.2f}, rupture={self.rupture:.2f}"
        )
        trajectory = ", ".join(
            f"{key}={value:+.2f}"
            for key, value in sorted(
                self.trajectory.items(), key=lambda item: abs(float(item[1])), reverse=True
            )[:5]
            if abs(float(value)) >= 0.01
        ) or "steady"
        return (
            f"AFFECTIVE_VOICE_STATE {self.version} channel={self.channel}. "
            f"Current affect: {current}. Personality shape: {shape}. Relationship bandwidth: {relation}. "
            f"Derived expression: expressive_drive={self.expressive_drive:.2f}, affiliation={self.affiliation:.2f}, "
            f"withdrawal={self.withdrawal:.2f}. Trajectory since previous sample: {trajectory}; "
            f"strength={self.trajectory_strength:.2f}; stable_for≈{self.stable_for_seconds:.0f}s. "
            "Affect hiện tại là authority cho hướng và cường độ cảm xúc trong lời nói. Personality chỉ định hình cadence, "
            "độ tự bộc lộ, directness và humor; không được kéo affect về một preset ấm/lạnh/điềm/restrained cố định. "
            "Nếu state đang vui/hứng thú thì cho phép câu sáng, nhanh hoặc playful hơn thật sự; nếu đang bực thì được có cạnh; "
            "nếu đang trầm/mệt thì được hạ năng lượng; nếu tò mò cao thì nhịp có thể mở và khám phá hơn. Không gọi tên mood một cách máy móc, "
            "không diễn quá tay, và tuyệt đối không dùng voice state làm bằng chứng về user hay môi trường."
        )


class AffectiveVoiceTracker:
    """Tracker nhẹ để direct chat và Surface nhìn cùng một trajectory.

    Không có policy speak/silence. Sample mới chỉ cập nhật history khi thời gian
    tiến đủ 0.25s, tránh retry cùng một turn tự biến thành trajectory giả.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_sample_at = 0.0
        self._last_values: dict[str, float] = {}
        self._stable_since = 0.0

    def project(
        self,
        *,
        internal_state: object | None,
        personality: object | None,
        relationship: object | None,
        channel: str,
        now: float | None = None,
    ) -> AffectiveVoiceState:
        current_time = float(now if now is not None else time.time())
        personality_mood = _mapping(getattr(personality, "mood", {}))
        temperament = _mapping(getattr(personality, "temperament", {}))

        valence = _signed(getattr(internal_state, "valence", 0.0) if internal_state is not None else 0.0)
        arousal = _attr(internal_state, "arousal", personality_mood.get("energy", 0.2))
        curiosity = _attr(internal_state, "curiosity", personality_mood.get("curiosity", 0.4))
        social_energy = _attr(internal_state, "social_energy", personality_mood.get("energy", 0.3))
        attachment = _attr(internal_state, "attachment", 0.0)
        tenderness_internal = _attr(internal_state, "tenderness", 0.0)
        irritation_internal = _attr(internal_state, "irritation", 0.0)
        fatigue = _attr(internal_state, "fatigue", 0.0)
        restraint = _attr(internal_state, "restraint_pressure", 0.0)
        playful_pressure = _attr(internal_state, "playful_pressure", 0.0)

        delight = _clamp01(personality_mood.get("delight", max(0.0, valence)))
        sadness = _clamp01(personality_mood.get("sadness", max(0.0, -valence)))
        anxiety = _clamp01(personality_mood.get("anxiety_tension", 0.0))
        mischief = _clamp01(personality_mood.get("mischief", 0.0))
        yearning = _clamp01(personality_mood.get("yearning", 0.0))
        tenderness = _clamp01(max(tenderness_internal, personality_mood.get("tenderness", 0.0)))
        irritation = _clamp01(max(irritation_internal, personality_mood.get("irritation", 0.0)))
        playfulness = _clamp01(mischief * 0.62 + playful_pressure * 0.38)

        disclosure_selectivity = _clamp01(temperament.get("self_disclosure_selectivity", 0.5))
        social_guardedness = _clamp01(temperament.get("social_guardedness", 0.5))
        directness_trait = _clamp01(temperament.get("directness", 0.5))
        dry_humor_trait = _clamp01(temperament.get("dry_humor", 0.0))
        playfulness_trait = _clamp01(temperament.get("playfulness", 0.0))

        familiarity = _clamp01(getattr(relationship, "familiarity", 0.0) if relationship is not None else 0.0)
        closeness = _clamp01(getattr(relationship, "closeness", 0.0) if relationship is not None else 0.0)
        playful_safety = _clamp01(getattr(relationship, "playful_safety", 0.0) if relationship is not None else 0.0)
        boundary_safety = _clamp01(getattr(relationship, "boundary_safety", 0.5) if relationship is not None else 0.5)
        rupture = _clamp01(getattr(relationship, "rupture", 0.0) if relationship is not None else 0.0)

        affiliation = _clamp01(tenderness * 0.42 + attachment * 0.34 + closeness * 0.14 + familiarity * 0.10)
        withdrawal = _clamp01(fatigue * 0.28 + sadness * 0.28 + restraint * 0.20 + anxiety * 0.14 + rupture * 0.10)
        expressive_drive = _clamp01(
            0.12
            + arousal * 0.20
            + social_energy * 0.18
            + delight * 0.16
            + playfulness * 0.12
            + curiosity * 0.12
            + affiliation * 0.10
            - restraint * 0.14
            - fatigue * 0.10
            - rupture * 0.08
        )

        values = {
            "valence": valence,
            "arousal": arousal,
            "curiosity": curiosity,
            "social_energy": social_energy,
            "delight": delight,
            "playfulness": playfulness,
            "tenderness": tenderness,
            "irritation": irritation,
            "sadness": sadness,
            "anxiety": anxiety,
            "fatigue": fatigue,
            "restraint": restraint,
            "affiliation": affiliation,
            "withdrawal": withdrawal,
            "expressive_drive": expressive_drive,
        }

        with self._lock:
            previous = dict(self._last_values)
            elapsed = max(0.0, current_time - float(self._last_sample_at or current_time))
            trajectory = {
                key: max(-1.0, min(1.0, value - float(previous.get(key, value))))
                for key, value in values.items()
            }
            strength = max((abs(value) for value in trajectory.values()), default=0.0)
            if self._stable_since <= 0.0:
                self._stable_since = current_time
            if strength >= 0.10:
                self._stable_since = current_time
            stable_for = max(0.0, current_time - self._stable_since)

            # Retry/cùng turn trong vài trăm ms không được tự tạo history giả.
            if not previous or elapsed >= 0.25:
                self._last_values = dict(values)
                self._last_sample_at = current_time

        return AffectiveVoiceState(
            channel=str(channel or "chat").strip().lower() or "chat",
            sampled_at=current_time,
            valence=valence,
            arousal=arousal,
            curiosity=curiosity,
            social_energy=social_energy,
            attachment=attachment,
            tenderness=tenderness,
            irritation=irritation,
            fatigue=fatigue,
            delight=delight,
            sadness=sadness,
            anxiety=anxiety,
            playfulness=playfulness,
            yearning=yearning,
            restraint=restraint,
            disclosure_selectivity=disclosure_selectivity,
            social_guardedness=social_guardedness,
            directness_trait=directness_trait,
            dry_humor_trait=dry_humor_trait,
            playfulness_trait=playfulness_trait,
            familiarity=familiarity,
            closeness=closeness,
            playful_safety=playful_safety,
            boundary_safety=boundary_safety,
            rupture=rupture,
            expressive_drive=expressive_drive,
            affiliation=affiliation,
            withdrawal=withdrawal,
            trajectory=trajectory,
            trajectory_strength=strength,
            stable_for_seconds=stable_for,
        )


def project_affective_voice_state(
    host: object,
    *,
    mind_state: object | None,
    channel: str,
    now: float | None = None,
) -> AffectiveVoiceState:
    """Project state từ host mà không tạo dependency vòng.

    ``host._get_internal_state`` là nguồn PersistentInternalState hiện hữu. Nếu
    một harness/test không có nó, projector vẫn dùng personality mood thay vì
    fail cả public writer.
    """

    tracker = getattr(host, "_affective_voice_tracker", None)
    if not isinstance(tracker, AffectiveVoiceTracker):
        tracker = AffectiveVoiceTracker()
        try:
            setattr(host, "_affective_voice_tracker", tracker)
        except Exception:
            pass

    internal_state = None
    getter = getattr(host, "_get_internal_state", None)
    if callable(getter):
        try:
            internal_state = getter()
        except Exception:
            internal_state = None

    personality = getattr(mind_state, "personality", None) if mind_state is not None else None
    relationship = getattr(mind_state, "relationship", None) if mind_state is not None else None
    return tracker.project(
        internal_state=internal_state,
        personality=personality,
        relationship=relationship,
        channel=channel,
        now=now,
    )


__all__ = [
    "AFFECTIVE_VOICE_VERSION",
    "AffectiveVoiceState",
    "AffectiveVoiceTracker",
    "project_affective_voice_state",
]
