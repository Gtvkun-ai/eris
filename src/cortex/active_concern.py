# -*- coding: utf-8 -*-
"""Projection ActiveConcern cho cognition liên tục của ERIS.

Module này KHÔNG lưu thêm một database concern. Nó chỉ hợp nhất các dấu hiệu đã
có từ PrivateConcern / ThoughtStream / InternalAgenda thành một view nhỏ để Neuro
và planner biết một ý đang sống lâu hay vừa xuất hiện.

Nguyên tắc V40:
- recurrence không đồng nghĩa "càng phải nói";
- evidence/mutation mới làm novelty hồi lại;
- nói cùng concern nhiều lần tạo habituation;
- silence không xóa concern, concern có thể tiếp tục nguội hoặc biến đổi.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


ACTIVE_CONCERN_VERSION = "eris.cognitive_continuity.v40.active_concern"


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = default
    if math.isnan(number) or math.isinf(number):
        number = default
    return max(0.0, min(1.0, number))


def compact(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _fold(value: Any) -> str:
    text = str(value or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


_STOP = {
    "toi", "minh", "ban", "eris", "mot", "nhung", "cac", "cua", "voi", "cho",
    "trong", "khi", "thi", "ma", "la", "co", "khong", "duoc", "nay", "do",
    "this", "that", "the", "and", "for", "from", "with", "about", "user",
}


def semantic_tokens(value: Any) -> frozenset[str]:
    return frozenset(
        token for token in re.findall(r"[a-z0-9]+", _fold(value))
        if len(token) >= 3 and token not in _STOP
    )


def semantic_overlap(left: Any, right: Any) -> float:
    a, b = semantic_tokens(left), semantic_tokens(right)
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared <= 0:
        return 0.0
    # Overlap coefficient hợp với premise ngắn gặp concern dài hơn Jaccard.
    return clamp01(shared / max(1, min(len(a), len(b))))


@dataclass(frozen=True, slots=True)
class ActiveConcernView:
    concern_id: str
    subject: str
    source_kinds: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    activation: float = 0.0
    persistence: float = 0.0
    tension: float = 0.0
    novelty: float = 0.0
    habituation: float = 0.0
    speech_pressure: float = 0.0
    interruption_cost: float = 0.0
    recurrence: int = 0
    mutation_count: int = 0
    surfaced_count: int = 0
    trajectory: str = "stable"
    state: str = "simmering"
    age_seconds: float = 0.0
    updated_age_seconds: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "activation", "persistence", "tension", "novelty", "habituation",
            "speech_pressure", "interruption_cost", "age_seconds", "updated_age_seconds",
        ):
            data[key] = round(float(data[key]), 3)
        return data


def private_concern_view(
    concern: Any,
    *,
    now: float | None = None,
    previous_activation: float | None = None,
    interruption_cost: float = 0.0,
) -> ActiveConcernView:
    current = float(now or time.time())
    meta = dict(getattr(concern, "metadata", {}) or {})
    created = float(getattr(concern, "created_at", current) or current)
    updated = float(getattr(concern, "updated_at", created) or created)
    age = max(0.0, current - created)
    updated_age = max(0.0, current - updated)
    pressure = clamp01(getattr(concern, "pressure", 0.0))
    uncertainty = clamp01(getattr(concern, "uncertainty", 0.5), 0.5)
    recurrence = max(1, int(getattr(concern, "recurrence", 1) or 1))
    mutation_count = max(0, int(meta.get("mutation_count", 0) or 0))
    surfaced_count = max(0, int(meta.get("surfaced_count", 0) or 0))
    last_mutation = float(meta.get("last_mutation_at", updated) or updated)
    last_surface = float(meta.get("last_surfaced_at", 0.0) or 0.0)
    echo_streak = max(0, int(meta.get("echo_streak", 0) or 0))

    # Persistence là khả năng còn treo, không phải áp lực nói.
    recurrence_term = min(1.0, math.log1p(recurrence) / math.log(8.0))
    freshness = 1.0 if updated_age <= 300.0 else max(0.12, 1.0 - (updated_age - 300.0) / 7200.0)
    persistence = clamp01(0.42 * pressure + 0.33 * recurrence_term + 0.25 * freshness)
    tension = clamp01(0.68 * pressure + 0.32 * uncertainty)

    mutation_age = max(0.0, current - last_mutation)
    mutation_freshness = 1.0 if mutation_count and mutation_age <= 600.0 else max(0.0, 1.0 - mutation_age / 3600.0)
    evidence_count = len(tuple(getattr(concern, "evidence_ids", ()) or ()))
    novelty = clamp01(
        0.20
        + 0.26 * mutation_freshness
        + min(0.18, evidence_count * 0.025)
        + 0.12 * uncertainty
        - min(0.34, echo_streak * 0.07)
    )

    if last_surface > 0.0:
        since_surface = max(0.0, current - last_surface)
        recent_surface = max(0.0, 1.0 - since_surface / 1800.0)
    else:
        recent_surface = 0.0
    habituation = clamp01(min(0.78, surfaced_count * 0.18) * (0.35 + 0.65 * recent_surface))

    activation = clamp01(0.46 * pressure + 0.26 * persistence + 0.18 * uncertainty + 0.10 * novelty)
    speech_pressure = clamp01(
        activation
        * (0.48 + 0.52 * novelty)
        * (1.0 - 0.72 * habituation)
        * (1.0 - 0.62 * clamp01(interruption_cost))
    )

    if previous_activation is None or abs(activation - previous_activation) < 0.05:
        trajectory = "stable"
    elif activation > previous_activation:
        trajectory = "rising"
    else:
        trajectory = "cooling"

    status = str(getattr(concern, "status", "open") or "open")
    if status == "blocked":
        state = "blocked"
    elif habituation >= 0.55 and novelty < 0.42:
        state = "habituated"
    elif trajectory == "rising" and activation >= 0.48:
        state = "reactivated"
    elif status == "watching" or activation < 0.30:
        state = "watching"
    else:
        state = "simmering"

    sources = tuple(str(x) for x in (meta.get("fragment_sources") or ()) if str(x).strip())[:6]
    if meta.get("seed_event_kind"):
        sources = tuple(dict.fromkeys((*sources, f"seed:{meta['seed_event_kind']}")))
    return ActiveConcernView(
        concern_id=str(getattr(concern, "id", "") or ""),
        subject=compact(getattr(concern, "theme", ""), 320),
        source_kinds=sources,
        evidence_refs=tuple(str(x) for x in (getattr(concern, "evidence_ids", ()) or ()) if str(x).strip())[:10],
        activation=activation,
        persistence=persistence,
        tension=tension,
        novelty=novelty,
        habituation=habituation,
        speech_pressure=speech_pressure,
        interruption_cost=clamp01(interruption_cost),
        recurrence=recurrence,
        mutation_count=mutation_count,
        surfaced_count=surfaced_count,
        trajectory=trajectory,
        state=state,
        age_seconds=age,
        updated_age_seconds=updated_age,
        metadata={
            "status": status,
            "echo_streak": echo_streak,
            "open_question_count": len(tuple(getattr(concern, "open_questions", ()) or ())),
        },
    )


def thought_concern_view(
    thought: Any,
    *,
    now: float | None = None,
    previous_activation: float | None = None,
    interruption_cost: float = 0.0,
) -> ActiveConcernView:
    """Project một ThoughtObject chưa resolved thành concern view tạm thời.

    ThoughtStream vẫn sở hữu thought. Projection này chỉ giúp planner thấy rằng
    một ý đã sống nhiều tick, không copy nó sang ConcernStore.
    """
    current = float(now or time.time())
    created = float(getattr(thought, "created_at", current) or current)
    updated = float(getattr(thought, "updated_at", created) or created)
    age = max(0.0, current - created)
    updated_age = max(0.0, current - updated)
    tension = clamp01(getattr(thought, "tension", 0.0))
    persistence = clamp01(getattr(thought, "persistence", 0.0))
    novelty = clamp01(getattr(thought, "novelty", 0.0))
    recurrence = max(0, int(getattr(thought, "recurrence_count", 0) or 0))
    surfaced = max(0, int(getattr(thought, "surfaced_count", 0) or 0))
    recurrence_term = min(1.0, recurrence / 3.0)
    activation = clamp01(0.40 * tension + 0.28 * persistence + 0.20 * novelty + 0.12 * recurrence_term)
    habituation = clamp01(min(0.72, surfaced * 0.16) * (0.62 + 0.38 * (1.0 - novelty)))
    speech_pressure = clamp01(
        activation * (0.42 + 0.58 * novelty) * (1.0 - 0.68 * habituation)
        * (1.0 - 0.62 * clamp01(interruption_cost))
    )
    if previous_activation is None or abs(activation - previous_activation) < 0.05:
        trajectory = "stable"
    elif activation > previous_activation:
        trajectory = "rising"
    else:
        trajectory = "cooling"
    last_reactivated = float(getattr(thought, "last_reactivated_at", 0.0) or 0.0)
    if habituation >= 0.52 and novelty < 0.38:
        state = "habituated"
    elif last_reactivated and current - last_reactivated <= 300.0 and recurrence > 0:
        state = "reactivated"
    elif activation < 0.28:
        state = "watching"
    else:
        state = "simmering"
    subject = compact(getattr(thought, "partial_text", "") or getattr(thought, "topic_seed", ""), 320)
    return ActiveConcernView(
        concern_id=f"thought:{str(getattr(thought, 'thought_id', '') or '')}",
        subject=subject,
        source_kinds=("thought_stream", str(getattr(thought, "mode", "") or "thought")),
        evidence_refs=tuple(str(x) for x in (getattr(thought, "evidence", ()) or ()) if str(x).strip())[:10],
        activation=activation,
        persistence=persistence,
        tension=tension,
        novelty=novelty,
        habituation=habituation,
        speech_pressure=speech_pressure,
        interruption_cost=clamp01(interruption_cost),
        recurrence=recurrence,
        mutation_count=0,
        surfaced_count=surfaced,
        trajectory=trajectory,
        state=state,
        age_seconds=age,
        updated_age_seconds=updated_age,
        metadata={
            "unresolved_reason": compact(getattr(thought, "unresolved_reason", ""), 160),
            "prediction_key": compact(getattr(thought, "prediction_key", ""), 100),
        },
    )


def agenda_concern_view(
    item: Any,
    *,
    now: float | None = None,
    previous_activation: float | None = None,
    interruption_cost: float = 0.0,
) -> ActiveConcernView:
    current = float(now or time.time())
    created = float(getattr(item, "created_at", current) or current)
    updated = float(getattr(item, "updated_at", created) or created)
    age = max(0.0, current - created)
    updated_age = max(0.0, current - updated)
    pressure = clamp01(getattr(item, "pressure", 0.0))
    urgency = clamp01(getattr(item, "urgency", 0.0))
    confidence = clamp01(getattr(item, "confidence", 0.0))
    speech_value = clamp01(getattr(item, "speech_value", 0.0))
    score = clamp01(getattr(item, "score", 0.0))
    freshness = 1.0 if updated_age <= 300.0 else max(0.12, 1.0 - (updated_age - 300.0) / 7200.0)
    activation = clamp01(max(score, 0.46 * pressure + 0.24 * urgency + 0.18 * confidence + 0.12 * freshness))
    persistence = clamp01(0.52 * pressure + 0.24 * confidence + 0.24 * freshness)
    tension = clamp01(0.58 * pressure + 0.42 * urgency)
    novelty = clamp01(0.20 + 0.28 * freshness + 0.20 * confidence)
    attempts = max(0, int(getattr(item, "attempts", 0) or 0))
    habituation = clamp01(min(0.65, attempts * 0.13) * (1.0 - 0.45 * novelty))
    speech_pressure = clamp01(
        activation * speech_value * (0.62 + 0.38 * novelty) * (1.0 - 0.64 * habituation)
        * (1.0 - 0.62 * clamp01(interruption_cost))
    )
    if previous_activation is None or abs(activation - previous_activation) < 0.05:
        trajectory = "stable"
    elif activation > previous_activation:
        trajectory = "rising"
    else:
        trajectory = "cooling"
    status = str(getattr(item, "status", "open") or "open")
    if status == "blocked":
        state = "blocked"
    elif habituation >= 0.5 and novelty < 0.4:
        state = "habituated"
    elif activation < 0.28:
        state = "watching"
    else:
        state = "simmering"
    return ActiveConcernView(
        concern_id=f"agenda:{str(getattr(item, 'id', '') or '')}",
        subject=compact(getattr(item, "summary", ""), 320),
        source_kinds=(f"agenda:{str(getattr(item, 'kind', 'misc') or 'misc')}",),
        evidence_refs=tuple(str(x) for x in (getattr(item, "evidence_ids", ()) or ()) if str(x).strip())[:10],
        activation=activation,
        persistence=persistence,
        tension=tension,
        novelty=novelty,
        habituation=habituation,
        speech_pressure=speech_pressure,
        interruption_cost=clamp01(interruption_cost),
        recurrence=attempts,
        mutation_count=0,
        surfaced_count=attempts,
        trajectory=trajectory,
        state=state,
        age_seconds=age,
        updated_age_seconds=updated_age,
        metadata={"status": status, "speech_value": round(speech_value, 3), "confidence": round(confidence, 3)},
    )


def merge_concern_views(views: Iterable[ActiveConcernView], *, overlap_threshold: float = 0.52) -> tuple[ActiveConcernView, ...]:
    """Gộp các projection semantic trùng mà không cộng áp lực hai lần.

    Khi PrivateConcern và ThoughtStream cùng nói về một chuyện, ta lấy max/bounded
    signals chứ không cộng. Nếu cộng, việc có nhiều subsystem sẽ tự biến thành bằng
    chứng rằng concern quan trọng hơn, một vòng tự khuếch đại khá máy móc.
    """
    merged: list[ActiveConcernView] = []
    for view in views:
        if not view.subject:
            continue
        match_index = -1
        best = 0.0
        for idx, existing in enumerate(merged):
            score = semantic_overlap(view.subject, existing.subject)
            if score >= overlap_threshold and score > best:
                best, match_index = score, idx
        if match_index < 0:
            merged.append(view)
            continue
        old = merged[match_index]
        # Ưu tiên ID concern persistent nếu một phía là PrivateConcern.
        keeper, other = (old, view) if not old.concern_id.startswith(("thought:", "agenda:")) else (view, old)
        if keeper.concern_id.startswith(("thought:", "agenda:")) and not other.concern_id.startswith(("thought:", "agenda:")):
            keeper, other = other, keeper
        merged[match_index] = ActiveConcernView(
            concern_id=keeper.concern_id,
            subject=keeper.subject or other.subject,
            source_kinds=tuple(dict.fromkeys((*keeper.source_kinds, *other.source_kinds)))[:8],
            evidence_refs=tuple(dict.fromkeys((*keeper.evidence_refs, *other.evidence_refs)))[:12],
            activation=max(keeper.activation, other.activation),
            persistence=max(keeper.persistence, other.persistence),
            tension=max(keeper.tension, other.tension),
            novelty=max(keeper.novelty, other.novelty),
            habituation=max(keeper.habituation, other.habituation),
            speech_pressure=max(keeper.speech_pressure, other.speech_pressure),
            interruption_cost=max(keeper.interruption_cost, other.interruption_cost),
            recurrence=max(keeper.recurrence, other.recurrence),
            mutation_count=max(keeper.mutation_count, other.mutation_count),
            surfaced_count=max(keeper.surfaced_count, other.surfaced_count),
            trajectory="rising" if "rising" in {keeper.trajectory, other.trajectory} else keeper.trajectory,
            state=("habituated" if "habituated" in {keeper.state, other.state} and max(keeper.novelty, other.novelty) < 0.42 else keeper.state),
            age_seconds=max(keeper.age_seconds, other.age_seconds),
            updated_age_seconds=min(keeper.updated_age_seconds, other.updated_age_seconds),
            metadata={**dict(other.metadata), **dict(keeper.metadata), "merged_projection": True},
        )
    return tuple(merged)


def match_concern(text: str, concerns: Iterable[Mapping[str, Any] | ActiveConcernView]) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for raw in concerns:
        data = raw.to_dict() if isinstance(raw, ActiveConcernView) else dict(raw)
        subject = str(data.get("subject") or data.get("theme") or "")
        overlap = semantic_overlap(text, subject)
        # Concern đang active có lợi thế nhẹ nhưng không được thắng nếu semantic lệch.
        score = overlap * (0.78 + 0.22 * clamp01(data.get("activation", 0.0)))
        if score > best_score:
            best, best_score = data, score
    if best_score < 0.26:
        return None, 0.0
    return best, clamp01(best_score)


__all__ = [
    "ActiveConcernView", "clamp01", "compact", "semantic_tokens", "semantic_overlap",
    "private_concern_view", "thought_concern_view", "agenda_concern_view",
    "merge_concern_views", "match_concern",
]
