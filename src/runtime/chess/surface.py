# -*- coding: utf-8 -*-
"""Typed chess state và câu trả lời engine có thẩm quyền.

Module này KHÔNG dựng lời bình autonomous và không giả lập cá tính khi Surface
provider lỗi. Bình luận, mỉa mai và đọc thế cờ thuộc Surface model. Đường local
chỉ được dùng cho một trường hợp hẹp: user hỏi thẳng nước nào và chess analyzer
đã trả đúng một suggestion có provenance. Khi đó runtime có thể phát kết quả
engine tối giản; thiếu suggestion thì im, tuyệt đối không rơi vào câu mẫu.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.cognition.normalization import normalize_vi


_COORD_RE = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b", re.IGNORECASE)


def _text(value: Any) -> str:
    raw = str(value or "").strip()
    return "" if raw.lower() in {"-", "none", "null", "unknown"} else raw


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float01(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class ChessSurfaceState:
    """Snapshot bất biến đủ cho wording và semantic fingerprint."""

    game_id: str = ""
    phase: str = ""
    board_fen: str = ""
    side_to_move: str = ""
    move_number: int = 0
    ply: int = 0
    last_move_uci: str = ""
    last_move_san: str = ""
    suggested_move_uci: str = ""
    suggested_move_san: str = ""
    evaluation_cp: int | None = None
    evaluation_label: str = ""
    evaluation_swing_cp: int | None = None
    move_quality: str = ""
    hint_focus: str = ""
    analysis_provider: str = ""
    analysis_depth: int = 0
    analysis_nodes: int = 0
    analysis_elapsed_ms: int = 0
    analysis_degraded: bool = False
    mate_in: int | None = None
    principal_variation: tuple[str, ...] = ()
    result: str = ""
    orientation: str = ""
    companion_mode: str = ""
    user_side: str = ""
    mover_side: str = ""
    actor: str = ""
    actor_is_user: bool = False
    event: str = ""
    speech_act: str = ""
    speech_reason: str = ""
    speech_priority: float = 0.0
    commentary_focus: str = ""
    suggestions_allowed: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ChessSurfaceState":
        data = value if isinstance(value, Mapping) else {}
        phase = _text(data.get("chess_phase") or data.get("phase"))
        board_fen = _text(data.get("board_fen") or data.get("fen"))
        move_number = _integer(data.get("move_number"), 0)
        side = _text(data.get("side_to_move") or data.get("to_move")).lower()
        ply = _integer(data.get("ply"), max(0, (move_number - 1) * 2 + (1 if side in {"black", "b"} else 0)))
        return cls(
            game_id=_text(data.get("game_id")),
            phase=phase.lower(),
            board_fen=board_fen,
            side_to_move=side,
            move_number=move_number,
            ply=ply,
            last_move_uci=_text(data.get("last_move_uci") or data.get("last_move")),
            last_move_san=_text(data.get("last_move_san")),
            suggested_move_uci=_text(data.get("suggested_move_uci") or data.get("suggested_move")),
            suggested_move_san=_text(data.get("suggested_move_san")),
            evaluation_cp=_optional_integer(data.get("evaluation_cp")),
            evaluation_label=_text(data.get("evaluation_label")),
            evaluation_swing_cp=_optional_integer(data.get("evaluation_swing_cp")),
            move_quality=_text(data.get("move_quality")).lower(),
            hint_focus=_text(data.get("hint_focus")).lower(),
            analysis_provider=_text(data.get("analysis_provider")).lower(),
            analysis_depth=_integer(data.get("analysis_depth"), 0),
            analysis_nodes=_integer(data.get("analysis_nodes"), 0),
            analysis_elapsed_ms=_integer(data.get("analysis_elapsed_ms"), 0),
            analysis_degraded=bool(data.get("analysis_degraded", False)),
            mate_in=_optional_integer(data.get("mate_in")),
            principal_variation=tuple(str(item) for item in (data.get("principal_variation") or ()) if str(item).strip())[:24],
            result=_text(data.get("result")),
            orientation=_text(data.get("orientation")).lower(),
            companion_mode=_text(data.get("companion_mode")).lower(),
            user_side=_text(data.get("user_side")).lower(),
            mover_side=_text(data.get("mover_side")).lower(),
            actor=_text(data.get("actor")).lower(),
            actor_is_user=bool(data.get("actor_is_user", False)),
            event=_text(data.get("event")).lower(),
            speech_act=_text(data.get("speech_act")).lower(),
            speech_reason=_text(data.get("speech_reason")).lower(),
            speech_priority=_float01(data.get("speech_priority", 0.0)),
            commentary_focus=_text(data.get("commentary_focus")),
            suggestions_allowed=bool(data.get("suggestions_allowed", False)),
        )

    @property
    def last_move(self) -> str:
        return self.last_move_san or self.last_move_uci

    @property
    def suggested_move(self) -> str:
        return self.suggested_move_san or self.suggested_move_uci

    @property
    def side_vi(self) -> str:
        return {"white": "trắng", "w": "trắng", "black": "đen", "b": "đen"}.get(
            self.side_to_move,
            self.side_to_move,
        )

    @property
    def meaningful(self) -> bool:
        return bool(self.board_fen or self.last_move or self.suggested_move or self.phase or self.result)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def event_fingerprint(self, event_kind: str = "") -> str:
        """Fingerprint đổi theo đúng position/event, không theo nhãn task chung."""

        raw = "|".join(
            (
                "chess",
                self.game_id,
                str(event_kind or "").strip().lower(),
                self.phase,
                str(self.ply),
                str(self.move_number),
                self.last_move_uci,
                self.suggested_move_uci,
                self.side_to_move,
                self.event,
                self.speech_reason,
                self.analysis_provider,
                str(self.analysis_depth),
                hashlib.sha1(self.board_fen.encode("utf-8", "ignore")).hexdigest()[:12] if self.board_fen else "",
                self.result,
            )
        )
        return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:20]


def chess_turn_relevant(user_text: str, *, engagement_active: bool = False) -> bool:
    """Bind câu cờ tự nhiên, kể cả câu không chứa đúng từ khóa sách giáo khoa."""

    normalized = normalize_vi(user_text)
    if not normalized:
        return False
    visual_only = (
        "mau highlight", "o sang", "o chop", "nut nao", "popup", "bo cuc",
        "vi tri tren man hinh", "giao dien",
    )
    if any(marker in normalized for marker in visual_only):
        return False
    explicit = (
        "co vua", "chess", "fen", "ban co", "van co", "nuoc co", "the co",
        "nuoc nao", "di gi", "danh gi", "nen danh", "nen di", "di sao",
        "di nuoc", "quan nao", "luot ai", "trang di", "den di", "toi ben trang",
        "tui ben trang", "toi ben den", "tui ben den", "an ma", "an tuong",
        "an xe", "an hau", "an tot", "chieu tuong", "chieu het", "nhap thanh",
        "phong hau", "con ma", "quan ma", "con tuong", "quan tuong",
        "con xe", "quan xe", "quan hau", "quan tot", "quan vua", "vo con ma",
    )
    if any(marker in normalized for marker in explicit):
        return True
    if _COORD_RE.search(str(user_text or "")):
        return True
    if not engagement_active:
        return False
    tokens = set(normalized.split())
    return bool(tokens & {"nuoc", "quan", "trang", "den"})



def chess_move_question(user_text: str) -> bool:
    """True khi user đang hỏi trực tiếp nước nên đi hoặc xác nhận một nước.

    Đây là classifier miền cờ, không phải router vision. Nó chỉ quyết định có
    được phép dùng kết quả analyzer tối giản khi Surface provider không trả lời.
    """

    normalized = normalize_vi(user_text)
    if not normalized:
        return False
    markers = (
        "nuoc nao", "danh gi", "di gi", "nen danh", "nen di", "di sao",
        "danh nuoc", "toi danh", "tui danh", "hay sao", "dung hong",
        "dung khong", "co nen", "an quan nao", "bat quan nao",
    )
    return any(marker in normalized for marker in markers) or bool(
        _COORD_RE.search(str(user_text or ""))
    )


def authoritative_chess_answer_text(
    state: ChessSurfaceState | Mapping[str, Any] | None,
    *,
    user_text: str,
) -> str:
    """Trả kết quả analyzer tối giản cho câu hỏi nước đi trực tiếp.

    Đây là tool result có thẩm quyền, KHÔNG phải Surface fallback:
    - chỉ chạy khi user thật sự hỏi nước;
    - bắt buộc có suggestion từ analyzer/bridge;
    - không mỉa, không kể chuyện, không đọc telemetry;
    - không có suggestion thì trả rỗng để caller im.
    """

    typed = state if isinstance(state, ChessSurfaceState) else ChessSurfaceState.from_mapping(state)
    if not chess_move_question(user_text):
        return ""
    move = typed.suggested_move
    if not move:
        return ""

    reason = {
        "forcing_check": "Đây là nước chiếu cưỡng bức.",
        "forcing_capture": "Đây là nước bắt quân cưỡng bức.",
        "develop_piece": "Nước này phát triển quân và cải thiện hoạt động.",
        "central_control": "Nước này giành thêm quyền kiểm soát trung tâm.",
        "king_safety": "Nước này ưu tiên an toàn cho vua.",
        "improve_piece_activity": "Nước này cải thiện vị trí quân mà không tạo thêm điểm yếu.",
    }.get(typed.hint_focus, "")
    return f"{move}. {reason}".strip() if reason else f"{move}."


__all__ = [
    "ChessSurfaceState",
    "chess_turn_relevant",
    "chess_move_question",
    "authoritative_chess_answer_text",
]
