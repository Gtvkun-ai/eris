# -*- coding: utf-8 -*-
"""Public-safe self context cho autonomous của Architecture C.

Architecture C là đường production duy nhất, nhưng trước đây planner của nó chỉ
nhìn telemetry/screen/history. Trong khi đó Cortex V2 vẫn âm thầm duy trì drive,
agenda, private mind và private life. Kết quả khá buồn cười: Eris có nội tâm ở
panel, còn lúc mở miệng thì cư xử như chưa từng gặp chính mình.

Module này chỉ đưa sang planner những tín hiệu đã qua ranh giới công khai:
- rolling internal state dạng số, không phải chain-of-thought;
- agenda có evidence;
- surface candidate đã qua SurfaceValve/PrivateLife policy;
- attention/resource signal của Cortex V2 (không có quyền phát ngôn).

Không đọc raw diary, raw concern hay hidden reasoning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric != numeric:
        numeric = default
    return max(0.0, min(1.0, numeric))


def _compact(value: Any, limit: int = 260) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _surface_preview(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        data = dict(item)
    elif callable(getattr(item, "to_context", None)):
        try:
            data = dict(item.to_context() or {})
        except Exception:
            data = {}
    elif callable(getattr(item, "to_dict", None)):
        try:
            data = dict(item.to_dict() or {})
        except Exception:
            data = {}
    else:
        data = {}
    raw_evidence = data.get("evidence_refs", data.get("evidence_ids", ()))
    if isinstance(raw_evidence, str):
        raw_evidence = (raw_evidence,) if raw_evidence.strip() else ()
    elif not isinstance(raw_evidence, (list, tuple)):
        raw_evidence = ()
    evidence_refs = tuple(
        item for item in (_compact(value, 120) for value in raw_evidence[:6]) if item
    )
    return {
        "id": _compact(data.get("id", ""), 80),
        "kind": _compact(data.get("kind", ""), 80),
        "source": _compact(data.get("source", data.get("root_source", "")), 80),
        "topic_seed": _compact(data.get("topic_seed", data.get("seed", "")), 240),
        "confidence": _clamp01(data.get("confidence", 0.0)),
        "pressure": _clamp01(data.get("pressure", data.get("vital_pressure", 0.0))),
        "score": _clamp01(data.get("score", data.get("usefulness", 0.0))),
        "reason": _compact(data.get("reason", ""), 160),
        "evidence_refs": list(evidence_refs),
    }


@dataclass(frozen=True, slots=True)
class AutonomousSelfContext:
    internal_state: Mapping[str, Any] = field(default_factory=dict)
    attention: Mapping[str, Any] = field(default_factory=dict)
    agenda: tuple[Mapping[str, Any], ...] = ()
    private_mind_surface: tuple[Mapping[str, Any], ...] = ()
    private_life_surface: tuple[Mapping[str, Any], ...] = ()
    has_public_seed: bool = False
    strongest_seed_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_state": dict(self.internal_state),
            "attention": dict(self.attention),
            "agenda": [dict(item) for item in self.agenda],
            "private_mind_surface": [dict(item) for item in self.private_mind_surface],
            "private_life_surface": [dict(item) for item in self.private_life_surface],
            "has_public_seed": bool(self.has_public_seed),
            "strongest_seed_score": round(float(self.strongest_seed_score), 3),
        }

    def prompt_context(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def build_autonomous_self_context(host: Any) -> AutonomousSelfContext:
    """Rút public-safe self context từ runtime owner hiện tại."""

    rolling = getattr(host, "rolling_internal_state", None)
    internal_state = {
        key: round(_clamp01(getattr(rolling, key, 0.0)), 3)
        for key in (
            "curiosity",
            "fatigue",
            "silence_pressure",
            "continuity_pressure",
            "attachment_pressure",
            "consolidation_pressure",
            "insight_pressure",
            "agenda_pressure",
            "speech_restraint",
            "resource_caution",
            "self_coherence",
        )
    }
    internal_state["internal_drive"] = round(_clamp01(getattr(rolling, "internal_drive", 0.0)), 3)

    attention_obj = getattr(host, "last_cortex_attention", None)
    attention = {
        "level": _compact(getattr(attention_obj, "level", "quiet"), 48),
        "reason": _compact(getattr(attention_obj, "reason", ""), 160),
        "confidence": round(_clamp01(getattr(attention_obj, "confidence", 1.0)), 3),
        "external_pressure": round(_clamp01(getattr(attention_obj, "external_pressure", 0.0)), 3),
        "internal_drive": round(_clamp01(getattr(attention_obj, "internal_drive", 0.0)), 3),
        "interrupt_cost": round(_clamp01(getattr(attention_obj, "interrupt_cost", 0.0)), 3),
        "resource_caution": round(_clamp01(getattr(attention_obj, "resource_caution", 0.0)), 3),
        "vision_refresh_recommended": bool(getattr(attention_obj, "vision_refresh_recommended", False)),
        "semantic_authority": "none",
    }

    agenda_items: list[Mapping[str, Any]] = []
    agenda_stack = getattr(host, "internal_agenda", None)
    top_items = getattr(agenda_stack, "top_items", None)
    if callable(top_items):
        try:
            candidates = tuple(top_items(limit=5) or ())
        except Exception:
            candidates = ()
        for item in candidates:
            evidence = tuple(str(value) for value in (getattr(item, "evidence_ids", ()) or ()) if str(value).strip())[:5]
            summary = _compact(getattr(item, "summary", ""), 260)
            if not summary or not evidence:
                continue
            agenda_items.append(
                {
                    "id": _compact(getattr(item, "id", ""), 80),
                    "kind": _compact(getattr(item, "kind", "misc"), 80),
                    "summary": summary,
                    "pressure": round(_clamp01(getattr(item, "pressure", 0.0)), 3),
                    "urgency": round(_clamp01(getattr(item, "urgency", 0.0)), 3),
                    "confidence": round(_clamp01(getattr(item, "confidence", 0.0)), 3),
                    "speech_value": round(_clamp01(getattr(item, "speech_value", 0.0)), 3),
                    "score": round(_clamp01(getattr(item, "score", 0.0)), 3),
                    "evidence_refs": list(evidence),
                }
            )

    mind_digest = _mapping(getattr(host, "private_mind_daemon_digest", None))
    daemon = _mapping(mind_digest.get("daemon"))
    mind_source = daemon.get("surface_queue_preview")
    if not isinstance(mind_source, (list, tuple)):
        mind_source = tuple(getattr(host, "private_mind_surface_queue", ()) or ())
    private_mind = tuple(
        preview for preview in (_surface_preview(item) for item in tuple(mind_source or ())[:6])
        if preview.get("topic_seed")
    )

    life_digest = _mapping(getattr(host, "private_life_digest", None))
    life_source = life_digest.get("surface_queue")
    if not isinstance(life_source, (list, tuple)):
        life_source = tuple(getattr(host, "private_life_surface_queue", ()) or ())
    private_life = tuple(
        preview for preview in (_surface_preview(item) for item in tuple(life_source or ())[:6])
        if preview.get("topic_seed")
    )

    seed_scores: list[float] = []
    for item in agenda_items:
        speech_value = _clamp01(item.get("speech_value", 0.0))
        confidence = _clamp01(item.get("confidence", 0.0))
        score = _clamp01(item.get("score", 0.0))
        seed_scores.append(0.45 * speech_value + 0.30 * confidence + 0.25 * score)
    for item in (*private_mind, *private_life):
        confidence = _clamp01(item.get("confidence", 0.0))
        pressure = _clamp01(item.get("pressure", 0.0))
        score = _clamp01(item.get("score", 0.0))
        seed_scores.append(max(score, 0.48 * confidence + 0.30 * pressure + 0.22 * score))

    strongest = max(seed_scores, default=0.0)
    # Chỉ coi là public seed khi đã qua queue công khai hoặc agenda có evidence
    # và điểm đủ dùng. Nội áp đơn thuần không được biến thành độc thoại.
    has_public_seed = bool(strongest >= 0.48)

    return AutonomousSelfContext(
        internal_state=internal_state,
        attention=attention,
        agenda=tuple(agenda_items[:5]),
        private_mind_surface=private_mind,
        private_life_surface=private_life,
        has_public_seed=has_public_seed,
        strongest_seed_score=strongest,
    )


__all__ = ["AutonomousSelfContext", "build_autonomous_self_context"]
