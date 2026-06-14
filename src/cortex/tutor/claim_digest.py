# -*- coding: utf-8 -*-
"""
cortex/tutor/claim_digest.py
============================

Chưng cất Tutor_Answer thành Knowledge_Claim qua đường commit claim hiện có của ERIS
(`claim_extractor` → trí nhớ ngữ nghĩa → consolidator), gắn provenance `source="tutor"`.

KHÔNG tạo store mới. KHÔNG phát answer ra kênh nói — module này chỉ ghi trí nhớ.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .config import TutorConfig, scrub_identity
from .contracts import TutorEpisode


# ingest_fn(text, *, source, gap_id, citations) -> số claim đã commit.
IngestFn = Callable[..., int]


class ClaimDigest:
    """Đưa câu trả lời gia sư vào trí nhớ ngữ nghĩa qua đường claim hiện có."""

    def __init__(self, config: Optional[TutorConfig] = None, *, ingest_fn: Optional[IngestFn] = None) -> None:
        self.config = (config or TutorConfig()).normalized()
        self._ingest_fn = ingest_fn

    def digest(self, episode: TutorEpisode) -> int:
        """Trả số Knowledge_Claim đã commit. 0 nếu answer rỗng/không trích được."""

        answer = episode.answer
        if answer is None or not answer.text:
            return 0
        if self._ingest_fn is None:
            # Không có đường commit ⇒ không học được gì (an toàn: không tạo store mới).
            return 0
        gap_id = episode.gap.gap_id
        text = scrub_identity(answer.text)
        try:
            count = self._ingest_fn(
                text,
                source="tutor",
                gap_id=gap_id,
                citations=tuple(answer.citations or ()),
            )
        except Exception:
            return 0
        try:
            return max(0, int(count))
        except (TypeError, ValueError):
            return 0


__all__ = ["ClaimDigest"]
