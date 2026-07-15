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
    from runtime.runtime_settings_store import runtime_bool
    return runtime_bool("tts", "stage_localize", default=True)


def _remote_provider_is_gemini() -> bool:
    provider = os.environ.get("ERIS_REMOTE_PROVIDER", "").strip().lower()
    if provider == "gemini":
        return True
    base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "").strip().lower()
    return "generativelanguage.googleapis.com" in base_url or "googleapis.com" in base_url


def _get_api_key() -> str:
    """Lấy key Gemini cho bước dịch TTS, không phụ thuộc vào tts_engine.

    Giữ thứ tự gần giống engine cũ để không phá cấu hình hiện tại của ông.
    """
    for env_name in ("ERIS_TTS_API_KEY", "ERIS_SPEECH_API_KEY", "GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    if _remote_provider_is_gemini():
        key = os.environ.get("ERIS_REMOTE_API_KEY", "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    try:
        from llm.key_pool import get_key_pool

        pool = get_key_pool("gemini")
        if pool and pool.size > 0:
            lease = pool.acquire(allow_cooling=True)
            return lease.key if lease is not None else ""
    except Exception:
        pass
    return ""



def _get_api_key_lease():
    """Lấy key + lease cho localizer để pool biết đúng key nào vừa lỗi.

    Env key riêng không có lease nên chỉ trả (key, None, None). Pool key phải đi
    qua acquire(), tuyệt đối không current_key() trong request path nữa.
    """
    for env_name in ("ERIS_TTS_API_KEY", "ERIS_SPEECH_API_KEY", "GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key and not key.startswith("PASTE_"):
            return key, None, None
    if _remote_provider_is_gemini():
        key = os.environ.get("ERIS_REMOTE_API_KEY", "").strip()
        if key and not key.startswith("PASTE_"):
            return key, None, None
    try:
        from llm.key_pool import get_key_pool

        pool = get_key_pool("gemini")
        if pool and pool.size > 0:
            lease = pool.acquire()
            if lease is not None:
                return lease.key, pool, lease
    except Exception:
        pass
    return "", None, None


def _already_japanese(text: str) -> bool:
    return bool(_JAPANESE_RE.search(text or ""))


class SpeechLocalizer:
    """Dịch/style câu public thành câu TTS.

    Cache nhỏ theo process để các câu lặp không tốn thêm một call Gemini.  Đây
    không phải memory; chỉ là chống gọi lại API cho cùng một câu trong runtime.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], str] = {}

    def localize(self, text: str, *, language_hint: str = "auto", prosody_style: str = "") -> str:
        clean = _normalize_transcript(text)
        if not clean:
            return ""

        lang = str(language_hint or "auto").strip().lower()
        if lang not in {"ja", "jp", "japanese"}:
            return clean
        if not _enabled() or _already_japanese(clean):
            return clean

        style = str(prosody_style or "").strip().lower()
        key = (lang, style, clean)
        if key in self._cache:
            return self._cache[key]

        translated = self._translate_to_japanese(clean, prosody_style=style)
        self._cache[key] = translated or clean
        return self._cache[key]

    def _translate_to_japanese(self, text: str, *, prosody_style: str = "") -> str:
        # Localizer là lane phụ. Khi TPM/429 nóng, bỏ pass này thay vì chồng retry
        # lên TTS chính rồi bắt key pool quay thêm một vòng vô nghĩa.
        all_lane_budget = os.environ.get("ERIS_TOKEN_BUDGET_ALL_LANES", "1").strip().lower() not in {
            "0", "false", "off", "no",
        }
        plan = None
        budgeted_text = str(text or "")
        if all_lane_budget:
            try:
                from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                estimated_prompt = max(64, len(str(text or "")) // 3 + 180)
                plan = GLOBAL_TOKEN_PRESSURE_GOVERNOR.plan_request(
                    "gemini",
                    lane="speech_localizer",
                    prompt_tokens=estimated_prompt,
                    requested_output_tokens=384,
                    optional_pass=True,
                )
                if not plan.allowed:
                    logger.info("[TTS.Localizer] Bỏ pass dịch do token pressure: %s", plan.reason)
                    return text
                from llm.token_budget import truncate_text_to_budget
                budgeted_text = truncate_text_to_budget(
                    budgeted_text, max(80, plan.prompt_limit - 220),
                    marker="…[transcript localizer rút gọn]…", preserve_tail=True,
                )
            except Exception:
                plan = None
                budgeted_text = str(text or "")

        api_key, pool, lease = _get_api_key_lease()
        if not api_key:
            return text
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            style_line = _style_line(prosody_style)
            prompt = (
                "Translate the transcript into natural, gentle, polite Japanese for a soft anime girl "
                "desktop companion speaking to the user. Avoid titles such as ご主人様 or マスター; "
                "prefer natural Japanese that omits second-person address when possible. Keep the meaning. Do not add stage "
                "directions, quotes, explanations, romanization, or the original text. Preserve line "
                "breaks as short breath groups; keep the same line order whenever possible.\n"
                f"{style_line}\n\n"
                "Transcript:\n"
                f"{budgeted_text}"
            )
            response = client.models.generate_content(
                model=os.environ.get("ERIS_TTS_LOCALIZER_MODEL", "gemini-2.5-flash").strip(),
                contents=prompt,
            )
            out = _clean_translation_output(getattr(response, "text", "") or "")
            try:
                if plan is not None:
                    from llm.token_budget import estimate_tokens
                    from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                    GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_request(
                        "gemini", lane="speech_localizer",
                        prompt_tokens=estimate_tokens([{"role": "user", "content": prompt}]),
                        output_tokens=plan.output_tokens,
                    )
                if pool is not None and lease is not None:
                    pool.mark_success(lease=lease)
                from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_success("gemini")
            except Exception:
                pass
            return out or text
        except Exception as exc:
            try:
                from llm.provider_errors import classify_provider_error
                kind = classify_provider_error(exc)
                if pool is not None and lease is not None:
                    if str(kind) == "key_revoked":
                        pool.mark_permanently_dead(lease=lease, reason="localizer_key_reported_leaked")
                    elif str(kind) == "rate_limit":
                        pool.mark_rate_limited(seconds=60.0, lease=lease, reason="localizer_http_429")
                        try:
                            from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                            GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_rate_limit("gemini", retry_after_s=60.0, lane="speech_localizer")
                        except Exception:
                            pass
                    elif str(kind) == "project_permission":
                        pool.mark_dead(3600.0, lease=lease, reason="localizer_project_permission")
            except Exception:
                pass
            logger.warning("[TTS.Localizer] Dịch sang JP lỗi: %s", exc)
            return text


def _normalize_transcript(text: str) -> str:
    """Giữ line break như nhịp thở, chỉ dọn khoảng trắng nội dòng."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _clean_translation_output(text: str) -> str:
    """Dọn output dịch nhưng không flatten nhiều dòng thành một dòng."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.strip().strip('"').strip("'").strip()
    lines = [" ".join(line.split()).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _style_line(style: str) -> str:
    """Hint dịch tự nhiên theo prosody, không biến nghĩa câu."""
    style = str(style or "").strip().lower()
    if style == "dry_tease":
        return "Style hint: preserve a dry teasing edge; polite, short, slightly unimpressed."
    if style == "soft_tease":
        return "Style hint: preserve soft teasing warmth; playful but restrained."
    if style == "self_aware_dry":
        return "Style hint: quietly self-aware and dry; admit the miss briefly without sounding submissive."
    if style == "annoyed_soft":
        return "Style hint: controlled mild irritation; crisp and concise, never loud."
    if style == "sharp_deadpan":
        return "Style hint: one sharp deadpan retort; measured pace and a clean ending."
    if style == "cold_boundary":
        return "Style hint: cold, controlled boundary; direct, non-threatening, no apology tail."
    if style == "deadpan":
        return "Style hint: deadpan and concise; polite but a little flat."
    if style == "focused":
        return "Style hint: technical and clear; avoid cute filler."
    if style == "low_quiet":
        return "Style hint: quiet and understated; avoid dramatic wording."
    return "Style hint: natural, restrained, and concise."


__all__ = ["SpeechLocalizer"]
