# -*- coding: utf-8 -*-
"""tom_history_adapter.py — ToMHistoryAdapter (history từ WorkspaceFrame only).

Cấp dữ liệu *lịch sử tương tác* cho ``TheoryOfMindCore`` **chỉ** từ
``WorkspaceFrame`` thông qua ``FrameReadView`` (R7.5) — không bao giờ chạm
``Raw_World`` (raw_signals / evidence chưa lọc / memory chưa chọn).

Nguồn history là ``selected_memory`` của frame: danh sách memory **đã được chọn
lọc** bởi Global Workspace (khác hẳn ``memory`` thô bị ``FrameReadView`` chặn vô
điều kiện). Mọi lần đọc đều đi qua hợp đồng ``downstream_contract``:

- Nếu module hiện tại được phép đọc ``selected_memory`` **và** frame có dữ liệu
  → trả ``ToMHistory(items=[...], available=True)``.
- Nếu field nằm ngoài hợp đồng của module (``RawWorldAccessError``), hoặc
  ``view is None``, hoặc dữ liệu vắng/trống → trả
  ``ToMHistory(items=[], available=False)``. Caller ghi "history unavailable" và
  ToM **vẫn chạy tiếp** mà không có history (R7.8).

Việc "degrade thay vì crash" được bảo đảm bằng cách bọc lần đọc trong
``try/except RawWorldAccessError``: một field ngoài hợp đồng làm history rơi về
``available=False`` chứ không làm sập pipeline.
"""

from __future__ import annotations

from typing import Optional

from .contracts import ToMHistory
from ..meaning.read_contract import FrameReadView, RawWorldAccessError


__all__ = ["ToMHistoryAdapter"]


class ToMHistoryAdapter:
    """Adapter cấp ``ToMHistory`` từ ``WorkspaceFrame`` qua ``FrameReadView``.

    Tham số khởi tạo (đều có mặc định an toàn):

    - ``module``: tên module dùng khi đọc qua hợp đồng. Mặc định
      ``"TheoryOfMindCore"`` (đồng nhất với stage ToM). Module không có quyền đọc
      field history → history degrade về ``available=False``.
    - ``history_field``: field của frame dùng làm nguồn history. Mặc định
      ``"selected_memory"`` — memory **đã chọn lọc**, không phải memory thô.
    """

    DEFAULT_MODULE = "TheoryOfMindCore"
    DEFAULT_HISTORY_FIELD = "selected_memory"

    __slots__ = ("_module", "_history_field")

    def __init__(
        self,
        *,
        module: Optional[str] = None,
        history_field: Optional[str] = None,
    ) -> None:
        self._module = module or self.DEFAULT_MODULE
        self._history_field = history_field or self.DEFAULT_HISTORY_FIELD

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def load(self, view: Optional[FrameReadView]) -> ToMHistory:
        """Trả ``ToMHistory`` lấy từ ``WorkspaceFrame`` qua ``view``.

        - ``view is None`` → không có nguồn nào để đọc → ``available=False``.
        - Đọc ``history_field`` qua hợp đồng; field ngoài hợp đồng
          (``RawWorldAccessError``) → ``available=False`` (degrade, không crash).
        - Dữ liệu vắng (``None``) hoặc rỗng → history cần nhưng absent →
          ``available=False`` (R7.8).
        - Có dữ liệu → ``ToMHistory(items=[...], available=True)``.
        """

        if view is None:
            return ToMHistory(items=[], available=False)

        try:
            raw = view.read(self._history_field, module=self._module)
        except RawWorldAccessError:
            # Field ngoài hợp đồng của module — degrade thay vì sập pipeline.
            return ToMHistory(items=[], available=False)

        items = self._normalize(raw)
        if not items:
            # History được cần nhưng vắng/trống trong WorkspaceFrame (R7.8).
            return ToMHistory(items=[], available=False)

        return ToMHistory(items=items, available=True)

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(raw: object) -> list[str]:
        """Chuẩn hoá giá trị đọc được thành ``list[str]`` cho ``ToMHistory.items``.

        Bỏ qua phần tử rỗng/``None``; ``None`` hay giá trị không lặp được → rỗng.
        """

        if raw is None:
            return []
        if isinstance(raw, str):
            # Một chuỗi đơn được coi là một item, không tách ký tự.
            text = raw.strip()
            return [text] if text else []
        try:
            iterator = iter(raw)  # type: ignore[arg-type]
        except TypeError:
            return []
        items: list[str] = []
        for entry in iterator:
            if entry is None:
                continue
            text = str(entry).strip()
            if text:
                items.append(text)
        return items
