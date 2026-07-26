# -*- coding: utf-8 -*-
"""Chess companion bridge and lightweight analysis support."""
from .contracts import BoardSnapshot, ChessAssistMode, ChessObservation, MoveSuggestion
from .engine import Move, Position, analyze, apply_move, evaluate, legal_moves, move_san
from .mode_policy import classify_mode
from .service import ChessCompanionService
from .tracker import ChessGameTracker

__all__ = [
    "BoardSnapshot", "ChessAssistMode", "ChessCompanionService", "ChessGameTracker",
    "ChessObservation", "Move", "MoveSuggestion", "Position", "analyze", "apply_move",
    "classify_mode", "evaluate", "legal_moves", "move_san",
]
