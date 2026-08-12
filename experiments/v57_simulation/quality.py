# -*- coding: utf-8 -*-
"""Đánh giá deterministic bổ sung cho lời thoại thật.

Rule ở đây chỉ bắt những lỗi máy móc rõ ràng. Nó KHÔNG thay LLM judge vì đánh giá
độ tự nhiên bằng một rừng regex là cách rất nhanh để tạo ra một benchmark tự lừa.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable, Sequence


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return " ".join(value.split())


def token_jaccard(a: str, b: str) -> float:
    left = set(normalize_text(a).split())
    right = set(normalize_text(b).split())
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def max_prior_similarity(current: str, prior_replies: Sequence[str]) -> float:
    if not current or not prior_replies:
        return 0.0
    return max((token_jaccard(current, item) for item in prior_replies if item), default=0.0)


def deterministic_failures(
    *,
    user_text: str,
    eris_text: str,
    prior_replies: Sequence[str],
    provider_real: bool,
) -> tuple[str, ...]:
    failures: list[str] = []
    clean = str(eris_text or "").strip()
    if not provider_real:
        failures.append("public_reply_not_proven_real_provider")
    if not clean:
        failures.append("empty_public_reply")
        return tuple(failures)
    if len(clean) > 3500:
        failures.append("runaway_public_reply")

    norm = normalize_text(clean)
    # Những fallback kỹ thuật này không phải hội thoại có chất lượng.
    technical_markers = (
        "loi phan tich cu phap", "loi dinh dang", "van de duong truyen",
        "service fallback", "format repair fallback", "no fallback block",
    )
    if any(marker in norm for marker in technical_markers):
        failures.append("technical_fallback_leaked_to_conversation")

    similarity = max_prior_similarity(clean, prior_replies)
    if len(prior_replies) >= 2 and similarity >= 0.92:
        failures.append("near_duplicate_reply")

    # Một câu lặp y nguyên nhiều lần bên trong cũng là lỗi rõ ràng.
    sentences = [normalize_text(item) for item in re.split(r"[.!?\n]+", clean) if normalize_text(item)]
    counts = Counter(sentences)
    if any(count >= 3 and len(sentence.split()) >= 3 for sentence, count in counts.items()):
        failures.append("internal_sentence_loop")

    return tuple(dict.fromkeys(failures))


def runtime_invariant_failures(artifact) -> tuple[str, ...]:
    """Bắt invariant typed có thể kiểm trực tiếp từ public payload + ledger.

    Không diễn giải tâm lý ở đây. Rule chỉ kiểm contract máy: số hữu hạn, range,
    learned record đủ outcome/after-state và public surface không mang failure_meta.
    """
    failures: list[str] = []
    payload = dict(getattr(artifact, "raw_public_payload", {}) or {})
    failure_meta = payload.get("failure_meta")
    if isinstance(failure_meta, dict) and failure_meta:
        kind = str(failure_meta.get("kind", "") or "").strip()
        if kind and kind not in {"none", "ok"}:
            failures.append(f"public_failure_meta:{kind}")

    seen_trace_ids: set[str] = set()
    for record in getattr(artifact, "subject_ledger_tail", ()) or ():
        if not isinstance(record, dict):
            continue
        trace_id = str(record.get("trace_id", "") or "")
        if trace_id:
            if trace_id in seen_trace_ids:
                failures.append("duplicate_decision_trace_in_tail")
            seen_trace_ids.add(trace_id)
        stage = str(record.get("stage", "") or "")
        if stage == "learned":
            if not str(record.get("outcome_id", "") or ""):
                failures.append("learned_record_missing_outcome")
            if not isinstance(record.get("after_state"), dict) or not record.get("after_state"):
                failures.append("learned_record_missing_after_state")
        appraisal_state = record.get("appraisal_state", {})
        appraisals = appraisal_state.get("appraisals", ()) if isinstance(appraisal_state, dict) else ()
        for appraisal in appraisals if isinstance(appraisals, list) else ():
            if not isinstance(appraisal, dict):
                continue
            for key in ("goal_congruence", "goal_progress_delta"):
                if key not in appraisal:
                    continue
                try:
                    value = float(appraisal[key])
                except (TypeError, ValueError):
                    failures.append(f"non_numeric_{key}")
                    continue
                if not math.isfinite(value):
                    failures.append(f"non_finite_{key}")
                elif value < -1.0001 or value > 1.0001:
                    failures.append(f"out_of_range_{key}")
    return tuple(dict.fromkeys(failures))


__all__ = ["deterministic_failures", "max_prior_similarity", "normalize_text", "runtime_invariant_failures", "token_jaccard"]
