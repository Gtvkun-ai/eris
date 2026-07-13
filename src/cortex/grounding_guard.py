# -*- coding: utf-8 -*-
"""Canonical sentence-level grounding guard.

It constrains or removes the risky unit while preserving the useful core. It is
not allowed to replace every imperfect sentence with customer-support oatmeal.
"""
from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from domain import Decision
from runtime.canonical_cognition import GroundingReport


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return max(0.0, min(1.0, default))


class GroundingGuardEngine:
    module_name = "grounding_guard"
    HIDDEN_MARKERS = (
        "[v3_cognitive_plan]", "v3_cognitive_plan", "global workspace", "theory of mind core",
        "permission engine", "cognitive arbitration", "system prompt",
    )
    BIOLOGICAL_CLAIMS = (
        "tim tôi", "trái tim tôi", "cơ thể tôi đau", "tôi đang khóc thật", "tôi không thở được",
    )
    CURRENT_SENSOR_CLAIMS = (
        "tôi đang nhìn thấy", "tôi thấy trên màn hình", "tôi đang nghe thấy", "tôi biết bạn đang",
    )

    def baseline(self, frame: Any) -> GroundingReport:
        permission = _get(frame, "permission", None)
        modality = _get(frame, "modality", None)
        return GroundingReport(
            factual_risk=0.0,
            unsupported_claims=[],
            overcertainty_risk=0.0,
            tone_violation=0.0,
            permission_violation=0.0 if bool(_get(permission, "public_sayable", True)) else 1.0,
            body_action_mismatch=_clamp(_get(modality, "contradiction_risk", 0.0), 0.0),
            repair_action="suppress_or_reduce_intensity" if not bool(_get(permission, "public_sayable", True)) else None,
            final_text=None,
        )

    def check(self, frame: Any, decision: Decision | None, *, external_grounding: Any = None) -> tuple[Decision, GroundingReport]:
        if decision is None:
            decision = Decision(text="", animation="stand", should_speak=False, parse_mode="v3_empty")
        repaired = replace(decision)
        text = str(repaired.text or "").strip()
        permission = _get(frame, "permission", None)
        opportunity = _get(frame, "speech_opportunity", None)
        modality = _get(frame, "modality", None)
        evidence = list(_get(frame, "evidence", []) or [])
        has_vision = any(str(_get(ev, "source", "")) in {"vision", "ocr", "telemetry", "active_window"} for ev in evidence)
        unsupported: list[str] = []
        tone_violation = 0.0
        permission_violation = 0.0
        overcertainty = 0.0
        repair_actions: list[str] = []

        if not bool(_get(permission, "public_sayable", True)) or not bool(_get(opportunity, "speech_allowed", True)):
            permission_violation = 1.0 if text else 0.0
            repaired.text = ""
            repaired.should_speak = False
            text = ""
            repair_actions.append("suppress_surface")

        if text:
            sentences = re.split(r"(?<=[.!?…])\s+", text)
            kept: list[str] = []
            for sentence in sentences:
                lowered = sentence.lower()
                hidden = next((m for m in self.HIDDEN_MARKERS if m in lowered), None)
                biological = next((m for m in self.BIOLOGICAL_CLAIMS if m in lowered), None)
                sensor = next((m for m in self.CURRENT_SENSOR_CLAIMS if m in lowered), None)
                if hidden:
                    unsupported.append(f"hidden_state:{sentence[:180]}")
                    repair_actions.append("remove_hidden_state_unit")
                    continue
                if biological:
                    unsupported.append(f"biological_claim:{sentence[:180]}")
                    repair_actions.append("remove_biological_claim_unit")
                    continue
                if sensor and not has_vision:
                    unsupported.append(f"sensor_claim_without_evidence:{sentence[:180]}")
                    repair_actions.append("remove_sensor_claim_unit")
                    continue
                kept.append(sentence)
            new_text = " ".join(x.strip() for x in kept if x.strip()).strip()
            if new_text != text:
                repaired.text = new_text
                repaired.should_speak = bool(new_text)
                text = new_text

        max_intensity = _clamp(_get(permission, "max_intensity", 0.5), 0.5)
        allowed_tease = bool(_get(permission, "allowed_tease", False))
        if not allowed_tease and str(repaired.delivery_hint or "").lower() in {"dry_tease", "soft_tease", "mischief", "playful_tease"}:
            repaired.delivery_hint = "restrained" if max_intensity < 0.45 else "focused"
            tone_violation = max(tone_violation, 0.55)
            repair_actions.append("clamp_tease_delivery")
        if max_intensity < 0.35 and repaired.stage_motion in {"step_closer", "lean_in_small"}:
            repaired.stage_motion = "stillness"
            tone_violation = max(tone_violation, 0.35)
            repair_actions.append("clamp_stage_intensity")

        mismatch = _clamp(_get(modality, "contradiction_risk", 0.0), 0.0)
        if mismatch >= 0.70:
            repaired.stage_motion = "stillness"
            repaired.motion_intent = "pose"
            repair_actions.append("repair_body_speech_mismatch")

        external_unsupported = list(_get(external_grounding, "unsupported_claims", []) or [])
        unsupported.extend(str(x) for x in external_unsupported if str(x).strip())
        factual_risk = _clamp(max(len(unsupported) * 0.24, _get(external_grounding, "factual_risk", 0.0)))
        overcertainty = _clamp(_get(external_grounding, "overcertainty_risk", overcertainty), overcertainty)
        report = GroundingReport(
            factual_risk=factual_risk,
            unsupported_claims=list(dict.fromkeys(unsupported)),
            overcertainty_risk=overcertainty,
            tone_violation=tone_violation,
            permission_violation=permission_violation,
            body_action_mismatch=mismatch,
            repair_action=";".join(dict.fromkeys(repair_actions)) or None,
            final_text=str(repaired.text or "") or None,
        )
        return repaired, report


__all__ = ["GroundingGuardEngine"]
