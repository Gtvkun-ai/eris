# -*- coding: utf-8 -*-
"""world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2).

``WorldInterpreter`` là stage thứ hai của pipeline meaning. Nó nhận một
``WorldScene`` (đầu ra của ``WorldSceneBuilder``) và rút ra một tập
``Observation`` — quan sát có-bằng-chứng, truy vết được về element gốc.

Module này **chỉ** thao tác trên dữ liệu scene đã được trích xuất dưới hợp đồng
``WorkspaceFrame``-only của ``WorldSceneBuilder``; nó **không** đọc
``WorkspaceFrame`` hay ``FrameReadView`` trực tiếp, nên không cần guard
``ReadContract`` riêng (scene đã được dựng trong hợp đồng).

Ràng buộc cưỡng chế (xem design "WorldInterpreter"):

- **Scene ≥ 1 element (R3.1, R3.4)**: trả tập 0..n ``Observation``; mỗi
  observation có ``confidence ∈ [0,1]`` (clamp ở ``__post_init__``), ≥1
  ``evidence_id`` và ``source_element_id`` trỏ về element gốc trong scene.
- **Nguồn observation**: rút từ **tất cả** element của scene — ``entities`` +
  ``salient_signals`` + ``active_threads``. ``evidence_ids`` của observation lấy
  nguyên vẹn từ ``evidence_ids`` của element gốc.
- **Loại candidate không có evidence (R3.6)**: element không gắn được ≥1
  ``evidence_id`` → candidate bị loại, không nằm trong tập trả về. (Theo thiết
  kế, element ``thread`` có ``evidence_ids`` rỗng nên sẽ bị loại tự nhiên — đúng
  hành vi mong đợi.)
- **Low confidence (R3.3)**: element có ``confidence < low_conf_threshold``
  (mặc định 0.5, cấu hình trong [0,1]) → observation dẫn xuất được đánh
  ``low_confidence=True``.
- **Scope guard (R3.2)**: KHÔNG sinh intent / mental-state inference — chỉ sinh
  ``Observation``.
- **Scene không hợp lệ (R3.5)**: scene là ``None``, không phải ``WorldScene``,
  hoặc sai cấu trúc (các field tập không phải list) → KHÔNG sinh observation và
  ném ``WorldSceneValidationError``; các observation đã sinh trước đó giữ nguyên
  (hàm thuần, không mutate state ngoài).

Phân biệt **scene rỗng hợp lệ** với **scene không hợp lệ**:

- ``scene is None`` / không phải ``WorldScene`` / sai cấu trúc → ``WorldSceneValidationError``.
- ``scene.is_empty is True`` (scene rỗng hợp lệ do ``WorldSceneBuilder`` dựng cho
  frame không có broadcast item) → trả ``[]`` **không** ném lỗi; đây là kết quả
  hợp lệ "không có quan sát nào", không phải lỗi cấu trúc.

Logic thuần, không I/O.
"""

from __future__ import annotations

from typing import Optional

from .contracts import (
    Observation,
    StageDebug,
    WorldScene,
    WorldSceneElement,
    WorldSceneValidationError,
    clamp01,
)


__all__ = ["WorldInterpreter"]


# Tên stage để gắn vào ``StageDebug``.
_MODULE = "WorldInterpreter"

# Ngưỡng low-confidence mặc định (R3.3); cấu hình được trong [0,1].
_DEFAULT_LOW_CONF_THRESHOLD = 0.5


class WorldInterpreter:
    """Diễn giải ``WorldScene`` thành tập ``Observation`` (WorldScene-only)."""

    def interpret(
        self,
        scene: WorldScene,
        *,
        low_conf_threshold: float = _DEFAULT_LOW_CONF_THRESHOLD,
    ) -> tuple[list[Observation], StageDebug]:
        """Rút ``(list[Observation], StageDebug)`` từ ``scene``.

        ``scene`` không hợp lệ (None / sai kiểu / sai cấu trúc) → ném
        ``WorldSceneValidationError`` (R3.5). ``scene.is_empty`` → trả ``[]`` hợp
        lệ. Ngược lại rút observation từ mọi element có ≥1 ``evidence_id`` (R3.1,
        R3.4, R3.6) và đánh ``low_confidence`` theo ``low_conf_threshold`` (R3.3).
        """

        debug = StageDebug(stage=_MODULE)

        # --- R3.5: validate cấu trúc trước khi sinh bất cứ observation nào ----
        self._validate_scene(scene)

        # Ngưỡng cấu hình phải nằm trong [0,1] (R3.3).
        threshold = clamp01(low_conf_threshold)

        # --- Scene rỗng hợp lệ -> không có quan sát, không lỗi ----------------
        if scene.is_empty:
            debug.notes.append(
                "scene is empty (is_empty=True); no observations produced"
            )
            debug.confidence = 0.0
            return [], debug

        # --- Rút candidate từ TẤT CẢ element của scene ------------------------
        elements: list[WorldSceneElement] = (
            list(scene.entities)
            + list(scene.salient_signals)
            + list(scene.active_threads)
        )

        observations: list[Observation] = []
        discarded_no_evidence = 0
        low_conf_count = 0

        for element in elements:
            evidence_ids = (
                list(element.evidence_ids) if element.evidence_ids else []
            )

            # --- R3.6: candidate không gắn được >=1 evidence -> loại ----------
            if not evidence_ids:
                discarded_no_evidence += 1
                continue

            # --- confidence dẫn xuất mirror element gốc (đã clamp) ------------
            confidence = clamp01(element.confidence)
            is_low_conf = confidence < threshold
            if is_low_conf:
                low_conf_count += 1

            observations.append(
                Observation(
                    observation_id=f"obs::{element.element_id}",
                    summary=element.summary,
                    evidence_ids=evidence_ids,
                    confidence=confidence,
                    source_element_id=element.element_id,  # R3.4
                    low_confidence=is_low_conf,  # R3.3
                )
            )

        # --- Debug bookkeeping ------------------------------------------------
        debug.confidence = self._aggregate_confidence(observations)
        debug.notes.append(
            f"low_conf_threshold={threshold}; "
            f"produced={len(observations)}; "
            f"discarded_no_evidence={discarded_no_evidence}; "
            f"low_confidence={low_conf_count}"
        )
        return observations, debug

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_scene(scene: Optional[WorldScene]) -> None:
        """Cưỡng chế cấu trúc ``WorldScene`` hợp lệ (R3.5).

        ``None`` / không phải ``WorldScene`` / các field tập không phải list →
        ``WorldSceneValidationError``. Không mutate gì; ném sớm trước khi sinh
        observation để các observation cũ (do caller giữ) không bị ảnh hưởng.
        """

        if scene is None:
            raise WorldSceneValidationError(
                "WorldScene is None; cannot interpret"
            )
        if not isinstance(scene, WorldScene):
            raise WorldSceneValidationError(
                "interpret() expects a WorldScene instance; "
                f"got {type(scene).__name__}"
            )
        for field_name in ("entities", "salient_signals", "active_threads"):
            value = getattr(scene, field_name, None)
            if not isinstance(value, list):
                raise WorldSceneValidationError(
                    f"WorldScene.{field_name} is malformed "
                    "(expected a list of WorldSceneElement)"
                )

    @staticmethod
    def _aggregate_confidence(observations: list[Observation]) -> float:
        """Confidence tổng hợp của stage = trung bình confidence observation."""

        if not observations:
            return 0.0
        total = sum(obs.confidence for obs in observations)
        return clamp01(total / len(observations))
