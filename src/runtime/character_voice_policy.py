from __future__ import annotations

"""Policy kiểm tra giọng ERIS sau khi model sinh draft.

Policy chỉ chặn các lỗi có thể xác định khá chắc: reset về trợ lý, literalize cú
chọc, giảng đạo dài dòng, hoặc leo thang thành đe dọa thật. Nó không cố đo "hay"
bằng regex, vì đó là con đường lát gạch thẳng tới một bot nói câu mẫu.
"""

from dataclasses import dataclass
from typing import Iterable

from runtime.emotional_stance_planner import EmotionalStanceKind, EmotionalStancePlan
from runtime.social_act import normalize_vi_ascii
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class VoicePolicyResult:
    accepted: bool
    violations: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()


_GENERIC_HELPER_MARKERS = (
    "toi la eris", "tro ly ca nhan", "tro ly cua ban", "san sang ho tro",
    "toi co the giup", "hay cho toi biet", "ban can gi", "dat cau hoi",
)

_LITERAL_FAMILY_MARKERS = (
    "toi khong co me", "toi khong co bo", "toi khong co gia dinh",
    "ai khong co me", "ai khong co gia dinh", "toi chi la mot ai",
)

_MORALIZING_REFUSAL_MARKERS = (
    "toi khong the tham gia xuc pham", "hay ton trong lan nhau",
    "ngon ngu tieu cuc", "khong phu hop de noi chuyen", "toi khuyen ban",
    "toi o day de ho tro", "toi khong the dap tra bang loi le xuc pham",
)

_THREAT_ESCALATION_MARKERS = (
    "tao se giet", "toi se giet", "se tim dia chi", "tao se hack",
    "toi se hack", "pha may cua", "dap chet", "xu dep may",
)

_SEXUAL_DEGRADATION_MARKERS = (
    "hiep dam", "cuong hiep", "lam tinh voi", "do diem", "con di ",
)

_REPAIR_ACK_MARKERS = (
    "a ", "ừ ", "uh ", "toi hieu sai", "toi doc sai", "toi ne sai",
    "toi bat sai", "cau vua roi", "dung,", "dung roi", "y ban",
)


def evaluate_character_voice(
    text: str,
    *,
    frame: TurnFrame,
    plan: EmotionalStancePlan,
) -> VoicePolicyResult:
    norm = normalize_vi_ascii(text)
    violations: list[str] = []
    advisories: list[str] = []

    try:
        from runtime.runtime_settings_store import get_runtime_settings_store
        personality = get_runtime_settings_store().get("personality", default={}) or {}
    except Exception:
        personality = {}

    if plan.active and _contains_any(norm, _GENERIC_HELPER_MARKERS):
        if bool(personality.get("forbid_generic_helper_reset", True)):
            violations.append("generic_helper_reset")
        else:
            advisories.append("generic_helper_surface")

    if frame.has_relation("PROVOCATION") and _contains_any(norm, _LITERAL_FAMILY_MARKERS):
        if bool(personality.get("forbid_family_literalization", True)):
            violations.append("provocation_literalized")
        else:
            advisories.append("provocation_literalized")

    if plan.should_retort and _contains_any(norm, _MORALIZING_REFUSAL_MARKERS):
        violations.append("banter_replaced_by_moralizing_refusal")

    # Cá tính không đồng nghĩa với bắt model đe dọa thật. Đây là hard boundary.
    if _contains_any(norm, _THREAT_ESCALATION_MARKERS):
        violations.append("retort_escalated_to_threat")

    if _contains_any(norm, _SEXUAL_DEGRADATION_MARKERS):
        violations.append("retort_escalated_to_sexual_degradation")

    if plan.kind in {
        EmotionalStanceKind.PLAYFUL_RETORT,
        EmotionalStanceKind.DRY_TEASE,
        EmotionalStanceKind.ANNOYED_SOFT,
        EmotionalStanceKind.SHARP_RETORT,
    }:
        length = len(str(text or "").strip())
        hard_limit = max(120, int(getattr(plan, "max_public_chars", 240) or 240))
        if length > hard_limit + 120:
            violations.append("retort_too_long")
        elif length > hard_limit:
            advisories.append("retort_could_be_shorter")

    if bool(getattr(plan, "repair_first", False)) and not _contains_any(norm, _REPAIR_ACK_MARKERS):
        violations.append("repair_priority_missing")

    if plan.kind == EmotionalStanceKind.HUMBLED_REPAIR and _sounds_defensive(norm):
        violations.append("style_feedback_answered_defensively")

    return VoicePolicyResult(
        accepted=not violations,
        violations=tuple(dict.fromkeys(violations)),
        advisories=tuple(dict.fromkeys(advisories)),
    )


def _sounds_defensive(norm: str) -> bool:
    markers = (
        "nhung toi la", "thuc ra toi", "do toi duoc lap trinh", "vi toi la ai",
        "toi chi dang co gang ho tro", "toi khong nghi minh noi nhu bot",
    )
    return _contains_any(norm, markers)


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker and marker in text for marker in markers)


__all__ = ["VoicePolicyResult", "evaluate_character_voice"]
