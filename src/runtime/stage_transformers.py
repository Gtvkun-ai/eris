# -*- coding: utf-8 -*-
"""stage_transformers.py — transformer chain cho output sân khấu.

Đây là lớp "biên tập sân khấu" đứng sau cognition:

    raw_model_text
    -> ActionTagExtractor
    -> DisplayFilter
    -> TTSFilter
    -> MemorySurfaceFilter
    -> StageFrameBuilder/Dispatcher

Mục tiêu: model/agent được phép sinh câu tự nhiên, nhưng UI/TTS/memory/avatar
không dùng cùng một string.  Tag diễn xuất như "(cười khẽ)" hoặc "[look_away]"
được bóc thành action event; TTS không đọc tag; memory không lưu rác sân khấu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class StageMarks:
    text: str
    actions: tuple[str, ...] = ()
    emotion_hint: str = ""
    motion_hint: str = ""


@dataclass(frozen=True, slots=True)
class StageTextSurfaces:
    raw_text: str
    display_text: str
    tts_text: str
    memory_text: str
    marks: StageMarks


_FENCE_RE = re.compile(r"```.*?```", re.S)
_INTERNAL_REASONING_RE = re.compile(
    r"<\s*(?:think|analysis|reasoning)\s*>.*?<\s*/\s*(?:think|analysis|reasoning)\s*>",
    re.I | re.S,
)
_INTERNAL_PREFIX_RE = re.compile(r"^\s*(?:analysis|reasoning|suy nghĩ|suy nghi)\s*:\s*", re.I)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_URL_RE = re.compile(r"https?://\S+")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BOLD_ITALIC_RE = re.compile(r"(\*\*?|__?)(.*?)\1")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    re.UNICODE,
)

_BRACKET_TAG_RE = re.compile(r"\[(?P<tag>[a-zA-Z_][a-zA-Z0-9_\-: ]{1,48})\]")
_ANGLE_TAG_RE = re.compile(r"<(?P<tag>[a-zA-Z_][a-zA-Z0-9_\-: ]{1,48})>")
_KV_TAG_RE = re.compile(
    r"\b(?P<key>emotion|mood|motion|action|voice_style|style)\s*[:=]\s*(?P<value>[a-zA-Z_][a-zA-Z0-9_\-]{1,48})",
    re.I,
)
_PARENS_ACTION_RE = re.compile(
    r"(?P<tag>[\(\*]\s*(?:"
    r"cười khẽ|cười nhẹ|cười|nhíu mắt|thở nhẹ|thở dài|im lặng|nghiêng đầu|"
    r"liếc|nhìn sang bên|nhìn xuống|gật|lắc đầu|mỉm cười|"
    r"smile|small smile|laugh|soft laugh|sigh|whisper|look away|look down|tilt head"
    r")[^)\*]{0,48}[\)\*])",
    re.I,
)

_ACTION_ALIASES: dict[str, str] = {
    "cười": "laugh_soft",
    "cười khẽ": "laugh_soft",
    "cười nhẹ": "laugh_soft",
    "mỉm cười": "small_smile",
    "smile": "small_smile",
    "small smile": "small_smile",
    "laugh": "laugh_soft",
    "soft laugh": "laugh_soft",
    "nhíu mắt": "squint_soft",
    "thở nhẹ": "soft_breath",
    "thở dài": "sigh_soft",
    "sigh": "sigh_soft",
    "nghiêng đầu": "tilt_head",
    "tilt head": "tilt_head",
    "liếc": "look_away",
    "nhìn sang bên": "look_away",
    "look away": "look_away",
    "nhìn xuống": "look_down",
    "look down": "look_down",
    "gật": "nod_small",
    "lắc đầu": "shake_head_small",
    "whisper": "voice_whisper",
    "look_away": "look_away",
    "look_down": "look_down",
    "tilt_head": "tilt_head",
    "small_smile": "small_smile",
    "laugh_soft": "laugh_soft",
    "sigh_soft": "sigh_soft",
    "scoff_soft": "scoff_soft",
    "soft_breath": "soft_breath",
}

_EMOTION_ALIASES = {
    "teasing",
    "dry_tease",
    "self_aware_dry",
    "annoyed_soft",
    "sharp_deadpan",
    "cold_boundary",
    "soft_tease",
    "mischief",
    "curious",
    "focused",
    "deadpan",
    "warm_soft",
    "quiet_low",
}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_markdown(text: str, *, code_placeholder: str = "") -> str:
    t = str(text or "")
    t = _FENCE_RE.sub(code_placeholder, t)
    t = _MARKDOWN_HEADING_RE.sub("", t)
    t = _INLINE_CODE_RE.sub(r"\1", t)
    t = _BOLD_ITALIC_RE.sub(r"\2", t)
    return _squash(t)


def _normalize_tag(raw: str) -> str:
    tag = str(raw or "").strip().lower()
    tag = tag.strip("[]()<>* ")
    tag = tag.replace("-", "_")
    tag = re.sub(r"\s+", " ", tag)
    return tag


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


class ActionTagExtractor:
    """Bóc tag diễn xuất khỏi text và trả thành action/emotion/motion.

    Nếu model lỡ viết "(cười khẽ)" thì tag đó không bị đọc ra TTS và không đi vào
    memory.  Avatar vẫn nhận được ``laugh_soft`` để diễn nếu frontend hỗ trợ.
    """

    def extract(self, text: str) -> StageMarks:
        working = str(text or "")
        actions: list[str] = []
        emotion_hint = ""
        motion_hint = ""

        def consume_tag(raw_tag: str) -> None:
            nonlocal emotion_hint, motion_hint
            tag = _normalize_tag(raw_tag)
            if not tag:
                return
            value = tag.split(":", 1)[-1].strip() if ":" in tag else tag
            mapped = _ACTION_ALIASES.get(value) or _ACTION_ALIASES.get(value.replace("_", " "))
            if mapped:
                actions.append(mapped)
                if mapped in {"look_away", "look_down", "tilt_head", "small_smile"}:
                    motion_hint = motion_hint or mapped
                return
            if value in _EMOTION_ALIASES:
                emotion_hint = emotion_hint or value
                return

        def parens_repl(match: re.Match[str]) -> str:
            consume_tag(match.group("tag"))
            return " "

        working = _PARENS_ACTION_RE.sub(parens_repl, working)

        def bracket_repl(match: re.Match[str]) -> str:
            consume_tag(match.group("tag"))
            return " "

        working = _BRACKET_TAG_RE.sub(bracket_repl, working)
        working = _ANGLE_TAG_RE.sub(bracket_repl, working)

        def kv_repl(match: re.Match[str]) -> str:
            nonlocal emotion_hint, motion_hint
            key = str(match.group("key") or "").lower()
            value = _normalize_tag(match.group("value"))
            if key in {"emotion", "mood", "voice_style", "style"} and value:
                emotion_hint = emotion_hint or value
            elif key in {"motion", "action"}:
                mapped = _ACTION_ALIASES.get(value) or value
                actions.append(mapped)
                motion_hint = motion_hint or mapped
            return " "

        working = _KV_TAG_RE.sub(kv_repl, working)
        return StageMarks(
            text=_squash(working),
            actions=_unique(actions),
            emotion_hint=emotion_hint,
            motion_hint=motion_hint,
        )


class DisplayFilter:
    """Text cho UI: đẹp, gọn, không chứa tag nội bộ."""

    def clean(self, text: str) -> str:
        return _strip_markdown(text, code_placeholder="[code]")


class TTSFilter:
    """Text cho TTS: không markdown, URL, emoji, code, tag sân khấu."""

    def clean(self, text: str) -> str:
        t = _strip_markdown(text, code_placeholder="")
        t = _URL_RE.sub("", t)
        t = _EMOJI_RE.sub("", t)
        return _squash(t)


class MemorySurfaceFilter:
    """Text lưu hội thoại/memory: chỉ nội dung thật, không action tag."""

    def clean(self, text: str) -> str:
        # Phòng thủ lớp cuối: reasoning không được lọt vào history/memory ngay cả
        # khi một adapter mới quên gọi json_sanitizer. Cùng một lỗi không cần có
        # đời sống lâu dài hơn chính nó.
        t = _INTERNAL_REASONING_RE.sub(" ", str(text or ""))
        t = _INTERNAL_PREFIX_RE.sub("", t)
        t = _strip_markdown(t, code_placeholder="[code]")
        t = _URL_RE.sub("", t)
        t = _EMOJI_RE.sub("", t)
        return _squash(t)


class StageTransformerChain:
    """Chạy toàn bộ transformer để tạo các bề mặt output."""

    def __init__(self) -> None:
        self.action_extractor = ActionTagExtractor()
        self.display_filter = DisplayFilter()
        self.tts_filter = TTSFilter()
        self.memory_filter = MemorySurfaceFilter()

    def transform(self, raw_text: str) -> StageTextSurfaces:
        raw = str(raw_text or "")
        # Bóc reasoning trước ActionTagExtractor. Nếu làm ngược, regex angle tag
        # sẽ nuốt riêng ``<think>`` rồi để phần suy nghĩ trơ trọi giữa sân khấu.
        safe_raw = _INTERNAL_REASONING_RE.sub(" ", raw)
        marks = self.action_extractor.extract(safe_raw)
        display_text = self.display_filter.clean(marks.text)
        tts_text = self.tts_filter.clean(marks.text)
        memory_text = self.memory_filter.clean(marks.text)
        return StageTextSurfaces(
            raw_text=raw,
            display_text=display_text,
            tts_text=tts_text,
            memory_text=memory_text,
            marks=marks,
        )


__all__ = [
    "ActionTagExtractor",
    "DisplayFilter",
    "MemorySurfaceFilter",
    "StageMarks",
    "StageTextSurfaces",
    "StageTransformerChain",
    "TTSFilter",
]
