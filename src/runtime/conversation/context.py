# -*- coding: utf-8 -*-
"""Context cơ học dành cho RootAgent V12.

Module này cố ý không chứa social state, agenda hay conversation plan. Nó chỉ
cung cấp hai primitive runtime mà root agent được phép dùng trong lúc suy nghĩ:

- ``ConversationNoteTools``: ghi/xóa plain-text working note do agent sở hữu;
- ``RootCapabilityRegistry``: registry các capability domain. Registry không tự
  chọn capability và không materialize public speech.

Mọi quyết định *có gọi capability hay không* vẫn thuộc RootAgent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


def normalize_note(note: str) -> str:
    """Giữ line-break do agent viết; chỉ cắt runaway payload cơ học."""

    return str(note or "").strip()[:12000]


@dataclass(frozen=True, slots=True)
class ConversationNoteTools:
    """Hai thao tác note tối thiểu mà RootAgent có thể gọi theo nhu cầu.

    Runtime không parse nội dung note, không merge semantic và không dùng note
    để tự tạo continuation. ``set_note``/``clear_note`` chỉ ghi state bền vững.
    """

    set_note: Callable[[str], None]
    clear_note: Callable[[], None]

    def set(self, text: str) -> None:
        self.set_note(normalize_note(text))

    def clear(self) -> None:
        self.clear_note()


@dataclass(frozen=True, slots=True)
class RootCapabilityRegistry:
    """Registry data/runtime-only cho capability mà RootAgent có thể gọi.

    Registry chỉ là dependency container. Nó không route dựa keyword, không tự
    gọi tutor ở mọi turn và không quyết định public response.
    """

    capabilities: Mapping[str, Any]

    def get(self, name: str) -> Any | None:
        return self.capabilities.get(str(name or "").strip().lower())

    def available_names(self) -> tuple[str, ...]:
        return tuple(sorted(str(name) for name, value in self.capabilities.items() if value is not None))


__all__ = [
    "ConversationNoteTools",
    "RootCapabilityRegistry",
    "normalize_note",
]
