# -*- coding: utf-8 -*-
"""
core/evidence_normalizer.py

Lớp trung gian bắt buộc của Phase 0/1:

    RawSignal  ->  EvidenceItem  ->  (CognitiveFrame.evidence)

Vì sao cần file này:
    V3 cấm module đọc raw input lung tung. Mọi claim dùng để suy luận phải đi
    qua EvidenceItem (có confidence, source, reliability, raw_or_inferred,
    privacy_level). Nếu một module tự bốc `frame.user_text` hay `raw_signals`
    rồi sinh câu, nó tạo ra "claim không neo" — đúng thứ V3 muốn diệt.

    EvidenceNormalizer là cửa duy nhất biến tín hiệu thô thành evidence chuẩn.
    Nó CỐ Ý deterministic và CỐ Ý không suy diễn ý nghĩa:
        - không đoán cảm xúc
        - không đoán ý định
        - không phán "user đang né việc"
    Mấy việc đó thuộc Meaning/ToM ở tầng sau, và chúng phải đọc evidence này,
    không được đọc lại raw signal.

Nguyên tắc:
    - Đầu vào: list[RawSignal] (hoặc frame.raw_signals).
    - Đầu ra: list[EvidenceItem] raw, mỗi cái neo vào đúng 1 RawSignal.
    - confidence khởi điểm = reliability của nguồn (nguồn yếu -> evidence yếu).
    - tags suy ra từ source, deterministic, để Attention/WorkingMemory lọc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from core.evidence import EvidenceItem, RawSignal, SignalSource


# Tag mặc định theo nguồn. Đây là nhãn cấu trúc, không phải diễn giải ngữ nghĩa.
_SOURCE_TAGS: dict[str, tuple[str, ...]] = {
    "user_chat": ("user", "direct_input"),
    "active_window": ("environment", "window"),
    "browser": ("environment", "browser"),
    "telemetry": ("environment", "telemetry"),
    "vision": ("perception", "screen"),
    "ocr": ("perception", "screen", "text"),
    "body": ("body", "proprioception"),
    "system_log": ("system", "runtime"),
    "memory": ("memory", "recall"),
    "time": ("temporal", "clock"),
}

# Nguồn nào nên được giữ confidence cao kể cả khi reliability mặc định.
_HIGH_TRUST_SOURCES: frozenset[str] = frozenset({"user_chat", "time"})


@dataclass(slots=True)
class EvidenceNormalizerConfig:
    """Cấu hình cho normalizer.

    Giữ trong dataclass để sau này load từ JSON nếu cần, thay vì rải magic number.
    """

    # Độ dài claim tối đa khi rút từ content thô.
    max_claim_chars: int = 240
    # Confidence sàn cho nguồn user_chat (user gõ thẳng thì gần như chắc chắn là đã xảy ra).
    user_chat_confidence_floor: float = 0.95
    # Có bỏ qua signal sensitive khỏi evidence công khai không.
    drop_sensitive: bool = False
    # Không tạo evidence rỗng (claim trắng).
    skip_empty_claim: bool = True


@dataclass(slots=True)
class NormalizationResult:
    """Kết quả normalize, kèm vài con số để debug_trace soi."""

    evidence: list[EvidenceItem] = field(default_factory=list)
    skipped: int = 0
    dropped_sensitive: int = 0

    @property
    def count(self) -> int:
        return len(self.evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "skipped": self.skipped,
            "dropped_sensitive": self.dropped_sensitive,
            "evidence_ids": [ev.id for ev in self.evidence],
        }


class EvidenceNormalizer:
    """Chuyển RawSignal thành EvidenceItem theo contract V3.

    Dùng:
        normalizer = EvidenceNormalizer()
        result = normalizer.normalize_into_frame(frame)

    hoặc độc lập:
        items = normalizer.normalize(signals)
    """

    module_name = "evidence_normalizer"

    def __init__(self, config: Optional[EvidenceNormalizerConfig] = None) -> None:
        self.config = config or EvidenceNormalizerConfig()

    # ------------------------------------------------------------------
    # API chính
    # ------------------------------------------------------------------

    def normalize(self, signals: Iterable[RawSignal]) -> NormalizationResult:
        """Chuyển một loạt RawSignal thành EvidenceItem raw."""

        result = NormalizationResult()
        for signal in signals:
            if not isinstance(signal, RawSignal):
                result.skipped += 1
                continue
            if self.config.drop_sensitive and signal.is_sensitive:
                result.dropped_sensitive += 1
                continue
            item = self._to_evidence(signal)
            if item is None:
                result.skipped += 1
                continue
            result.evidence.append(item)
        return result

    def normalize_into_frame(self, frame) -> NormalizationResult:
        """Đọc frame.raw_signals, sinh evidence, và add vào frame.

        Frame phải có `raw_signals` và `add_evidence` (CognitiveFrame core có sẵn).
        """

        signals = list(getattr(frame, "raw_signals", []) or [])
        result = self.normalize(signals)

        add_evidence = getattr(frame, "add_evidence", None)
        if callable(add_evidence):
            for item in result.evidence:
                add_evidence(item, actor=self.module_name)
        else:  # frame lạ: cố gắn vào .evidence list
            existing = list(getattr(frame, "evidence", []) or [])
            existing.extend(result.evidence)
            try:
                frame.evidence = existing
            except Exception:
                pass

        add_debug_note = getattr(frame, "add_debug_note", None)
        if callable(add_debug_note):
            add_debug_note(
                f"evidence_normalizer: {result.count} evidence từ {len(signals)} raw_signals"
                f" (skipped={result.skipped}, dropped_sensitive={result.dropped_sensitive})",
                actor=self.module_name,
            )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _to_evidence(self, signal: RawSignal) -> Optional[EvidenceItem]:
        claim = signal.summarize_content(max_length=self.config.max_claim_chars).strip()
        if self.config.skip_empty_claim and not claim:
            return None

        confidence = self._initial_confidence(signal)
        tags = self._tags_for(signal.source)

        return EvidenceItem.from_raw_signal(
            signal,
            claim=claim or f"[{signal.source}] (no content)",
            confidence=confidence,
            tags=tags,
            raw_or_inferred="raw",
            metadata={
                "normalizer": self.module_name,
                "source_reliability": signal.reliability,
            },
        )

    def _initial_confidence(self, signal: RawSignal) -> float:
        if signal.source == "user_chat":
            return max(signal.reliability, self.config.user_chat_confidence_floor)
        if signal.source in _HIGH_TRUST_SOURCES:
            return max(signal.reliability, 0.9)
        return signal.reliability

    def _tags_for(self, source: SignalSource) -> tuple[str, ...]:
        return _SOURCE_TAGS.get(str(source), ("environment",))


def normalize_signals(signals: Iterable[RawSignal]) -> list[EvidenceItem]:
    """Shortcut hàm thuần cho test/call nhanh."""

    return EvidenceNormalizer().normalize(signals).evidence


__all__ = [
    "EvidenceNormalizer",
    "EvidenceNormalizerConfig",
    "NormalizationResult",
    "normalize_signals",
]
