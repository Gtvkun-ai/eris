from __future__ import annotations

import array

from runtime.tts_audio_polish import polish_pcm16_mono


def _pcm(samples: list[int]) -> bytes:
    return array.array("h", samples).tobytes()


def _samples(pcm: bytes) -> list[int]:
    out = array.array("h")
    out.frombytes(pcm)
    return list(out)


def test_audio_polish_trims_edge_silence_but_keeps_small_breath():
    # 100ms silence + voice + 100ms silence ở sample_rate 1000 để test dễ đọc.
    raw = _pcm([0] * 100 + [900] * 20 + [0] * 100)

    result = polish_pcm16_mono(
        raw,
        sample_rate=1000,
        silence_threshold=100,
        edge_keep_ms=10,
        max_internal_silence_ms=80,
        target_peak=0.5,
        max_gain=1.0,
    )

    polished = _samples(result.pcm)
    assert len(polished) == 40
    assert result.stats.trimmed_head_ms == 90
    assert result.stats.trimmed_tail_ms == 90
    assert polished[:10] == [0] * 10
    assert polished[-10:] == [0] * 10


def test_audio_polish_compresses_long_internal_pause():
    # Giữ pause nội bộ tối đa 30ms, không xoá hoàn toàn nhịp nghỉ.
    raw = _pcm([800] * 10 + [0] * 120 + [800] * 10)

    result = polish_pcm16_mono(
        raw,
        sample_rate=1000,
        silence_threshold=100,
        edge_keep_ms=0,
        max_internal_silence_ms=30,
        target_peak=0.5,
        max_gain=1.0,
    )

    polished = _samples(result.pcm)
    assert len(polished) == 50
    assert result.stats.compressed_pause_ms == 90
    assert polished[10:40] == [0] * 30


def test_audio_polish_normalizes_quiet_audio_without_clipping():
    raw = _pcm([100, -100, 200, -200])

    result = polish_pcm16_mono(
        raw,
        sample_rate=1000,
        silence_threshold=10,
        edge_keep_ms=0,
        max_internal_silence_ms=30,
        target_peak=0.5,
        max_gain=2.0,
    )

    polished = _samples(result.pcm)
    assert max(abs(x) for x in polished) == 400
    assert result.stats.peak_before == 200
    assert result.stats.peak_after == 400
