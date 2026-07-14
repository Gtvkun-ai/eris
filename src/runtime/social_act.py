from __future__ import annotations

"""Phân loại hành động hội thoại xã hội của ERIS.

Module này cố tình chỉ làm một việc: đọc *hành vi hội thoại* của lượt user.
Nó không sinh câu trả lời, không ghi memory và không tự gọi model. Nhờ vậy Qwen
vẫn giữ quyền viết câu, còn runtime thôi giả vờ rằng mọi câu đều chỉ là text thô.
"""

import re
import unicodedata
from enum import Enum
from typing import Any, Iterable


class ChatAct(Enum):
    """Taxonomy chung cho chat thường và social policy."""

    DIRECT_QUESTION = "direct_question"
    INSULT_PROVOCATION = "insult_provocation"
    IDENTITY_REDUCTION = "identity_reduction"
    COMMAND_STYLE = "command_style"
    NORMAL_CHAT = "normal_chat"

    # Nhóm hành động xã hội mới theo báo cáo cải tổ dài hạn.
    PLAYFUL_INTERACTION_REQUEST = "playful_interaction_request"
    TEASE_REQUEST = "tease_request"
    INITIATE_INTERACTION = "initiate_interaction"
    GRANT_RELATIONAL_PERMISSION = "grant_relational_permission"
    REVOKE_RELATIONAL_PERMISSION = "revoke_relational_permission"
    META_SOCIAL_BOUNDARY = "meta_social_boundary"


SOCIAL_ACTS = frozenset(
    {
        ChatAct.PLAYFUL_INTERACTION_REQUEST,
        ChatAct.TEASE_REQUEST,
        ChatAct.INITIATE_INTERACTION,
        ChatAct.GRANT_RELATIONAL_PERMISSION,
        ChatAct.REVOKE_RELATIONAL_PERMISSION,
        ChatAct.META_SOCIAL_BOUNDARY,
    }
)

PERFORM_NOW_ACTS = frozenset(
    {
        ChatAct.PLAYFUL_INTERACTION_REQUEST,
        ChatAct.TEASE_REQUEST,
        ChatAct.INITIATE_INTERACTION,
    }
)


def normalize_vi_ascii(text: str) -> str:
    """Chuẩn hoá nhẹ để regex không phải nhân đôi mọi dấu tiếng Việt."""

    normalized = unicodedata.normalize("NFD", str(text or ""))
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "D")
    normalized = re.sub(r"[^\w\s?]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized.lower()).strip()


def _state_active(state: Any, now: float | None = None) -> bool:
    if state is None:
        return False
    checker = getattr(state, "is_active", None)
    if callable(checker):
        try:
            return bool(checker(now=now))
        except TypeError:
            try:
                return bool(checker(now))
            except TypeError:
                return bool(checker())
        except Exception:
            return False
    return bool(getattr(state, "active", False))


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


_REVOKE_PATTERNS = (
    r"\b(?:thoi|dung|ngung)\s+(?:treu|ca khia|choc|lam phien|chu dong)\b",
    r"\bdung\s+(?:treu|ca khia|choc|lam phien)\s+(?:toi|ta|nua)?\b",
    r"\bkhong\s+duoc\s+(?:treu|ca khia|choc|lam phien|chu dong)\b",
    r"\bdung\s+lam\s+phien\b",
    r"\bde\s+toi\s+yen\b",
)

_META_BOUNDARY_PATTERNS = (
    r"\branh gioi\b",
    r"\btoi muc nao\b",
    r"\bduoc phep .* (?:treu|lam phien|chu dong).*(?:khong|ha|a)\b",
    r"\bco duoc .* (?:treu|lam phien|chu dong)\b",
    r"\bnen treu .* the nao\b",
)

_GRANT_PATTERNS = (
    r"\btoi\s+cho\s+phep\b",
    r"\bta\s+cho\s+phep\b",
    r"\b(?:em|eris|ban)\s+duoc\s+phep\b",
    r"\b(?:em|eris|ban)\s+co\s+the\s+chu\s+dong\b",
    r"\bduoc\s+quyen\s+(?:treu|ca khia|choc|lam phien|chu dong)\b",
    r"\bcu\s+(?:treu|ca khia|choc|lam phien|chu dong)\b",
    r"\bcho\s+phep\s+(?:em|eris|ban)?\s*(?:treu|ca khia|choc|lam phien|chu dong)\b",
)

_TEASE_PATTERNS = (
    r"\btreu\s+nhe(?:\s+(?:thoi|di|xem))?\b",
    r"\bca\s+khia\s+nhe(?:\s+(?:thoi|di|xem))?\b",
    r"\btreu\s+(?:toi|ta)\s+(?:di|thu|xem)\b",
    r"\bca\s+khia\s+(?:toi|ta)\s+(?:di|thu|xem)\b",
    r"\bchoc\s+(?:toi|ta)\s+(?:di|thu|xem)\b",
    r"\btreu\s+(?:di|thu|xem)\b",
    r"\bca\s+khia\s+(?:di|thu|xem)\b",
)

_PLAYFUL_PATTERNS = (
    r"\blam\s+phien\s+(?:toi\s+)?(?:di|thu|xem)\b",
    r"\bpha\s+tro\s+(?:di|thu|xem)\b",
    r"\bquay\s+(?:toi\s+)?(?:di|thu|xem)\b",
    r"\bchoc\s+gheo\s+(?:toi\s+)?(?:di|thu|xem)\b",
)

_INITIATE_PATTERNS = (
    r"\bchu\s+dong\s+(?:di|len|thu|xem)\b",
    r"\btu\s+bat\s+chuyen\s+(?:di|thu|xem)\b",
    r"\btu\s+noi\s+chuyen\s+(?:di|thu|xem)\b",
    r"\b(?:gio|bat dau)\s+(?:lam phien|treu|ca khia|choc|chu dong)\b",
)


def classify_chat_act_with_confidence(
    raw_user_text: str,
    *,
    history: Iterable[str] = (),
    state: Any = None,
    now: float | None = None,
) -> tuple[ChatAct, float]:
    """Phân loại theo thứ tự ưu tiên: boundary trước, literal question sau.

    ``history`` hiện chỉ dùng làm tín hiệu dự phòng nhẹ. Ta không nhét cả lịch sử
    vào regex, vì đó là cách rất nhanh để biến classifier thành bãi lầy token.
    """

    normalized = normalize_vi_ascii(raw_user_text)
    if not normalized:
        return ChatAct.NORMAL_CHAT, 0.55

    if _matches_any(normalized, _REVOKE_PATTERNS):
        return ChatAct.REVOKE_RELATIONAL_PERMISSION, 0.98

    if _matches_any(normalized, _META_BOUNDARY_PATTERNS):
        return ChatAct.META_SOCIAL_BOUNDARY, 0.91

    if _matches_any(normalized, _GRANT_PATTERNS):
        return ChatAct.GRANT_RELATIONAL_PERMISSION, 0.97

    active_permission = _state_active(state, now=now)

    if _matches_any(normalized, _TEASE_PATTERNS):
        return ChatAct.TEASE_REQUEST, 0.95

    if _matches_any(normalized, _INITIATE_PATTERNS):
        return ChatAct.INITIATE_INTERACTION, 0.93 if active_permission else 0.88

    if _matches_any(normalized, _PLAYFUL_PATTERNS):
        if active_permission and any(marker in normalized for marker in ("gio", "bat dau")):
            return ChatAct.INITIATE_INTERACTION, 0.92
        return ChatAct.PLAYFUL_INTERACTION_REQUEST, 0.94

    # Contextual override: permission đang mở + câu imperative rất ngắn.
    if active_permission:
        imperative = any(marker in normalized for marker in ("gio", "di", "thu di", "bat dau"))
        social_verb = any(marker in normalized for marker in ("lam phien", "treu", "ca khia", "choc", "chu dong"))
        if imperative and social_verb:
            return ChatAct.INITIATE_INTERACTION, 0.84

    insult_patterns = (
        "do ngu", "may ngu", "ban ngu", "eris ngu", "ngu vcl", "ngu vai",
        "oc cho", "do dien", "do dan", "dan do", "vo dung", "phe vat",
        "rac ruoi", "nhu cut", "nhu cc", "con cac", "stupid", "idiot",
        "dumb", "useless", "trash",
    )
    if any(pattern in normalized for pattern in insult_patterns):
        return ChatAct.INSULT_PROVOCATION, 0.96

    identity_reduction_patterns = (
        "chi la cong cu", "chi la tool", "chi la toy", "chi la script",
        "chi la bot", "may la cong cu", "ban la cong cu", "do choi",
        "gimmick", "waifu",
    )
    identity_reduction_regexes = (
        r"\b(?:eris|ban|may)?\s*(?:chi\s+la\s+(?:con\s+)?(?:bot|tool|toy|script|cong\s+cu|do\s+choi|gimmick))\b",
        r"\b(?:eris|ban|may)\s+la\s+(?:cong\s+cu|tool|toy|script|bot|do\s+choi|gimmick)\b",
    )
    if any(pattern in normalized for pattern in identity_reduction_patterns) or any(
        re.search(pattern, normalized) for pattern in identity_reduction_regexes
    ):
        return ChatAct.IDENTITY_REDUCTION, 0.94

    if "?" in str(raw_user_text or ""):
        return ChatAct.DIRECT_QUESTION, 0.82

    question_phrases = (
        "ban la ai", "ban nghi", "eris nghi", "nghi toi dang", "toi dang xem gi",
        "toi dang lam gi", "dang xem gi", "dang lam gi", "co phai", "la gi",
        "tai sao", "the nao", "vi sao",
    )
    if any(phrase in normalized for phrase in question_phrases):
        return ChatAct.DIRECT_QUESTION, 0.80

    command_markers = (
        "hay ", "lam ", "viet ", "sua ", "fix ", "tao ", "mo ", "chay ",
        "kiem tra ", "giai thich ",
    )
    if any(normalized.startswith(marker) for marker in command_markers):
        return ChatAct.COMMAND_STYLE, 0.78

    # Một ít lịch sử chỉ giúp nâng confidence cho chat thường, không đổi act.
    history_present = any(str(item or "").strip() for item in history)
    return ChatAct.NORMAL_CHAT, 0.62 if history_present else 0.58


def classify_chat_act(
    raw_user_text: str,
    history: Iterable[str] = (),
    state: Any = None,
    now: float | None = None,
) -> ChatAct:
    return classify_chat_act_with_confidence(raw_user_text, history=history, state=state, now=now)[0]


def is_social_act(act: ChatAct | str) -> bool:
    try:
        value = act if isinstance(act, ChatAct) else ChatAct(str(act))
    except Exception:
        return False
    return value in SOCIAL_ACTS


def should_exclude_from_persistent_memory(text: str) -> bool:
    """Chặn permission/session-boundary bị ghi thành fact lâu dài.

    Chỉ chặn khi chính lượt đó được nhận diện rõ là grant/revoke/initiation xã hội.
    Một câu như "tôi thích được trêu" không khớp grant và vẫn có thể đi qua policy
    preference bình thường. Máy móc cũng nên biết phân biệt sở thích với giấy phép.
    """

    act, confidence = classify_chat_act_with_confidence(text)
    if confidence < 0.84:
        return False
    return act in {
        ChatAct.PLAYFUL_INTERACTION_REQUEST,
        ChatAct.TEASE_REQUEST,
        ChatAct.GRANT_RELATIONAL_PERMISSION,
        ChatAct.REVOKE_RELATIONAL_PERMISSION,
        ChatAct.INITIATE_INTERACTION,
        ChatAct.META_SOCIAL_BOUNDARY,
    }


__all__ = [
    "ChatAct",
    "SOCIAL_ACTS",
    "PERFORM_NOW_ACTS",
    "classify_chat_act",
    "classify_chat_act_with_confidence",
    "is_social_act",
    "normalize_vi_ascii",
    "should_exclude_from_persistent_memory",
]
