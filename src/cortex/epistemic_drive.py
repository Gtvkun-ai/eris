# -*- coding: utf-8 -*-
"""Epistemic pressure engine. Curiosity is pressure, not permission."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import EpistemicDrive, CanonicalMeaningReport, CanonicalTheoryOfMindReport


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class EpistemicDriveEngine:
    module_name = "epistemic_drive"

    def evaluate(self, frame: Any, meaning: CanonicalMeaningReport, tom: CanonicalTheoryOfMindReport) -> EpistemicDrive:
        salience = _get(frame, "salience", None)
        contradiction = 0.0
        for ev in list(_get(frame, "evidence", []) or []):
            tags = {str(x).lower() for x in (_get(ev, "tags", []) or [])}
            if tags & {"contradiction", "correction", "user_correction"}:
                contradiction = max(contradiction, _clamp(_get(ev, "confidence", 0.65), 0.65))
        temporal = _get(frame, "temporal", None)
        contradiction = max(contradiction, _clamp(_get(temporal, "meaning_debt", 0.0), 0.0))
        user_relevance = _clamp(_get(salience, "user_relevance", _get(salience, "broadcast_priority", 0.5)), 0.5)
        gap = _clamp(max(meaning.ambiguity, 1.0 - meaning.confidence))
        curiosity = _clamp(_get(_get(frame, "homeostasis", None), "curiosity_pressure", 0.2), 0.2)
        privacy_sensitivity = _clamp(_get(_get(frame, "relation", None), "privacy_sensitivity", 0.5), 0.5)
        overread = _clamp(tom.global_overread_risk, 1.0)
        intrusion = _clamp(overread * 0.62 + privacy_sensitivity * 0.26 + gap * 0.08)
        urgency = _clamp(gap * user_relevance * 0.65 + contradiction * 0.55 + curiosity * 0.18)
        return EpistemicDrive(
            curiosity_pressure=curiosity,
            knowledge_gap=gap,
            contradiction_pressure=contradiction,
            worldview_tension=_clamp(contradiction * 0.52),
            user_relevance=user_relevance,
            identity_relevance=_clamp(_get(salience, "identity_relevance", 0.0)),
            inquiry_urgency=urgency,
            intrusion_risk=intrusion,
        )


__all__ = ["EpistemicDriveEngine"]
