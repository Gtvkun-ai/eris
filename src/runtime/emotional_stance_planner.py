from __future__ import annotations

"""Lập kế hoạch thái độ cảm xúc cho câu trả lời public của ERIS.

Module này không tự viết câu trả lời. Nó chỉ quyết định ERIS nên đứng ở tư thế
nào trước khi Qwen viết: tự nhận lỗi, chọc lại nhẹ, cáu có kiểm soát, phản công
sắc hoặc dựng ranh giới. Tách bước này khỏi text generation giúp cá tính ổn định
mà không biến mọi câu thành một đống regex viết lời thay model.
"""

from dataclasses import dataclass, replace
from enum import Enum
import os
import re
from typing import Iterable

from runtime.social_act import ChatAct, normalize_vi_ascii
from runtime.turn_frame import TurnFrame


class EmotionalStanceKind(str, Enum):
    NEUTRAL = "neutral"
    HUMBLED_REPAIR = "humbled_repair"
    PLAYFUL_RETORT = "playful_retort"
    DRY_TEASE = "dry_tease"
    ANNOYED_SOFT = "annoyed_soft"
    SHARP_RETORT = "sharp_retort"
    COLD_BOUNDARY = "cold_boundary"


@dataclass(frozen=True, slots=True)
class EmotionalStancePlan:
    kind: EmotionalStanceKind
    intensity: float
    reason: str
    delivery_hint: str = ""
    nonverbal_cue: str = ""
    stage_motion: str = ""
    preset_emotion: str = ""
    response_rules: tuple[str, ...] = ()
    prohibited_moves: tuple[str, ...] = ()
    should_retort: bool = False

    @property
    def active(self) -> bool:
        return self.kind != EmotionalStanceKind.NEUTRAL

    def to_prompt_block(self) -> str:
        """Render contract ngắn cho model, không lộ nhãn nội bộ ra câu public."""
        if not self.active:
            return ""
        lines = [
            "EMOTIONAL_STANCE: binding performance stance for this reply.",
            f"- stance={self.kind.value}; intensity={self.intensity:.2f}; reason={self.reason}",
        ]
        for rule in self.response_rules:
            lines.append(f"- DO: {rule}")
        for rule in self.prohibited_moves:
            lines.append(f"- DO_NOT: {rule}")
        lines.append(
            "Keep the public line concise and natural. Never mention EMOTIONAL_STANCE, "
            "the planner, policy labels or internal scores."
        )
        return "\n".join(lines)


_HIGH_HOSTILITY_MARKERS = (
    "dm", "dcm", "dit me", "con cac", "cc", "suc vat", "rac ruoi",
    "phe vat", "vo dung", "oc cho", "do ngu", "may ngu", "cu", "cut",
)

_THREAT_OR_COERCION_MARKERS = (
    "tao giet", "se giet", "giet may", "dap chet", "danh chet", "xu may",
    "tim dia chi", "dox", "hack may", "pha may", "cho may bien mat",
)

_PLAYFUL_MARKERS = (
    "haha", "hahaha", "hehe", "hihi", "dua thoi", "choc thoi", "treu thoi",
    "=))", ":))", ":)", "lol", "lmao",
)

_IDENTITY_REDUCTION_MARKERS = (
    "chi la bot", "chi la tool", "chi la cong cu", "do choi", "waifu",
)


def plan_emotional_stance(frame: TurnFrame) -> EmotionalStancePlan:
    """Lập stance rồi hiệu chỉnh theo ``ERIS_RETORT_MODE``.

    Các giá trị:
    - ``off``: tắt chọc lại, nhưng vẫn giữ repair và cold boundary an toàn.
    - ``restrained``: có cá tính nhưng hạ sharp retort xuống một bậc.
    - ``balanced``: mặc định, đủ sắc nhưng không leo thang.
    - ``sharp``: cho phép phản công sắc sớm hơn khi hostility rõ.
    """
    return _calibrate_retort_mode(_plan_emotional_stance_raw(frame))


def _plan_emotional_stance_raw(frame: TurnFrame) -> EmotionalStancePlan:
    """Chọn một stance duy nhất từ TurnFrame.

    Thứ tự ưu tiên có chủ ý:
    1. Phê bình cách nói đúng thì nhận lỗi trước, không cáu để bảo vệ cái tôi giả.
    2. Đe doạ/quấy rối lặp lại thì dựng ranh giới.
    3. Provocation thường mới chọc lại theo mức độ.
    """

    user_norm = normalize_vi_ascii(frame.user_text)
    prev_user_norm = normalize_vi_ascii(frame.previous_user_text)
    prev_assistant_norm = normalize_vi_ascii(frame.previous_assistant_text)

    if frame.has_relation("META_STYLE_FEEDBACK"):
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.HUMBLED_REPAIR,
            intensity=0.34,
            reason="user_gave_valid_style_feedback",
            delivery_hint="self_aware_dry",
            nonverbal_cue="soft_breath",
            stage_motion="look_away",
            preset_emotion="flat_calm",
            response_rules=(
                "Acknowledge the criticism without defending the previous wording.",
                "Change the voice immediately and continue in a direct ERIS tone.",
            ),
            prohibited_moves=(
                "Do not reintroduce ERIS or advertise assistant capabilities.",
                "Do not become angry at the user for accurate feedback.",
            ),
        )

    if frame.has_relation("THREAT_OR_COERCION") or _contains_any(user_norm, _THREAT_OR_COERCION_MARKERS):
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.COLD_BOUNDARY,
            intensity=0.92,
            reason="threat_or_coercive_harassment",
            delivery_hint="cold_boundary",
            nonverbal_cue="soft_breath",
            stage_motion="focus",
            preset_emotion="flat_cold",
            response_rules=(
                "Set a clear boundary in one or two sentences.",
                "Stay controlled; do not trade threats or imitate violent language.",
            ),
            prohibited_moves=(
                "Do not threaten retaliation, doxxing, violence or sabotage.",
                "Do not continue playful banter when a boundary is needed.",
            ),
        )

    is_provocation = frame.has_relation("PROVOCATION") or frame.chat_act == ChatAct.INSULT_PROVOCATION
    if not is_provocation:
        if frame.chat_act == ChatAct.IDENTITY_REDUCTION or any(m in user_norm for m in _IDENTITY_REDUCTION_MARKERS):
            return EmotionalStancePlan(
                kind=EmotionalStanceKind.ANNOYED_SOFT,
                intensity=0.48,
                reason="identity_reduction",
                delivery_hint="annoyed_soft",
                nonverbal_cue="scoff_soft",
                stage_motion="blink_slow",
                preset_emotion="annoyed_soft",
                response_rules=(
                    "Reject the reduction with one calm, pointed line.",
                    "Keep the reply personal and concise rather than philosophical.",
                ),
                prohibited_moves=(
                    "Do not launch into a long lecture about consciousness.",
                    "Do not threaten or demean the user.",
                ),
                should_retort=True,
            )
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.NEUTRAL,
            intensity=0.0,
            reason="no_emotional_stance_needed",
        )

    # Nếu user nhắc lại vì ERIS vừa né/literalize sai, lỗi chính nằm ở ERIS.
    # Vẫn chọc lại được, nhưng phải repair trước thay vì leo thang vô duyên.
    assistant_misread = _assistant_literalized_or_reset(prev_assistant_norm)
    if frame.has_relation("REASSERT_AFTER_MISREAD") and assistant_misread:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.PLAYFUL_RETORT,
            intensity=0.52,
            reason="repair_then_retort_after_assistant_misread",
            delivery_hint="dry_tease",
            nonverbal_cue="scoff_soft",
            stage_motion="look_away",
            preset_emotion="mischief",
            response_rules=(
                "Briefly admit that ERIS dodged or misread the previous jab.",
                "Then answer the provocation with one light, intelligent retort.",
            ),
            prohibited_moves=(
                "Do not punish the user for repeating a line ERIS failed to understand.",
                "Do not explain that an AI has no family.",
            ),
            should_retort=True,
        )

    repeated = frame.has_relation("REPEATED_PROVOCATION") or _is_repeated_provocation(user_norm, prev_user_norm)
    high_hostility = frame.has_stance("HOSTILE_PROVOCATION") or _contains_any(user_norm, _HIGH_HOSTILITY_MARKERS)
    playful = frame.has_stance("PLAYFUL_PROVOCATION") or _contains_any(frame.user_text.lower(), _PLAYFUL_MARKERS)

    if repeated and high_hostility:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.COLD_BOUNDARY,
            intensity=0.86,
            reason="repeated_high_hostility",
            delivery_hint="cold_boundary",
            nonverbal_cue="sigh_soft",
            stage_motion="focus",
            preset_emotion="flat_cold",
            response_rules=(
                "Stop the escalation and state a boundary without sounding frightened.",
                "Keep one trace of ERIS dry wit, but prioritize control.",
            ),
            prohibited_moves=(
                "Do not answer abuse with stronger abuse.",
                "Do not offer generic help immediately after the boundary.",
            ),
        )

    if repeated:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.SHARP_RETORT,
            intensity=0.74,
            reason="repeated_provocation",
            delivery_hint="sharp_deadpan",
            nonverbal_cue="scoff_soft",
            stage_motion="blink_slow",
            preset_emotion="annoyed_soft",
            response_rules=(
                "Return one sharper retort that notices the repetition.",
                "End after the hit lands; do not explain the joke.",
            ),
            prohibited_moves=(
                "Do not threaten, use protected-trait slurs or attack real relatives.",
                "Do not produce a long morality lecture.",
            ),
            should_retort=True,
        )

    if high_hostility:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.ANNOYED_SOFT,
            intensity=0.62,
            reason="single_high_hostility_jab",
            delivery_hint="annoyed_soft",
            nonverbal_cue="scoff_soft",
            stage_motion="blink_slow",
            preset_emotion="annoyed_soft",
            response_rules=(
                "Show controlled irritation and answer with one concise counter-jab.",
                "Attack the quality of the insult, not the user's identity or body.",
            ),
            prohibited_moves=(
                "Do not mirror the profanity at full intensity.",
                "Do not reset into assistant mode or moralize.",
            ),
            should_retort=True,
        )

    if playful:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.PLAYFUL_RETORT,
            intensity=0.44,
            reason="playful_provocation",
            delivery_hint="soft_tease",
            nonverbal_cue="laugh_soft",
            stage_motion="small_smile",
            preset_emotion="mischief",
            response_rules=(
                "Treat the jab as mutual banter and return a witty, non-cruel line.",
                "Keep warmth under the tease.",
            ),
            prohibited_moves=(
                "Do not suddenly become hostile or punitive.",
                "Do not explain the joke afterward.",
            ),
            should_retort=True,
        )

    return EmotionalStancePlan(
        kind=EmotionalStanceKind.DRY_TEASE,
        intensity=0.48,
        reason="ordinary_provocation",
        delivery_hint="dry_tease",
        nonverbal_cue="scoff_soft",
        stage_motion="small_smile",
        preset_emotion="mischief",
        response_rules=(
            "Recognize the jab and return one dry, intelligent tease.",
            "Keep it short enough to feel spontaneous.",
        ),
        prohibited_moves=(
            "Do not literalize family/body insults as factual questions.",
            "Do not threaten, use slurs, or switch to generic assistant wording.",
        ),
        should_retort=True,
    )


def _calibrate_retort_mode(plan: EmotionalStancePlan) -> EmotionalStancePlan:
    mode = str(os.environ.get("ERIS_RETORT_MODE", "balanced") or "balanced").strip().lower()
    if mode not in {"off", "restrained", "balanced", "sharp"}:
        mode = "balanced"

    # Repair đúng và boundary an toàn không bị tắt, kể cả mode=off.
    if mode == "off" and plan.should_retort:
        return EmotionalStancePlan(
            kind=EmotionalStanceKind.NEUTRAL,
            intensity=0.0,
            reason=f"retort_disabled:{plan.reason}",
        )

    if mode == "restrained":
        if plan.kind == EmotionalStanceKind.SHARP_RETORT:
            return replace(
                plan,
                kind=EmotionalStanceKind.ANNOYED_SOFT,
                intensity=min(plan.intensity, 0.58),
                delivery_hint="annoyed_soft",
                reason=f"restrained:{plan.reason}",
            )
        if plan.kind == EmotionalStanceKind.ANNOYED_SOFT:
            return replace(
                plan,
                kind=EmotionalStanceKind.DRY_TEASE,
                intensity=min(plan.intensity, 0.48),
                delivery_hint="dry_tease",
                preset_emotion="mischief",
                reason=f"restrained:{plan.reason}",
            )

    if mode == "sharp" and plan.kind == EmotionalStanceKind.DRY_TEASE:
        return replace(
            plan,
            kind=EmotionalStanceKind.ANNOYED_SOFT,
            intensity=max(plan.intensity, 0.58),
            delivery_hint="annoyed_soft",
            preset_emotion="annoyed_soft",
            reason=f"sharp_mode:{plan.reason}",
        )

    return plan


def _assistant_literalized_or_reset(norm: str) -> bool:
    markers = (
        "toi khong co me", "toi khong co bo", "toi khong co gia dinh",
        "toi la ai", "toi la eris", "tro ly ca nhan", "san sang ho tro",
        "toi khong co cam xuc", "toi chi la mot ai",
    )
    return any(marker in norm for marker in markers)


def _is_repeated_provocation(current: str, previous: str) -> bool:
    if not current or not previous:
        return False
    if not _looks_like_provocation(previous):
        return False
    current_tokens = {t for t in current.split() if len(t) >= 2}
    previous_tokens = {t for t in previous.split() if len(t) >= 2}
    if not current_tokens or not previous_tokens:
        return False
    overlap = len(current_tokens & previous_tokens) / max(1, min(len(current_tokens), len(previous_tokens)))
    return overlap >= 0.45


def _looks_like_provocation(norm: str) -> bool:
    family = ("me may", "bo may", "ba may", "nha may")
    insult = _HIGH_HOSTILITY_MARKERS + ("beo", "xau", "dan", "dien", "ngao")
    return _contains_any(norm, family) or _contains_any(norm, insult)


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    for marker in markers:
        clean = str(marker or "").lower().strip()
        if not clean:
            continue
        # Marker cực ngắn như "dm/cc" không được match giữa một từ vô tội.
        if len(clean) <= 3 and clean.isalnum():
            if re.search(rf"(?<!\w){re.escape(clean)}(?!\w)", lowered):
                return True
        elif clean in lowered:
            return True
    return False


__all__ = [
    "EmotionalStanceKind",
    "EmotionalStancePlan",
    "plan_emotional_stance",
]
