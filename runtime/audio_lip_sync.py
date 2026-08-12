# -*- coding: utf-8 -*-
"""Rút envelope độ mở miệng gọn từ WAV PCM để gửi sang Live2D.

Envelope không chứa audio và không cố nhận dạng phoneme. Nó chỉ lấy RMS theo
khung thời gian, noise-gate, nén động học rồi làm mượt attack/release. Payload
vài KB đủ đi qua UDP, trong khi renderer nhận đúng nhịp im lặng và âm lượng của
clip thật thay vì đoán bằng đồng hồ riêng.
"""

from __future__ import annotations

import io
import math
import sys
import wave
from array import array
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LipSyncEnvelope:
    values: tuple[float, ...] = ()
    frame_ms: int = 40
    duration_ms: int = 0

    def to_payload(self) -> dict[str, object]:
        if not self.values:
            return {}
        return {
            "audio_envelope": list(self.values),
            "audio_frame_ms": int(self.frame_ms),
            "audio_duration_ms": int(self.duration_ms),
        }


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(1.0, float(ratio))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _pcm_samples(raw: bytes, *, sample_width: int) -> tuple[list[int], float]:
    if sample_width == 1:
        # WAV 8-bit PCM là unsigned.
        return ([int(value) - 128 for value in raw], 128.0)
    if sample_width == 2:
        samples = array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        return (list(samples), 32768.0)
    if sample_width == 4:
        samples = array("i")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        return (list(samples), 2147483648.0)
    if sample_width == 3:
        result: list[int] = []
        for offset in range(0, len(raw) - 2, 3):
            value = raw[offset] | (raw[offset + 1] << 8) | (raw[offset + 2] << 16)
            if value & 0x800000:
                value -= 1 << 24
            result.append(value)
        return (result, 8388608.0)
    return ([], 1.0)


def build_lip_sync_envelope(
    wav_bytes: bytes,
    *,
    frame_ms: int = 40,
    max_frames: int = 1800,
) -> LipSyncEnvelope:
    """Trả envelope 0..0.86 từ WAV; dữ liệu lạ thì fail mềm về envelope rỗng."""

    if not wav_bytes:
        return LipSyncEnvelope(frame_ms=max(20, int(frame_ms)))
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as stream:
            channels = max(1, int(stream.getnchannels()))
            sample_rate = max(1, int(stream.getframerate()))
            sample_width = int(stream.getsampwidth())
            frame_count = max(0, int(stream.getnframes()))
            compression = str(stream.getcomptype() or "NONE")
            if compression != "NONE":
                return LipSyncEnvelope(frame_ms=max(20, int(frame_ms)))
            raw = stream.readframes(frame_count)
    except (wave.Error, EOFError, OSError, ValueError):
        return LipSyncEnvelope(frame_ms=max(20, int(frame_ms)))

    samples, full_scale = _pcm_samples(raw, sample_width=sample_width)
    if not samples or full_scale <= 0.0:
        return LipSyncEnvelope(frame_ms=max(20, int(frame_ms)))

    frame_ms = max(20, min(80, int(frame_ms)))
    samples_per_window = max(channels, int(round(sample_rate * frame_ms / 1000.0)) * channels)
    rms_values: list[float] = []
    for start in range(0, len(samples), samples_per_window):
        block = samples[start : start + samples_per_window]
        if not block:
            break
        # Stereo/multichannel đều có thể dùng RMS chung; miệng quan tâm năng lượng,
        # không cần tranh luận bên tai nào có quyền biểu quyết lớn hơn.
        square_sum = sum(float(value) * float(value) for value in block)
        rms_values.append(math.sqrt(square_sum / len(block)) / full_scale)

    if not rms_values:
        return LipSyncEnvelope(frame_ms=frame_ms)

    if len(rms_values) > max_frames:
        stride = int(math.ceil(len(rms_values) / max_frames))
        collapsed: list[float] = []
        for start in range(0, len(rms_values), stride):
            block = rms_values[start : start + stride]
            collapsed.append(max(block))
        rms_values = collapsed
        frame_ms *= stride

    floor = _percentile(rms_values, 0.16)
    peak = max(_percentile(rms_values, 0.94), floor + 0.004)
    span = max(0.004, peak - floor)

    normalized: list[float] = []
    for value in rms_values:
        gated = max(0.0, (value - floor * 1.18) / span)
        # Căn bậc làm lời nói nhỏ vẫn thấy được; cap giữ rig không há quá tay.
        mouth = min(0.86, (min(1.35, gated) ** 0.58) * 0.78)
        normalized.append(mouth if mouth >= 0.035 else 0.0)

    # Attack nhanh, release vừa phải. Phần đóng nhanh cuối cùng còn được xử lý ở
    # stage_state để khe giữa âm tiết không bị smoothing nuốt mất.
    smoothed: list[float] = []
    current = 0.0
    for target in normalized:
        coefficient = 0.72 if target > current else 0.54
        current += (target - current) * coefficient
        smoothed.append(round(max(0.0, min(0.86, current)), 3))

    duration_ms = int(round(frame_count / sample_rate * 1000.0))
    return LipSyncEnvelope(values=tuple(smoothed), frame_ms=frame_ms, duration_ms=duration_ms)


__all__ = ["LipSyncEnvelope", "build_lip_sync_envelope"]
