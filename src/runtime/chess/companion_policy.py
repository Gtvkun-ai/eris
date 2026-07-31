# -*- coding: utf-8 -*-
"""Domain attention policy for the Chess.com companion bridge.

The browser extension reports board state. This module turns that state into a
small, typed *interaction* signal: who moved, whether it was the user, how
noteworthy the change was, and what kind of public reaction would be relevant.
It deliberately does not write dialogue. Surface still owns wording.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any, Mapping

from .contracts import BoardSnapshot, ChessObservation, ChessObservationPhase


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9+#=\-]+", " ", text).split())


def _side(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"w", "white", "trang"}:
        return "white"
    if raw in {"b", "black", "den"}:
        return "black"
    return ""


def infer_companion_mode(objective: str) -> str:
    """Infer the user's requested role from their explicit chess request."""

    text = _fold(objective)
    spectator = (
        "xem toi", "xem tui", "coi toi", "coi tui", "lam khan gia",
        "khan gia", "watch me", "watch my game", "xem minh choi",
    )
    coach = (
        "chi toi", "goi y", "giup toi", "giup tui", "day toi", "huong dan",
        "phan tich", "nen di", "nen danh", "coach me", "help me",
    )
    opponent = (
        "choi voi toi", "choi voi tui", "dau voi toi", "dau voi tui",
        "play against me", "play with me",
    )
    if any(marker in text for marker in spectator):
        return "spectator"
    if any(marker in text for marker in coach):
        return "coach"
    if any(marker in text for marker in opponent):
        return "opponent"
    return "companion"


@dataclass(frozen=True, slots=True)
class ChessCompanionSignal:
    companion_mode: str = "companion"
    user_side: str = ""
    mover_side: str = ""
    actor: str = "unknown"
    actor_is_user: bool = False
    event: str = "state_changed"
    speech_act: str = "observe_position"
    commentary_focus: str = ""
    speech_reason: str = ""
    speech_priority: float = 0.0
    should_speak: bool = False
    should_wake: bool = False
    suppress_generic_screen_topics: bool = True
    suggestions_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_companion_signal(
    observation: ChessObservation,
    snapshot: BoardSnapshot,
    engagement_state: Mapping[str, Any] | None = None,
) -> ChessCompanionSignal:
    """Convert one structured chess observation into a public-attention signal."""

    state = engagement_state if isinstance(engagement_state, Mapping) else {}
    mode = str(state.get("companion_mode") or "companion").strip().lower()
    if mode not in {"spectator", "coach", "opponent", "companion"}:
        mode = "companion"

    metadata = snapshot.metadata if isinstance(snapshot.metadata, Mapping) else {}
    user_side = _side(
        state.get("user_side")
        or metadata.get("player_side")
        or metadata.get("user_side")
        or observation.user_side
        or snapshot.orientation
    )
    mover_side = _side(observation.mover_side)
    actor_is_user = bool(user_side and mover_side and user_side == mover_side)
    actor = "user" if actor_is_user else "opponent" if mover_side else "unknown"

    phase = observation.phase
    last_move = str(observation.last_move_san or observation.last_move_uci or "").strip()
    quality = str(observation.move_quality or "").strip().lower()
    swing = abs(int(observation.evaluation_swing_cp or 0))
    focus = str(observation.hint_focus or "").strip().lower()

    event = "state_changed"
    speech_act = "observe_position"
    reason = "position_changed"
    priority = 0.0

    if observation.game_over or phase is ChessObservationPhase.COMPLETED:
        event = "game_over"
        speech_act = "summarize_game"
        reason = "game_finished"
        priority = 1.0
    elif observation.game_started and not last_move:
        event = "game_started"
        speech_act = "open_watch_along"
        reason = "game_started"
        priority = 0.78
    elif phase is ChessObservationPhase.WAITING_FOR_START:
        event = "board_ready"
        speech_act = "acknowledge_ready"
        reason = "board_ready"
        priority = 0.42
    elif last_move:
        event = "user_move" if actor_is_user else "opponent_move" if mover_side else "move"
        speech_act = "react_to_user_move" if actor_is_user else "react_to_opponent_move"
        reason = f"{event}_routine"
        priority = 0.30 if actor_is_user else 0.20

        quality_weight = {
            "blunder": 0.96,
            "mistake": 0.82,
            "inaccuracy": 0.62,
            "strong": 0.76,
            "good": 0.46,
            "normal": 0.24,
        }.get(quality, 0.0)
        if quality_weight:
            priority = max(priority, quality_weight)
            reason = f"{event}_{quality}"

        if swing >= 300:
            priority = max(priority, 0.94)
            reason = f"{event}_large_eval_swing"
        elif swing >= 140:
            priority = max(priority, 0.78)
            reason = f"{event}_meaningful_eval_swing"
        elif swing >= 60:
            priority = max(priority, 0.58)

        if "#" in last_move:
            priority = 1.0
            reason = f"{event}_checkmate"
        elif "+" in last_move:
            priority = max(priority, 0.76)
            reason = f"{event}_check"
        elif "=" in last_move:
            priority = max(priority, 0.82)
            reason = f"{event}_promotion"
        elif "o-o" in last_move.lower() or "0-0" in last_move.lower():
            priority = max(priority, 0.54)
            reason = f"{event}_castling"
        elif "x" in last_move:
            priority = max(priority, 0.48)
            reason = f"{event}_capture"

        if focus in {"forcing_check", "forcing_capture"}:
            priority = max(priority, 0.60)
        if actor_is_user and mode == "spectator":
            priority = min(1.0, priority + 0.08)
        if observation.game_started:
            priority = max(priority, 0.72)
            reason = f"{event}_opens_game"

    threshold = {
        "spectator": 0.56,
        "coach": 0.48,
        "opponent": 0.50,
        "companion": 0.58,
    }[mode]
    should_speak = bool(
        event in {"game_started", "game_over"}
        or (event == "board_ready" and not bool(state.get("board_acknowledged", False)))
        or priority >= threshold
    )

    # Spectator mode means commentary, not unsolicited engine moves. Coach mode
    # may expose suggestions, while direct user questions still use the separate
    # authoritative answer path.
    suggestions_allowed = mode == "coach"
    if event in {"user_move", "opponent_move", "move"}:
        actor_phrase = "the user's move" if actor_is_user else "the opponent's move" if mover_side else "the latest move"
        commentary_focus = (
            f"React to {actor_phrase} {last_move or '(unknown SAN)'}. "
            f"Use move_quality={quality or 'unknown'}, evaluation_swing_cp={observation.evaluation_swing_cp}, "
            f"evaluation={observation.evaluation_label or 'unknown'}, motif={focus or 'none'}. "
            + (
                "Do not recommend a move unless the user asks; behave as a watch-along spectator."
                if mode == "spectator"
                else "A concrete suggestion is allowed only when present in typed state."
            )
        )
    elif event == "game_started":
        commentary_focus = "Open the chess watch-along naturally. Do not mention bridge telemetry or OCR."
    elif event == "board_ready":
        commentary_focus = "Acknowledge that the game is ready and wait for the first move. Do not say 'snapshot received'."
    elif event == "game_over":
        commentary_focus = "Give one concise result-aware closing comment grounded in the final typed state."
    else:
        commentary_focus = "Keep attention on the active chess game and remain silent unless a meaningful event occurs."

    return ChessCompanionSignal(
        companion_mode=mode,
        user_side=user_side,
        mover_side=mover_side,
        actor=actor,
        actor_is_user=actor_is_user,
        event=event,
        speech_act=speech_act,
        commentary_focus=commentary_focus,
        speech_reason=reason,
        speech_priority=round(max(0.0, min(1.0, priority)), 3),
        should_speak=should_speak,
        should_wake=should_speak,
        suppress_generic_screen_topics=True,
        suggestions_allowed=suggestions_allowed,
    )


__all__ = [
    "ChessCompanionSignal",
    "build_companion_signal",
    "infer_companion_mode",
]
