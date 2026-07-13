# -*- coding: utf-8 -*-
"""Synchronizes speech, body and system action plans."""
from __future__ import annotations
from runtime.canonical_cognition import ModalitySyncFrame, SpeechPlan, BodyActionPlan, SpatialFrame, PermissionReport


class ModalitySyncEngine:
    module_name = "modality_sync"

    def sync(self, speech: SpeechPlan, body: BodyActionPlan, spatial: SpatialFrame, permission: PermissionReport, *, system_action: str = "") -> ModalitySyncFrame:
        notes: list[str] = []
        contradiction = 0.0
        if speech.speech_act in {"support", "repair"} and body.action in {"withdraw", "turn_away_softly"}:
            contradiction = max(contradiction, 0.74)
            notes.append("Repair/support cannot be paired with strong withdrawal.")
        if speech.speech_act == "tease" and body.action == "step_closer" and permission.max_intensity < 0.55:
            contradiction = max(contradiction, 0.70)
            notes.append("Tease plus approach exceeds relational intensity permission.")
        if body.action not in permission.allowed_body_action:
            contradiction = max(contradiction, 0.88)
            notes.append("Body action is outside permission; replaced by stillness.")
            body = BodyActionPlan(action="stillness", posture="neutral", intensity=0.1)
        if spatial.obstruction_risk > 0.55 and body.action in {"step_closer", "approach_focus"}:
            contradiction = max(contradiction, 0.84)
            notes.append("Approach blocked by spatial obstruction; replaced by look_at_focus.")
            body = BodyActionPlan(action="look_at_focus", gaze_target=spatial.gaze_target, posture="attentive", intensity=0.18)
        safety = max(0.0, min(1.0, 1.0 - spatial.obstruction_risk))
        return ModalitySyncFrame(
            speech_plan=speech,
            body_plan=body,
            system_action=system_action or None,
            emotional_congruence=max(0.0, min(1.0, 1.0 - contradiction * 0.68)),
            spatial_safety=safety,
            contradiction_risk=contradiction,
            final_delay_ms=max(0, int(body.timing_delay_ms)),
            correction_notes=notes,
        )


__all__ = ["ModalitySyncEngine"]
