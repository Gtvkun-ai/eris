# -*- coding: utf-8 -*-
"""Typed chess state và renderer dùng chung cho chat/autonomous.

Renderer này chỉ là lưới an toàn khi Surface model không trả câu. Nó không đọc
chuỗi ``key=value`` và không phát thông báo kiểu máy. Mỗi câu phải bám vào thế cờ,
nước vừa đi, gợi ý, chất lượng nước hoặc kết quả; thiếu dữ liệu thì im.
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
    result: str = ""
    orientation: str = ""

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
            result=_text(data.get("result")),
            orientation=_text(data.get("orientation")).lower(),
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


def _pick(seed: str, *options: str) -> str:
    clean = tuple(option for option in options if option)
    if not clean:
        return ""
    digest = hashlib.sha1(seed.encode("utf-8", "ignore")).digest()
    return clean[int.from_bytes(digest[:4], "big") % len(clean)]


def _move_reason(state: ChessSurfaceState) -> str:
    return {
        "forcing_check": "Ép vua trước, đừng cho bên kia kịp bày thêm trò.",
        "forcing_capture": "Có quân treo trước mặt mà bỏ qua thì hơi phụ lòng đối thủ.",
        "develop_piece": "Kéo quân ra chơi đi; để nó ngồi làm nội thất mãi cũng phí.",
        "central_control": "Chiếm trung tâm trước khi bên kia đem đồ đạc tới đóng trại.",
        "king_safety": "Đưa vua vào chỗ tử tế trước, đừng bắt nó sống giữa công trường.",
        "improve_piece_activity": "Nước này sửa thế quân mà không tự khoét thêm lỗ.",
    }.get(state.hint_focus, "Nước này giữ thế gọn hơn và bắt bên kia phải trả lời.")


def _quality_comment(state: ChessSurfaceState) -> str:
    move = state.last_move
    quality = state.move_quality
    if not move:
        return ""
    seed = f"{state.game_id}:{state.ply}:{move}:{quality}"
    if quality == "blunder":
        return _pick(
            seed,
            f"{move} à? Hào phóng ghê, biếu đối thủ nguyên một cơ hội.",
            f"Nước {move} vừa rồi hơi giống hoạt động từ thiện quân cờ đấy.",
        )
    if quality == "mistake":
        return _pick(
            seed,
            f"{move} làm thế xấu đi kha khá. Chưa chết, nhưng đừng tặng thêm.",
            f"Nước {move} hơi đau. Bên kia mà tỉnh là cậu phải trả học phí ngay.",
        )
    if quality == "inaccuracy":
        return _pick(
            seed,
            f"{move} hơi mềm. Bên kia chưa phạt thì coi như còn được tha.",
            f"Nước {move} không hỏng hẳn, chỉ mở cửa cho đối thủ nghịch thôi.",
        )
    if quality in {"strong", "good"}:
        return _pick(
            seed,
            f"{move} ổn đấy. Ít nhất lần này tôi chưa phải viết điếu văn cho thế cờ.",
            f"Nước {move} khá sạch. Bên kia bắt đầu phải tự giải bài của mình rồi.",
        )
    return _pick(
        seed,
        f"Sau {move}, thế vẫn chơi được. Chưa đẹp đến mức khoe, cũng chưa xấu đến mức giấu.",
        f"{move} giữ ván còn nguyên. Tạm thời bàn cờ chưa cần gọi cấp cứu.",
    )


def render_chess_surface_text(
    state: ChessSurfaceState | Mapping[str, Any] | None,
    *,
    user_text: str = "",
    event_kind: str = "",
    autonomous: bool = False,
) -> str:
    """Viết một câu cờ tự nhiên, có nhận xét và chút mỉa nhẹ.

    Không trả câu telemetry kiểu “bàn cờ đã được nhận” hoặc “nước gợi ý hiện tại”.
    Nếu state không đủ cụ thể thì trả chuỗi rỗng để pipeline im/body-only.
    """

    typed = state if isinstance(state, ChessSurfaceState) else ChessSurfaceState.from_mapping(state)
    if not typed.meaningful:
        return ""

    normalized = normalize_vi(user_text)
    asks_move = any(marker in normalized for marker in (
        "nuoc nao", "danh gi", "di gi", "nen danh", "nen di", "di sao",
        "danh nuoc", "toi danh", "tui danh", "hay sao", "dung hong", "dung khong",
    )) or bool(_COORD_RE.search(str(user_text or "")))

    if typed.result or typed.phase in {"completed", "game_over", "finished"}:
        if typed.result:
            return f"Xong ván, kết quả {typed.result}. Giờ mới đến phần thú vị: xem ai phải nhận trách nhiệm cho đống đổ nát này."
        return "Ván xong rồi. Đừng chạy; còn phải mổ lại chỗ thế cờ bắt đầu trượt nữa."

    if typed.phase in {"waiting_for_board"}:
        return "Mở bàn đi. Tôi chưa có gì để soi ngoài sự tự tin đáng ngờ của cậu."
    if typed.phase in {"waiting_for_start", "waiting", "ready"} and not typed.last_move:
        return _pick(
            typed.game_id or typed.board_fen,
            "Bàn mở rồi đấy. Đi nước đầu đi, tôi ngồi đây soi xem cậu chơi cờ hay hiến quân.",
            "Ván chưa chạy. Cứ đi nước đầu; tôi hứa chỉ mỉa khi thật sự đáng mỉa.",
        )

    suggestion = typed.suggested_move
    quality_line = _quality_comment(typed)
    if asks_move and suggestion:
        return f"{suggestion} đi. {_move_reason(typed)}"
    if asks_move and not suggestion:
        if typed.last_move:
            return f"Sau {typed.last_move}, tôi chưa có nước ép đủ sạch để phán bừa. Đi chậm lại một nhịp, đừng tự hiến quân vì nóng ruột."
        return "Tôi có thế cờ nhưng chưa có nước nào đủ sạch để chỉ thẳng. Đừng bắt tôi bói bằng lòng tự trọng của cậu."

    if suggestion and quality_line:
        return f"{quality_line} Tôi nghiêng về {suggestion}; {_move_reason(typed).lower()}"
    if suggestion:
        return _pick(
            f"{typed.game_id}:{typed.ply}:{suggestion}",
            f"{suggestion} nhìn khó chịu nhất cho bên kia. {_move_reason(typed)}",
            f"Tôi sẽ cân {suggestion}. {_move_reason(typed)}",
        )
    if quality_line:
        return quality_line

    if typed.last_move:
        return f"Nước {typed.last_move} vừa xuống. Thế còn sống, nhưng chưa ai được phép tự mãn cả."
    if autonomous:
        return ""
    if typed.side_vi:
        return f"Đến lượt {typed.side_vi}. Cứ đi đi; tôi đang chờ một nước đủ hay để khen, hoặc đủ tệ để có chuyện nói."
    return ""


__all__ = [
    "ChessSurfaceState",
    "chess_turn_relevant",
    "render_chess_surface_text",
]
