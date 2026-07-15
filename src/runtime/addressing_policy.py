# -*- coding: utf-8 -*-
"""Chính sách xưng hô public của Eris.

Mục tiêu không phải thay mù ``Ngài`` thành ``bạn`` ở mọi nơi. Cách vá đó giữ
nguyên nguồn gây lỗi và còn tạo câu méo như ``Thưa bạn`` hoặc ``Tên bạn vẫn còn
đây``. Module này gom toàn bộ xử lý về một contract:

1. bỏ lời gọi kiểu nghi lễ ở đầu câu;
2. sửa các cấu trúc sở hữu/chủ ngữ tối thiểu để câu vẫn đúng ngữ pháp;
3. tuyệt đối không để ``Ngài``/``Master`` lọt ra UI, TTS hoặc memory;
4. không đụng tới các từ kỹ thuật như ``master switch`` hay ``audio mastering``
   nếu chúng không phải cách gọi người dùng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_LEGACY_TERM = r"(?:ng\u00e0i|ngai|master)"

# Lời gọi trực tiếp ở đầu câu. Xóa cả dấu câu theo sau để không còn dấu phẩy lẻ.
_VOCATIVE_START_RE = re.compile(
    rf"^\s*(?:(?:th\u01b0a|thua)\s+{_LEGACY_TERM}(?:\s+(?:\u01a1i|oi))?\s*[,;:\-–—.]*"
    rf"|{_LEGACY_TERM}\s+(?:\u01a1i|oi)\s*[,;:\-–—.]*"
    rf"|{_LEGACY_TERM}\s*[,;:\-–—.]+\s*)",
    re.IGNORECASE,
)

# Những cấu trúc cần giữ quan hệ ngữ pháp. Đây là rewrite có chủ đích, không phải
# global replace. ``của Ngài`` cần thành ``của bạn``; còn lời gọi trống thì bỏ.
_POSSESSIVE_RE = re.compile(rf"\bc\u1ee7a\s+{_LEGACY_TERM}\b|\bcua\s+{_LEGACY_TERM}\b", re.IGNORECASE)

# Chủ ngữ rõ ràng. Danh sách động từ đủ rộng cho câu hội thoại, nhưng không chạm
# vào cụm kỹ thuật ``master branch`` hoặc ``master switch``.
_SUBJECT_RE = re.compile(
    rf"\b{_LEGACY_TERM}\s+(?=(?:\u0111ang|dang|\u0111\u00e3|da|s\u1ebd|se|c\u00f3|co|mu\u1ed1n|muon|"
    rf"c\u1ea7n|can|ngh\u0129|nghi|th\u1ea5y|thay|nh\u1edb|nho|n\u00f3i|noi|h\u1ecfi|hoi|l\u00e0m|lam|"
    rf"th\u00edch|thich|kh\u00f4ng|khong|ch\u01b0a|chua|v\u1eabn|van|v\u1eeba|vua)\b)",
    re.IGNORECASE,
)

# Một vài mẫu danh từ hay xuất hiện trong memory. Giữ nghĩa thay vì để sanitizer
# xóa mất slot đang được hỏi.
_NOUN_OWNER_RE = re.compile(
    rf"\b(?P<noun>t\u00ean|ten|\u00fd|y|s\u1edf th\u00edch|so thich|k\u00fd \u1ee9c|ky uc|"
    rf"c\u00e2u h\u1ecfi|cau hoi|c\u00e2u tr\u1ea3 l\u1eddi|cau tra loi|m\u00e1y|may|project|repo)\s+{_LEGACY_TERM}\b",
    re.IGNORECASE,
)

# Chỉ bắt standalone legacy address. ``master_switch`` và ``mastering`` không bị
# đụng tới vì boundary/underscore khác hình dạng lời gọi.
_STANDALONE_RE = re.compile(rf"(?<![\w]){_LEGACY_TERM}(?![\w])", re.IGNORECASE)

_TECHNICAL_MASTER_NEIGHBORS = {
    "audio", "branch", "bus", "channel", "clock", "code", "control",
    "controller", "copy", "database", "data", "fader", "file", "gain",
    "key", "mix", "model", "node", "password", "process", "prompt",
    "record", "seed", "server", "switch", "track", "volume",
}


@dataclass(frozen=True, slots=True)
class AddressingResult:
    text: str
    changed: bool = False
    rules: tuple[str, ...] = ()


def _squash(text: str) -> str:
    out = re.sub(r"[ \t]+", " ", str(text or ""))
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;:]){2,}", r"\1", out)
    out = re.sub(r"^\s*[,;:]+\s*", "", out)
    return out.strip()


def _replacement_at(match: re.Match[str], replacement: str) -> str:
    """Viết hoa chỉ khi token thật sự đứng đầu câu, không theo chữ nguồn."""
    before = match.string[: match.start()]
    stripped = before.rstrip()
    at_sentence_start = not stripped or stripped[-1:] in {".", "!", "?", "\n"}
    if at_sentence_start:
        return replacement[:1].upper() + replacement[1:]
    return replacement


def sanitize_legacy_addressing(text: str, *, surface: str = "display") -> AddressingResult:
    """Loại cách gọi cũ và sửa câu ở mức tối thiểu.

    ``surface`` hiện chỉ dùng cho trace/khả năng mở rộng. Cả display, TTS và
    memory đều phải có cùng invariant: không còn từ xưng hô legacy.
    """

    raw = str(text or "")
    if not raw:
        return AddressingResult(raw)

    out = raw
    rules: list[str] = []

    out2, count = _VOCATIVE_START_RE.subn("", out)
    if count:
        out = out2
        # Sau khi bỏ lời gọi đầu câu, giữ hình thức câu tự nhiên thay vì để
        # ``tôi`` viết thường ở đầu transcript.
        for index, char in enumerate(out):
            if char.isalpha():
                out = out[:index] + char.upper() + out[index + 1 :]
                break
        rules.append("drop_vocative")

    def possessive_repl(match: re.Match[str]) -> str:
        source = match.group(0)
        return "của bạn" if any(ch in source for ch in "ủà") else "cua ban"

    out2, count = _POSSESSIVE_RE.subn(possessive_repl, out)
    if count:
        out = out2
        rules.append("repair_possessive")

    def noun_owner_repl(match: re.Match[str]) -> str:
        noun = match.group("noun")
        return f"{noun} bạn"

    out2, count = _NOUN_OWNER_RE.subn(noun_owner_repl, out)
    if count:
        out = out2
        rules.append("repair_noun_owner")

    def subject_repl(match: re.Match[str]) -> str:
        return _replacement_at(match, "bạn") + " "

    out2, count = _SUBJECT_RE.subn(subject_repl, out)
    if count:
        out = out2
        rules.append("repair_subject")

    # Nếu còn standalone, dùng đại từ trung tính để bảo toàn nghĩa. Đây là lưới
    # cuối, không phải chiến lược chính. Nguồn sinh đã được cấm ở prompt/dataset.
    def standalone_repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.lower() == "master":
            before = match.string[: match.start()]
            after = match.string[match.end() :]
            prev_match = re.search(r"([A-Za-z_]+)\s*$", before)
            next_match = re.match(r"\s*([A-Za-z_]+)", after)
            prev_word = (prev_match.group(1).lower() if prev_match else "")
            next_word = (next_match.group(1).lower() if next_match else "")
            if prev_word in _TECHNICAL_MASTER_NEIGHBORS or next_word in _TECHNICAL_MASTER_NEIGHBORS:
                return token
        return _replacement_at(match, "bạn")

    out2 = _STANDALONE_RE.sub(standalone_repl, out)
    if out2 != out:
        out = out2
        rules.append("legacy_failsafe")

    out = _squash(out)
    out = re.sub(r"\b[Bb]\u1ea1n\s+[Bb]\u1ea1n\b", lambda m: "Bạn" if m.group(0)[:1].isupper() else "bạn", out)
    return AddressingResult(out, changed=out != raw, rules=tuple(dict.fromkeys(rules)))


def clean_public_addressing(text: str, *, surface: str = "display") -> str:
    return sanitize_legacy_addressing(text, surface=surface).text


__all__ = ["AddressingResult", "clean_public_addressing", "sanitize_legacy_addressing"]
