from __future__ import annotations

import io
import tempfile
import wave

from domain.decision import Decision
from runtime.performance_act_catalog import PERFORMANCE_ACT_CATALOG, act_spec_by_kind
from runtime.stage_contracts import StageFrameBuilder
from runtime.tts_engine import _concat_wav_bytes
from runtime.vocal_cache import VocalCache, VocalCacheKey, strip_audible_prefix


def _wav(samples: bytes, *, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples)
    return buf.getvalue()


def _frames(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.readframes(wf.getnframes())


def test_act_catalog_contains_core_requests():
    kinds = {spec.kind for spec in PERFORMANCE_ACT_CATALOG}

    assert "playful_laugh" in kinds
    assert "fake_annoyed_deadpan" in kinds
    assert "soft_sigh" in kinds
    assert act_spec_by_kind("playful_laugh").audible_prefix == "Hah... haha."


def test_stage_builder_uses_catalog_for_laugh_request():
    decision = Decision(text="Được.", animation="", intent="chat")
    frame = StageFrameBuilder().build(
        decision,
        payload={
            "text": decision.text,
            "should_speak": True,
            "user_text": "cười cho tôi nghe",
        },
        channel="chat",
    )

    assert frame.tts_text.startswith("Hah... haha.")
    assert frame.memory_text == "Ngài định cho tôi làm trò hề gì vậy?"
    assert frame.delivery["performance_act"]["kind"] == "playful_laugh"


def test_vocal_cache_put_get_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache = VocalCache(root=tmp)
        key = VocalCacheKey(
            voice="Aoede",
            model="gemini-2.5-flash-preview-tts",
            kind="playful_laugh",
            style="dry_tease",
            text="Hah... haha.",
        )
        data = _wav(b"\x01\x00\x02\x00")

        assert cache.get(key) is None
        cache.put(key, data)
        assert cache.get(key) == data


def test_strip_audible_prefix_only_when_prefix_is_at_start():
    assert strip_audible_prefix("Hah... haha. Ngài lại phá gì rồi?", "Hah... haha.") == "Ngài lại phá gì rồi?"
    assert strip_audible_prefix("Ngài nói Hah... haha. ở giữa", "Hah... haha.") == "Ngài nói Hah... haha. ở giữa"


def test_concat_wav_bytes_keeps_single_wav_output():
    first = _wav(b"\x01\x00\x02\x00")
    second = _wav(b"\x03\x00\x04\x00")

    joined = _concat_wav_bytes(first, second)

    assert _frames(joined) == b"\x01\x00\x02\x00\x03\x00\x04\x00"
