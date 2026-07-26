# -*- coding: utf-8 -*-
"""tts_budget.py - budget riêng cho TTS, không dùng token pressure của LLM.

Gemini TTS nhận text + chỉ dẫn và trả audio; ``requested_output_tokens`` của LLM
không có ý nghĩa ở đây. Phase 7 chỉ giới hạn transcript/prompt/concurrency bằng
hard limit rõ ràng. Pressure 429/5xx do circuit breaker + key pool xử lý.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class TtsRequestBudget:
    max_transcript_chars: int = 260
    max_prompt_chars: int = 8000
    max_style_chars: int = 900
    max_concurrency: int = 2

    @classmethod
    def from_env(cls) -> "TtsRequestBudget":
        return cls(
            max_transcript_chars=_env_int("ERIS_TTS_MAX_TRANSCRIPT_CHARS", 260, 48, 1600),
            max_prompt_chars=_env_int("ERIS_TTS_MAX_PROMPT_CHARS", 8000, 1200, 24000),
            max_style_chars=_env_int("ERIS_TTS_MAX_STYLE_CHARS", 900, 120, 4000),
            max_concurrency=_env_int("ERIS_TTS_MAX_CONCURRENCY", 2, 1, 8),
        )

    def validate(self, *, transcript: str, prompt: str, style_text: str = "") -> None:
        text = str(transcript or "").strip()
        full_prompt = str(prompt or "")
        style = str(style_text or "")
        if len(text) > self.max_transcript_chars:
            raise RuntimeError(
                f"TTS transcript quá dài ({len(text)}>{self.max_transcript_chars}); "
                "StageOutputPipeline phải chia segment trước khi synthesize"
            )
        if len(style) > self.max_style_chars:
            raise RuntimeError(
                f"TTS style notes quá dài ({len(style)}>{self.max_style_chars}); hãy rút gọn director notes"
            )
        if len(full_prompt) > self.max_prompt_chars:
            raise RuntimeError(
                f"TTS prompt vượt hard limit ({len(full_prompt)}>{self.max_prompt_chars})"
            )


GLOBAL_TTS_REQUEST_BUDGET = TtsRequestBudget.from_env()


__all__ = ["TtsRequestBudget", "GLOBAL_TTS_REQUEST_BUDGET"]
