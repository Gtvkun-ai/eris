# -*- coding: utf-8 -*-
"""Feature flags, deterministic canary assignment and shadow evaluation.

A social planner is exactly the sort of feature humans switch on globally five
minutes before lunch and then spend the afternoon discovering that silence was a
feature. This policy keeps assignment stable for a session/user and supports a
shadow mode where model appraisals are measured without granting microphone
rights.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping

from .social_plan import empty_social_plan, normalize_social_plan


_VARIANT_LANES = {
    "control": frozenset({"conversation_arc"}),
    "afterbeat": frozenset({"conversation_arc", "afterbeat"}),
    "exposure": frozenset({"conversation_arc", "afterbeat", "exposure"}),
    "full": frozenset({"conversation_arc", "afterbeat", "exposure", "agenda_update"}),
}


def _env(name: str, default: str) -> str:
    return str(os.getenv(name, default) or default).strip()


def _bucket(subject_id: str, experiment: str) -> float:
    raw = f"{experiment}:{subject_id}".encode("utf-8", errors="ignore")
    value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return value / float(2**64 - 1)


def _parse_weights(raw: str) -> tuple[tuple[str, float], ...]:
    weights: list[tuple[str, float]] = []
    for part in str(raw or "").split(","):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        variant = name.strip().lower()
        if variant not in _VARIANT_LANES:
            continue
        try:
            weight = max(0.0, float(value.strip()))
        except (TypeError, ValueError):
            continue
        weights.append((variant, weight))
    total = sum(weight for _, weight in weights)
    if total <= 0.0:
        return (("control", 0.25), ("afterbeat", 0.25), ("exposure", 0.25), ("full", 0.25))
    return tuple((variant, weight / total) for variant, weight in weights)


@dataclass(frozen=True, slots=True)
class SocialRolloutPolicy:
    experiment: str
    subject_id: str
    mode: str
    variant: str
    sample_rate: float
    bucket: float

    @classmethod
    def from_env(cls, *, subject_id: str) -> "SocialRolloutPolicy":
        experiment = _env("ERIS_SOCIAL_EXPERIMENT", "social_agenda_v21")
        mode = _env("ERIS_SOCIAL_ROLLOUT_MODE", "shadow").lower()
        if mode not in {"off", "shadow", "active"}:
            mode = "off"
        try:
            sample_rate = max(0.0, min(1.0, float(_env("ERIS_SOCIAL_ROLLOUT_RATE", "1.0"))))
        except ValueError:
            sample_rate = 1.0
        subject = str(subject_id or "anonymous-session").strip() or "anonymous-session"
        bucket = _bucket(subject, experiment)
        if bucket >= sample_rate:
            variant = "control"
        else:
            relative = bucket / sample_rate if sample_rate > 0.0 else 1.0
            cumulative = 0.0
            variant = "control"
            for candidate, weight in _parse_weights(
                _env("ERIS_SOCIAL_VARIANT_WEIGHTS", "control:25,afterbeat:25,exposure:25,full:25")
            ):
                cumulative += weight
                if relative <= cumulative:
                    variant = candidate
                    break
        forced = _env("ERIS_SOCIAL_FORCE_VARIANT", "").lower()
        if forced in _VARIANT_LANES:
            variant = forced
        return cls(
            experiment=experiment,
            subject_id=subject,
            mode=mode,
            variant=variant,
            sample_rate=sample_rate,
            bucket=bucket,
        )

    def allows(self, lane: str) -> bool:
        if self.mode != "active":
            return False
        return str(lane or "").strip().lower() in _VARIANT_LANES.get(self.variant, frozenset())

    def filter_social_plan(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        original = normalize_social_plan(payload)
        filtered = empty_social_plan()
        if self.mode == "off":
            # Conversation arcs existed before this rollout and remain part of the
            # baseline unless the operator explicitly disables their own flag.
            filtered["conversation_arc"] = original["conversation_arc"]
            return filtered
        allowed = _VARIANT_LANES.get(self.variant, frozenset()) if self.mode == "active" else frozenset()
        for lane in ("afterbeat", "exposure", "agenda_update", "conversation_arc"):
            if lane in allowed:
                filtered[lane] = original[lane]
        self.observe(original, filtered)
        return filtered

    def observe(self, original: Mapping[str, Any], filtered: Mapping[str, Any]) -> None:
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY

            decision_fields = {
                "afterbeat": str(dict(original.get("afterbeat", {})).get("decision", "none")),
                "exposure": str(dict(original.get("exposure", {})).get("decision", "none")),
                "agenda": str(dict(original.get("agenda_update", {})).get("decision", "none")),
                "arc": str(dict(original.get("conversation_arc", {})).get("decision", "none")),
            }
            active_fields = {
                "afterbeat": str(dict(filtered.get("afterbeat", {})).get("decision", "none")),
                "exposure": str(dict(filtered.get("exposure", {})).get("decision", "none")),
                "agenda": str(dict(filtered.get("agenda_update", {})).get("decision", "none")),
                "arc": str(dict(filtered.get("conversation_arc", {})).get("decision", "none")),
            }
            GLOBAL_OBSERVABILITY.increment(
                "eris_social_plan_appraisals_total",
                tags={"experiment": self.experiment, "variant": self.variant, "mode": self.mode},
                fields={"proposed": decision_fields, "activated": active_fields},
            )
        except Exception:
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "subject_id_hash": hashlib.sha256(self.subject_id.encode("utf-8")).hexdigest()[:12],
            "mode": self.mode,
            "variant": self.variant,
            "sample_rate": self.sample_rate,
            "bucket": round(self.bucket, 8),
            "allowed_lanes": sorted(_VARIANT_LANES.get(self.variant, frozenset())) if self.mode == "active" else [],
        }


__all__ = ["SocialRolloutPolicy"]
