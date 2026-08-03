# -*- coding: utf-8 -*-
"""Full social-plan execution policy.

V22 is a hard cutover. There is no control, shadow, canary, percentage bucket,
or legacy arc-only branch. Every valid social-plan lane is active. Runtime safety
still decides whether a claimed move owns the floor; this module only removes the
old product rollout fork.
"""
from __future__ import annotations

from typing import Any, Mapping

from .social_plan import normalize_social_plan

FULL_SOCIAL_LANES = frozenset({"afterbeat", "exposure", "agenda_update", "conversation_arc"})


def accept_full_social_plan(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    plan = normalize_social_plan(payload)
    _observe(plan)
    return plan


def _observe(plan: Mapping[str, Any]) -> None:
    try:
        from runtime.observability import GLOBAL_OBSERVABILITY

        decisions = {
            "afterbeat": str(dict(plan.get("afterbeat", {})).get("decision", "none")),
            "exposure": str(dict(plan.get("exposure", {})).get("decision", "none")),
            "agenda": str(dict(plan.get("agenda_update", {})).get("decision", "none")),
            "arc": str(dict(plan.get("conversation_arc", {})).get("decision", "none")),
        }
        GLOBAL_OBSERVABILITY.increment(
            "eris_social_plan_appraisals_total",
            tags={"execution": "full_cutover", "version": "v22"},
            fields={"proposed": decisions, "activated": decisions},
        )
    except Exception:
        pass


def status() -> dict[str, Any]:
    return {
        "mode": "full_cutover",
        "variant": "full",
        "allowed_lanes": sorted(FULL_SOCIAL_LANES),
        "legacy_generic_initiative": False,
        "legacy_top_level_conversation_arc": False,
    }


__all__ = ["FULL_SOCIAL_LANES", "accept_full_social_plan", "status"]
