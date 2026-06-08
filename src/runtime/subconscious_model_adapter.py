# -*- coding: utf-8 -*-
"""Adapter gọi model/API riêng cho Lane 3 subconscious synthesis.

Lane 3 không sinh lời thoại public. Nó chỉ lập một "biên bản phiên toà nội tâm":
- các mảnh nào đang tranh nhau ý nghĩa,
- bên công tố/biện hộ nhìn thấy gì,
- thẩm phán kết luận ThoughtObject nào đủ evidence.

Nếu API hỏng hoặc thiếu key, adapter trả lỗi và Synthesizer rơi về deterministic path.
Nội tâm mà chết vì một provider 500 thì cũng hơi giống con người, nhưng runtime không
nên chết theo. Thế giới đã đủ lộn xộn rồi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Mapping

from eris_secrets import apply_secrets_to_environ, get_agent_profile, get_config, get_secret
from llm.client import GeminiClient, OpenAICompatibleClient


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _cfg_flag(path: str, default: bool) -> bool:
    value = get_config(path, default=default)
    if isinstance(value, str):
        raw = value.strip().lower()
        if not raw:
            return default
        return raw not in {"0", "false", "no", "off", "none"}
    return bool(value)


@dataclass(slots=True, frozen=True)
class SubconsciousModelAdapterConfig:
    """Cấu hình riêng cho Lane 3 API synthesis.

    Ưu tiên cấu hình:
    1. Env ERIS_LANE3_*
    2. config/secrets.json -> agent_keys.lane3_synthesis
    3. config/secrets.json -> providers.<provider>.lane3_synthesis
    4. remote provider/key đang dùng cho remote_main
    """

    enabled: bool = field(
        default_factory=lambda: _env_flag(
            "ERIS_LANE3_API_ENABLED",
            _cfg_flag("subconscious_runtime.lanes.lane3_synthesis.enabled", True),
        )
    )
    agent_name: str = "lane3_synthesis"
    slot: str = field(default_factory=lambda: str(os.getenv("ERIS_LANE3_SLOT", "lane3_synthesis") or "lane3_synthesis").strip())
    provider: str = field(
        default_factory=lambda: str(
            os.getenv("ERIS_LANE3_PROVIDER", "")
            or get_config("subconscious_runtime.lanes.lane3_synthesis.provider", default="")
            or os.getenv("ERIS_REMOTE_PROVIDER", "gemini")
            or "gemini"
        ).strip().lower()
    )
    model: str = field(
        default_factory=lambda: str(
            os.getenv("ERIS_LANE3_MODEL", "")
            or get_config("subconscious_runtime.lanes.lane3_synthesis.model", default="")
            or ""
        ).strip()
    )
    base_url: str = field(
        default_factory=lambda: str(
            os.getenv("ERIS_LANE3_BASE_URL", "")
            or get_config("subconscious_runtime.lanes.lane3_synthesis.base_url", default="")
            or ""
        ).strip()
    )
    api_key: str = field(default_factory=lambda: str(os.getenv("ERIS_LANE3_API_KEY", "") or "").strip())
    timeout_seconds: float = field(
        default_factory=lambda: max(
            4.0,
            _as_float(
                os.getenv("ERIS_LANE3_TIMEOUT", "")
                or get_config("subconscious_runtime.lanes.lane3_synthesis.timeout_seconds", default=18.0),
                18.0,
            ),
        )
    )
    temperature: float = field(
        default_factory=lambda: max(
            0.0,
            min(
                0.7,
                _as_float(
                    os.getenv("ERIS_LANE3_TEMPERATURE", "")
                    or get_config("subconscious_runtime.lanes.lane3_synthesis.temperature", default=0.15),
                    0.15,
                ),
            ),
        )
    )
    max_tokens: int = field(
        default_factory=lambda: max(
            256,
            int(
                _as_float(
                    os.getenv("ERIS_LANE3_MAX_TOKENS", "")
                    or get_config("subconscious_runtime.lanes.lane3_synthesis.max_tokens", default=900),
                    900,
                )
            ),
        )
    )


@dataclass(slots=True, frozen=True)
class SubconsciousModelResult:
    ok: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    error: str = ""
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RuntimeSubconsciousModelAdapter:
    """Client mỏng cho Lane 3.

    Không dùng để trả lời user. Không được gọi từ public speech path trực tiếp.
    Nó chỉ trả JSON riêng tư cho ModelBackedConsciousSynthesizer.
    """

    def __init__(self, *, config: SubconsciousModelAdapterConfig | None = None, logger: Any | None = None) -> None:
        apply_secrets_to_environ()
        self.config = config or SubconsciousModelAdapterConfig()
        self.logger = logger
        self.profile = self._resolve_profile()
        self.provider = str(self.profile.get("provider") or self.config.provider or "").strip().lower()
        self.model = self._resolve_model()
        self.base_url = self._resolve_base_url()
        self.api_key = self._resolve_api_key()
        self.client = self._build_client()

    @classmethod
    def from_env(cls, *, logger: Any | None = None) -> "RuntimeSubconsciousModelAdapter | None":
        config = SubconsciousModelAdapterConfig()
        if not config.enabled:
            return None
        try:
            adapter = cls(config=config, logger=logger)
        except Exception as exc:
            fn = getattr(logger, "warning", None) if logger is not None else None
            if callable(fn):
                fn("[Lane3 API] Khong khoi tao duoc subconscious model adapter: %s", exc)
            return None
        if adapter.client is None:
            adapter._log("warning", "[Lane3 API] disabled: missing client/provider/key provider=%s slot=%s", adapter.provider, config.slot)
            return None
        adapter._log("info", "[Lane3 API] ready provider=%s model=%s slot=%s", adapter.provider, adapter.model, config.slot)
        return adapter

    def synthesize(self, messages: list[dict[str, Any]]) -> SubconsciousModelResult:
        """Gọi provider và parse JSON object."""

        if self.client is None:
            return SubconsciousModelResult(ok=False, error="missing_client", provider=self.provider, model=self.model)
        try:
            raw = self.client.create_chat_completion(
                messages=messages,
                temperature=self.config.temperature,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
                timeout=self.config.timeout_seconds,
            )
            content = self._extract_content(raw)
            parsed = self._parse_json_object(content)
            if not isinstance(parsed, dict):
                return SubconsciousModelResult(
                    ok=False,
                    content=content,
                    error="invalid_json",
                    provider=self.provider,
                    model=self.model,
                    raw=self._safe_raw(raw),
                )
            return SubconsciousModelResult(
                ok=True,
                parsed=parsed,
                content=content,
                provider=self.provider,
                model=self.model,
                raw=self._safe_raw(raw),
            )
        except Exception as exc:
            self._log("warning", "[Lane3 API] model call failed: %s", exc)
            return SubconsciousModelResult(
                ok=False,
                error=f"{type(exc).__name__}:{exc}",
                provider=self.provider,
                model=self.model,
            )

    def _resolve_profile(self) -> dict[str, Any]:
        profile = get_agent_profile(
            self.config.agent_name,
            default_provider=self.config.provider,
            default_slot=self.config.slot,
            default={},
        )
        return dict(profile or {})

    def _resolve_model(self) -> str:
        model = (
            str(self.config.model or "").strip()
            or str(self.profile.get("model") or "").strip()
            or str(self.profile.get("model_name") or "").strip()
        )
        if model:
            return model
        if self.provider == "gemini":
            return os.getenv("ERIS_REMOTE_MODEL", "").strip() or os.getenv("GEMINI_MODEL", "").strip() or "gemma-4-26b-a4b-it"
        if self.provider in {"openai", "openai_compatible", "compatible", "remote"}:
            return os.getenv("ERIS_REMOTE_MODEL", "").strip() or "gemini-3-flash-preview"
        return model or "lane3-model"

    def _resolve_base_url(self) -> str:
        base = str(self.config.base_url or "").strip() or str(self.profile.get("base_url") or "").strip()
        if base:
            return base
        if self.provider == "gemini":
            return os.getenv("ERIS_REMOTE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip()
        if self.provider in {"openai", "openai_compatible", "compatible", "remote"}:
            return os.getenv("ERIS_REMOTE_BASE_URL", "https://api-v2.shopaikey.com/v1").strip()
        return base

    def _resolve_api_key(self) -> str:
        key = str(self.config.api_key or "").strip() or str(self.profile.get("api_key") or "").strip()
        if key:
            return key
        if self.provider == "gemini":
            return get_secret("ERIS_LANE3_API_KEY", "GEMINI_API_KEY", "ERIS_REMOTE_API_KEY")
        if self.provider in {"openai", "openai_compatible", "compatible", "remote"}:
            return get_secret("ERIS_LANE3_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
        return ""

    def _build_client(self) -> Any | None:
        if not self.provider:
            return None
        timeout = int(max(4.0, self.config.timeout_seconds))
        if self.provider == "gemini":
            if not self.api_key:
                return None
            return GeminiClient(base_url=self.base_url, api_key=self.api_key, model_name=self.model, timeout=timeout)
        if self.provider in {"openai", "openai_compatible", "compatible", "remote"}:
            if not self.api_key:
                return None
            return OpenAICompatibleClient(base_url=self.base_url, api_key=self.api_key, model_name=self.model, timeout=timeout)
        return None

    def _extract_content(self, raw: Mapping[str, Any]) -> str:
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, Mapping):
                message = first.get("message")
                if isinstance(message, Mapping):
                    return str(message.get("content") or "")
                if "text" in first:
                    return str(first.get("text") or "")

        candidates = raw.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, Mapping):
                content = first.get("content")
                if isinstance(content, Mapping):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        texts = []
                        for part in parts:
                            if isinstance(part, Mapping) and "text" in part:
                                texts.append(str(part.get("text") or ""))
                        if texts:
                            return "\n".join(texts)
        return str(raw.get("content") or raw.get("text") or "")

    def _parse_json_object(self, text: str) -> dict[str, Any] | None:
        candidate = str(text or "").strip()
        if not candidate:
            return None
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s*```$", "", candidate).strip()
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    def _safe_raw(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        # Không dump nguyên provider payload quá lớn vào report. Log là để debug, không phải bãi rác JSON.
        usage = raw.get("usage") if isinstance(raw, Mapping) else None
        return {"usage": usage} if isinstance(usage, Mapping) else {}

    def _log(self, level: str, msg: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(msg, *args)
