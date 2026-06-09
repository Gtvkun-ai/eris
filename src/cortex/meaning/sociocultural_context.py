# -*- coding: utf-8 -*-
"""sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set.

``SocioculturalContext`` gắn ngữ cảnh xã hội - văn hóa (quan hệ / *relationship*,
register, và chuẩn mực giao tiếp / *social-norm*) vào từng ``Observation`` do
``WorldInterpreter`` sinh ra, **mà không phán bậy**: các giả thuyết xã hội
(``social_hypotheses``) chỉ được đưa vào dạng *chưa xác nhận* (unconfirmed),
không bao giờ bị coi là sự thật đã xác nhận (R4.2).

Cưỡng chế WorkspaceFrame-only (R1): module chỉ đọc frame qua ``FrameReadView``.
Hợp đồng đọc cho module này gồm ``social_hypotheses`` và ``forbidden_assumptions``
(``frame_id`` luôn đọc được vì là metadata định danh). Mọi lần đọc đều bọc trong
``try/except RawWorldAccessError`` để: nếu một field nằm ngoài hợp đồng của frame
hiện tại, ta coi tín hiệu đó là **không khả dụng** (unavailable) và rơi về neutral
default — thay vì làm sập pipeline.

Xác định "tính khả dụng" của ba loại ngữ cảnh (frame không có field literal
``relationship`` / ``register`` / ``social_norm`` nên ta dẫn xuất một cách
**xác định, kiểm thử được** từ các tín hiệu mà hợp đồng cho phép đọc):

- **relationship** khả dụng ⇔ frame expose ``social_hypotheses`` không rỗng —
  có tương tác xã hội để suy ra quan hệ.
- **register** khả dụng ⇔ frame expose ``social_hypotheses`` không rỗng —
  register (giọng điệu/đăng ký ngôn ngữ) được suy từ bối cảnh xã hội đang hoạt động.
- **social_norm** khả dụng ⇔ ``forbidden_assumptions`` không rỗng **hoặc**
  ``social_hypotheses`` không rỗng — có ràng buộc/chuẩn mực để tôn trọng.

Loại nào không khả dụng → áp **neutral default** (không thiên kiến diễn giải)
*trước khi* xử lý observations (R4.3) và ghi tên loại đó vào
``ContextAnnotation.defaults_applied`` (R4.4). Khi đủ cả ba → annotate mỗi
observation cả ba loại (R4.1). Mỗi annotation mang ``confidence ∈ [0,1]`` (R4.5).
Observation set rỗng → trả ``[]``, kết thúc không lỗi (R4.6).
"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import (
    ContextAnnotation,
    Observation,
    StageDebug,
    clamp01,
)
from .read_contract import FrameReadView, RawWorldAccessError

__all__ = [
    "SocioculturalContext",
    "MODULE_NAME",
    "NEUTRAL_RELATIONSHIP",
    "NEUTRAL_REGISTER",
    "NEUTRAL_SOCIAL_NORM",
]


# Tên module dùng cho FrameReadView (R1.3) — đồng nhất với key downstream_contract.
MODULE_NAME = "SocioculturalContext"

# ---------------------------------------------------------------------------
# Neutral default constants — "applies no interpretive bias" (R4.3)
# ---------------------------------------------------------------------------
# Giá trị trung tính tuyệt đối: không nghiêng về thân/sơ, trang trọng/suồng sã,
# hay bất kỳ chuẩn mực cụ thể nào. Dùng khi loại ngữ cảnh tương ứng không khả dụng.
NEUTRAL_RELATIONSHIP = "neutral"
NEUTRAL_REGISTER = "neutral"
NEUTRAL_SOCIAL_NORM = "neutral"

# Giá trị dẫn xuất (non-neutral) khi loại ngữ cảnh khả dụng từ frame.
_DERIVED_RELATIONSHIP = "engaged"
_DERIVED_REGISTER = "conversational"
_DERIVED_SOCIAL_NORM = "norm-sensitive"

# Tên ba loại ngữ cảnh — dùng để ghi defaults_applied (R4.4).
_CTX_RELATIONSHIP = "relationship"
_CTX_REGISTER = "register"
_CTX_SOCIAL_NORM = "social_norm"

# Mỗi default áp vào làm giảm độ tin cậy annotation một chút (ít ngữ cảnh hơn ->
# tin cậy thấp hơn), nhưng không bao giờ đẩy ra ngoài [0,1] (clamp01).
_DEFAULT_CONF_PENALTY = 0.15


class SocioculturalContext:
    """Stage 3 của pipeline meaning: gắn ngữ cảnh xã hội - văn hóa.

    Không trạng thái giữa các lần chạy; toàn bộ tín hiệu đọc từ ``FrameReadView``
    theo đúng hợp đồng WorkspaceFrame-only.
    """

    def annotate(
        self, observations: list[Observation], view: FrameReadView
    ) -> tuple[list[ContextAnnotation], StageDebug]:
        """Annotate mỗi observation với ba loại ngữ cảnh xã hội - văn hóa.

        Trả về ``(annotations, debug)``. Observation set rỗng → ``([], debug)``
        (R4.6).
        """

        debug = StageDebug(stage=MODULE_NAME)

        # ---- Đọc tín hiệu frame (qua hợp đồng, guard mọi vi phạm) ----
        frame_id = self._safe_frame_id(view)
        if frame_id:
            debug.notes.append(f"frame_id={frame_id}")

        social_hypotheses = self._read_field(view, "social_hypotheses") or []
        forbidden_assumptions = self._read_field(view, "forbidden_assumptions") or []

        has_social = bool(social_hypotheses)
        has_forbidden = bool(forbidden_assumptions)

        # ---- Xác định tính khả dụng từng loại + áp neutral default trước xử lý ----
        relationship, register, social_norm, defaults_applied = self._resolve_context(
            has_social=has_social, has_forbidden=has_forbidden
        )
        if defaults_applied:
            debug.missing_fields.extend(defaults_applied)
            debug.notes.append(
                "neutral defaults applied: " + ", ".join(defaults_applied)
            )

        # ---- social_hypotheses -> unconfirmed (không bao giờ coi là fact) (R4.2) ----
        unconfirmed_social = self._collect_unconfirmed(social_hypotheses)
        if unconfirmed_social:
            debug.notes.append(
                f"{len(unconfirmed_social)} social hypotheses marked unconfirmed"
            )

        # ---- Observation set rỗng -> không annotation, không lỗi (R4.6) ----
        if not observations:
            debug.notes.append("empty observation set; no annotations produced")
            debug.confidence = 0.0
            return [], debug

        # ---- Annotate từng observation ----
        annotations: list[ContextAnnotation] = []
        for obs in observations:
            confidence = self._annotation_confidence(obs, defaults_applied)
            annotations.append(
                ContextAnnotation(
                    observation=obs,
                    relationship=relationship,
                    register=register,
                    social_norm=social_norm,
                    # Bản sao danh sách để mỗi annotation độc lập, không chia sẻ
                    # tham chiếu có thể bị mutate ngoài ý muốn.
                    unconfirmed_social=list(unconfirmed_social),
                    defaults_applied=list(defaults_applied),
                    confidence=confidence,
                )
            )

        if annotations:
            # Confidence stage = trung bình confidence các annotation (chỉ báo tổng quan).
            debug.confidence = clamp01(
                sum(a.confidence for a in annotations) / len(annotations)
            )
        debug.notes.append(f"annotated {len(annotations)} observations")
        return annotations, debug

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _resolve_context(
        self, *, has_social: bool, has_forbidden: bool
    ) -> tuple[str, str, str, list[str]]:
        """Suy ba loại ngữ cảnh + danh sách loại đã dùng neutral default.

        Quy tắc xác định (xem docstring module):
        - relationship / register khả dụng ⇔ ``has_social``.
        - social_norm khả dụng ⇔ ``has_forbidden`` hoặc ``has_social``.
        """

        defaults_applied: list[str] = []

        if has_social:
            relationship = _DERIVED_RELATIONSHIP
        else:
            relationship = NEUTRAL_RELATIONSHIP
            defaults_applied.append(_CTX_RELATIONSHIP)

        if has_social:
            register = _DERIVED_REGISTER
        else:
            register = NEUTRAL_REGISTER
            defaults_applied.append(_CTX_REGISTER)

        if has_forbidden or has_social:
            social_norm = _DERIVED_SOCIAL_NORM
        else:
            social_norm = NEUTRAL_SOCIAL_NORM
            defaults_applied.append(_CTX_SOCIAL_NORM)

        return relationship, register, social_norm, defaults_applied

    def _collect_unconfirmed(self, social_hypotheses: list[Any]) -> list[str]:
        """Chuyển ``social_hypotheses`` thành chuỗi *chưa xác nhận* (R4.2).

        Hỗ trợ cả ``WorkspaceSocialHypothesis`` (object có ``label``/``description``)
        lẫn dict; bất kỳ thứ gì khác rơi về ``str()``.
        """

        unconfirmed: list[str] = []
        for hyp in social_hypotheses:
            text = self._hypothesis_text(hyp)
            if text:
                unconfirmed.append(text)
        return unconfirmed

    @staticmethod
    def _hypothesis_text(hyp: Any) -> str:
        label = getattr(hyp, "label", None)
        description = getattr(hyp, "description", None)
        if label is None and isinstance(hyp, dict):
            label = hyp.get("label")
            description = hyp.get("description")
        if label is None:
            return str(hyp).strip()
        if description:
            return f"{label}: {description}"
        return str(label)

    @staticmethod
    def _annotation_confidence(
        observation: Observation, defaults_applied: list[str]
    ) -> float:
        """Confidence cho annotation ∈ [0,1] (R4.5).

        Bắt nguồn từ ``observation.confidence``, giảm dần theo số loại ngữ cảnh
        phải dùng neutral default (ít ngữ cảnh thật hơn -> kém chắc chắn hơn).
        """

        base = clamp01(getattr(observation, "confidence", 0.0))
        penalty = _DEFAULT_CONF_PENALTY * len(defaults_applied)
        return clamp01(base * (1.0 - penalty))

    @staticmethod
    def _safe_frame_id(view: Optional[FrameReadView]) -> Optional[str]:
        if view is None:
            return None
        try:
            return view.frame_id
        except Exception:
            return None

    @staticmethod
    def _read_field(view: Optional[FrameReadView], field_name: str) -> Any:
        """Đọc một field qua ``FrameReadView`` với guard.

        Ngoài hợp đồng / kênh Raw_World (``RawWorldAccessError``) hoặc bất kỳ lỗi
        đọc nào → coi field **không khả dụng**, trả ``None`` (kích hoạt neutral
        default ở tầng trên). Không bao giờ làm sập pipeline.
        """

        if view is None:
            return None
        try:
            return view.read(field_name, module=MODULE_NAME)
        except RawWorldAccessError:
            return None
        except Exception:
            return None
