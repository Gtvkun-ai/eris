# -*- coding: utf-8 -*-
"""Canonical body-action planner constrained by spatial affordance/permission."""
from __future__ import annotations

from typing import Any

from runtime.canonical_cognition import BodyActionPlan, PermissionReport, SpatialFrame, SpeechOpportunity


class BodyActionPlannerEngine:
    module_name = "body_action_planner"

    def plan(self, frame: Any, opportunity: SpeechOpportunity, spatial: SpatialFrame, permission: PermissionReport) -> BodyActionPlan:
        if not permission.allowed_body_action:
            return BodyActionPlan()
        if opportunity.mode == "silence":
            action = "stillness"
        elif spatial.obstruction_risk > 0.55:
            action = "look_at_focus" if spatial.gaze_target else "stillness"
        elif spatial.gaze_target and spatial.gaze_target != "user":
            action = "look_at_focus"
        elif str(getattr(frame, "channel", "") or "") == "chat":
            action = "face_user"
        else:
            action = "idle_shift"
        return BodyActionPlan(
            action=action,  # type: ignore[arg-type]
            gaze_target=spatial.gaze_target,
            posture="attentive" if opportunity.speech_allowed else "neutral",
            movement=action,
            intensity=min(permission.max_intensity, 0.35 if opportunity.speech_allowed else 0.15),
            timing_delay_ms=80 if opportunity.speech_allowed else 180,
        )


__all__ = ["BodyActionPlannerEngine"]
