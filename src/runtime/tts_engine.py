# -*- coding: utf-8 -*-
"""tts_engine.py — Emotional TTS cho ERIS dùng Gemini TTS API.

Gemini TTS hỗ trợ inline audio tags: [whispers], [excited], [trembling]...
Engine này đọc valence/arousal/stance từ payload của Eris và tự động
inject audio tag phù hợp trước khi gọi TTS → giọng tự nhấn nhá theo cảm xúc thật.

Giọng mặc định: Aoede (Breezy, nữ, phù hợp anime girl JP accent).
Có thể đổi qua ERIS_TTS_VOICE trong .env.

Hỗ trợ ngôn ngữ: Gemini TTS tự detect → Japanese text → đọc JP.

Backend phát âm: miniaudio (không cần ffmpeg, không có audioop issue với Python 3.13).
"""

from __future__ import annotations

import io
import asyncio
import inspect
import logging
import os
import queue
import random
import re
import struct
import subprocess
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from typing import Optional

from runtime.prosody_director import ProsodyDirector
from runtime.speech_localizer import SpeechLocalizer
from runtime.tts_audio_polish import audio_polish_enabled, polish_pcm16_mono
from runtime.tts_markup import render_tts_markup
from runtime.vocal_cache import VocalCache, VocalCacheKey, strip_audible_prefix, vocal_cache_enabled
from runtime.speech_contract import normalize_language
from runtime.addressing_policy import clean_public_addressing
from runtime.tts_circuit_breaker import GLOBAL_TTS_BREAKER

logger = logging.getLogger("TTS")


@dataclass(frozen=True, slots=True)
class TtsPlaybackEvent:
    """Lifecycle event của một đoạn TTS.

    Đây là phần "end đúng": caller biết đoạn nào đã được queue, bắt đầu phát,
    phát xong, bị hủy, hoặc lỗi. UI/interrupt ledger có thể bám vào event này
    mà không cần đoán từ log hay thread state.
    """

    type: str
    turn_id: str = ""
    segment_id: int = 0
    text: str = ""
    reason: str = ""
    error: str = ""

# ── Feature flag (runtime language reload) ───────────────────────────────────

def _enabled() -> bool:
    from runtime.runtime_settings_store import runtime_bool
    return runtime_bool("tts", "enabled", default=True)

def _voice() -> str:
    # Aoede = Breezy nữ; Leda = Youthful nữ; Achernar = Soft nữ
    from runtime.runtime_settings_store import runtime_text
    return runtime_text("tts", "voice", default="Aoede") or "Aoede"

def _model() -> str:
    # gemini-2.5-flash-preview-tts = stable TTS model hiện tại (2025-06+)
    # gemini-3.1-flash-tts-preview đã deprecated/không ổn định, dễ trả về 404
    return os.environ.get("ERIS_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()

def _normalize_language_hint(value: str) -> str:
    """Chuẩn hoá value từ .env/UI thành mã ngôn ngữ nội bộ ổn định."""
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "vi", "vietnamese", "vi-vn"}:
        return "vi"
    if raw in {"ja", "jp", "japanese", "ja-jp", "jp-jp", "日本語", "日本语"}:
        return "ja"
    return raw


def _language_hint() -> str:
    # Eris nói tiếng Việt mặc định. Chỉ dịch/đọc Nhật khi cấu hình rõ ``ja``.
    from runtime.runtime_settings_store import runtime_text
    return _normalize_language_hint(runtime_text("tts", "language", default="vi"))


def _quality_mode() -> str:
    """balanced | high.

    ``high`` không gọi thêm API; nó chỉ đổi prompt/markup để Gemini diễn câu kỹ
    hơn. Nếu cần latency thấp hơn, set ERIS_TTS_QUALITY=balanced.
    """
    from runtime.runtime_settings_store import runtime_text
    value = runtime_text("tts", "quality", default="high").strip().lower()
    return value if value in {"balanced", "high"} else "high"



def _output_volume() -> float:
    from runtime.runtime_settings_store import runtime_float
    value = runtime_float("tts", "volume", default=1.0)
    return max(0.0, min(1.0, value))


def _speech_speed() -> float:
    from runtime.runtime_settings_store import runtime_float
    value = runtime_float("tts", "speed", default=1.0)
    return max(0.85, min(1.15, value))


def _pace_directive() -> str:
    speed = _speech_speed()
    if speed <= 0.90:
        return "Pacing target: noticeably slower and more deliberate than normal, without stretching vowels unnaturally.\n"
    if speed >= 1.10:
        return "Pacing target: brisk and responsive, about ten percent faster than normal, while keeping articulation clear.\n"
    if speed < 0.98:
        return "Pacing target: slightly slower than normal.\n"
    if speed > 1.02:
        return "Pacing target: slightly faster than normal.\n"
    return ""

def _queue_size() -> int:
    raw = os.environ.get("ERIS_TTS_QUEUE_SIZE", "4").strip()
    try:
        return max(1, min(24, int(raw)))
    except ValueError:
        return 4


def _remote_provider_is_gemini() -> bool:
    provider = os.environ.get("ERIS_REMOTE_PROVIDER", "").strip().lower()
    if provider == "gemini":
        return True
    base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "").strip().lower()
    return "generativelanguage.googleapis.com" in base_url or "googleapis.com" in base_url


def _prelocalize_japanese_enabled() -> bool:
    return os.environ.get("ERIS_TTS_PRELOCALIZE_JA", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_tts_fallback_enabled() -> bool:
    return os.environ.get("ERIS_TTS_LOCAL_FALLBACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _edge_tts_fallback_enabled() -> bool:
    return os.environ.get("ERIS_TTS_EDGE_FALLBACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sapi_tts_fallback_enabled() -> bool:
    # SAPI keeps Eris from going silent, but the stock Windows voices are not
    # suitable for the anime/Japanese persona, so only use it when requested.
    return os.environ.get("ERIS_TTS_SAPI_FALLBACK", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

# ── Emotion → Audio Tag mapping ───────────────────────────────────────────────
# valence: [-1, 1]  arousal: [0, 1]  stance: string từ appraisal
# Gemini audio tags: inline trong text, phải là tiếng Anh cho best results

_STANCE_TO_TAG: dict[str, str] = {
    # tích cực
    "warm":              "warmly",
    "playful":           "playfully",
    "curious":           "curiously",
    "amused":            "with a slight laugh",
    "tender":            "gently",
    "affectionate":      "warmly, soft",
    "hopeful":           "hopefully",
    "content":           "contentedly",
    # trung tính / tập trung
    "focused":           "clearly",
    "composed":          "evenly",
    "neutral":           "",
    "detached":          "flatly",
    "guarded":           "carefully",
    "guarded_tender":    "gently but carefully",
    "observant":         "with calm curiosity",
    # tiêu cực / căng thẳng
    "melancholy":        "softly, with a hint of sadness",
    "sad":               "sadly",
    "withdrawn":         "quietly, distant",
    "anxious":           "nervously",
    "irritated":         "with slight irritation",
    "frustrated":        "with frustration",
    "tired":             "tiredly",
    "overwhelmed":       "trembling, overwhelmed",
    # cảm xúc mạnh
    "excited":           "excitedly",
    "surprised":         "surprised",
    "fearful":           "with a trembling voice",
    "panicked":          "panicked",
}

def _emotion_to_tag(
    valence: float,
    arousal: float,
    stance: str = "",
) -> str:
    """Chuyển valence/arousal/stance thành audio tag Gemini."""
    stance_clean = (stance or "").strip().lower()

    # Ưu tiên stance nếu có mapping rõ
    if stance_clean in _STANCE_TO_TAG:
        tag = _STANCE_TO_TAG[stance_clean]
        if tag:
            return f"[{tag}]"

    # Fallback từ valence × arousal
    # Vui + kích thích cao → excited
    if valence > 0.4 and arousal > 0.55:
        return "[excitedly]"
    # Vui nhẹ + arousal trung = playful/warm
    if valence > 0.25 and arousal > 0.3:
        return "[warmly]"
    # Vui nhẹ, bình tĩnh = content
    if valence > 0.1:
        return "[contentedly]"
    # Buồn + low arousal = softly/sadly
    if valence < -0.3 and arousal < 0.35:
        return "[softly, with sadness]"
    # Buồn + arousal cao = trembling/anxious
    if valence < -0.3 and arousal > 0.5:
        return "[trembling]"
    # Tiêu cực nhẹ
    if valence < -0.1:
        return "[quietly]"
    # Arousal cao, valence trung = tập trung/nghiêm túc
    if arousal > 0.65:
        return "[seriously]"
    # Default
    return ""


# ── System prompt cho Gemini TTS (character profile) ─────────────────────────

def _build_tts_prompt(
    text: str,
    audio_tag: str,
    language_hint: str,
    *,
    prosody_notes: str = "",
    prelocalized: bool = False,
    quality_mode: str = "high",
) -> str:
    """
    Xây dựng prompt TTS theo format advanced prompting của Gemini.

    language_hint:
      "auto" hoặc ""  = để Gemini tự detect ngôn ngữ từ transcript (khuyên dùng).
      "ja"            = ép Japanese (dịch transcript sang tiếng Nhật trước khi đọc).
      bất kỳ string   = truyền thẳng vào director notes.

    Style anime girl giữ nguyên bất kể ngôn ngữ — Gemini sẽ apply accent/breathiness
    lên ngôn ngữ tự detect được.
    """
    # Language instruction — chỉ thêm nếu được chỉ định rõ, không phải "auto"
    lang_line = ""
    if language_hint and language_hint.lower() not in ("auto", ""):
        if language_hint == "ja":
            if prelocalized:
                lang_line = (
                    "The transcript is already in Japanese. Read it aloud in Japanese. "
                    "Do not translate it again and do not read any hidden notes.\n"
                )
            else:
                lang_line = (
                    "The transcript is in Vietnamese or English. Translate the transcript into natural, "
                    "gentle Japanese first for a soft, polite anime girl desktop companion. "
                    "Do not use old Vietnamese honorifics or the word 'Master'. "
                    "Then read the Japanese translation aloud in Japanese. Do not read the original non-Japanese text.\n"
                )
        elif language_hint == "vi":
            lang_line = (
                "The transcript is in Vietnamese. Read it in Vietnamese only. "
                "Do not translate to Japanese or English, and do not switch language mid-line.\n"
            )
        else:
            lang_line = f"The transcript language is {language_hint}. Read it naturally.\n"

    # Inject audio tag vào đầu transcript
    tagged_text = f"{audio_tag} {text}".strip() if audio_tag else text
    quality = str(quality_mode or "high").strip().lower()
    if quality not in {"balanced", "high"}:
        quality = "high"

    prosody_line = ""
    if prosody_notes:
        prosody_line = f"Line performance: {prosody_notes}\n"

    performance_rules = ""
    transcript_title = "## TRANSCRIPT"
    if quality == "high":
        transcript_title = "## PERFORMANCE SCRIPT"
        performance_rules = (
            "Performance rules:\n"
            "- Bracketed audio tags are acting directions. Never speak the tag text aloud.\n"
            "- Line breaks are short speech beats, usually under 350ms; avoid long silence between lines.\n"
            "- For dry teasing or deadpan lines, press the final phrase lightly, as if amused but unimpressed.\n"
            "- Keep the anime quality understated: close, crisp, and alive, not theatrical or childish.\n"
            "- Do not read ellipses as words; use them only as tiny pauses.\n"
            "- Never use old Vietnamese honorifics or the word 'Master'; say 'bạn' if a direct address is needed.\n\n"
        )

    prompt = (
        "# AUDIO PROFILE: Eris\n"
        '## "The Desktop Companion"\n\n'
        "## SCENE\n"
        "A quiet desktop companion. Late at night. Eris is small, thoughtful,\n"
        "and speaks as if half-talking to herself. Intimate, not performative.\n\n"
        "## DIRECTOR'S NOTES\n"
        "Style: Soft anime girl voice. Slightly breathy. Youthful but with interior depth.\n"
        "Emotionally nuanced — not flat, not over-the-top. Warmth is subtle, not bubbly.\n"
        "Apply this voice style to whatever language the transcript is in.\n\n"
        "Pacing: Unhurried but responsive. Let tiny silences breathe; do not stall between short lines.\n"
        f"{_pace_directive()}\n"
        f"{performance_rules}"
        f"{prosody_line}"
        f"{lang_line}"
        f"{transcript_title}\n"
        f"{tagged_text}\n"
    )
    return prompt


# ── Gemini TTS call ───────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Lấy Gemini API key theo thứ tự ưu tiên."""
    # 1. Env riêng cho TTS
    key = os.environ.get("ERIS_TTS_API_KEY", "").strip()
    if key:
        return key

    # Dùng key pool để tự động xoay key khi bị 429
    try:
        from llm.key_pool import get_key_pool
        pool = get_key_pool("gemini")
        if pool and pool.size > 0:
            lease = pool.acquire(allow_cooling=True)
            return lease.key if lease is not None else ""
    except Exception:
        pass

    # 2. Speech key (đã set trong secrets.json)
    key = os.environ.get("ERIS_SPEECH_API_KEY", "").strip()
    if key:
        return key
    # 3. Gemini key chung
    for env_name in ("GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    # 4. Chỉ dùng ERIS_REMOTE_API_KEY nếu remote thật sự là Gemini.
    if _remote_provider_is_gemini():
        key = os.environ.get("ERIS_REMOTE_API_KEY", "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    return ""


def _short_error(exc: Exception, *, limit: int = 220) -> str:
    text = " ".join(str(exc or "").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _edge_voice_candidates(language_hint: str = "") -> list[str]:
    lang = normalize_language(language_hint)
    expected_prefix = {"ja": "ja-JP-", "vi": "vi-VN-", "en": "en-US-"}.get(lang, "")
    configured = {
        "ja": os.environ.get("ERIS_TTS_EDGE_JA_VOICE", "ja-JP-NanamiNeural").strip(),
        "vi": os.environ.get("ERIS_TTS_EDGE_VI_VOICE", "vi-VN-HoaiMyNeural").strip(),
        "en": os.environ.get("ERIS_TTS_EDGE_EN_VOICE", "en-US-JennyNeural").strip(),
    }.get(lang, "")
    # Config sai locale bị reject thay vì đọc tiếng Việt bằng voice Nhật rồi gọi đó
    # là fallback. Một lỗi cấu hình không cần được biến thành tính cách mới của Eris.
    if not configured or (expected_prefix and not configured.lower().startswith(expected_prefix.lower())):
        return []
    return [configured]


def _edge_romaji_enabled() -> bool:
    return os.environ.get("ERIS_TTS_EDGE_ROMAJI", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _contains_japanese_chars(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", str(text or "")))


def _strip_tts_honorifics(text: str) -> str:
    return clean_public_addressing(str(text or ""), surface="tts")


def _ascii_for_edge(text: str) -> str:
    source = str(text or "").replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", source)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii", "ignore")
    return " ".join(ascii_text.split()).strip()


def _clean_edge_romaji_output(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.strip().strip('"').strip("'").strip()
    lines = [" ".join(line.split()).strip() for line in raw.split("\n")]
    out = " ".join(line for line in lines if line).strip()
    out = re.sub(r"^(romaji|output)\s*:\s*", "", out, flags=re.IGNORECASE).strip()
    out = re.sub(r"\[[^\]]+\]", "", out).strip()
    return out


def _edge_japanese_romaji_text(text: str) -> str:
    """Chỉ transliterate câu Nhật đã có sẵn; tuyệt đối không dịch ở fallback."""
    clean = _clean_text(text)
    if not clean or not _edge_romaji_enabled() or not _contains_japanese_chars(clean):
        return ""

    try:
        from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
        plan = GLOBAL_TOKEN_PRESSURE_GOVERNOR.plan_request(
            "gemini", lane="romaji_localizer", prompt_tokens=max(64, len(clean) // 3),
            requested_output_tokens=160, optional_pass=True, min_prompt_tokens=64, min_output_tokens=64,
        )
        if not plan.allowed:
            return ""
    except Exception:
        plan = None

    api_key = _get_api_key()
    if not api_key:
        return ""

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "Transliterate the following Japanese text into Hepburn romaji. "
            "Do not translate, paraphrase, add labels, stage directions, or original text. "
            "Output only simple romaji and punctuation.\n\n"
            f"Japanese text:\n{clean}"
        )
        response = client.models.generate_content(
            model=os.environ.get("ERIS_TTS_LOCALIZER_MODEL", "gemini-2.5-flash").strip(),
            contents=prompt,
        )
        if plan is not None:
            try:
                GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_request(
                    "gemini", lane="romaji_localizer", prompt_tokens=max(64, len(prompt) // 3),
                    output_tokens=160,
                )
                GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_success("gemini")
            except Exception:
                pass
        return _clean_edge_romaji_output(getattr(response, "text", "") or "")
    except Exception as exc:
        logger.warning("[TTS] Edge JP romaji transliterator loi: %s", _short_error(exc))
        return ""


def _edge_text_candidates(text: str, language_hint: str = "") -> list[tuple[str, str]]:
    clean = _clean_text(text)
    if not clean:
        return []

    lang = normalize_language(language_hint)
    if lang == "ja":
        # Contract Nhật chỉ được fallback nếu transcript thật sự đã là Nhật. Nếu
        # Gemini chính định dịch trong prompt nhưng chết trước khi trả audio, Edge
        # không được gọi một LLM phụ để dịch lại. Khi đó im lặng an toàn còn hơn
        # đổi tiếng/giọng lén lút.
        if not _contains_japanese_chars(clean):
            return []
        candidates: list[tuple[str, str]] = [("raw", clean)]
        romaji = _edge_japanese_romaji_text(clean)
        if romaji:
            candidates.append(("romaji", romaji))
    else:
        candidates = [("raw", clean)]

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for mode, candidate in candidates:
        value = str(candidate or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append((mode, value))
    return result


def _mp3_file_to_wav_bytes(path: str) -> bytes:
    import miniaudio

    with open(path, "rb") as fh:
        mp3_bytes = fh.read()
    decoded = miniaudio.decode(mp3_bytes)
    samples = getattr(decoded, "samples", b"")
    if hasattr(samples, "tobytes"):
        pcm = samples.tobytes()
    else:
        pcm = bytes(samples)

    sample_width = int(getattr(decoded, "sample_width", 2) or 2)
    nchannels = int(getattr(decoded, "nchannels", 1) or 1)
    sample_rate = int(getattr(decoded, "sample_rate", 24000) or 24000)
    if not pcm:
        return b""

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _edge_tts_save_mp3(text: str, voice: str, path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(path)


def _synthesize_edge_tts_wav(text: str, *, language_hint: str = "") -> tuple[bytes, str]:
    text_candidates = _edge_text_candidates(text, language_hint)
    if not text_candidates or not _edge_tts_fallback_enabled():
        return b"", ""

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="eris_edge_tts_") as tmpdir:
        for voice in _edge_voice_candidates(language_hint):
            for mode, candidate_text in text_candidates:
                mp3_path = os.path.join(tmpdir, f"{voice}_{mode}.mp3")
                try:
                    asyncio.run(_edge_tts_save_mp3(candidate_text, voice, mp3_path))
                    if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) <= 0:
                        raise RuntimeError("Edge TTS returned an empty MP3")
                    wav_bytes = _mp3_file_to_wav_bytes(mp3_path)
                    if wav_bytes:
                        return wav_bytes, f"{voice}/{mode}"
                    raise RuntimeError("Edge TTS MP3 decode returned empty WAV")
                except Exception as exc:
                    errors.append(f"{voice}/{mode}: {_short_error(exc, limit=120)}")

    if errors:
        raise RuntimeError("; ".join(errors))
    return b"", ""


def _synthesize_windows_sapi_wav(text: str, *, language_hint: str = "") -> bytes:
    """Render WAV with built-in Windows SAPI when remote TTS quota is exhausted."""
    clean = _clean_text(text)
    if os.name != "nt" or not clean:
        return b""

    script = r"""
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$textPath = $env:ERIS_SAPI_TEXT_PATH
$wavPath = $env:ERIS_SAPI_WAV_PATH
$lang = ($env:ERIS_SAPI_LANGUAGE_HINT -as [string]).ToLowerInvariant()
$text = [System.IO.File]::ReadAllText($textPath, [System.Text.Encoding]::UTF8)
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $target = ""
    if ($lang.StartsWith("ja") -or $lang -eq "jp" -or $lang -eq "japanese") { $target = "ja" }
    elseif ($lang.StartsWith("vi")) { $target = "vi" }
    elseif ($lang.StartsWith("en")) { $target = "en" }
    if (-not $target) { throw "unsupported_language_contract" }
    $voice = $speaker.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name.ToLowerInvariant().StartsWith($target) } |
        Select-Object -First 1
    if (-not $voice) { throw "no_compatible_sapi_voice" }
    $speaker.SelectVoice($voice.VoiceInfo.Name)
    $speaker.Rate = -1
    $speaker.Volume = 100
    $speaker.SetOutputToWaveFile($wavPath)
    $speaker.Speak($text) | Out-Null
}
finally {
    $speaker.Dispose()
}
"""
    with tempfile.TemporaryDirectory(prefix="eris_tts_") as tmpdir:
        text_path = os.path.join(tmpdir, "input.txt")
        wav_path = os.path.join(tmpdir, "fallback.wav")
        with open(text_path, "w", encoding="utf-8") as fh:
            fh.write(clean)
        env = dict(os.environ)
        env["ERIS_SAPI_TEXT_PATH"] = text_path
        env["ERIS_SAPI_WAV_PATH"] = wav_path
        env["ERIS_SAPI_LANGUAGE_HINT"] = str(language_hint or "")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=20,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or "Windows SAPI fallback failed").strip())
        with open(wav_path, "rb") as fh:
            return fh.read()


def _try_local_tts_fallback(exc: Exception, *, fallback_text: str = "", language_hint: str = "") -> bytes:
    if not _local_tts_fallback_enabled() or not str(fallback_text or "").strip():
        return b""
    try:
        from runtime.rollout_control import feature_enabled
        pin_enabled = feature_enabled("tts_language_pin")
    except Exception:
        pin_enabled = str(os.environ.get("ERIS_TTS_LANGUAGE_PIN", "1") or "1").strip().lower() not in {"0", "false", "off", "no"}
    if not pin_enabled:
        language_hint = normalize_language("", text=fallback_text)
    expected_locale = _same_language_locale(language_hint)
    try:
        wav_bytes, voice = _synthesize_edge_tts_wav(fallback_text, language_hint=language_hint)
        if wav_bytes:
            actual_locale = "-".join(str(voice).split("/", 1)[0].split("-")[:2])
            try:
                from runtime.hardening_metrics import record_tts_fallback
                record_tts_fallback(provider="edge", locale=actual_locale, expected_locale=expected_locale, success=True, reason=type(exc).__name__)
            except Exception:
                pass
            logger.warning(
                "[TTS] Gemini TTS loi/quota (%s). Dung Edge fallback cung ngon ngu voice=%s.",
                _short_error(exc), voice,
            )
            return wav_bytes
        try:
            from runtime.hardening_metrics import record_tts_fallback
            record_tts_fallback(provider="edge", locale="", expected_locale=expected_locale, success=False, reason="same_language_candidate_unavailable")
        except Exception:
            pass
    except Exception as edge_exc:
        try:
            from runtime.hardening_metrics import record_tts_fallback
            record_tts_fallback(provider="edge", locale="", expected_locale=expected_locale, success=False, reason=type(edge_exc).__name__)
        except Exception:
            pass
        logger.warning("[TTS] Edge neural TTS fallback loi: %s", _short_error(edge_exc))

    if not _sapi_tts_fallback_enabled():
        return b""

    try:
        wav_bytes = _synthesize_windows_sapi_wav(fallback_text, language_hint=language_hint)
        if wav_bytes:
            try:
                from runtime.hardening_metrics import record_tts_fallback
                record_tts_fallback(provider="sapi", locale=expected_locale, expected_locale=expected_locale, success=True, reason=type(exc).__name__)
            except Exception:
                pass
            logger.warning("[TTS] Gemini TTS loi/quota (%s). Dung Windows SAPI cung ngon ngu.", _short_error(exc))
            return wav_bytes
    except Exception as sapi_exc:
        try:
            from runtime.hardening_metrics import record_tts_fallback
            record_tts_fallback(provider="sapi", locale="", expected_locale=expected_locale, success=False, reason=type(sapi_exc).__name__)
        except Exception:
            pass
        logger.warning("[TTS] Windows SAPI fallback loi: %s", _short_error(sapi_exc))
    return b""


def _extract_gemini_tts_pcm(response) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        for part in parts or []:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None) if inline_data is not None else None
            if data:
                return data
    raise RuntimeError("Gemini TTS không trả audio parts hợp lệ.")


def _tts_breaker_enabled() -> bool:
    try:
        from runtime.rollout_control import feature_enabled
        return feature_enabled("tts_breaker")
    except Exception:
        return os.environ.get("ERIS_TTS_BREAKER_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}


def _tts_max_attempts() -> int:
    try:
        return max(1, min(4, int(os.environ.get("ERIS_TTS_MAX_ATTEMPTS", "2") or 2)))
    except (TypeError, ValueError):
        return 2


def _same_language_locale(language_hint: str, locale: str = "") -> str:
    if str(locale or "").strip():
        return str(locale).strip()
    lang = normalize_language(language_hint)
    return {"vi": "vi-VN", "ja": "ja-JP", "en": "en-US"}.get(lang, lang)


def _synthesize_wav(
    prompt: str,
    voice: str,
    model: str,
    *,
    fallback_text: str = "",
    language_hint: str = "",
    locale: str = "",
) -> bytes:
    """Gọi Gemini TTS, trả về WAV bytes (24kHz, mono, 16-bit PCM)."""
    from google import genai
    from google.genai import types

    tts_budget_plan = None
    try:
        from llm.token_budget import estimate_tokens
        from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR

        estimated_prompt = estimate_tokens([{"role": "user", "content": prompt}])
        tts_budget_plan = GLOBAL_TOKEN_PRESSURE_GOVERNOR.plan_request(
            "gemini", lane="tts", prompt_tokens=estimated_prompt,
            requested_output_tokens=768, optional_pass=False,
            min_prompt_tokens=256, min_output_tokens=256,
        )
        # TTS là exact recitation. Cắt prompt âm thầm sẽ làm mất lời, nên khi một
        # segment vượt hard budget phải fail rõ để StageOutputPipeline chia nhỏ.
        if tts_budget_plan.prompt_limit < estimated_prompt:
            exc = RuntimeError(
                f"TTS segment vượt lane budget ({estimated_prompt}>{tts_budget_plan.prompt_limit}); "
                "hãy chia segment ở stage trước khi synthesize"
            )
            fallback = _try_local_tts_fallback(
                exc, fallback_text=fallback_text, language_hint=language_hint,
            )
            if fallback:
                return fallback
            raise exc
    except RuntimeError:
        raise
    except Exception:
        tts_budget_plan = None

    # Dùng key pool để tự động xoay key khi bị 429
    try:
        from llm.key_pool import get_key_pool
        pool = get_key_pool("gemini")
        pool_attempts = pool.size if (pool and pool.size > 0) else 1
    except Exception:
        pool = None
        pool_attempts = 1
    max_attempts = min(pool_attempts, _tts_max_attempts())

    breaker_key = ("gemini", str(model or ""), str(voice or ""), _same_language_locale(language_hint, locale))
    permit = None
    if _tts_breaker_enabled():
        permit = GLOBAL_TTS_BREAKER.allow(breaker_key)
        if not permit.allowed:
            exc = RuntimeError(f"TTS circuit breaker {permit.state.value}: {permit.reason}")
            fallback = _try_local_tts_fallback(exc, fallback_text=fallback_text, language_hint=language_hint)
            if fallback:
                return fallback
            raise exc

    last_exc = None
    pcm_data = None
    attempted_indices: set[int] = set()
    for attempt in range(max_attempts):
        lease = None
        if pool is not None and pool.size > 0:
            lease = pool.acquire(exclude_indices=attempted_indices)
            if lease is None:
                wait_s = pool.next_available_in()
                exc = RuntimeError(f"Gemini TTS key pool đang cooldown; thử lại sau khoảng {wait_s:.1f}s")
                fallback = _try_local_tts_fallback(
                    exc,
                    fallback_text=fallback_text,
                    language_hint=language_hint,
                )
                if fallback:
                    return fallback
                raise exc
            attempted_indices.add(lease.index)
            api_key = lease.key
        else:
            api_key = _get_api_key()
        if not api_key:
            raise RuntimeError("Không tìm thấy Gemini API key cho TTS.")

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice,
                            )
                        )
                    ),
                ),
            )
            pcm_data = _extract_gemini_tts_pcm(response)
            if tts_budget_plan is not None:
                try:
                    from llm.token_budget import estimate_tokens
                    from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                    GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_request(
                        "gemini", lane="tts",
                        prompt_tokens=estimate_tokens([{"role": "user", "content": prompt}]),
                        output_tokens=tts_budget_plan.output_tokens,
                    )
                except Exception:
                    pass
            if pool is not None and lease is not None:
                pool.mark_success(lease=lease)
            if _tts_breaker_enabled():
                GLOBAL_TTS_BREAKER.record_success(breaker_key)
            try:
                from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_success("gemini")
            except Exception:
                pass
            break
        except Exception as exc:
            last_exc = exc
            try:
                from llm.provider_errors import ProviderErrorKind, classify_provider_error
                error_kind = classify_provider_error(exc)
            except Exception:
                ProviderErrorKind = None  # type: ignore
                error_kind = None
            is_rate_limit = str(error_kind) == "rate_limit" or "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            is_revoked = str(error_kind) == "key_revoked"
            try:
                from google.genai.errors import ClientError
                if isinstance(exc, ClientError) and exc.code == 429:
                    is_rate_limit = True
                if isinstance(exc, ClientError) and exc.code in (401, 403) and "reported as leaked" in str(exc).lower():
                    is_revoked = True
            except Exception:
                pass

            error_text = str(exc).lower()
            is_invalid_shape = "audio parts" in error_text or "parts hợp lệ" in error_text or "nonetype" in error_text
            is_transient = bool(
                str(error_kind) == "transient_server"
                or any(code in error_text for code in ("500", "502", "503", "504", "temporarily unavailable"))
            )
            breaker_failure = ""
            if is_rate_limit:
                breaker_failure = "rate_limit"
            elif is_invalid_shape:
                breaker_failure = "invalid_shape"
            elif is_transient:
                breaker_failure = "transient_server"
            # Ở HALF_OPEN, bất kỳ probe nào lỗi cũng phải mở breaker lại.
            # Nếu chỉ tính 429/5xx, một lỗi auth/shape lạ sẽ giữ probes_in_flight
            # mãi mãi và breaker kẹt ở half-open.
            is_half_open_probe = bool(
                permit is not None and getattr(getattr(permit, "state", None), "value", "") == "half_open"
            )
            if _tts_breaker_enabled() and (breaker_failure or is_half_open_probe):
                GLOBAL_TTS_BREAKER.record_failure(
                    breaker_key,
                    kind=breaker_failure or str(error_kind or "provider_error"),
                )
            if is_rate_limit:
                try:
                    from llm.token_pressure import GLOBAL_TOKEN_PRESSURE_GOVERNOR
                    GLOBAL_TOKEN_PRESSURE_GOVERNOR.record_rate_limit("gemini", retry_after_s=60.0, lane="tts")
                except Exception:
                    pass

            if is_revoked and pool is not None and lease is not None:
                pool.mark_permanently_dead(lease=lease, reason="tts_key_reported_leaked")
                logger.warning(
                    "[TTS] Key index %s bị provider báo leaked/revoked; quarantine, không thử lại trong lượt sau.",
                    getattr(lease, "index", "?"),
                )
                if attempt < max_attempts - 1:
                    time.sleep(min(1.5, 0.20 * (2 ** attempt) + random.uniform(0.0, 0.20)))
                    continue

            if is_rate_limit and pool is not None:
                may_rotate = pool.mark_rate_limited(seconds=60.0, lease=lease, reason="tts_http_429")
                logger.warning(
                    "[TTS] Key index %s bị rate limit/hết quota (lượt %d/%d).",
                    getattr(lease, "index", "?"),
                    attempt + 1,
                    max_attempts,
                )
                if may_rotate and attempt < max_attempts - 1:
                    time.sleep(min(1.5, 0.20 * (2 ** attempt) + random.uniform(0.0, 0.20)))
                    continue
            elif (is_invalid_shape or is_transient) and attempt < max_attempts - 1:
                time.sleep(min(1.5, 0.20 * (2 ** attempt) + random.uniform(0.0, 0.20)))
                continue
            fallback = _try_local_tts_fallback(exc, fallback_text=fallback_text, language_hint=language_hint)
            if fallback:
                return fallback
            raise

    if pcm_data is None:
        if last_exc:
            fallback = _try_local_tts_fallback(last_exc, fallback_text=fallback_text, language_hint=language_hint)
            if fallback:
                return fallback
            raise last_exc
        raise RuntimeError("Không thể tổng hợp giọng nói từ Gemini API.")

    if audio_polish_enabled():
        try:
            polished = polish_pcm16_mono(pcm_data, sample_rate=24000)
            pcm_data = polished.pcm or pcm_data
            stats = polished.stats
            if stats.trimmed_head_ms or stats.trimmed_tail_ms or stats.compressed_pause_ms:
                logger.debug(
                    "[TTS] Audio polish: %dms → %dms, trim=%d/%dms, compressed_pause=%dms, peak=%d→%d",
                    stats.original_ms,
                    stats.polished_ms,
                    stats.trimmed_head_ms,
                    stats.trimmed_tail_ms,
                    stats.compressed_pause_ms,
                    stats.peak_before,
                    stats.peak_after,
                )
        except Exception as exc:
            # Hậu xử lý chỉ là lớp polish. Nếu lỗi, dùng PCM gốc để không làm TTS câm.
            logger.warning("[TTS] Audio polish lỗi, dùng audio gốc: %s", exc)

    # Wrap vào WAV để miniaudio hiểu
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)       # 16-bit
        wf.setframerate(24000)   # 24kHz
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _invoke_synthesize_wav(
    prompt: str,
    voice: str,
    model: str,
    **kwargs,
) -> bytes:
    """Gọi synth với contract mới nhưng vẫn tương thích adapter/mock cũ.

    Kiểm tra chữ ký trước khi gọi, không bắt bừa ``TypeError`` phát sinh bên
    trong provider. Nhờ vậy backend cũ ba tham số vẫn sống trong giai đoạn migration.
    """
    try:
        params = tuple(inspect.signature(_synthesize_wav).parameters.values())
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        names = {p.name for p in params}
    except (TypeError, ValueError):
        accepts_kwargs = True
        names = set(kwargs)
    supported = kwargs if accepts_kwargs else {key: value for key, value in kwargs.items() if key in names}
    return _synthesize_wav(prompt, voice, model, **supported)


def _concat_wav_bytes(*items: bytes) -> bytes:
    """Ghép nhiều WAV PCM cùng format thành một WAV.

    Dùng cho vocal prefix cache: prefix và câu chính được synth riêng, nhưng phát
    ra như một audio duy nhất để tránh gap do mở playback hai lần.
    """
    chunks = [item for item in items if item]
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]

    params = None
    frames: list[bytes] = []
    for wav_bytes in chunks:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                current = wf.getparams()
                if params is None:
                    params = current
                elif (
                    current.nchannels != params.nchannels
                    or current.sampwidth != params.sampwidth
                    or current.framerate != params.framerate
                ):
                    return chunks[-1]
                frames.append(wf.readframes(wf.getnframes()))
        except Exception:
            return chunks[-1]
    if params is None:
        return b""
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(params.nchannels)
        wf.setsampwidth(params.sampwidth)
        wf.setframerate(params.framerate)
        wf.writeframes(b"".join(frames))
    return out.getvalue()


def _wav_duration_seconds(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            framerate = max(1, int(wf.getframerate() or 24000))
            frames = max(0, int(wf.getnframes() or 0))
            return frames / float(framerate)
    except Exception:
        return 0.0


def _apply_output_volume(wav_bytes: bytes) -> bytes:
    """Scale PCM16 volume before playback, without depending on audioop/numpy."""

    volume = _output_volume()
    if not wav_bytes or abs(volume - 1.0) < 0.001:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
        if params.sampwidth != 2:
            return wav_bytes

        sample_count = len(frames) // 2
        samples = struct.unpack("<" + "h" * sample_count, frames)
        scaled = bytearray(len(frames))
        for index, sample in enumerate(samples):
            value = max(-32768, min(32767, int(sample * volume)))
            struct.pack_into("<h", scaled, index * 2, value)

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setparams(params)
            wf.writeframes(bytes(scaled))
        return out.getvalue()
    except Exception as exc:
        logger.debug("[TTS] volume transform skipped: %s", exc)
        return wav_bytes


def _play_wav_winsound(wav_bytes: bytes, stop_event: threading.Event) -> bool:
    if os.name != "nt":
        return False
    try:
        import winsound
        import time

        duration = max(0.05, _wav_duration_seconds(wav_bytes))
        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        started_at = time.time()
        while (time.time() - started_at) < duration:
            if stop_event.is_set():
                winsound.PlaySound(None, 0)
                return True
            time.sleep(0.02)
        return True
    except Exception as exc:
        logger.debug("[TTS] winsound playback unavailable: %s", exc)
        return False


def _play_wav_bytes(wav_bytes: bytes, stop_event: threading.Event) -> None:
    """Phát WAV bytes qua backend phù hợp. Windows ưu tiên winsound."""
    wav_bytes = _apply_output_volume(wav_bytes)
    if _play_wav_winsound(wav_bytes, stop_event):
        return
    try:
        import sounddevice as sd
        import numpy as np

        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            sr = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        dtype = np.int16 if sampwidth == 2 else np.int32
        arr = np.frombuffer(frames, dtype=dtype).astype(np.float32)
        arr /= float(2 ** (sampwidth * 8 - 1))
        if channels > 1:
            arr = arr.reshape(-1, channels)

        chunk_size = sr // 10  # 100ms mỗi chunk
        idx = 0
        with sd.OutputStream(samplerate=sr, channels=channels, dtype="float32") as stream:
            while idx < len(arr) and not stop_event.is_set():
                end = min(idx + chunk_size, len(arr))
                stream.write(arr[idx:end])
                idx = end

    except ImportError:
        # Fallback: miniaudio
        _play_wav_miniaudio(wav_bytes, stop_event)
    except Exception as exc:
        logger.warning("[TTS] sounddevice playback lỗi, fallback miniaudio: %s", exc)
        _play_wav_miniaudio(wav_bytes, stop_event)


def _play_wav_miniaudio(wav_bytes: bytes, stop_event: threading.Event) -> None:
    """Phát WAV qua miniaudio (không cần sounddevice)."""
    import miniaudio

    def _pcm_stream():
        decoded = miniaudio.decode(wav_bytes)
        chunk = 4096
        data = bytes(decoded.samples)
        for i in range(0, len(data), chunk * decoded.nchannels * 2):
            if stop_event.is_set():
                return
            yield data[i : i + chunk * decoded.nchannels * 2]

    device = miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000,
    )
    stream = miniaudio.stream_with_callbacks(
        _pcm_stream(),
        playback_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000,
    )
    with device:
        device.start(stream)
        import time
        while device.is_active() and not stop_event.is_set():
            time.sleep(0.05)


def _translate_to_japanese(text: str, api_key: str) -> str:
    """Dịch câu tiếng Việt/Anh sang tiếng Nhật (giọng dễ thương) bằng Gemini."""
    from google import genai
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are a translation assistant. Translate the following Vietnamese or English sentence "
            "into natural, gentle, and polite Japanese, suitable for a soft anime girl companion speaking "
            "to the user. Avoid titles such as ご主人様 or マスター; prefer polite Japanese "
            "that omits second-person address when possible. "
            "Output ONLY the Japanese translation, with absolutely no quotes, annotations, or English/Vietnamese explanations.\n\n"
            f"Sentence to translate: {text}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        translated = (response.text or "").strip()
        if translated.startswith('"') and translated.endswith('"'):
            translated = translated[1:-1].strip()
        if translated.startswith("'") and translated.endswith("'"):
            translated = translated[1:-1].strip()
        if translated:
            return translated
    except Exception as exc:
        logger.warning("[TTS] Dịch sang JP lỗi: %s", exc)
    return text


# ── Worker thread ─────────────────────────────────────────────────────────────

class _SpeakRequest:
    __slots__ = (
        "text",
        "valence",
        "arousal",
        "stance",
        "on_start_play",
        "prelocalized",
        "prosody_style",
        "prosody_notes",
        "turn_id",
        "segment_id",
        "interruptible",
        "vocal_cache_kind",
        "vocal_prefix",
        "language_hint",
        "voice_family",
        "locale",
        "on_event",
    )

    def __init__(
        self,
        text: str,
        valence: float = 0.0,
        arousal: float = 0.3,
        stance: str = "",
        on_start_play = None,
        prelocalized: bool = False,
        prosody_style: str = "",
        prosody_notes: str = "",
        turn_id: str = "",
        segment_id: int = 0,
        interruptible: bool = True,
        vocal_cache_kind: str = "",
        vocal_prefix: str = "",
        language_hint: str = "",
        voice_family: str = "",
        locale: str = "",
        on_event = None,
    ):
        self.text = text
        self.valence = valence
        self.arousal = arousal
        self.stance = stance
        self.on_start_play = on_start_play
        # True khi StageFrame đã chuẩn bị sẵn tts_text theo ngôn ngữ cần đọc.
        # Khi đó engine không dịch lại, tránh "dịch một câu Nhật sang Nhật" làm mất tự nhiên.
        self.prelocalized = bool(prelocalized)
        self.prosody_style = str(prosody_style or "")
        self.prosody_notes = str(prosody_notes or "")
        self.turn_id = str(turn_id or "")
        try:
            self.segment_id = int(segment_id)
        except (TypeError, ValueError):
            self.segment_id = 0
        self.interruptible = bool(interruptible)
        self.vocal_cache_kind = str(vocal_cache_kind or "")
        self.vocal_prefix = str(vocal_prefix or "")
        self.language_hint = str(language_hint or "")
        self.voice_family = str(voice_family or "")
        self.locale = str(locale or "")
        self.on_event = on_event


class _TtsWorker:
    def __init__(self, voice: str, model: str, language_hint: str) -> None:
        self._voice = voice
        self._model = model
        self._language_hint = language_hint
        self._localizer = SpeechLocalizer()
        self._prosody = ProsodyDirector()
        self._vocal_cache = VocalCache()
        self._queue: queue.Queue[Optional[_SpeakRequest]] = queue.Queue(maxsize=_queue_size())
        self._stop_event = threading.Event()
        self._current_stop = threading.Event()
        self._current_req: Optional[_SpeakRequest] = None
        self._current_lock = threading.RLock()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TTS-Worker")
        self._thread.start()

    def speak(self, req: _SpeakRequest, *, replace: bool = True) -> None:
        """Enqueue một đoạn TTS.

        ``replace=True`` giữ hành vi cũ: câu mới cắt câu đang nói. Khi sau này
        StageDispatcher tách một lượt thành nhiều segment, caller có thể dùng
        ``replace=False`` để phát tuần tự segment 0, 1, 2.
        """
        if replace:
            self._current_stop.set()
            self._drain_pending(reason="replaced")
        try:
            self._queue.put_nowait(req)
        except queue.Full:
            self._drop_one_pending(reason="queue_full")
            try:
                self._queue.put_nowait(req)
            except queue.Full:
                self._emit(req, "audio_failed", reason="queue_full", error="TTS queue is full")
                return
        self._emit(req, "audio_queued")

    def shutdown(self) -> None:
        self._stop_event.set()
        self._current_stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _emit(self, req: Optional[_SpeakRequest], event_type: str, *, reason: str = "", error: str = "") -> None:
        if req is None:
            return
        event = TtsPlaybackEvent(
            type=event_type,
            turn_id=req.turn_id,
            segment_id=req.segment_id,
            text=req.text,
            reason=reason,
            error=error,
        )
        callback = getattr(req, "on_event", None)
        if callback is not None:
            try:
                callback(event)
            except Exception as cb_exc:
                logger.error("[TTS] Error in on_event callback: %s", cb_exc)

    def _drop_one_pending(self, *, reason: str) -> None:
        try:
            old = self._queue.get_nowait()
        except queue.Empty:
            return
        if old is not None:
            self._emit(old, "audio_cancelled", reason=reason)

    def _drain_pending(self, *, reason: str) -> None:
        while True:
            try:
                old = self._queue.get_nowait()
            except queue.Empty:
                return
            if old is not None:
                self._emit(old, "audio_cancelled", reason=reason)

    def cancel_current(self, *, reason: str = "cancelled", only_interruptible: bool = True) -> bool:
        """Dừng đoạn TTS đang chạy và bỏ các đoạn đang chờ.

        Coordinator gọi hàm này khi user chen vào. Worker vẫn tự emit
        ``audio_cancelled`` ở vòng phát hiện tại; hàm này chỉ bật cờ dừng thật
        nhanh, để loa không tiếp tục đọc như máy sau khi lượt đã đổi sang user.
        """
        with self._current_lock:
            current = self._current_req
            if current is None:
                self._drain_pending(reason=reason)
                return False
            if only_interruptible and not bool(getattr(current, "interruptible", True)):
                return False
            self._current_stop.set()
        self._drain_pending(reason=reason)
        return True

    def _request_language(self, req: _SpeakRequest) -> str:
        return _normalize_language_hint(req.language_hint or self._language_hint)

    def _request_voice(self, req: _SpeakRequest) -> str:
        requested = str(req.voice_family or "").strip()
        if not requested or requested.lower() in {"eris_primary", "primary", "default"}:
            return self._voice
        return requested

    def _request_locale(self, req: _SpeakRequest) -> str:
        return _same_language_locale(self._request_language(req), req.locale)

    def _vocal_prefix_wav(self, req: _SpeakRequest, prefix: str, prosody_plan) -> bytes:
        """Lấy/sinh WAV cho prefix nghe được như "Hah... haha.".

        Prefix cache dùng prompt riêng, rất ngắn. Nếu cache miss thì sinh một lần
        rồi lưu. Nếu lỗi cache/synth, trả b"" để câu chính vẫn được đọc bình thường.
        """
        prefix = str(prefix or "").strip()
        if not prefix or not vocal_cache_enabled():
            return b""
        kind = str(getattr(req, "vocal_cache_kind", "") or "vocal_prefix")
        language_hint = self._request_language(req)
        voice = self._request_voice(req)
        locale = self._request_locale(req)
        key = VocalCacheKey(
            voice=voice,
            model=self._model,
            kind=kind,
            style=req.prosody_style or getattr(prosody_plan, "style", "") or "neutral",
            text=prefix,
            language_hint=language_hint,
        )
        cached = self._vocal_cache.get(key)
        if cached:
            logger.debug("[TTS] Vocal cache hit kind=%s text=%r", kind, prefix)
            return cached

        try:
            prefix_plan = self._prosody.plan(
                prefix,
                stance=req.stance,
                valence=req.valence,
                arousal=req.arousal,
                style_hint=req.prosody_style or getattr(prosody_plan, "style", ""),
                notes_hint=(
                    "Render only this short nonverbal vocalization. "
                    "Do not add words before or after it."
                ),
            )
            marked = render_tts_markup(prefix, prefix_plan)
            prompt = _build_tts_prompt(
                marked,
                "",
                language_hint,
                prosody_notes=prefix_plan.director_notes,
                prelocalized=True,
                quality_mode=_quality_mode(),
            )
            wav_bytes = _invoke_synthesize_wav(
                prompt,
                voice,
                self._model,
                fallback_text=prefix,
                language_hint=language_hint,
                locale=locale,
            )
            self._vocal_cache.put(key, wav_bytes)
            logger.debug("[TTS] Vocal cache stored kind=%s text=%r", kind, prefix)
            return wav_bytes
        except Exception as exc:
            logger.debug("[TTS] Vocal cache synth miss failed: %s", exc)
            return b""

    def synthesize(self, req: _SpeakRequest) -> bytes:
        """Sinh WAV cho một request nhưng chưa phát ra loa.

        Đây là cửa backend cho ``TtsTaskManager``: nhiều segment có thể synth song
        song, còn manager chịu trách nhiệm phát theo đúng ``segment_id``. Worker cũ
        vẫn dùng đường ``speak`` tuần tự để tương thích với code hiện có.
        """

        language_hint = self._request_language(req)
        voice = self._request_voice(req)
        locale = self._request_locale(req)
        audio_tag = _emotion_to_tag(req.valence, req.arousal, req.stance)
        vocal_prefix = str(getattr(req, "vocal_prefix", "") or "").strip()
        main_text_raw = strip_audible_prefix(req.text, vocal_prefix) if vocal_prefix else req.text
        prefix_is_separate = bool(vocal_prefix and main_text_raw != req.text)
        text_to_speak = main_text_raw
        localized = bool(req.prelocalized)
        if language_hint == "ja" and _prelocalize_japanese_enabled() and not req.prelocalized:
            # Dịch/style chạy ở backend nhưng trả về WAV thuần. Manager không cần
            # biết câu đã localize thế nào, chỉ cần audio bytes để xếp hàng phát.
            text_to_speak = self._localizer.localize(
                main_text_raw,
                language_hint=language_hint,
                prosody_style=req.prosody_style,
            )
            localized = text_to_speak != main_text_raw
        prosody_plan = self._prosody.plan(
            text_to_speak,
            stance=req.stance,
            valence=req.valence,
            arousal=req.arousal,
            fallback_tag=audio_tag,
            notes_hint=req.prosody_notes,
            style_hint=req.prosody_style,
        )
        main_wav = b""
        if str(text_to_speak or "").strip():
            marked_text = render_tts_markup(text_to_speak, prosody_plan)
            prompt = _build_tts_prompt(
                marked_text,
                "",
                language_hint,
                prosody_notes=prosody_plan.director_notes,
                prelocalized=localized or req.prelocalized,
                quality_mode=_quality_mode(),
            )
            main_wav = _invoke_synthesize_wav(
                prompt,
                voice,
                self._model,
                fallback_text=text_to_speak,
                language_hint=language_hint,
                locale=locale,
            )

        logger.debug(
            "[TTS] valence=%.2f arousal=%.2f stance=%r → style=%r tag=%r",
            req.valence, req.arousal, req.stance, prosody_plan.style, prosody_plan.opening_tag,
        )

        prefix_wav = b""
        if prefix_is_separate:
            prefix_wav = self._vocal_prefix_wav(req, vocal_prefix, prosody_plan)
        return _concat_wav_bytes(prefix_wav, main_wav) or main_wav or prefix_wav

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                req = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if req is None:
                break

            self._current_stop.clear()
            with self._current_lock:
                self._current_req = req
            callback_called = False
            try:
                try:
                    language_hint = self._request_language(req)
                    voice = self._request_voice(req)
                    locale = self._request_locale(req)
                    audio_tag = _emotion_to_tag(req.valence, req.arousal, req.stance)
                    vocal_prefix = str(getattr(req, "vocal_prefix", "") or "").strip()
                    main_text_raw = strip_audible_prefix(req.text, vocal_prefix) if vocal_prefix else req.text
                    prefix_is_separate = bool(vocal_prefix and main_text_raw != req.text)
                    text_to_speak = main_text_raw
                    localized = bool(req.prelocalized)
                    if language_hint == "ja" and _prelocalize_japanese_enabled() and not req.prelocalized:
                        # Dịch/style TTS chạy trong worker nền để UI/runtime không bị
                        # kẹt bởi một call Gemini phụ. Engine vẫn chỉ nhận text sạch.
                        text_to_speak = self._localizer.localize(
                            main_text_raw,
                            language_hint=language_hint,
                            prosody_style=req.prosody_style,
                        )
                        localized = text_to_speak != main_text_raw
                    prosody_plan = self._prosody.plan(
                        text_to_speak,
                        stance=req.stance,
                        valence=req.valence,
                        arousal=req.arousal,
                        fallback_tag=audio_tag,
                        notes_hint=req.prosody_notes,
                        style_hint=req.prosody_style,
                    )
                    main_wav = b""
                    if str(text_to_speak or "").strip():
                        marked_text = render_tts_markup(text_to_speak, prosody_plan)
                        prompt = _build_tts_prompt(
                            marked_text,
                            "",
                            language_hint,
                            prosody_notes=prosody_plan.director_notes,
                            prelocalized=localized or req.prelocalized,
                            quality_mode=_quality_mode(),
                        )
                        main_wav = _invoke_synthesize_wav(
                            prompt,
                            voice,
                            self._model,
                            fallback_text=text_to_speak,
                            language_hint=language_hint,
                            locale=locale,
                        )

                    logger.debug(
                        "[TTS] valence=%.2f arousal=%.2f stance=%r → style=%r tag=%r",
                        req.valence, req.arousal, req.stance, prosody_plan.style, prosody_plan.opening_tag,
                    )

                    prefix_wav = b""
                    if prefix_is_separate:
                        prefix_wav = self._vocal_prefix_wav(req, vocal_prefix, prosody_plan)
                    wav_bytes = _concat_wav_bytes(prefix_wav, main_wav) or main_wav or prefix_wav

                    if self._current_stop.is_set():
                        self._emit(req, "audio_cancelled", reason="cancelled_before_playback")
                    else:
                        if req.on_start_play is not None:
                            try:
                                req.on_start_play()
                            except Exception as cb_exc:
                                logger.error("[TTS] Error in on_start_play callback: %s", cb_exc)
                            callback_called = True
                        self._emit(req, "audio_start")
                        _play_wav_bytes(wav_bytes, self._current_stop)
                        if self._current_stop.is_set():
                            self._emit(req, "audio_cancelled", reason="cancelled_during_playback")
                        else:
                            self._emit(req, "audio_done")

                except Exception as exc:
                    self._emit(req, "audio_failed", error=str(exc))
                    logger.warning("[TTS] Lỗi: %s", exc)
                    # _synthesize_wav đã đánh dấu đúng lease gây 429. Không được
                    # mark "key hiện tại" lần nữa ở đây vì thread khác có thể đã xoay pool.
            finally:
                if not callback_called and req.on_start_play is not None:
                    try:
                        req.on_start_play()
                    except Exception as cb_exc:
                        logger.error("[TTS] Error in fallback on_start_play callback: %s", cb_exc)
                with self._current_lock:
                    if self._current_req is req:
                        self._current_req = None


# ── Public API ────────────────────────────────────────────────────────────────

class TtsEngine:
    """Engine TTS chính. Gắn vào coordinator.tts_engine."""

    def __init__(self) -> None:
        self._worker: Optional[_TtsWorker] = None
        self._ok = False
        self._closed = False
        self._config_lock = threading.RLock()
        self._config_signature = ""

        if not _enabled():
            logger.info("[TTS] Đã tắt bởi runtime settings.")
            return

        # Kiểm tra google-genai
        try:
            import google.genai  # noqa: F401
        except ImportError:
            logger.warning("[TTS] google-genai chưa cài. Chạy: pip install google-genai")
            return

        # Kiểm tra API key
        if not _get_api_key():
            logger.warning(
                "[TTS] Không tìm thấy Gemini API key. "
                "Set ERIS_SPEECH_API_KEY hoặc GEMINI_API_KEY trong .env/secrets.json"
            )
            return

        voice = _voice()
        model = _model()
        lang = _language_hint()
        self._worker = _TtsWorker(voice, model, lang)
        self._config_signature = f"{voice}|{model}|{lang}"
        self._ok = True
        logger.info("[TTS] Khởi động. Model=%s Voice=%s Language=%s", model, voice, lang)

    def refresh_configuration(self) -> bool:
        """Nạp lại language setting và dựng worker mới nếu dropdown đã đổi."""
        # Không biến một engine đã tắt/khởi động lỗi thành enabled chỉ vì panel
        # đổi language. Chỉ hot-reload worker đã khởi động thành công.
        if self._closed or not self._ok or self._worker is None:
            return False
        voice = _voice()
        model = _model()
        lang = _language_hint()
        signature = f"{voice}|{model}|{lang}"
        with self._config_lock:
            if signature == self._config_signature:
                return False
            old_signature = self._config_signature or "<none>"
            manager = getattr(self, "task_manager", None)
            if manager is not None and callable(getattr(manager, "shutdown", None)):
                try:
                    manager.shutdown()
                except Exception as exc:
                    logger.debug("[TTS] task manager config refresh failed: %s", exc)
                self.task_manager = None
            old_worker = self._worker
            if old_worker is not None:
                old_worker.shutdown()
            self._worker = _TtsWorker(voice, model, lang)
            self._config_signature = signature
            self._ok = True
            logger.info("[TTS] Đã nạp lại setting. %s -> %s (Language=%s)", old_signature, signature, lang)
            return True

    def speak(
        self,
        text: str,
        *,
        valence: float = 0.0,
        arousal: float = 0.3,
        stance: str = "",
        on_start_play = None,
        prelocalized: bool = False,
        prosody_style: str = "",
        prosody_notes: str = "",
        turn_id: str = "",
        segment_id: int = 0,
        interruptible: bool = True,
        vocal_cache_kind: str = "",
        vocal_prefix: str = "",
        language_hint: str = "",
        voice_family: str = "",
        locale: str = "",
        replace: bool = True,
        on_event = None,
    ) -> None:
        """Phát TTS cho text với cảm xúc cho trước. Non-blocking."""
        self.refresh_configuration()
        if not _enabled() or not self._ok or self._worker is None:
            if on_event is not None:
                try:
                    on_event(TtsPlaybackEvent(type="audio_failed", text=str(text or ""), reason="tts_disabled"))
                except Exception as cb_exc:
                    logger.error("[TTS] Error in on_event callback: %s", cb_exc)
            if on_start_play is not None:
                try:
                    on_start_play()
                except Exception as cb_exc:
                    logger.error("[TTS] Error in fallback on_start_play callback: %s", cb_exc)
            return
        clean = _clean_text(text)
        if not clean:
            if on_event is not None:
                try:
                    on_event(TtsPlaybackEvent(type="audio_cancelled", text=str(text or ""), reason="empty_text"))
                except Exception as cb_exc:
                    logger.error("[TTS] Error in on_event callback: %s", cb_exc)
            if on_start_play is not None:
                try:
                    on_start_play()
                except Exception as cb_exc:
                    logger.error("[TTS] Error in fallback on_start_play callback: %s", cb_exc)
            return
        self._worker.speak(
            _SpeakRequest(
                clean,
                valence,
                arousal,
                stance,
                on_start_play,
                prelocalized=prelocalized,
                prosody_style=prosody_style,
                prosody_notes=prosody_notes,
                turn_id=turn_id,
                segment_id=segment_id,
                interruptible=interruptible,
                vocal_cache_kind=vocal_cache_kind,
                vocal_prefix=vocal_prefix,
                language_hint=language_hint,
                voice_family=voice_family,
                locale=locale,
                on_event=on_event,
            ),
            replace=replace,
        )

    def shutdown(self) -> None:
        self._closed = True
        manager = getattr(self, "task_manager", None)
        if manager is not None and callable(getattr(manager, "shutdown", None)):
            try:
                manager.shutdown()
            except Exception as exc:
                logger.debug("[TTS] task manager shutdown failed: %s", exc)
        if self._worker is not None:
            self._worker.shutdown()
            self._worker = None

    def cancel_current(self, *, reason: str = "cancelled", only_interruptible: bool = True) -> bool:
        """Public API để runtime dừng TTS khi user cắt lượt."""
        manager = getattr(self, "task_manager", None)
        if manager is not None and callable(getattr(manager, "cancel_current", None)):
            try:
                if manager.cancel_current(reason=reason, only_interruptible=only_interruptible):
                    return True
            except Exception as exc:
                logger.debug("[TTS] task manager cancel failed: %s", exc)
        if not self._ok or self._worker is None:
            return False
        return self._worker.cancel_current(reason=reason, only_interruptible=only_interruptible)

    def synthesize(
        self,
        text: str,
        *,
        valence: float = 0.0,
        arousal: float = 0.3,
        stance: str = "",
        prelocalized: bool = False,
        prosody_style: str = "",
        prosody_notes: str = "",
        turn_id: str = "",
        segment_id: int = 0,
        interruptible: bool = True,
        vocal_cache_kind: str = "",
        vocal_prefix: str = "",
        language_hint: str = "",
        voice_family: str = "",
        locale: str = "",
    ) -> bytes:
        """Backend API mới: text sạch -> WAV bytes, chưa phát ra loa."""
        self.refresh_configuration()
        if not _enabled() or not self._ok or self._worker is None:
            raise RuntimeError("tts_disabled")
        clean = _clean_text(text)
        if not clean:
            return b""
        req = _SpeakRequest(
            clean,
            valence,
            arousal,
            stance,
            None,
            prelocalized=prelocalized,
            prosody_style=prosody_style,
            prosody_notes=prosody_notes,
            turn_id=turn_id,
            segment_id=segment_id,
            interruptible=interruptible,
            vocal_cache_kind=vocal_cache_kind,
            vocal_prefix=vocal_prefix,
            language_hint=language_hint,
            voice_family=voice_family,
            locale=locale,
            on_event=None,
        )
        return self._worker.synthesize(req)

    def play_audio(self, wav_bytes: bytes, stop_event: threading.Event) -> None:
        """Backend API mới: phát WAV bytes, có cờ dừng từ task manager."""
        if wav_bytes:
            _play_wav_bytes(wav_bytes, stop_event)

    def cache_signature(self) -> str:
        """Chữ ký cấu hình TTS để task manager cache đúng voice/model/style."""
        with self._config_lock:
            signature = self._config_signature or f"{_voice()}|{_model()}|{_language_hint()}"
        return f"{signature}|{_quality_mode()}"


def _clean_text(text: str) -> str:
    """Bỏ markdown/code/URL trước khi đọc, nhưng giữ line break có chủ ý."""
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"```.*?```", "", t, flags=re.S)
    t = re.sub(r"\*{1,2}([^*]*)\*{1,2}", r"\1", t)
    t = re.sub(r"_{1,2}([^_]*)_{1,2}", r"\1", t)
    t = re.sub(r"`{1,3}[^`]*`{1,3}", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = _strip_tts_honorifics(t)
    # Space ngang thì gọn lại; newline giữ lại để stage/dispatcher truyền nhịp
    # sang Gemini như các breath group ngắn.
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r" *\n+ *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n")).strip()
    return t


def build_tts_engine() -> TtsEngine:
    """Entry point — gọi một lần trong vision.py."""
    return TtsEngine()


__all__ = ["TtsEngine", "TtsPlaybackEvent", "build_tts_engine"]
