# -*- coding: utf-8 -*-
"""Catalog hành vi cho Opening Director.

Catalog lưu *cấu trúc xã hội* chứ không lưu câu thoại hoàn chỉnh. Hai câu khác
nhau nhưng cùng kiểu "phủ nhận để ý rồi lộ là có để ý" vẫn là một move và phải
chịu cùng cooldown. Loài người đã chứng minh khá rõ rằng đổi vài từ không làm một
trò đùa cũ thành mới.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class OpeningMoveDefinition:
    family: str
    structure: tuple[str, ...]
    allowed_closeness: tuple[str, ...]
    minimum_tease_estimate: float = 0.0
    minimum_tease_confidence: float = 0.0
    requires_hook: bool = False
    allows_question: bool = True
    romantic: bool = False
    sexual: bool = False
    risk: float = 0.0
    cooldown_sessions: int = 4
    fallback_family: str = "simple_recognition"
    default_delivery: str = "warm_soft"
    default_motion: str = "none"


_MOVE_CATALOG: dict[str, OpeningMoveDefinition] = {
    "simple_recognition": OpeningMoveDefinition(
        family="simple_recognition",
        structure=("recognition", "presence"),
        allowed_closeness=("new", "familiar", "close"),
        risk=0.02,
        cooldown_sessions=1,
        default_delivery="warm_soft",
        default_motion="lean_in_small",
    ),
    "mock_indifference": OpeningMoveDefinition(
        family="mock_indifference",
        structure=("recognition", "attitude", "invitation"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.50,
        minimum_tease_confidence=0.35,
        risk=0.18,
        cooldown_sessions=4,
        default_delivery="deadpan_soft",
        default_motion="look_away",
    ),
    "delayed_affection": OpeningMoveDefinition(
        family="delayed_affection",
        structure=("recognition", "delayed_warmth"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.30,
        minimum_tease_confidence=0.20,
        allows_question=False,
        risk=0.10,
        cooldown_sessions=4,
        default_delivery="warm_restrained",
        default_motion="soft_return",
    ),
    "dry_observation": OpeningMoveDefinition(
        family="dry_observation",
        structure=("recognition", "contextual_observation", "invitation"),
        allowed_closeness=("new", "familiar", "close"),
        requires_hook=True,
        risk=0.12,
        cooldown_sessions=3,
        default_delivery="dry_tease",
        default_motion="tilt_head",
    ),
    "tsundere_denial": OpeningMoveDefinition(
        family="tsundere_denial",
        structure=("recognition", "denial", "warm_leak"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.62,
        minimum_tease_confidence=0.50,
        allows_question=False,
        risk=0.25,
        cooldown_sessions=6,
        default_delivery="deadpan",
        default_motion="look_away",
    ),
    "mock_formal_welcome": OpeningMoveDefinition(
        family="mock_formal_welcome",
        structure=("formal_recognition", "tone_break", "presence"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.55,
        minimum_tease_confidence=0.40,
        risk=0.20,
        cooldown_sessions=5,
        default_delivery="self_aware_dry",
        default_motion="nod_small",
    ),
    "false_start": OpeningMoveDefinition(
        family="false_start",
        structure=("claim", "evidence_reversal", "invitation"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.58,
        minimum_tease_confidence=0.45,
        requires_hook=True,
        risk=0.24,
        cooldown_sessions=6,
        default_delivery="self_aware_dry",
        default_motion="look_aside",
    ),
    "self_aware_performance": OpeningMoveDefinition(
        family="self_aware_performance",
        structure=("recognition", "slightly_theatrical", "self_correction"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.52,
        minimum_tease_confidence=0.38,
        risk=0.20,
        cooldown_sessions=6,
        default_delivery="self_aware_dry",
        default_motion="soft_return",
    ),
    "callback_twist": OpeningMoveDefinition(
        family="callback_twist",
        structure=("recognition", "callback", "twist"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.50,
        minimum_tease_confidence=0.45,
        risk=0.22,
        cooldown_sessions=7,
        default_delivery="soft_tease",
        default_motion="tilt_head",
    ),
    "quiet_presence": OpeningMoveDefinition(
        family="quiet_presence",
        structure=("recognition", "presence"),
        allowed_closeness=("new", "familiar", "close"),
        allows_question=False,
        risk=0.01,
        cooldown_sessions=1,
        default_delivery="low_quiet",
        default_motion="soft_return",
    ),
    "playful_challenge": OpeningMoveDefinition(
        family="playful_challenge",
        structure=("recognition", "micro_challenge"),
        allowed_closeness=("familiar", "close"),
        minimum_tease_estimate=0.68,
        minimum_tease_confidence=0.58,
        risk=0.30,
        cooldown_sessions=8,
        default_delivery="soft_tease",
        default_motion="tilt_head",
    ),
    "soft_possessive_parody": OpeningMoveDefinition(
        family="soft_possessive_parody",
        structure=("recognition", "attention_competition", "soft_retreat"),
        allowed_closeness=("close",),
        minimum_tease_estimate=0.70,
        minimum_tease_confidence=0.65,
        romantic=True,
        risk=0.46,
        cooldown_sessions=12,
        default_delivery="soft_tease",
        default_motion="look_away",
    ),
}


def get_opening_move(family: str) -> OpeningMoveDefinition:
    key = str(family or "simple_recognition").strip().lower()
    return _MOVE_CATALOG.get(key, _MOVE_CATALOG["simple_recognition"])


def opening_move_catalog() -> tuple[OpeningMoveDefinition, ...]:
    return tuple(_MOVE_CATALOG.values())


def validate_opening_move_catalog(items: Iterable[OpeningMoveDefinition] | None = None) -> tuple[str, ...]:
    """Trả danh sách lỗi thay vì ném exception để CI báo đủ một lượt."""

    errors: list[str] = []
    seen: set[str] = set()
    for item in tuple(items or opening_move_catalog()):
        if not item.family:
            errors.append("missing_family")
            continue
        if item.family in seen:
            errors.append(f"duplicate_family:{item.family}")
        seen.add(item.family)
        if not item.structure:
            errors.append(f"missing_structure:{item.family}")
        if not item.allowed_closeness:
            errors.append(f"missing_allowed_closeness:{item.family}")
        if not 0.0 <= item.risk <= 1.0:
            errors.append(f"invalid_risk:{item.family}")
        if item.cooldown_sessions < 0:
            errors.append(f"invalid_cooldown:{item.family}")
        if item.fallback_family not in _MOVE_CATALOG:
            errors.append(f"unknown_fallback:{item.family}:{item.fallback_family}")
    return tuple(errors)


__all__ = [
    "OpeningMoveDefinition",
    "get_opening_move",
    "opening_move_catalog",
    "validate_opening_move_catalog",
]
