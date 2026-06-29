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
import logging
import os
import queue
import re
import struct
import threading
import wave
from dataclasses import dataclass
from typing import Optional

from runtime.prosody_director import ProsodyDirector
from runtime.speech_localizer import SpeechLocalizer
from runtime.tts_audio_polish import audio_polish_enabled, polish_pcm16_mono
from runtime.tts_markup import render_tts_markup
from runtime.vocal_cache import VocalCache, VocalCacheKey, strip_audible_prefix, vocal_cache_enabled

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

# ── Feature flag ──────────────────────────────────────────────────────────────

def _enabled() -> bool:
    return os.environ.get("ERIS_TTS_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}

def _voice() -> str:
    # Aoede = Breezy nữ; Leda = Youthful nữ; Achernar = Soft nữ
    return os.environ.get("ERIS_TTS_VOICE", "Aoede").strip()

def _model() -> str:
    # gemini-2.5-flash-preview-tts = stable TTS model hiện tại (2025-06+)
    # gemini-3.1-flash-tts-preview đã deprecated/không ổn định, dễ trả về 404
    return os.environ.get("ERIS_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()

def _language_hint() -> str:
    # "auto" = detect từ text; "ja" = ép Japanese; "vi" = Vietnamese; v.v.
    return os.environ.get("ERIS_TTS_LANGUAGE", "auto").strip()


def _quality_mode() -> str:
    """balanced | high.

    ``high`` không gọi thêm API; nó chỉ đổi prompt/markup để Gemini diễn câu kỹ
    hơn. Nếu cần latency thấp hơn, set ERIS_TTS_QUALITY=balanced.
    """
    value = os.environ.get("ERIS_TTS_QUALITY", "high").strip().lower()
    return value if value in {"balanced", "high"} else "high"


def _queue_size() -> int:
    raw = os.environ.get("ERIS_TTS_QUEUE_SIZE", "4").strip()
    try:
        return max(1, min(24, int(raw)))
    except ValueError:
        return 4

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
                    "gentle Japanese first (appropriate for a soft, polite anime girl companion speaking to her Master/Ngài), "
                    "then read the Japanese translation aloud in Japanese. Do not read the original non-Japanese text.\n"
                )
        elif language_hint == "vi":
            lang_line = "The transcript is in Vietnamese. Read it in Vietnamese.\n"
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
            "- Do not read ellipses as words; use them only as tiny pauses.\n\n"
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
        "Pacing: Unhurried but responsive. Let tiny silences breathe; do not stall between short lines.\n\n"
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
            return pool.current_key()
    except Exception:
        pass

    # 2. Speech key (đã set trong secrets.json)
    key = os.environ.get("ERIS_SPEECH_API_KEY", "").strip()
    if key:
        return key
    # 3. Fallback key chung
    for env_name in ("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key and not key.startswith("PASTE_"):
            return key
    return ""


def _synthesize_wav(prompt: str, voice: str, model: str) -> bytes:
    """Gọi Gemini TTS, trả về WAV bytes (24kHz, mono, 16-bit PCM)."""
    from google import genai
    from google.genai import types

    # Dùng key pool để tự động xoay key khi bị 429
    try:
        from llm.key_pool import get_key_pool
        pool = get_key_pool("gemini")
        max_attempts = pool.size if (pool and pool.size > 0) else 1
    except Exception:
        pool = None
        max_attempts = 1

    last_exc = None
    pcm_data = None
    for attempt in range(max_attempts):
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
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            break
        except Exception as exc:
            last_exc = exc
            is_rate_limit = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            try:
                from google.genai.errors import ClientError
                if isinstance(exc, ClientError) and exc.code == 429:
                    is_rate_limit = True
            except Exception:
                pass

            if is_rate_limit and pool is not None and attempt < max_attempts - 1:
                logger.warning("[TTS] Key index %d bị rate limit/hết quota (lượt %d/%d). Đang xoay key...", pool.index(), attempt + 1, max_attempts)
                pool.mark_dead(seconds=60.0)
                pool.rotate()
                continue
            raise

    if pcm_data is None:
        if last_exc:
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


def _play_wav_bytes(wav_bytes: bytes, stop_event: threading.Event) -> None:
    """Phát WAV bytes qua sounddevice. Fallback → miniaudio stream."""
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
            "to her Master/Ngài (e.g., using polite forms like ご主人様, です, ます, etc.). "
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

    def _vocal_prefix_wav(self, req: _SpeakRequest, prefix: str, prosody_plan) -> bytes:
        """Lấy/sinh WAV cho prefix nghe được như "Hah... haha.".

        Prefix cache dùng prompt riêng, rất ngắn. Nếu cache miss thì sinh một lần
        rồi lưu. Nếu lỗi cache/synth, trả b"" để câu chính vẫn được đọc bình thường.
        """
        prefix = str(prefix or "").strip()
        if not prefix or not vocal_cache_enabled():
            return b""
        kind = str(getattr(req, "vocal_cache_kind", "") or "vocal_prefix")
        key = VocalCacheKey(
            voice=self._voice,
            model=self._model,
            kind=kind,
            style=req.prosody_style or getattr(prosody_plan, "style", "") or "neutral",
            text=prefix,
            language_hint="auto",
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
                "auto",
                prosody_notes=prefix_plan.director_notes,
                prelocalized=True,
                quality_mode=_quality_mode(),
            )
            wav_bytes = _synthesize_wav(prompt, self._voice, self._model)
            self._vocal_cache.put(key, wav_bytes)
            logger.debug("[TTS] Vocal cache stored kind=%s text=%r", kind, prefix)
            return wav_bytes
        except Exception as exc:
            logger.debug("[TTS] Vocal cache synth miss failed: %s", exc)
            return b""

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
                    audio_tag = _emotion_to_tag(req.valence, req.arousal, req.stance)
                    vocal_prefix = str(getattr(req, "vocal_prefix", "") or "").strip()
                    main_text_raw = strip_audible_prefix(req.text, vocal_prefix) if vocal_prefix else req.text
                    prefix_is_separate = bool(vocal_prefix and main_text_raw != req.text)
                    text_to_speak = main_text_raw
                    localized = bool(req.prelocalized)
                    if self._language_hint == "ja" and not req.prelocalized:
                        # Dịch/style TTS chạy trong worker nền để UI/runtime không bị
                        # kẹt bởi một call Gemini phụ. Engine vẫn chỉ nhận text sạch.
                        text_to_speak = self._localizer.localize(
                            main_text_raw,
                            language_hint=self._language_hint,
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
                            self._language_hint,
                            prosody_notes=prosody_plan.director_notes,
                            prelocalized=localized or req.prelocalized,
                            quality_mode=_quality_mode(),
                        )
                        main_wav = _synthesize_wav(prompt, self._voice, self._model)

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
                    # Đánh dấu key hiện tại chết và xoay key trong pool khi gặp 429/RESOURCE_EXHAUSTED
                    try:
                        from google.genai.errors import ClientError
                        is_rate_limit = isinstance(exc, ClientError) and exc.code == 429
                        if is_rate_limit or "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                            from llm.key_pool import get_key_pool
                            pool = get_key_pool("gemini")
                            if pool:
                                pool.mark_dead(seconds=60.0)
                                pool.rotate()
                    except Exception:
                        pass
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

        if not _enabled():
            logger.info("[TTS] Đã tắt (ERIS_TTS_ENABLED=0).")
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
                "Set ERIS_SPEECH_API_KEY hoặc ERIS_REMOTE_API_KEY trong .env/secrets.json"
            )
            return

        voice = _voice()
        model = _model()
        lang = _language_hint()
        self._worker = _TtsWorker(voice, model, lang)
        self._ok = True
        logger.info("[TTS] Khởi động. Model=%s Voice=%s Language=%s", model, voice, lang)

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
        replace: bool = True,
        on_event = None,
    ) -> None:
        """Phát TTS cho text với cảm xúc cho trước. Non-blocking."""
        if not self._ok or self._worker is None:
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
                on_event=on_event,
            ),
            replace=replace,
        )

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.shutdown()
            self._worker = None

    def cancel_current(self, *, reason: str = "cancelled", only_interruptible: bool = True) -> bool:
        """Public API để runtime dừng TTS khi user cắt lượt."""
        if not self._ok or self._worker is None:
            return False
        return self._worker.cancel_current(reason=reason, only_interruptible=only_interruptible)


def _clean_text(text: str) -> str:
    """Bỏ markdown/code/URL trước khi đọc, nhưng giữ line break có chủ ý."""
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"```.*?```", "", t, flags=re.S)
    t = re.sub(r"\*{1,2}([^*]*)\*{1,2}", r"\1", t)
    t = re.sub(r"_{1,2}([^_]*)_{1,2}", r"\1", t)
    t = re.sub(r"`{1,3}[^`]*`{1,3}", "", t)
    t = re.sub(r"https?://\S+", "", t)
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
