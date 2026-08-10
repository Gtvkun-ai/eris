# -*- coding: utf-8 -*-
"""Gate claim public dùng chung cho chat và autonomous.

Một câu public chỉ được phép claim tri giác/hành động khi SourceGroundingReport
có evidence tương ứng. Module này không viết lại câu, không sinh fallback và
không tự quyết nội dung. Nó chỉ trả verdict typed để cả hai lane dùng đúng cùng
một luật, thay vì chat nghiêm còn autonomous đi cửa sau như một quan chức nhỏ.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Sequence


def _fold_vi(value: Any) -> str:
    """Chuẩn hóa tiếng Việt để các guard hẹp không phụ thuộc dấu/case."""

    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9_\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Chỉ bắt các claim về trạng thái hiện tại mà ERIS phải có sensor/evidence mới
# được nói như fact. Danh sách cố ý hẹp để không biến grounding guard thành một
# semantic classifier thứ hai.
#
# ĐÃ XOÁ (quá rộng, chặn cả thơ/văn thuần ngôn ngữ không phải perception claim):
#   - "ngoai troi / ben ngoai / ngoai kia / ngoai cua so" — autonomous dùng trong ẩn dụ
#   - "troi dang / hien tai / bay gio" — nói về thời tiết theo cảm xúc, không phải claim
#   - "hom nay troi / thoi tiet" — idem
# Chỉ giữ lại claim trực tiếp về perception sensor (thấy/nhìn/quan sát).
_CURRENT_WORLD_PATTERNS = (
    re.compile(r"\btoi (?:dang )?(?:thay|nhin thay|nhin|quan sat)\b"),
)

_CORRECTION_MARKERS = (
    "khong phai", "dau co", "co dau", "lam gi co", "sai", "nham",
    "cai gi", "xanh cai gi", "sap toi", "toi den noi", "noi gi vay",
    "noi gi the", "gi vay ma", "gi vay",
)


def _autonomous_strict_grounding_enabled() -> bool:
    """Env flag để tắt grounding gate cho autonomous khi creative mode."""
    raw = str(os.environ.get("ERIS_AUTONOMOUS_STRICT_GROUNDING", "1") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def has_current_world_claim(text: str) -> bool:
    """True khi câu đang khẳng định một trạng thái hiện tại cần evidence."""

    folded = _fold_vi(text)
    return bool(folded and any(pattern.search(folded) for pattern in _CURRENT_WORLD_PATTERNS))


def current_world_claim_without_evidence(text: str, evidence_refs: Sequence[str] | None = None) -> bool:
    """Chặn autonomous nói như đang nhìn/thấy thế giới khi không có provenance."""

    refs = tuple(str(item or "").strip() for item in (evidence_refs or ()) if str(item or "").strip())
    return has_current_world_claim(text) and not refs


def is_grounding_correction(user_text: str, previous_assistant_text: str) -> bool:
    """Nhận diện hẹp việc user sửa một claim tri giác/trạng thái vừa rồi của ERIS.

    Đây không phải bộ phân loại disagreement tổng quát. Nó chỉ bật khi câu ERIS
    trước đó có hình dạng current-world claim và user hiện tại chứa dấu hiệu phủ
    định/chỉnh fact đủ rõ. Nhờ vậy "xanh cái gì" không bị biến thành tranh luận
    quan điểm như lần chạy lỗi.
    """

    if not has_current_world_claim(previous_assistant_text):
        return False
    folded = _fold_vi(user_text)
    if not folded:
        return False
    return any(marker in folded for marker in _CORRECTION_MARKERS)


@dataclass(frozen=True, slots=True)
class GroundingSurfaceVerdict:
    allowed: bool
    annotations: tuple[Any, ...] = ()

    @property
    def violation_code(self) -> str:
        return "" if self.allowed else "UNGROUNDED_PERCEPTION_OR_ACTION_CLAIM"

    def retry_instruction(self) -> str:
        if self.allowed:
            return ""
        return (
            "The draft made a perception/action claim without current evidence. "
            "Rewrite it without claiming that ERIS is literally seeing, reading, opening, "
            "or completing anything. A hypothesis must name its evidence and leave room "
            "for the user to correct it."
        )


def evaluate_grounded_surface(
    engine: Any,
    text: str,
    *,
    report: Any = None,
    channel: str = "",
) -> GroundingSurfaceVerdict:
    """Chạy đúng một luật annotation cho mọi public lane.

    channel="autonomous": nếu ERIS_AUTONOMOUS_STRICT_GROUNDING=0 thì bỏ qua gate
    để không chặn creative speech không có perception claim thật.
    """

    if str(channel or "").strip().lower() == "autonomous" and not _autonomous_strict_grounding_enabled():
        return GroundingSurfaceVerdict(True, ())
    annotate = getattr(engine, "annotate_claims", None)
    if not callable(annotate) or not str(text or "").strip():
        return GroundingSurfaceVerdict(True, ())
    try:
        annotations = tuple(
            item
            for item in annotate(str(text or ""), report=report)
            if str(getattr(item, "claim_status", "grounded") or "grounded") != "grounded"
        )
    except Exception:
        # Gate không được tự bịa lỗi grounding khi chính annotator hỏng. Caller log
        # riêng, còn câu vẫn đi qua acceptance gate khác.
        return GroundingSurfaceVerdict(True, ())
    return GroundingSurfaceVerdict(not annotations, annotations)


__all__ = [
    "GroundingSurfaceVerdict",
    "_autonomous_strict_grounding_enabled",
    "current_world_claim_without_evidence",
    "evaluate_grounded_surface",
    "has_current_world_claim",
    "is_grounding_correction",
]
