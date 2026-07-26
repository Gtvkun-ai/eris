from __future__ import annotations

"""Các intent hội thoại cực ngắn cần nhận dạng deterministic.

Đặt ở ``core`` để memory compiler và runtime cùng dùng một grammar, tránh mỗi tầng
nuôi một danh sách câu riêng rồi vài tháng sau lại bất đồng như hai cuốn sổ hộ khẩu.
"""

import re
import unicodedata


def normalize_conversation_text(text: str) -> str:
    """Chuẩn hóa tiếng Việt có/không dấu cho grammar hội thoại ngắn."""

    value = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9\s]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def is_recent_user_turn_recall(text: str) -> bool:
    """User hỏi chính câu mình vừa nói, không hỏi profile dài hạn."""

    norm = normalize_conversation_text(text)
    if not norm:
        return False
    patterns = (
        r"^(?:toi|tui|minh|tao)\s+(?:vua\s+|nay\s+|ban\s+nay\s+|luc\s+nay\s+)?(?:noi|bao|hoi)\s+(?:cai\s+|cau\s+)?gi(?:\s+(?:ta|nhi|ay|vay))?$",
        r"^(?:nay|ban\s+nay|luc\s+nay|vua\s+roi)\s+(?:toi|tui|minh|tao)\s+(?:noi|bao|hoi)\s+(?:cai\s+|cau\s+)?gi(?:\s+(?:ta|nhi|ay|vay))?$",
        r"^(?:cau|loi)\s+(?:toi|tui|minh|tao)\s+(?:vua\s+)?(?:noi|bao|hoi)\s+la\s+gi(?:\s+(?:ta|nhi|ay|vay))?$",
        r"^(?:toi|tui|minh|tao)\s+(?:noi|bao|hoi)\s+gi\s+(?:vua\s+roi|luc\s+nay|ban\s+nay)$",
    )
    return any(re.fullmatch(pattern, norm) for pattern in patterns)


def is_short_repair_request(text: str) -> bool:
    """User yêu cầu sửa/giải thích lại bằng một câu cực ngắn."""

    return normalize_conversation_text(text) in {
        "ha",
        "ha gi",
        "gi",
        "gi co",
        "gi vay",
        "ua",
        "ua gi",
        "y gi",
        "sao co",
        "noi gi",
        "khong hieu",
    }
