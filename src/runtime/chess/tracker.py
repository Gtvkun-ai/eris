# -*- coding: utf-8 -*-
"""Stateful board tracker and mode-aware companion analysis."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from .contracts import (
    BoardSnapshot,
    ChessAssistMode,
    ChessObservation,
    ChessObservationPhase,
    MoveSuggestion,
)
from .engine import Position, analyze, apply_move, evaluate, evaluation_label, in_check, infer_transition, move_san
from .mode_policy import classify_mode


@dataclass(slots=True)
class _GameState:
    position: Position
    seen: int = 0
    last_evaluation_cp: int | None = None
    phase: ChessObservationPhase = ChessObservationPhase.WAITING_FOR_START
    last_ply: int = 0
    # Chess.com /play/computer có thể giữ nguyên URL/game_id và còn gửi status
    # ``completed`` của ván trước trong vài snapshot đầu ván mới. Khi đã phát hiện
    # ply quay về đầu, tạm bỏ qua status terminal cũ cho tới khi có result thật.
    ignore_stale_terminal_status: bool = False


class ChessGameTracker:
    def __init__(self, *, depth: int = 2, direct_move_rate: float = 0.18) -> None:
        self.depth = max(1, min(4, int(depth)))
        self.direct_move_rate = max(0.0, min(1.0, float(direct_move_rate)))
        self._games: dict[str, _GameState] = {}
        self._lock = threading.RLock()

    def observe(self, snapshot: BoardSnapshot) -> ChessObservation:
        if not snapshot.board_fen:
            raise ValueError("board_fen is required")
        mode = classify_mode(snapshot)
        key = f"{snapshot.platform}:{snapshot.game_id}"
        with self._lock:
            state = self._games.get(key)
            game_started = False
            last_move = None
            last_san = ""
            resynced = False
            mover = ""
            previous_score = state.last_evaluation_cp if state is not None else None

            # Trang chơi với máy thường tái sử dụng cùng game_id. Dấu hiệu chắc
            # nhất của ván mới là tracker đã COMPLETED nhưng ply quay lùi mạnh
            # hoặc trở về đầu trong khi bàn đã đổi. Nếu không reset tại đây, mọi
            # nước của ván sau sẽ tiếp tục mang phase=completed, một cách rất
            # hiệu quả để khiến trợ lý tuyên bố đám tang giữa khai cuộc.
            reset_completed_game = bool(
                state is not None
                and state.phase is ChessObservationPhase.COMPLETED
                and state.position.board_fen != snapshot.board_fen
                and (
                    snapshot.ply < state.last_ply
                    or snapshot.ply <= 1
                )
            )
            if state is None or reset_completed_game:
                turn = "w" if snapshot.ply % 2 == 0 else "b"
                position = Position.from_board_fen(snapshot.board_fen, turn=turn, ply=snapshot.ply)
                phase = (
                    ChessObservationPhase.ACTIVE
                    if _snapshot_has_started(snapshot)
                    else ChessObservationPhase.WAITING_FOR_START
                )
                state = _GameState(
                    position=position,
                    seen=1,
                    phase=phase,
                    last_ply=snapshot.ply,
                    ignore_stale_terminal_status=reset_completed_game,
                )
                previous_score = None
                game_started = phase is ChessObservationPhase.ACTIVE
                self._games[key] = state
                resynced = reset_completed_game
            elif state.position.board_fen != snapshot.board_fen:
                last_move, child = infer_transition(state.position, snapshot.board_fen)
                if child is not None and last_move is not None:
                    mover = state.position.turn
                    last_san = move_san(state.position, last_move)
                    state.position = child
                else:
                    turn = "w" if snapshot.ply % 2 == 0 else "b"
                    state.position = Position.from_board_fen(snapshot.board_fen, turn=turn, ply=snapshot.ply)
                    resynced = True
                state.seen += 1

            # Snapshot đầu tiên chỉ chứng minh "đã thấy bàn". Chỉ chuyển sang
            # ACTIVE khi có nước đi, bàn không còn ở thế xuất phát, đồng hồ chạy,
            # hoặc bridge gửi cờ game_started rõ ràng.
            if state.phase is ChessObservationPhase.WAITING_FOR_START:
                if last_move is not None or _snapshot_has_started(snapshot):
                    state.phase = ChessObservationPhase.ACTIVE
                    game_started = True
            state.last_ply = snapshot.ply
            position = state.position

            score = None
            label = ""
            swing = None
            quality = ""
            suggestion = None
            hint_focus = ""
            if mode.full_assistance:
                raw = evaluate(position)
                score = raw
                label = evaluation_label(raw)
                if previous_score is not None and last_move is not None and mover:
                    swing = raw - previous_score if mover == "w" else previous_score - raw
                    quality = _move_quality(swing)
                state.last_evaluation_cp = raw
                candidates = analyze(position, depth=self.depth, top_n=3)
                if candidates:
                    hint_focus = _hint_focus(position, candidates[0][0])
                if candidates and self._should_reveal_direct_move(snapshot, state.seen):
                    move, move_score = candidates[0]
                    suggestion = MoveSuggestion(
                        uci=move.uci,
                        san=move_san(position, move),
                        score_cp=move_score,
                        depth=self.depth,
                    )

            result = snapshot.result
            terminal_status = snapshot.status in {"completed", "finished", "game_over", "checkmate", "draw"}
            if state.ignore_stale_terminal_status and not result:
                # Sau reset ván mới, status terminal có thể còn dính từ DOM cũ.
                # Chỉ tin lại status khi extension đã gửi một trạng thái không
                # terminal; result rõ ràng thì luôn thắng cơ chế cứu hộ này.
                if terminal_status:
                    terminal_status = False
                else:
                    state.ignore_stale_terminal_status = False
            game_over = bool(result or terminal_status)
            if game_over:
                state.phase = ChessObservationPhase.COMPLETED
            metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else dict(snapshot.metadata or {})
            raw_user_side = str(metadata.get("player_side") or metadata.get("user_side") or snapshot.orientation or "").strip().lower()
            user_side = "white" if raw_user_side in {"w", "white"} else "black" if raw_user_side in {"b", "black"} else ""
            mover_side = "white" if mover == "w" else "black" if mover == "b" else ""
            return ChessObservation(
                game_id=snapshot.game_id,
                mode=mode,
                fen=position.fen,
                board_fen=position.board_fen,
                side_to_move="white" if position.turn == "w" else "black",
                move_number=position.fullmove,
                user_side=user_side,
                mover_side=mover_side,
                actor_is_user=bool(user_side and mover_side and user_side == mover_side),
                last_move_uci=last_move.uci if last_move else "",
                last_move_san=last_san,
                evaluation_cp=score,
                evaluation_label=label,
                evaluation_swing_cp=swing,
                move_quality=quality,
                hint_focus=hint_focus,
                suggestion=suggestion,
                phase=state.phase,
                board_detected=True,
                game_started=game_started,
                game_over=game_over,
                result=result,
                resynced=resynced,
                confidence=0.65 if resynced else 1.0,
            )

    def _should_reveal_direct_move(self, snapshot: BoardSnapshot, seen: int) -> bool:
        if self.direct_move_rate <= 0.0:
            return False
        seed = f"{snapshot.game_id}:{snapshot.board_fen}:{seen}".encode("utf-8", "ignore")
        value = int(hashlib.sha256(seed).hexdigest()[:12], 16) / float(0xFFFFFFFFFFFF)
        return value < self.direct_move_rate


def _hint_focus(position: Position, move) -> str:
    piece = position.board[move.from_sq].lower()
    target = position.board[move.to_sq]
    if move.castle:
        return "king_safety"
    child = apply_move(position, move)
    if in_check(child, child.turn):
        return "forcing_check"
    if target != "." or move.en_passant:
        return "forcing_capture"
    if piece in {"n", "b"} and move.from_sq // 8 in {0, 7}:
        return "develop_piece"
    if piece == "p" and move.to_sq % 8 in {3, 4}:
        return "central_control"
    return "improve_piece_activity"


def _move_quality(swing_cp: int) -> str:
    if swing_cp <= -300:
        return "blunder"
    if swing_cp <= -140:
        return "mistake"
    if swing_cp <= -60:
        return "inaccuracy"
    if swing_cp >= 180:
        return "strong"
    if swing_cp >= 80:
        return "good"
    return "normal"


def _snapshot_has_started(snapshot: BoardSnapshot) -> bool:
    """Suy ra ván đã bắt đầu từ bằng chứng đủ mạnh, không từ chữ ``active`` mơ hồ.

    Bản extension cũ luôn gửi ``status=active`` ngay cả khi bàn còn nguyên vị trí
    xuất phát. Vì thế trạng thái đó không được dùng một mình để kết luận ván đã
    chạy. Đây là chỗ nhỏ nhưng trước kia khiến ERIS tuyên bố bắt đầu quá sớm.
    """

    metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else dict(snapshot.metadata or {})
    if bool(metadata.get("game_started") or metadata.get("clock_running")):
        return True
    if snapshot.ply > 0:
        return True
    if snapshot.board_fen != Position.initial().board_fen:
        return True
    return snapshot.status in {"playing", "in_progress", "started"}


__all__ = ["ChessGameTracker"]
