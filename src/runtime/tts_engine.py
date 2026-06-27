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
from typing import Optional

from runtime.speech_localizer import SpeechLocalizer

logger = logging.getLogger("TTS")

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

def _build_tts_prompt(text: str, audio_tag: str, language_hint: str) -> str:
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
        "Pacing: Unhurried. Let silences breathe. Natural pauses.\n\n"
        f"{lang_line}"
        "## TRANSCRIPT\n"
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

    # Wrap vào WAV để miniaudio hiểu
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)       # 16-bit
        wf.setframerate(24000)   # 24kHz
        wf.writeframes(pcm_data)
    return buf.getvalue()


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
    __slots__ = ("text", "valence", "arousal", "stance", "on_start_play", "prelocalized")

    def __init__(
        self,
        text: str,
        valence: float = 0.0,
        arousal: float = 0.3,
        stance: str = "",
        on_start_play = None,
        prelocalized: bool = False,
    ):
        self.text = text
        self.valence = valence
        self.arousal = arousal
        self.stance = stance
        self.on_start_play = on_start_play
        # True khi StageFrame đã chuẩn bị sẵn tts_text theo ngôn ngữ cần đọc.
        # Khi đó engine không dịch lại, tránh "dịch một câu Nhật sang Nhật" làm mất tự nhiên.
        self.prelocalized = bool(prelocalized)


class _TtsWorker:
    def __init__(self, voice: str, model: str, language_hint: str) -> None:
        self._voice = voice
        self._model = model
        self._language_hint = language_hint
        self._localizer = SpeechLocalizer()
        self._queue: queue.Queue[Optional[_SpeakRequest]] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._current_stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TTS-Worker")
        self._thread.start()

    def speak(self, req: _SpeakRequest) -> None:
        """Enqueue câu mới. Huỷ câu cũ nếu đang phát."""
        self._current_stop.set()
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(req)
        except queue.Full:
            pass

    def shutdown(self) -> None:
        self._stop_event.set()
        self._current_stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                req = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if req is None:
                break

            self._current_stop.clear()
            callback_called = False
            try:
                try:
                    audio_tag = _emotion_to_tag(req.valence, req.arousal, req.stance)
                    text_to_speak = req.text
                    if self._language_hint == "ja" and not req.prelocalized:
                        # Dịch/style TTS chạy trong worker nền để UI/runtime không bị
                        # kẹt bởi một call Gemini phụ. Engine vẫn chỉ nhận text sạch.
                        text_to_speak = self._localizer.localize(req.text, language_hint=self._language_hint)
                    prompt = _build_tts_prompt(text_to_speak, audio_tag, self._language_hint)

                    logger.debug(
                        "[TTS] valence=%.2f arousal=%.2f stance=%r → tag=%r",
                        req.valence, req.arousal, req.stance, audio_tag,
                    )

                    wav_bytes = _synthesize_wav(prompt, self._voice, self._model)

                    if not self._current_stop.is_set():
                        if req.on_start_play is not None:
                            try:
                                req.on_start_play()
                            except Exception as cb_exc:
                                logger.error("[TTS] Error in on_start_play callback: %s", cb_exc)
                            callback_called = True
                        _play_wav_bytes(wav_bytes, self._current_stop)

                except Exception as exc:
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
    ) -> None:
        """Phát TTS cho text với cảm xúc cho trước. Non-blocking."""
        if not self._ok or self._worker is None:
            if on_start_play is not None:
                try:
                    on_start_play()
                except Exception as cb_exc:
                    logger.error("[TTS] Error in fallback on_start_play callback: %s", cb_exc)
            return
        clean = _clean_text(text)
        if not clean:
            if on_start_play is not None:
                try:
                    on_start_play()
                except Exception as cb_exc:
                    logger.error("[TTS] Error in fallback on_start_play callback: %s", cb_exc)
            return
        self._worker.speak(_SpeakRequest(clean, valence, arousal, stance, on_start_play, prelocalized=prelocalized))

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.shutdown()
            self._worker = None


def _clean_text(text: str) -> str:
    """Bỏ markdown, code fence, URL khỏi text trước khi đọc."""
    t = text or ""
    t = re.sub(r"\*{1,2}([^*]*)\*{1,2}", r"\1", t)
    t = re.sub(r"_{1,2}([^_]*)_{1,2}", r"\1", t)
    t = re.sub(r"`{1,3}[^`]*`{1,3}", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_tts_engine() -> TtsEngine:
    """Entry point — gọi một lần trong vision.py."""
    return TtsEngine()
