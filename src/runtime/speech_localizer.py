# -*- coding: utf-8 -*-
"""speech_localizer.py — chuẩn hoá câu trước khi đưa vào TTS.

TTS engine chỉ nên làm một việc: ``text -> audio``.  Nếu nhét luôn dịch Nhật /
rewrite anime vào engine thì rất khó debug: giọng lỗi do TTS, do dịch, hay do
câu gốc?  Module này là lớp "localizer" mỏng đứng TRƯỚC TTS:

    display_text tiếng Việt/Anh -> tts_text theo ngôn ngữ cần đọc.

Hiện tại chỉ bật nhánh ``ja`` vì repo đang dùng giọng anime Nhật qua Gemini TTS.
Nếu lỗi API/quota, localizer trả lại câu gốc để ERIS vẫn nói được thay vì câm.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("TTS.Localizer")


_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def _enabled() -> bool:
    return os.environ.get("ERIS_TTS_STAGE_LOCALIZE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_api_key() -> str:
    """Lấy key Gemini cho bước dịch TTS, không phụ thuộc vào tts_engine.

    Giữ thứ tự gần giống engine cũ để không phá cấu hình hiện tại của ông.
    """
    for env_name in ("ERIS_TTS_API_KEY", "ERIS_SPEECH_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    try:
        from llm.key_pool import get_key_pool

        pool = get_key_pool("gemini")
        if pool and pool.size > 0:
            return pool.current_key()
    except Exception:
        pass
    return ""


def _already_japanese(text: str) -> bool:
    return bool(_JAPANESE_RE.search(text or ""))


class SpeechLocalizer:
    """Dịch/style câu public thành câu TTS.

    Cache nhỏ theo process để các câu lặp không tốn thêm một call Gemini.  Đây
    không phải memory; chỉ là chống gọi lại API cho cùng một câu trong runtime.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], str] = {}

    def localize(self, text: str, *, language_hint: str = "auto") -> str:
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return ""

        lang = str(language_hint or "auto").strip().lower()
        if lang not in {"ja", "jp", "japanese"}:
            return clean
        if not _enabled() or _already_japanese(clean):
            return clean

        key = (lang, clean)
        if key in self._cache:
            return self._cache[key]

        translated = self._translate_to_japanese(clean)
        self._cache[key] = translated or clean
        return self._cache[key]

    def _translate_to_japanese(self, text: str) -> str:
        api_key = _get_api_key()
        if not api_key:
            return text
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            prompt = (
                "Translate the sentence into natural, gentle, polite Japanese for a soft anime girl "
                "desktop companion speaking to her Master/Ngài. Keep the meaning. Do not add stage "
                "directions, quotes, explanations, romanization, or the original text.\n\n"
                f"Sentence: {text}"
            )
            response = client.models.generate_content(
                model=os.environ.get("ERIS_TTS_LOCALIZER_MODEL", "gemini-2.5-flash").strip(),
                contents=prompt,
            )
            out = " ".join(str(getattr(response, "text", "") or "").split()).strip()
            out = out.strip('"').strip("'").strip()
            return out or text
        except Exception as exc:
            logger.warning("[TTS.Localizer] Dịch sang JP lỗi: %s", exc)
            return text


__all__ = ["SpeechLocalizer"]
