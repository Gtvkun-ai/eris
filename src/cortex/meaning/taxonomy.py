# -*- coding: utf-8 -*-
"""taxonomy.py — registry meaning/intent/mental-state categories + startup validation.

Registry **nguồn sự thật** cho ba họ category của Phase 2:

- ``MEANING``        — loại ý nghĩa bề mặt của một phát ngôn/tín hiệu.
- ``INTENT``         — ý định thực dụng (pragmatic) đằng sau phát ngôn.
- ``MENTAL_STATE``   — trạng thái tâm trí được suy luận bởi Theory of Mind.

Mỗi họ được khai báo dưới dạng ``tuple`` nguồn (``*_SOURCE``) rồi đóng băng thành
``frozenset`` để dùng ở runtime. Giữ tuple nguồn cho phép ``validate_on_startup``
phát hiện id trùng bằng cách so độ dài tuple với độ dài set (frozenset tự khử
trùng nên độ dài lệch ⇔ có id lặp) — R11.4.

``require()`` là **cổng bắt buộc** trước mọi lần gán category (R11.2, R11.3): mọi
stage muốn gán ``category`` cho một artifact phải đi qua ``require()`` để đảm bảo
id thuộc đúng họ; gán không qua cổng này bị coi là bug.
"""

from __future__ import annotations

from .contracts import ConfigurationError


__all__ = ["Taxonomy"]


class Taxonomy:
    """Registry category tĩnh cho meaning / intent / mental-state.

    Ba thuộc tính lớp ``MEANING``/``INTENT``/``MENTAL_STATE`` là ``frozenset[str]``
    (mỗi set ≥ 1 category). Dùng ``require(set_name, category_id)`` làm cổng gán.
    """

    # --- Nguồn (tuple) — giữ để phát hiện trùng id ở validate_on_startup (R11.4) ---
    MEANING_SOURCE: tuple[str, ...] = (
        "literal_statement",
        "request",
        "question",
        "complaint",
        "joke",
        "probe",
        "emotional_disclosure",
        "sarcasm",
        "agreement",
        "disagreement",
        "small_talk",
    )

    INTENT_SOURCE: tuple[str, ...] = (
        "ask_for_help",
        "express_frustration",
        "tease",
        "seek_reassurance",
        "share_information",
        "request_action",
        "test_boundary",
        "seek_connection",
        "vent_emotion",
        "deflect",
    )

    MENTAL_STATE_SOURCE: tuple[str, ...] = (
        "frustrated",
        "curious",
        "anxious",
        "content",
        "bored",
        "hurt",
        "affectionate",
        "playful",
        "withdrawn",
        "reassured",
    )

    # --- Frozen sets dùng ở runtime ---
    MEANING: frozenset[str] = frozenset(MEANING_SOURCE)
    INTENT: frozenset[str] = frozenset(INTENT_SOURCE)
    MENTAL_STATE: frozenset[str] = frozenset(MENTAL_STATE_SOURCE)

    # Ánh xạ tên set -> (tuple nguồn, frozenset) để dùng chung cho validate/require.
    _REGISTRY: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
        "MEANING": (MEANING_SOURCE, MEANING),
        "INTENT": (INTENT_SOURCE, INTENT),
        "MENTAL_STATE": (MENTAL_STATE_SOURCE, MENTAL_STATE),
    }

    @classmethod
    def validate_on_startup(cls) -> None:
        """Kiểm mỗi họ có id duy nhất và không rỗng (R11.1, R11.4).

        - Trùng id: so độ dài tuple nguồn với độ dài frozenset; lệch ⇒ có id lặp,
          ném ``ConfigurationError(duplicate_id, set_name)``.
        - Họ rỗng: ném ``ConfigurationError("<empty>", set_name)``.
        """

        for set_name, (source, frozen) in cls._REGISTRY.items():
            if len(frozen) == 0:
                raise ConfigurationError("<empty>", set_name)
            if len(source) != len(frozen):
                # Xác định id trùng đầu tiên để báo lỗi rõ ràng.
                seen: set[str] = set()
                duplicate = next(
                    (cid for cid in source if cid in seen or seen.add(cid)),  # type: ignore[func-returns-value]
                    "<duplicate>",
                )
                raise ConfigurationError(duplicate, set_name)

    @classmethod
    def require(cls, set_name: str, category_id: str) -> str:
        """Cổng bắt buộc trước mọi gán category (R11.2, R11.3).

        Trả về ``category_id`` nếu nó thuộc họ ``set_name``; ngược lại (set không
        tồn tại hoặc id không hợp lệ) ném ``ConfigurationError(category_id, set_name)``.
        """

        entry = cls._REGISTRY.get(set_name)
        if entry is None:
            raise ConfigurationError(category_id, set_name)
        _, frozen = entry
        if category_id not in frozen:
            raise ConfigurationError(category_id, set_name)
        return category_id
