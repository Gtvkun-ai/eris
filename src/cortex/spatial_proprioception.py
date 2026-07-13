# -*- coding: utf-8 -*-
"""Spatial/body state adapter for canonical V3.

Reads real renderer/telemetry fields when present and degrades explicitly to an
unknown shared-space state. Defaults are not magically treated as observations.
"""
from __future__ import annotations

import math
from typing import Any

from runtime.canonical_cognition import SpatialFrame


def _get(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        if obj is None:
            break
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None and value != "":
            return value
    return default


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class SpatialProprioceptionEngine:
    module_name = "spatial_proprioception"

    def evaluate(self, frame: Any, *, snapshot: Any = None, legacy_frame: Any = None) -> SpatialFrame:
        body_state = _get(legacy_frame, ("body_state", "body_state_before", "body_state_after"), None)
        source = snapshot if snapshot is not None else body_state

        x = _clamp(_get(source, ("inferred_pos_x", "body_x", "position_x", "x"), 0.5), 0.5)
        y = _clamp(_get(source, ("inferred_pos_y", "body_y", "position_y", "y"), 0.5), 0.5)
        facing_x = _num(_get(source, ("facing_x", "look_dx", "direction_x"), 0.0), 0.0)
        facing_y = _num(_get(source, ("facing_y", "look_dy", "direction_y"), 1.0), 1.0)
        norm = math.hypot(facing_x, facing_y) or 1.0
        facing = (facing_x / norm, facing_y / norm)

        active = str(_get(snapshot, ("active_window", "active_app", "focus_summary", "active_window_kind"), "") or "").strip()
        gaze = str(_get(source, ("gaze_target", "look_target", "focus_target"), active) or "").strip() or None
        idle = max(0.0, _num(_get(snapshot, ("idle_seconds",), 0.0), 0.0))
        posture_raw = str(_get(source, ("posture", "body_posture", "pose"), "") or "").strip().lower()
        posture_alias = {
            "stand": "neutral", "standing": "neutral", "listen": "attentive", "focused": "attentive",
            "away": "withdrawn", "withdraw": "withdrawn", "walk": "approaching", "leaving": "leaving",
        }
        posture = posture_alias.get(posture_raw, posture_raw)
        if posture not in {"neutral", "attentive", "withdrawn", "idle", "approaching", "leaving"}:
            posture = "idle" if idle >= 30 else "attentive"

        distance = _clamp(_get(source, ("distance_to_focus", "focus_distance", "normalized_distance"), 0.35 if gaze else 0.5), 0.5)
        obstruction = _clamp(_get(source, ("obstruction_risk", "collision_risk", "blocked_ratio"), 0.0), 0.0)
        relation_raw = str(_get(source, ("shared_space_relation", "space_relation"), "") or "").strip().lower()
        if relation_raw not in {"near", "far", "blocking", "parallel", "unknown"}:
            if obstruction >= 0.6:
                relation_raw = "blocking"
            elif gaze and distance <= 0.35:
                relation_raw = "near"
            elif gaze and distance >= 0.75:
                relation_raw = "far"
            elif gaze:
                relation_raw = "parallel"
            else:
                relation_raw = "unknown"

        approach = _clamp((1.0 - obstruction) * (0.72 if distance > 0.35 else 0.42) * (0.7 if idle > 30 else 1.0))
        withdrawal = _clamp(0.25 + obstruction * 0.65 + (0.25 if posture in {"withdrawn", "leaving"} else 0.0))
        meaning = None
        if obstruction >= 0.6:
            meaning = "avoid_obstruction"
        elif gaze:
            meaning = "attend_to_active_focus"

        return SpatialFrame(
            body_position=(x, y),
            facing_direction=facing,
            gaze_target=gaze or ("user" if str(getattr(frame, "channel", "")) == "chat" else None),
            posture=posture,  # type: ignore[arg-type]
            distance_to_focus=distance,
            obstruction_risk=obstruction,
            shared_space_relation=relation_raw,  # type: ignore[arg-type]
            approach_affordance=approach,
            withdrawal_affordance=withdrawal,
            body_interaction_meaning=meaning,
        )


__all__ = ["SpatialProprioceptionEngine"]
