# -*- coding: utf-8 -*-
"""Relational homeostasis cho Subject Core.

Đây là state causal rẻ, không phải personality trait và không gọi model. Nó mô tả
mức thiếu/thừa tương tác, động lực muốn chia sẻ/tò mò, kỳ vọng reciprocity và chi
phí làm phiền. State chỉ tạo *pressure/opportunity* cho connection need; Executive
vẫn quyết định có hành động hay không.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class RelationalConfig:
    # Đây là time-scale để deficit tăng dần, không phải timer ép nói.
    affiliation_horizon_seconds: float = 15.0 * 60.0
    satiety_half_life_seconds: float = 7.0 * 60.0
    sharing_half_life_seconds: float = 9.0 * 60.0
    curiosity_half_life_seconds: float = 12.0 * 60.0
    outreach_response_window_seconds: float = 150.0
    minimum_contact_pressure: float = 0.34


@dataclass(frozen=True, slots=True)
class RelationalState:
    schema: str = "eris.relational_state.v1"
    revision: int = 0
    updated_at: float = 0.0
    last_user_at: float = 0.0
    last_public_at: float = 0.0
    last_meaningful_exchange_at: float = 0.0
    last_outreach_at: float = 0.0
    outreach_waiting: bool = False
    affiliation_deficit: float = 0.0
    interaction_satiety: float = 0.0
    sharing_pressure: float = 0.0
    social_curiosity: float = 0.0
    reciprocity_expectation: float = 0.55
    partner_availability: float = 0.50
    interruption_cost: float = 0.25
    outreach_confidence: float = 0.55
    successful_outreach: int = 0
    unanswered_outreach: int = 0
    evidence_refs: tuple[str, ...] = ()

    @property
    def opportunity(self) -> float:
        return _clamp01(
            self.partner_availability
            * (1.0 - 0.72 * self.interruption_cost)
            * (0.62 + 0.38 * self.outreach_confidence)
        )

    @property
    def connection_pressure(self) -> float:
        want = max(
            self.affiliation_deficit,
            0.72 * self.sharing_pressure,
            0.62 * self.social_curiosity,
        )
        # Satiety giảm nhu cầu phá im lặng nhưng không xóa curiosity/share thật.
        return _clamp01(want * (1.0 - 0.58 * self.interaction_satiety))

    @property
    def outreach_drive(self) -> float:
        return _clamp01(
            self.connection_pressure
            * (0.52 + 0.48 * self.opportunity)
            * (0.72 + 0.28 * self.reciprocity_expectation)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "last_user_at": self.last_user_at,
            "last_public_at": self.last_public_at,
            "last_meaningful_exchange_at": self.last_meaningful_exchange_at,
            "last_outreach_at": self.last_outreach_at,
            "outreach_waiting": self.outreach_waiting,
            "affiliation_deficit": self.affiliation_deficit,
            "interaction_satiety": self.interaction_satiety,
            "sharing_pressure": self.sharing_pressure,
            "social_curiosity": self.social_curiosity,
            "reciprocity_expectation": self.reciprocity_expectation,
            "partner_availability": self.partner_availability,
            "interruption_cost": self.interruption_cost,
            "outreach_confidence": self.outreach_confidence,
            "successful_outreach": self.successful_outreach,
            "unanswered_outreach": self.unanswered_outreach,
            "evidence_refs": list(self.evidence_refs),
            "connection_pressure": self.connection_pressure,
            "opportunity": self.opportunity,
            "outreach_drive": self.outreach_drive,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "RelationalState":
        data = payload or {}
        return cls(
            revision=max(0, int(data.get("revision", 0) or 0)),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            last_user_at=float(data.get("last_user_at", 0.0) or 0.0),
            last_public_at=float(data.get("last_public_at", 0.0) or 0.0),
            last_meaningful_exchange_at=float(data.get("last_meaningful_exchange_at", 0.0) or 0.0),
            last_outreach_at=float(data.get("last_outreach_at", 0.0) or 0.0),
            outreach_waiting=bool(data.get("outreach_waiting", False)),
            affiliation_deficit=_clamp01(data.get("affiliation_deficit", 0.0)),
            interaction_satiety=_clamp01(data.get("interaction_satiety", 0.0)),
            sharing_pressure=_clamp01(data.get("sharing_pressure", 0.0)),
            social_curiosity=_clamp01(data.get("social_curiosity", 0.0)),
            reciprocity_expectation=_clamp01(data.get("reciprocity_expectation", 0.55), 0.55),
            partner_availability=_clamp01(data.get("partner_availability", 0.50), 0.50),
            interruption_cost=_clamp01(data.get("interruption_cost", 0.25), 0.25),
            outreach_confidence=_clamp01(data.get("outreach_confidence", 0.55), 0.55),
            successful_outreach=max(0, int(data.get("successful_outreach", 0) or 0)),
            unanswered_outreach=max(0, int(data.get("unanswered_outreach", 0) or 0)),
            evidence_refs=tuple(str(item) for item in data.get("evidence_refs", ()) if str(item or "").strip()),
        )


class RelationalHomeostasis:
    def __init__(self, config: RelationalConfig | None = None) -> None:
        self.config = config or RelationalConfig()

    @staticmethod
    def _decay(value: float, elapsed: float, half_life: float) -> float:
        if elapsed <= 0.0:
            return _clamp01(value)
        return _clamp01(value * math.pow(2.0, -elapsed / max(1.0, half_life)))

    def tick(
        self,
        state: RelationalState,
        *,
        now: float,
        partner_available: float | None = None,
        interruption_cost: float | None = None,
        sharing_signal: float = 0.0,
        curiosity_signal: float = 0.0,
        unresolved_signal: float = 0.0,
        evidence_refs: tuple[str, ...] = (),
    ) -> RelationalState:
        elapsed = max(0.0, float(now) - float(state.updated_at or now))
        last_exchange = state.last_meaningful_exchange_at or state.last_user_at or state.updated_at or now
        quiet = max(0.0, float(now) - float(last_exchange))
        horizon = max(30.0, self.config.affiliation_horizon_seconds)
        time_deficit = 1.0 - math.exp(-quiet / horizon)
        satiety = self._decay(state.interaction_satiety, elapsed, self.config.satiety_half_life_seconds)
        sharing = self._decay(state.sharing_pressure, elapsed, self.config.sharing_half_life_seconds)
        curiosity = self._decay(state.social_curiosity, elapsed, self.config.curiosity_half_life_seconds)
        sharing = 1.0 - (1.0 - sharing) * (1.0 - _clamp01(sharing_signal) * 0.72)
        curiosity = 1.0 - (1.0 - curiosity) * (1.0 - _clamp01(curiosity_signal) * 0.66)
        affiliation = _clamp01(max(state.affiliation_deficit * 0.96, time_deficit, unresolved_signal * 0.55))

        waiting = state.outreach_waiting
        unanswered = state.unanswered_outreach
        outreach_conf = state.outreach_confidence
        reciprocity = state.reciprocity_expectation
        learned_interrupt = state.interruption_cost
        refs = list(state.evidence_refs[-8:])
        if waiting and state.last_outreach_at > 0.0 and now - state.last_outreach_at >= self.config.outreach_response_window_seconds:
            waiting = False
            unanswered += 1
            outreach_conf = _clamp01(0.88 * outreach_conf + 0.12 * 0.25)
            reciprocity = _clamp01(0.92 * reciprocity + 0.08 * 0.30)
            learned_interrupt = _clamp01(learned_interrupt + 0.06)
            refs.append(f"relational:no_response:{state.revision + 1}")

        if partner_available is not None:
            availability = _clamp01(0.72 * state.partner_availability + 0.28 * _clamp01(partner_available))
        else:
            availability = state.partner_availability
        if interruption_cost is not None:
            learned_interrupt = _clamp01(0.76 * learned_interrupt + 0.24 * _clamp01(interruption_cost))

        refs.extend(str(item) for item in evidence_refs if str(item or "").strip())
        refs = list(dict.fromkeys(refs))[-12:]
        return replace(
            state,
            revision=state.revision + 1,
            updated_at=float(now),
            affiliation_deficit=affiliation,
            interaction_satiety=satiety,
            sharing_pressure=sharing,
            social_curiosity=curiosity,
            partner_availability=availability,
            interruption_cost=learned_interrupt,
            outreach_confidence=outreach_conf,
            reciprocity_expectation=reciprocity,
            outreach_waiting=waiting,
            unanswered_outreach=unanswered,
            evidence_refs=tuple(refs),
        )

    def note_user_turn(
        self,
        state: RelationalState,
        *,
        now: float,
        meaningful: bool = True,
        engagement: float = 0.75,
        evidence_ref: str = "",
    ) -> RelationalState:
        success = bool(state.outreach_waiting and state.last_outreach_at > 0.0 and now >= state.last_outreach_at)
        refs = list(state.evidence_refs[-8:])
        if evidence_ref:
            refs.append(evidence_ref)
        if success:
            refs.append(f"relational:outreach_reciprocated:{state.revision + 1}")
        return replace(
            state,
            revision=state.revision + 1,
            updated_at=float(now),
            last_user_at=float(now),
            last_meaningful_exchange_at=float(now) if meaningful else state.last_meaningful_exchange_at,
            outreach_waiting=False if success else state.outreach_waiting,
            affiliation_deficit=_clamp01(state.affiliation_deficit * (0.28 if meaningful else 0.62)),
            interaction_satiety=_clamp01(max(state.interaction_satiety, 0.58 + 0.30 * _clamp01(engagement))),
            social_curiosity=_clamp01(state.social_curiosity * 0.72),
            reciprocity_expectation=_clamp01(
                0.86 * state.reciprocity_expectation + 0.14 * (0.90 if success else _clamp01(engagement))
            ),
            outreach_confidence=_clamp01(
                0.84 * state.outreach_confidence + 0.16 * (0.92 if success else 0.70)
            ),
            interruption_cost=_clamp01(state.interruption_cost * (0.86 if success else 0.94)),
            successful_outreach=state.successful_outreach + (1 if success else 0),
            evidence_refs=tuple(dict.fromkeys(refs))[-12:],
        )

    def note_public_act(
        self,
        state: RelationalState,
        *,
        now: float,
        outreach: bool,
        sharing: bool = False,
        evidence_ref: str = "",
    ) -> RelationalState:
        refs = list(state.evidence_refs[-8:])
        if evidence_ref:
            refs.append(evidence_ref)
        return replace(
            state,
            revision=state.revision + 1,
            updated_at=float(now),
            last_public_at=float(now),
            last_outreach_at=float(now) if outreach else state.last_outreach_at,
            outreach_waiting=bool(outreach),
            interaction_satiety=_clamp01(max(state.interaction_satiety, 0.28 if outreach else 0.18)),
            sharing_pressure=_clamp01(state.sharing_pressure * (0.34 if sharing else 0.82)),
            affiliation_deficit=_clamp01(state.affiliation_deficit * (0.74 if outreach else 0.92)),
            evidence_refs=tuple(dict.fromkeys(refs))[-12:],
        )


__all__ = ["RelationalConfig", "RelationalHomeostasis", "RelationalState"]
