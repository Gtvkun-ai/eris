# -*- coding: utf-8 -*-
"""Biến relational pressure của Subject Core thành affordance công khai typed.

Nguồn này không viết lời và không chọn speak/silence. Nó chỉ tạo một khả năng
``contact_bid`` có motivational provenance; Executive vẫn phải chọn coalition.
"""
from __future__ import annotations

from typing import Any, Mapping

from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def build_relational_affordance(
    relational: Mapping[str, Any] | None,
    *,
    now: float,
    reply_expected: bool = False,
    user_busy: bool = False,
    interaction_busy: bool = False,
) -> ExecutiveAffordance | None:
    state = relational or {}
    pressure = _clamp01(state.get("connection_pressure", 0.0))
    opportunity = _clamp01(state.get("opportunity", 0.0))
    drive = _clamp01(state.get("outreach_drive", 0.0))
    interruption = _clamp01(state.get("interruption_cost", 0.25), 0.25)
    confidence = _clamp01(state.get("outreach_confidence", 0.55), 0.55)
    if reply_expected or user_busy or interaction_busy:
        return None
    if pressure < 0.30 or drive < 0.30 or opportunity < 0.22:
        return None

    sharing = _clamp01(state.get("sharing_pressure", 0.0))
    curiosity = _clamp01(state.get("social_curiosity", 0.0))
    affiliation = _clamp01(state.get("affiliation_deficit", 0.0))
    if sharing >= max(curiosity, affiliation) and sharing >= 0.34:
        motive = "want_to_share"
        topic = (
            "Offer one small self-originated thought to reopen contact. The motive may be internal, "
            "but do not invent any external event, user state, or factual pretext."
        )
        speech_act = "share_self_originated_thought"
    elif curiosity >= affiliation and curiosity >= 0.30:
        motive = "social_curiosity"
        topic = (
            "Open one low-pressure question motivated by curiosity about the user. Do not assume what "
            "the user is doing, feeling, or intending; leave them an easy way not to engage."
        )
        speech_act = "curiosity_bid"
    else:
        motive = "affiliation"
        topic = (
            "Make one low-pressure contact bid because continued connection currently matters to Eris. "
            "Do not cite loneliness, guilt the user, or fabricate a situational reason for speaking."
        )
        speech_act = "contact_bid"

    revision = max(0, int(state.get("revision", 0) or 0))
    refs = tuple(
        dict.fromkeys(
            (
                f"relational-state:{revision}",
                *(str(item) for item in state.get("evidence_refs", ()) if str(item or "").strip()),
            )
        )
    )[:8]
    candidate = SocialSpeechCandidate(
        decision="candidate",
        kind="social_check_in",
        topic=topic,
        speech_act=speech_act,
        anchor_type="idle",
        anchor_id=f"relational:{revision}",
        evidence_refs=refs,
        requires_grounding=False,
        confidence=_clamp01(0.35 + 0.35 * confidence + 0.20 * opportunity),
        relevance=max(0.32, drive),
        urgency=_clamp01(0.18 + 0.62 * pressure),
        tone="casual_warm",
        reason=f"subject_relational_homeostasis:{motive}:drive={drive:.2f}:opportunity={opportunity:.2f}",
        source="subject_relational_homeostasis",
        eris_motive_kind=motive,
        eris_motive_why_now="relational pressure crossed a learned opportunity window",
        personal_stake=pressure,
        authenticity=1.0,
        uncertainty=1.0 - confidence,
        seed_intrusion_risk=interruption,
        face_risk=_clamp01(0.18 + 0.35 * interruption),
        recovery_available=True,
    )
    return ExecutiveAffordance(
        affordance_id=f"relational:contact:{revision}",
        owner="subject_relational_homeostasis",
        revision=revision,
        candidate=candidate,
        claim_required=False,
        expires_at=float(now) + 45.0,
        metadata={
            "motivational_provenance": True,
            "connection_pressure": pressure,
            "opportunity": opportunity,
            "outreach_drive": drive,
        },
    )


__all__ = ["build_relational_affordance"]
