# -*- coding: utf-8 -*-
"""Cầu nối từ Identity Kernel sang biểu hiện sân khấu.

Module này không viết lại public text. Nó chỉ chọn preset sân khấu cơ học dựa
trên state đã được reducer chấp nhận: appraisal, motive, defense, conflict và
relationship. Main model vẫn sở hữu câu chữ; frontend chỉ nhận nhịp/pose/cue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contracts import RuntimeMindState, clamp01, compact


@dataclass(frozen=True, slots=True)
class IdentityExpression:
    preset: str = "neutral"
    confidence: float = 0.0
    intensity: float = 0.0
    sentence_bias: str = "balanced"
    initiative_bias: float = 0.0
    reasons: tuple[str, ...] = ()
    source: str = "identity_expression_bridge"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


class IdentityExpressionBridge:
    """Suy ra một preset duy nhất, có ưu tiên và hysteresis nhẹ theo state.

    Hysteresis ở đây không lưu mode riêng. Nó chỉ tránh việc một tín hiệu yếu
    thay preset rõ do planner/main model đã chọn. Derived dark-form labels tuyệt
    đối không được dùng làm prompt hoặc trigger trực tiếp.
    """

    def derive(
        self,
        state: RuntimeMindState | None,
        *,
        requested_hint: str = "neutral",
        channel: str = "chat",
    ) -> IdentityExpression:
        requested = self._normalize_hint(requested_hint)
        if state is None:
            return IdentityExpression(preset=requested, confidence=0.30, reasons=("no_state",))

        appraisal = state.appraisal
        identity = state.identity
        relation = identity.primary_relationship()
        active_motives = {item.key: item.strength for item in identity.active_motives}
        active_defenses = {item.key: item.strength for item in identity.active_defenses}
        conflict = identity.active_conflict
        observation = dict(state.latest_observation or {})

        candidates: list[tuple[float, str, str, str, float]] = []

        def add(score: float, preset: str, reason: str, sentence_bias: str = "balanced", initiative: float = 0.0) -> None:
            if score <= 0.0:
                return
            candidates.append((clamp01(score), preset, reason, sentence_bias, max(-1.0, min(1.0, initiative))))

        # Repair phải thắng diễn xuất màu mè. Một lỗi thật mà vẫn cười khẽ là cách
        # rất hiệu quả để biến cá tính thành khó chịu.
        if bool(observation.get("repair_needed", False)):
            add(0.96, "repair", "repair_needed", "short_direct", -0.35)

        embarrassment = appraisal.embarrassment
        irritation = appraisal.irritation
        curiosity = max(appraisal.curiosity, appraisal.novelty * 0.72, active_motives.get("curiosity_drive", 0.0))
        tenderness = appraisal.tenderness
        pressure = appraisal.pressure

        intellectualization = active_defenses.get("intellectualization", 0.0)
        cold_distance = active_defenses.get("cold_distancing", 0.0)
        sarcastic_deflection = active_defenses.get("sarcastic_deflection", 0.0)
        withdrawal = active_defenses.get("withdrawal", 0.0)
        silent_compensation = active_defenses.get("silent_compensation", 0.0)

        if embarrassment >= 0.42 and intellectualization >= 0.48:
            add(
                0.52 + 0.30 * embarrassment + 0.18 * intellectualization,
                "focused",
                "embarrassment_hidden_by_technical_precision",
                "short_technical",
                -0.20,
            )
        if irritation >= 0.40 and (identity.values.get("dignity", 0.0) >= 0.72 or cold_distance >= 0.45):
            preset = "cold_precision" if irritation < 0.68 else "annoyed_soft"
            add(
                0.50 + 0.34 * irritation + 0.16 * max(cold_distance, withdrawal),
                preset,
                "dignity_under_pressure",
                "short_cold",
                -0.30,
            )
        if silent_compensation >= 0.55 and embarrassment >= 0.30:
            add(0.58 + 0.28 * silent_compensation, "repair", "silent_compensation_after_error", "short_direct", -0.25)

        if curiosity >= 0.58:
            add(0.45 + 0.45 * curiosity, "curious", "active_curiosity", "compact_then_invite", 0.18)
        if tenderness >= 0.46 and relation.closeness >= 0.42:
            add(0.42 + 0.32 * tenderness + 0.18 * relation.closeness, "soft_warm", "relational_warmth", "soft_compact", 0.08)

        playful = max(relation.playful_safety, state.personality.temperament.get("playfulness", 0.0))
        if playful >= 0.50 and sarcastic_deflection >= 0.34 and irritation < 0.46:
            add(0.40 + 0.30 * playful + 0.20 * sarcastic_deflection, "dry_tease", "safe_counter_teasing", "compact_punchline", 0.10)
        elif playful >= 0.62 and irritation < 0.34:
            add(0.42 + 0.35 * playful, "playful", "playful_safety", "compact_punchline", 0.14)

        if conflict.conflict_id == "attachment_vs_pride" and conflict.activation >= 0.52:
            chosen = compact(conflict.chosen_side, 60).lower()
            if "pride" in chosen:
                add(0.58 + 0.28 * conflict.activation, "cold_precision", "attachment_vs_pride_pride_wins", "short_cold", -0.20)
            else:
                add(0.54 + 0.26 * conflict.activation, "warm_embarrassed", "attachment_vs_pride_attachment_leaks", "soft_compact", 0.06)

        if pressure >= 0.72 and withdrawal >= 0.48:
            add(0.60 + 0.28 * pressure, "sad_distant", "overload_withdrawal", "very_short", -0.45)

        # Requested hint vẫn có trọng lượng. Bridge chỉ override khi state đủ rõ.
        requested_score = 0.52 if requested != "neutral" else 0.26
        add(requested_score, requested, "planner_or_main_hint")

        candidates.sort(key=lambda item: item[0], reverse=True)
        score, preset, reason, sentence_bias, initiative = candidates[0]
        reasons = tuple(item[2] for item in candidates[:3] if item[0] >= score - 0.14)
        return IdentityExpression(
            preset=preset,
            confidence=round(score, 4),
            intensity=round(max(irritation, curiosity, tenderness, embarrassment, pressure), 4),
            sentence_bias=sentence_bias,
            initiative_bias=round(initiative, 4),
            reasons=reasons,
        )

    @staticmethod
    def _normalize_hint(value: str) -> str:
        key = str(value or "neutral").strip().lower().replace("-", "_").replace(" ", "_")
        return key or "neutral"


__all__ = ["IdentityExpression", "IdentityExpressionBridge"]
