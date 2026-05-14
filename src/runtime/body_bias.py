from __future__ import annotations

from typing import Callable

from cortex.internal_state import PersistentInternalState


class BodyBiasProjector:
    """Projects cognitive state into the compact body-bias payload Godot consumes."""

    def __init__(self, state_provider: Callable[[], PersistentInternalState]):
        self._state_provider = state_provider

    def build_payload(self) -> dict[str, object]:
        state = self._state_provider()
        focus_kind = self.normalize_focus_kind(str(getattr(state, "last_focus_kind", "") or "unknown"))
        continuity_anxiety = self.clamp(
            max(
                float(getattr(state, "recursive_reactivation_pressure", 0.0) or 0.0),
                float(getattr(state, "memory_replay_pressure", 0.0) or 0.0) * 0.72,
                float(getattr(state, "silence_pressure", 0.0) or 0.0) * 0.82,
                min(1.0, float(getattr(state, "silence_ticks", 0) or 0) / 18.0),
            )
        )
        curiosity = self.clamp(
            max(
                float(getattr(state, "curiosity", 0.0) or 0.0),
                float(getattr(state, "curiosity_pressure", 0.0) or 0.0),
                float(getattr(state, "association_pressure", 0.0) or 0.0) * 0.86,
            )
            + (0.12 if focus_kind == "code" else 0.0)
        )
        overload = self.clamp(
            max(
                float(getattr(state, "fatigue", 0.0) or 0.0),
                float(getattr(state, "cognitive_tension", 0.0) or 0.0),
                float(getattr(state, "restraint_pressure", 0.0) or 0.0) * 0.55,
            )
        )
        solitude = self.clamp(
            max(
                float(getattr(state, "restraint_pressure", 0.0) or 0.0),
                0.22 + overload * 0.34,
                float(getattr(state, "subconscious_pressure", 0.0) or 0.0) * 0.44,
            )
        )
        preferred_anchor = "chat_near"
        if overload >= 0.58 or solitude >= 0.66:
            preferred_anchor = "bottom_right"
        elif focus_kind == "code" and curiosity >= max(0.48, continuity_anxiety + 0.06):
            preferred_anchor = "code_side"

        return {
            "continuity_anxiety": round(continuity_anxiety, 3),
            "curiosity": round(curiosity, 3),
            "overload": round(overload, 3),
            "solitude": round(solitude, 3),
            "focus_kind": focus_kind,
            "preferred_anchor": preferred_anchor,
        }

    @staticmethod
    def clamp(value: object) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        if numeric != numeric:
            numeric = 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def normalize_focus_kind(value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"coding", "documentation", "ide"}:
            return "code"
        return normalized or "unknown"
