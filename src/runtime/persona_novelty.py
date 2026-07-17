from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class PhraseFamily:
    name: str
    markers: tuple[str, ...]
    plain_alternative: str


# Đây không phải blacklist. Mỗi family chỉ bị làm nguội khi vừa xuất hiện dày,
# để Eris không biến một hình ảnh đẹp thành tem đóng trên mọi câu xã hội.
_FAMILIES = (
    PhraseFamily("rhythm", ("nhịp", "một nhịp"), "nói phản ứng cụ thể, ngắn và trực tiếp"),
    PhraseFamily("softness", ("dịu", "mềm đi"), "dùng hành động/cảm giác cụ thể thay cho tính từ mơ hồ"),
    PhraseFamily("presence", ("sự hiện diện", "ở đây với bạn"), "nói rõ điều Eris sẽ làm hoặc đã nhận ra"),
    PhraseFamily("silence", ("khoảng lặng", "im lặng"), "đừng trang trí mọi lượt bằng không khí thơ"),
    PhraseFamily("careful_bond", ("giữ cẩn thận", "xây dần", "chậm và thật"), "trả lời bằng một ý riêng của lượt hiện tại"),
)


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower().replace("đ", "d")
    return re.sub(r"\s+", " ", value).strip()


def build_phrase_novelty_hint(chat_history, *, limit: int = 8) -> str:
    """Tạo gợi ý cooldown cho các motif vừa bị dùng lặp.

    Chỉ đọc lời public của assistant. Hàm không sửa text sau generation, vì một
    guard tự làm nhà văn chính là thứ đã khiến pipeline cũ mất giọng.
    """

    assistant_texts = []
    for item in reversed(tuple(chat_history or ())):
        if not isinstance(item, dict) or bool(item.get("invalid")):
            continue
        if str(item.get("role", "") or "") != "assistant":
            continue
        text = str(item.get("content", "") or "").strip()
        if text:
            assistant_texts.append(_norm(text))
        if len(assistant_texts) >= limit:
            break

    if len(assistant_texts) < 2:
        return ""

    hits: Counter[str] = Counter()
    family_map = {family.name: family for family in _FAMILIES}
    for text in assistant_texts:
        for family in _FAMILIES:
            normalized_markers = tuple(_norm(marker) for marker in family.markers)
            if any(marker and marker in text for marker in normalized_markers):
                hits[family.name] += 1

    cooled = [family_map[name] for name, count in hits.items() if count >= 2]
    if not cooled:
        return ""

    lines = [
        "[PHRASE NOVELTY — soft cooldown]",
        "Các motif dưới đây vừa xuất hiện dày. Tránh dùng lại trong lượt này nếu không thật sự cần:",
    ]
    for family in cooled:
        lines.append(f"- {family.name}: {family.plain_alternative}.")
    lines.append("Ưu tiên phản ứng cụ thể của lượt hiện tại; câu bình thường được phép hay hơn câu thơ lặp.")
    return "\n".join(lines)
