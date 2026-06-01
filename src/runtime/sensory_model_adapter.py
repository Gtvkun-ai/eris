from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from llm.ollama_client import OllamaClient

try:
    from cortex.observer_contracts import SignalDiff, SignalSnapshot
except Exception:  # pragma: no cover
    from src.cortex.observer_contracts import SignalDiff, SignalSnapshot  # type: ignore


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


@dataclass(slots=True, frozen=True)
class SensoryModelAdapterConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_SENSORY_ENABLED", False))
    provider: str = field(default_factory=lambda: str(os.getenv("ERIS_SENSORY_PROVIDER", "ollama") or "ollama").strip().lower())
    model: str = field(default_factory=lambda: str(os.getenv("ERIS_SENSORY_MODEL", "qwen3:0.6b") or "qwen3:0.6b").strip())
    keep_alive: str | int = field(default_factory=lambda: os.getenv("ERIS_SENSORY_KEEP_ALIVE", "30m"))
    temperature: float = field(default_factory=lambda: float(os.getenv("ERIS_SENSORY_TEMPERATURE", "0.0") or 0.0))


class RuntimeSensoryModelAdapter:
    """Adapter riêng cho tầng cảm giác 0.6B."""

    def __init__(
        self,
        *,
        config: SensoryModelAdapterConfig | None = None,
        ollama_client: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self.config = config or SensoryModelAdapterConfig()
        self.logger = logger
        self.client = ollama_client if ollama_client is not None else (OllamaClient() if self.config.provider == "ollama" else None)

    @classmethod
    def from_env(cls, *, logger: Any | None = None) -> "RuntimeSensoryModelAdapter | None":
        config = SensoryModelAdapterConfig()
        if not config.enabled:
            return None
        return cls(config=config, logger=logger)

    def observe(
        self,
        *,
        snapshot: SignalSnapshot,
        diff: SignalDiff,
        recent_summary: str = "",
    ) -> dict[str, Any] | None:
        if not self.config.enabled or self.config.provider != "ollama" or self.client is None:
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ERIS sensory observer 0.6B. "
                    "Classify runtime signals only. Return JSON only. "
                    "Do not answer the user. Do not infer hidden inner life."
                ),
            },
            {
                "role": "user",
                "content": self._prompt(snapshot=snapshot, diff=diff, recent_summary=recent_summary),
            },
        ]
        result = self.client.chat_json(
            self.config.model,
            messages,
            schema=self._schema(),
            keep_alive=self.config.keep_alive,
            temperature=self.config.temperature,
        )
        if not getattr(result, "ok", False):
            self._log("warning", "Sensory adapter failed: %s", getattr(result, "error", "unknown"))
            return None
        parsed = getattr(result, "parsed", None)
        return dict(parsed) if isinstance(parsed, dict) else None

    def _prompt(self, *, snapshot: SignalSnapshot, diff: SignalDiff, recent_summary: str) -> str:
        return (
            "Classify this runtime snapshot into a compact observer frame.\n"
            "Return grounded values only.\n\n"
            f"snapshot:\n{snapshot.compact_summary()}\n\n"
            f"diff: score={diff.diff_score:.2f}; novelty={diff.novelty:.2f}; "
            f"repetition={diff.repetition:.2f}; reasons={list(diff.reason)}\n\n"
            f"recent_summary:\n{recent_summary or '(none)'}"
        )

    def _schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus_kind": {"type": "string", "enum": ["code", "docs", "browser", "chat", "media", "game", "system", "unknown"]},
                "activity_intent": {"type": "string", "enum": ["debugging", "designing", "reading", "searching", "communicating", "resting", "fragmented", "idle", "unknown"]},
                "salience": {"type": "number"},
                "novelty": {"type": "number"},
                "repetition": {"type": "number"},
                "ambiguity": {"type": "number"},
                "possible_error": {"type": "number"},
                "user_presence": {"type": "number"},
                "recommended_action": {"type": "string", "enum": ["observe_only", "update_body_bias", "call_vision_compressor", "wake_main_cognition", "suppress"]},
                "recommended_budget": {"type": "string", "enum": ["fast", "normal", "deep"]},
                "confidence": {"type": "number"},
                "notes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "focus_kind",
                "activity_intent",
                "salience",
                "novelty",
                "repetition",
                "ambiguity",
                "possible_error",
                "user_presence",
                "recommended_action",
                "recommended_budget",
                "confidence",
            ],
        }

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(msg, *args)
