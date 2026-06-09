# -*- coding: utf-8 -*-
"""read_contract.py — ReadContract guard (WorkspaceFrame-only enforcement).

Cơ chế cưỡng chế xương sống #1 của Phase 2 (R1): mọi stage chỉ được đọc
``WorkspaceFrame`` (và đầu ra của các stage Phase 2 phía trước), KHÔNG bao giờ
chạm tới ``Raw_World`` (``raw_signals`` / evidence chưa lọc / memory chưa chọn).

Thay vì truyền thẳng ``WorkspaceFrame`` cho từng stage, pipeline bọc nó trong một
``FrameReadView`` — một *typed read boundary*:

- ``FrameReadView`` chỉ cho phép đọc các field nằm trong
  ``downstream_contract[module]`` của module đang gọi (R1.3). Mỗi lần đọc gắn
  tên module gọi.
- Nó KHÔNG expose bất kỳ kênh nào tới ``Raw_World``. Module này cũng không import
  bất kỳ symbol Raw_World nào — sự vắng mặt đó là một phần của cưỡng chế cấu trúc.
- Đọc một field ngoài hợp đồng (hoặc một kênh Raw_World) → ghi vi phạm vào
  ``frame.debug["contract_violations"]`` rồi ném ``RawWorldAccessError(module,
  field)`` nêu đích danh module + field (R1.2). Hành vi đọc không bao giờ mutate
  dữ liệu của frame.

Lựa chọn thiết kế — module không có entry trong ``downstream_contract``:
diễn giải an toàn theo đúng mục tiêu cưỡng chế cấu trúc là **không field nào được
phép** (mọi lần đọc đều ném). Một module muốn đọc field phải được liệt kê tường
minh trong hợp đồng; "không khai báo" = "không được đọc gì".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .contracts import RawWorldAccessError

if TYPE_CHECKING:  # pragma: no cover - chỉ phục vụ type-checker
    from ..global_workspace import WorkspaceFrame


__all__ = ["FrameReadView", "RAW_WORLD_FIELDS"]


# ---------------------------------------------------------------------------
# Raw_World channels — luôn bị chặn, bất kể downstream_contract nói gì
# ---------------------------------------------------------------------------
# Theo glossary requirements: Raw_World = raw_signals + evidence chưa lọc +
# memory chưa chọn. Các tên này KHÔNG phải field của WorkspaceFrame (frame chỉ
# expose ``selected_evidence`` / ``selected_memory`` đã qua chọn lọc). Liệt kê
# tường minh để mọi mưu toan đọc kênh thô đều bị bắt ở boundary, kể cả khi một
# hợp đồng cấu hình sai vô tình liệt kê chúng.
RAW_WORLD_FIELDS: frozenset[str] = frozenset(
    {
        "raw_signals",
        "raw_world",
        "evidence",            # evidence chưa lọc (khác selected_evidence)
        "raw_evidence",
        "unfiltered_evidence",
        "memory",              # memory chưa chọn (khác selected_memory)
        "raw_memory",
        "unselected_memory",
    }
)


class FrameReadView:
    """Boundary đọc có kiểu, bọc một ``WorkspaceFrame``.

    Một stage không bao giờ nhận thẳng ``WorkspaceFrame``; nó nhận một
    ``FrameReadView`` đã ``for_module(...)`` để có sẵn tên module mặc định. Mọi
    lần đọc đi qua kiểm tra hợp đồng ``downstream_contract``.
    """

    __slots__ = ("_frame", "_module", "_stage")

    def __init__(
        self,
        frame: "WorkspaceFrame",
        *,
        module: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        self._frame = frame
        self._module = module
        self._stage = stage

    # ------------------------------------------------------------------
    # Scoping
    # ------------------------------------------------------------------
    def for_module(
        self, module: str, *, stage: Optional[str] = None
    ) -> "FrameReadView":
        """Trả về một view mới gắn ``module`` làm mặc định cho mọi lần đọc.

        Cho phép stage có một bề mặt đọc sạch theo từng module:
        ``view.for_module("WorldInterpreter").read("broadcast_items")``.
        """

        return FrameReadView(
            self._frame, module=module, stage=stage or self._stage or module
        )

    @property
    def frame_id(self) -> str:
        """``frame_id`` luôn đọc được — đây là metadata định danh, không phải
        Raw_World, và mọi artifact phải gắn nó (R1.5)."""

        return self._frame.frame_id

    @property
    def module(self) -> Optional[str]:
        return self._module

    # ------------------------------------------------------------------
    # Hợp đồng
    # ------------------------------------------------------------------
    def allowed_fields(self, module: Optional[str] = None) -> list[str]:
        """Danh sách field mà ``module`` được phép đọc theo hợp đồng.

        Module không có entry → danh sách rỗng (không được đọc gì).
        """

        module_name = self._resolve_module(module)
        contract = self._frame.downstream_contract or {}
        return list(contract.get(module_name, []))

    def can_read(self, field_name: str, module: Optional[str] = None) -> bool:
        """``True`` nếu ``module`` được phép đọc ``field_name`` (không ném)."""

        if field_name in RAW_WORLD_FIELDS:
            return False
        module_name = self._resolve_module(module)
        contract = self._frame.downstream_contract or {}
        return field_name in contract.get(module_name, [])

    # ------------------------------------------------------------------
    # Đọc
    # ------------------------------------------------------------------
    def read(self, field_name: str, module: Optional[str] = None) -> Any:
        """Đọc một field của ``WorkspaceFrame`` qua hợp đồng.

        - ``field_name`` ∈ ``downstream_contract[module]`` và không phải kênh
          Raw_World → trả ``getattr(frame, field_name)`` (không mutate).
        - Ngược lại → ghi vi phạm vào ``debug.contract_violations`` rồi ném
          ``RawWorldAccessError(module, field_name)`` (R1.2).
        """

        module_name = self._resolve_module(module)

        # Kênh Raw_World: chặn vô điều kiện, kể cả khi hợp đồng cấu hình sai.
        if field_name in RAW_WORLD_FIELDS:
            self._deny(module_name, field_name, reason="raw_world_channel")

        contract = self._frame.downstream_contract or {}
        allowed = contract.get(module_name)
        # Không có entry cho module -> không field nào được phép (lựa chọn an toàn).
        if not allowed or field_name not in allowed:
            self._deny(module_name, field_name, reason="field_not_in_contract")

        # Hợp lệ: trả dữ liệu không bị mutate.
        return getattr(self._frame, field_name)

    # ------------------------------------------------------------------
    # Convenience accessors — guarded passthroughs tới helper của frame
    # ------------------------------------------------------------------
    # Stage không bao giờ chạm thẳng WorkspaceFrame; các helper dưới đây đi qua
    # kiểm tra hợp đồng (dựa trên field nền tảng mà helper phụ thuộc) trước khi
    # gọi helper gốc.
    def evidence_ids(self, module: Optional[str] = None) -> list[str]:
        """``WorkspaceFrame.evidence_ids()`` qua guard (cần đọc ``broadcast_items``)."""

        module_name = self._resolve_module(module)
        self._require(module_name, "broadcast_items")
        return self._frame.evidence_ids()

    def items_by_kind(self, kind: Any, module: Optional[str] = None) -> list[Any]:
        """``WorkspaceFrame.items_by_kind(kind)`` qua guard."""

        module_name = self._resolve_module(module)
        self._require(module_name, "broadcast_items")
        return self._frame.items_by_kind(kind)

    def surface_items(
        self, scope: Any = None, module: Optional[str] = None
    ) -> list[Any]:
        """``WorkspaceFrame.surface_items(scope)`` qua guard."""

        module_name = self._resolve_module(module)
        self._require(module_name, "broadcast_items")
        return self._frame.surface_items(scope)

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _resolve_module(self, module: Optional[str]) -> str:
        module_name = module or self._module
        if not module_name:
            raise ValueError(
                "FrameReadView read requires a module name; gọi qua "
                "view.for_module('<Stage>') hoặc truyền module=..."
            )
        return module_name

    def _require(self, module_name: str, field_name: str) -> None:
        """Kiểm tra quyền đọc ``field_name``; vi phạm -> ghi debug + ném."""

        if field_name in RAW_WORLD_FIELDS:
            self._deny(module_name, field_name, reason="raw_world_channel")
        contract = self._frame.downstream_contract or {}
        allowed = contract.get(module_name)
        if not allowed or field_name not in allowed:
            self._deny(module_name, field_name, reason="field_not_in_contract")

    def _deny(self, module_name: str, field_name: str, *, reason: str) -> None:
        """Ghi vi phạm vào ``debug.contract_violations`` rồi ném lỗi.

        Không bao giờ mutate dữ liệu được đọc; chỉ thêm bản ghi vi phạm vào
        ``debug`` để truy vết (R1.2).
        """

        debug = self._frame.debug
        if not isinstance(debug, dict):  # pragma: no cover - phòng thủ
            debug = {}
            self._frame.debug = debug
        violations = debug.setdefault("contract_violations", [])
        violations.append(
            {
                "module": module_name,
                "field": field_name,
                "stage": self._stage or module_name,
                "reason": reason,
            }
        )
        raise RawWorldAccessError(module_name, field_name)
