# -*- coding: utf-8 -*-
"""world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1).

``WorldSceneBuilder`` là stage đầu tiên của pipeline meaning. Nó nhận một
``FrameReadView`` (bề mặt đọc có kiểm soát bọc ``WorkspaceFrame``) và dựng một
``WorldScene``: tập ``entities`` / ``salient_signals`` / ``active_threads`` rút
ra từ ``broadcast_items`` và ``active_threads`` của frame.

Ràng buộc cưỡng chế (xem design "WorldSceneBuilder"):

- **WorkspaceFrame-only (R1.3)**: chỉ đọc các field nằm trong
  ``downstream_contract["WorldSceneBuilder"]`` thông qua ``FrameReadView``
  (``frame_id``, ``broadcast_items``, ``active_threads``, ``dominant_thread``,
  ``broadcast_reason``). KHÔNG bao giờ chạm ``Raw_World``; không đọc field ngoài
  hợp đồng.
- **view is None (R1.4)**: không có frame → trả ``WorldScene`` rỗng,
  ``confidence=0.0``, ``frame_id=None`` + ghi lý do; tuyệt đối không đọc gì.
- **Có broadcast_items (R2.1, R2.2)**: đúng một ``WorldScene`` với element mang
  ``confidence ∈ [0,1]`` (clamp ở ``__post_init__``).
- **dominant_thread (R2.3)**: nếu lộ ra và khác ``None`` → đúng một element
  ``thread`` được đánh ``is_dominant_focus=True``.
- **broadcast_items rỗng (R2.4)**: một ``WorldScene`` rỗng có ``reason``; vẫn
  tính là một scene được sinh.
- **evidence_ids (R2.5)**: bảo toàn nguyên vẹn ``evidence_ids`` của từng
  ``WorkspaceItem`` lên element dẫn xuất.
- **frame malformed (R2.6)**: ``broadcast_items`` không phải list, hoặc truy cập
  frame ném lỗi bất ngờ → ``InvalidWorkspaceFrameError``, không sinh scene.
- **thiếu field bắt buộc (R1.6)**: một field bắt buộc mà builder cần lại là
  ``None`` (hoặc không đọc được do hợp đồng bị gỡ) → cap ``confidence ≤ 0.5`` và
  ghi tên field thiếu vào ``StageDebug.missing_fields``.
- **frame_id (R1.5)**: luôn gắn ``frame_id`` của frame lên ``WorldScene``.

Logic thuần, không I/O → mục tiêu < 500ms (R2 timing).
"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import (
    InvalidWorkspaceFrameError,
    RawWorldAccessError,
    StageDebug,
    WorldScene,
    WorldSceneElement,
    clamp01,
)
from .read_contract import FrameReadView


__all__ = ["WorldSceneBuilder"]


# Tên module dùng để tra ``downstream_contract`` (R1.3).
_MODULE = "WorldSceneBuilder"

# Cap confidence khi thiếu field bắt buộc (R1.6).
_MISSING_FIELD_CAP = 0.5

# Ánh xạ ``WorkspaceItemKind`` -> loại element của scene.
# entity        : thực thể/đối tượng hiện diện trong scene.
# salient_signal: tín hiệu nổi bật cần chú ý (rủi ro/cảm xúc/thời điểm/độ nổi bật).
_ENTITY_KINDS: frozenset[str] = frozenset(
    {
        "user_request",
        "social_hypothesis",
        "body_state",
        "goal",
        "memory",
        "evidence",
        "working_memory",
        "constraint",
        "unknown",
    }
)
_SALIENT_KINDS: frozenset[str] = frozenset(
    {
        "salience",
        "risk",
        "affect",
        "temporal",
        "homeostasis",
    }
)


class WorldSceneBuilder:
    """Dựng ``WorldScene`` từ một ``FrameReadView`` (WorkspaceFrame-only)."""

    def build(
        self, view: Optional[FrameReadView]
    ) -> tuple[WorldScene, StageDebug]:
        """Dựng ``(WorldScene, StageDebug)`` từ ``view``.

        ``view is None`` → scene rỗng ``confidence=0.0`` (R1.4). Ngược lại đọc các
        field hợp đồng và dựng scene theo R2.*; thiếu field bắt buộc → cap
        confidence (R1.6); frame malformed → ``InvalidWorkspaceFrameError`` (R2.6).
        """

        debug = StageDebug(stage=_MODULE)

        # --- R1.4: không có frame -> scene rỗng, không đọc bất cứ gì ----------
        if view is None:
            debug.notes.append("view is None; no WorkspaceFrame to read (R1.4)")
            debug.confidence = 0.0
            scene = WorldScene(
                frame_id=None,
                entities=[],
                salient_signals=[],
                active_threads=[],
                confidence=0.0,
                is_empty=True,
                reason="no workspace frame available",
            )
            return scene, debug

        # --- R1.5: frame_id luôn gắn lên artifact -----------------------------
        try:
            frame_id: Optional[str] = view.frame_id
        except RawWorldAccessError:
            raise
        except InvalidWorkspaceFrameError:
            raise
        except Exception as exc:  # frame hỏng khi truy cập định danh (R2.6)
            raise InvalidWorkspaceFrameError(
                "WorkspaceFrame raised while reading frame_id"
            ) from exc

        missing_fields: list[str] = []

        # --- Đọc các field hợp đồng (None / không đọc được = missing, R1.6) ---
        broadcast_items = self._read_required(
            view, "broadcast_items", missing_fields
        )
        active_threads = self._read_required(
            view, "active_threads", missing_fields
        )
        # broadcast_reason là field bắt buộc theo hợp đồng nhưng chỉ dùng cho
        # debug/lý do; vẫn ghi nhận nếu thiếu.
        self._read_required(view, "broadcast_reason", missing_fields)
        # dominant_thread là tùy chọn: None là hợp lệ, KHÔNG coi là thiếu field.
        dominant_thread = self._read_optional(view, "dominant_thread")

        # --- R2.6: broadcast_items phải là list (nếu hiện diện) ---------------
        if broadcast_items is not None and not isinstance(broadcast_items, list):
            raise InvalidWorkspaceFrameError(
                "broadcast_items is not a list; WorkspaceFrame is malformed"
            )

        items: list[Any] = list(broadcast_items) if broadcast_items else []
        threads: list[str] = (
            [t for t in active_threads if t is not None]
            if isinstance(active_threads, list)
            else []
        )

        # --- Dựng element entity / salient_signal từ broadcast_items ----------
        entities: list[WorldSceneElement] = []
        salient_signals: list[WorldSceneElement] = []
        try:
            for item in items:
                element = self._element_from_item(item)
                if element.kind == "entity":
                    entities.append(element)
                else:
                    salient_signals.append(element)
        except (RawWorldAccessError, InvalidWorkspaceFrameError):
            raise
        except Exception as exc:  # item không parse được (R2.6)
            raise InvalidWorkspaceFrameError(
                "broadcast_items contains an unparseable WorkspaceItem"
            ) from exc

        # --- Dựng element thread + đánh dominant focus (R2.3) -----------------
        thread_elements = self._build_threads(threads, dominant_thread)

        # --- R2.4: không có broadcast_items -> scene rỗng có reason -----------
        scene_elements = entities + salient_signals
        is_empty = not scene_elements

        if is_empty:
            reason = (
                "no broadcast items; required field(s) missing: "
                + ", ".join(missing_fields)
                if missing_fields
                else "no broadcast items in workspace frame"
            )
            confidence = 0.0
            debug.confidence = confidence
            debug.missing_fields = list(missing_fields)
            if missing_fields:
                debug.notes.append(
                    "missing required field(s): " + ", ".join(missing_fields)
                )
            debug.notes.append(reason)
            scene = WorldScene(
                frame_id=frame_id,
                entities=[],
                salient_signals=[],
                active_threads=thread_elements,
                confidence=confidence,
                is_empty=True,
                reason=reason,
            )
            return scene, debug

        # --- Confidence tổng hợp của scene ------------------------------------
        confidence = self._aggregate_confidence(scene_elements)
        if missing_fields:
            # R1.6: thiếu field bắt buộc -> cap confidence.
            confidence = min(confidence, _MISSING_FIELD_CAP)

        debug.confidence = confidence
        debug.missing_fields = list(missing_fields)
        if missing_fields:
            debug.notes.append(
                "missing required field(s) -> confidence capped at "
                f"{_MISSING_FIELD_CAP}: " + ", ".join(missing_fields)
            )

        scene = WorldScene(
            frame_id=frame_id,
            entities=entities,
            salient_signals=salient_signals,
            active_threads=thread_elements,
            confidence=confidence,
            is_empty=False,
            reason="",
        )
        return scene, debug

    # ------------------------------------------------------------------
    # Đọc field qua hợp đồng
    # ------------------------------------------------------------------
    def _read_required(
        self, view: FrameReadView, field_name: str, missing_fields: list[str]
    ) -> Any:
        """Đọc một field bắt buộc; ``None``/không đọc được -> ghi missing (R1.6).

        - Field không nằm trong hợp đồng (vd ``downstream_contract`` bị gỡ) ->
          không thể đọc -> coi như thiếu field bắt buộc.
        - Field đọc được nhưng giá trị là ``None`` -> coi như thiếu field (theo
          chỉ dẫn: read một field hợp lệ trả ``None`` là "missing", không phải vi
          phạm hợp đồng).
        """

        if not view.can_read(field_name, module=_MODULE):
            missing_fields.append(field_name)
            return None
        try:
            value = view.read(field_name, module=_MODULE)
        except RawWorldAccessError:
            # Hợp đồng từ chối -> với builder nghĩa là field không khả dụng.
            missing_fields.append(field_name)
            return None
        except InvalidWorkspaceFrameError:
            raise
        except Exception as exc:  # truy cập field ném lỗi bất ngờ (R2.6)
            raise InvalidWorkspaceFrameError(
                f"WorkspaceFrame raised while reading '{field_name}'"
            ) from exc
        if value is None:
            missing_fields.append(field_name)
        return value

    def _read_optional(self, view: FrameReadView, field_name: str) -> Any:
        """Đọc một field tùy chọn; ``None`` là hợp lệ (không ghi missing)."""

        if not view.can_read(field_name, module=_MODULE):
            return None
        try:
            return view.read(field_name, module=_MODULE)
        except RawWorldAccessError:
            return None
        except InvalidWorkspaceFrameError:
            raise
        except Exception as exc:  # pragma: no cover - phòng thủ (R2.6)
            raise InvalidWorkspaceFrameError(
                f"WorkspaceFrame raised while reading '{field_name}'"
            ) from exc

    # ------------------------------------------------------------------
    # Dựng element
    # ------------------------------------------------------------------
    def _element_from_item(self, item: Any) -> WorldSceneElement:
        """Adapt một ``WorkspaceItem`` -> ``WorldSceneElement``.

        - ``kind`` ánh xạ qua ``_ENTITY_KINDS`` / ``_SALIENT_KINDS`` (mặc định
          entity cho kind lạ).
        - ``confidence`` suy từ ``confidence`` (trội) và ``priority`` của item,
          luôn ∈ [0,1] sau ``clamp01``.
        - ``evidence_ids`` bảo toàn nguyên vẹn (R2.5).
        """

        item_kind = getattr(item, "kind", None)
        element_kind = "entity" if item_kind in _ENTITY_KINDS else (
            "salient_signal" if item_kind in _SALIENT_KINDS else "entity"
        )

        item_id = getattr(item, "id", None)
        summary = getattr(item, "summary", "") or ""
        raw_evidence = getattr(item, "evidence_ids", None)
        evidence_ids = list(raw_evidence) if raw_evidence else []

        confidence = clamp01(self._derive_confidence(item))

        return WorldSceneElement(
            element_id=str(item_id) if item_id is not None else "element",
            kind=element_kind,
            summary=str(summary),
            evidence_ids=evidence_ids,
            confidence=confidence,
            is_dominant_focus=False,
            source_item_id=str(item_id) if item_id is not None else None,
        )

    @staticmethod
    def _derive_confidence(item: Any) -> float:
        """Suy ``confidence`` của element từ ``confidence``/``priority`` của item.

        Trọng số nghiêng về ``confidence`` (0.7) và bổ sung ``priority`` (0.3) để
        một item ưu tiên cao nhưng confidence trung bình vẫn nổi bật hợp lý. Mọi
        giá trị không parse được quy về 0.0 (qua ``clamp01``).
        """

        confidence = clamp01(getattr(item, "confidence", 0.0))
        priority = clamp01(getattr(item, "priority", 0.0))
        return 0.7 * confidence + 0.3 * priority

    def _build_threads(
        self, threads: list[str], dominant_thread: Any
    ) -> list[WorldSceneElement]:
        """Dựng element ``thread`` từ ``active_threads`` + đánh dominant (R2.3).

        Đúng MỘT element được đánh ``is_dominant_focus=True`` khi
        ``dominant_thread`` khác ``None``. Nếu ``dominant_thread`` không nằm trong
        ``active_threads`` (frame lệch), một element thread cho nó vẫn được thêm
        để bất biến "đúng một dominant focus" được giữ.
        """

        elements: list[WorldSceneElement] = []
        seen: set[str] = set()
        for thread in threads:
            label = str(thread)
            if label in seen:
                continue
            seen.add(label)
            elements.append(
                WorldSceneElement(
                    element_id=f"thread::{label}",
                    kind="thread",
                    summary=label,
                    evidence_ids=[],
                    confidence=0.0,
                    is_dominant_focus=False,
                )
            )

        if dominant_thread is None:
            return elements

        dominant_label = str(dominant_thread)
        marked = False
        for element in elements:
            if element.summary == dominant_label and not marked:
                element.is_dominant_focus = True
                marked = True

        if not marked:
            # dominant_thread không có element tương ứng -> tạo mới để giữ R2.3.
            elements.append(
                WorldSceneElement(
                    element_id=f"thread::{dominant_label}",
                    kind="thread",
                    summary=dominant_label,
                    evidence_ids=[],
                    confidence=0.0,
                    is_dominant_focus=True,
                )
            )

        return elements

    @staticmethod
    def _aggregate_confidence(elements: list[WorldSceneElement]) -> float:
        """Confidence của scene = trung bình confidence các element mang evidence.

        Nếu không có element nào (đã chặn trước đó), trả 0.0.
        """

        if not elements:
            return 0.0
        total = sum(element.confidence for element in elements)
        return clamp01(total / len(elements))
