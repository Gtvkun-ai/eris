# -*- coding: utf-8 -*-
"""Các contract provider độc lập nền tảng theo kiến trúc trong báo cáo.

Protocol không ép implementation Windows/Gemini/Edge hiện tại phải viết lại ngay.
Nó tạo đường nối ổn định để thay provider mà coordinator không cần biết chi tiết
SDK, quota hay hệ điều hành, một ý tưởng kỳ lạ gọi là tách trách nhiệm.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    ready: bool
    provider: str
    reason: str = ""
    details: Mapping[str, Any] | None = None


@runtime_checkable
class ActionProvider(Protocol):
    def execute(self, action_name: str, action_input: str = "") -> Any: ...
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class SpeechProvider(Protocol):
    def synthesize(self, contract: Any, text: str) -> Any: ...
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class MemoryProvider(Protocol):
    def query(self, request: Any) -> Any: ...
    def commit(self, record: Any) -> Any: ...
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class BudgetGovernor(Protocol):
    def plan(self, *, provider: str, lane: str, prompt_tokens: int, output_tokens: int) -> Any: ...
    def health(self) -> ProviderHealth: ...


class ProviderRegistry:
    """Registry nhỏ, typed và fail-fast cho bốn provider contract chính."""

    _KINDS = {
        "action": ActionProvider,
        "speech": SpeechProvider,
        "memory": MemoryProvider,
        "budget": BudgetGovernor,
    }

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, kind: str, provider: Any) -> None:
        normalized = str(kind or "").strip().lower()
        expected = self._KINDS.get(normalized)
        if expected is None:
            raise KeyError(f"Loại provider không hợp lệ: {kind}")
        if not isinstance(provider, expected):
            raise TypeError(f"Provider {normalized} không thỏa contract bắt buộc")
        self._providers[normalized] = provider

    def get(self, kind: str) -> Any:
        normalized = str(kind or "").strip().lower()
        if normalized not in self._providers:
            raise LookupError(f"Chưa đăng ký provider: {normalized}")
        return self._providers[normalized]

    def health(self) -> dict[str, ProviderHealth]:
        result: dict[str, ProviderHealth] = {}
        for kind, provider in self._providers.items():
            try:
                value = provider.health()
                result[kind] = value if isinstance(value, ProviderHealth) else ProviderHealth(bool(value), type(provider).__name__)
            except Exception as exc:
                result[kind] = ProviderHealth(False, type(provider).__name__, type(exc).__name__)
        return result


__all__ = [
    "ActionProvider", "BudgetGovernor", "MemoryProvider", "ProviderHealth",
    "ProviderRegistry", "SpeechProvider",
]
