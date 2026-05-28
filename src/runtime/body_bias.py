from __future__ import annotations

from typing import Callable

from cortex.internal_state import PersistentInternalState


class BodyBiasProjector:
    """Projects cognitive state into the compact body-bias payload Godot consumes."""

    def __init__(self, state_provider: Callable[[], PersistentInternalState]):
        self._state_provider = state_provider

    def build_payload(self, observer_frame=None) -> dict[str, object]:
        state = self._state_provider()
        focus_kind = self.normalize_focus_kind(str(getattr(state, "last_focus_kind", "") or "unknown"))
        observer_salience = self.clamp(getattr(observer_frame, "salience", 0.0) if observer_frame is not None else 0.0)
        observer_error = self.clamp(getattr(observer_frame, "possible_error", 0.0) if observer_frame is not None else 0.0)
        continuity_anxiety = self.clamp(
            max(
                float(getattr(state, "recursive_reactivation_pressure", 0.0) or 0.0),
                float(getattr(state, "memory_replay_pressure", 0.0) or 0.0) * 0.72,
                float(getattr(state, "silence_pressure", 0.0) or 0.0) * 0.82,
                min(1.0, float(getattr(state, "silence_ticks", 0) or 0) / 18.0),
                observer_error * 0.80,
            )
        )
        curiosity = self.clamp(
            max(
                float(getattr(state, "curiosity", 0.0) or 0.0),
                float(getattr(state, "curiosity_pressure", 0.0) or 0.0),
                float(getattr(state, "association_pressure", 0.0) or 0.0) * 0.86,
                observer_salience * (0.74 if focus_kind == "code" else 0.52),
            )
            + (0.12 if focus_kind == "code" else 0.0)
        )
        overload = self.clamp(
            max(
                float(getattr(state, "fatigue", 0.0) or 0.0),
                float(getattr(state, "cognitive_tension", 0.0) or 0.0),
                float(getattr(state, "restraint_pressure", 0.0) or 0.0) * 0.55,
                observer_error * 0.68,
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
        if normalized in {"coding", "ide"}:
            return "code"
        if normalized in {"documentation", "doc", "reference"}:
            return "docs"
        if normalized in {"focus_aid_media", "entertainment"}:
            return "media"
        return normalized or "unknown"
