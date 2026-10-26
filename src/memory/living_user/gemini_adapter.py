# -*- coding: utf-8 -*-
"""Adapter Gemini Web -> Living User Memory Operations.

Dùng Gemini Web (2.5 Flash) làm Memory Curator & Dreamer, giải phóng DeepSeek
khỏi việc bị spam đè lane khi tổng hợp hồ sơ người dùng.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .runtime_adapter import _PROFILE_SYSTEM, _EPISODE_SYSTEM, _parse_json, CuratorInferenceError

logger = logging.getLogger(__name__)


def _find_credentials_path() -> Path | None:
    env_path = os.environ.get("GEMINI_CREDENTIALS_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    # Check repo paths
    current = Path(__file__).resolve()
    for parent in current.parents:
        cand = parent / "tools" / "gemini_vision_docker" / "data_cache" / "gemini_credentials.json"
        if cand.is_file():
            return cand
        cand2 = parent / ".eris_home" / "gemini_credentials.json"
        if cand2.is_file():
            return cand2
    return None


@dataclass
class GeminiWebUserProfileAdapter:
    """Model adapter cho living user memory dùng Gemini Web."""

    psid: str = ""
    psidts: str = ""
    timeout: float = 60.0
    _client: Any = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def create_if_available(cls, *, timeout: float = 60.0) -> GeminiWebUserProfileAdapter | None:
        """Khởi tạo nếu có gemini_webapi và file credentials/cookie."""
        try:
            import gemini_webapi  # type: ignore # noqa: F401
        except ImportError:
            return None

        psid = os.environ.get("GEMINI_SECURE_1PSID", "").strip()
        psidts = os.environ.get("GEMINI_SECURE_1PSIDTS", "").strip()

        if not psid:
            cred_file = _find_credentials_path()
            if cred_file and cred_file.is_file():
                try:
                    data = json.loads(cred_file.read_text(encoding="utf-8"))
                    psid = str(data.get("psid") or "").strip()
                    psidts = str(data.get("psidts") or "").strip()
                except Exception as exc:
                    logger.warning("[gemini_adapter] Không đọc được credentials file %s: %s", cred_file, exc)

        if not psid:
            return None

        return cls(psid=psid, psidts=psidts, timeout=timeout)

    def propose_profile_operations(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        prompt = (
            f"{_PROFILE_SYSTEM}\n\n"
            f"User Turn Evidence:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        return self._generate_json(prompt, operation="living_user_profile")

    def summarize_episode(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        prompt = (
            f"{_EPISODE_SYSTEM}\n\n"
            f"Episode Evidence:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        return self._generate_json(prompt, operation="living_user_episode")

    def _generate_json(self, prompt: str, *, operation: str) -> Mapping[str, Any] | None:
        with self._lock:
            try:
                raw_text = asyncio.run(self._async_call(prompt))
            except Exception as exc:
                logger.warning("[gemini_adapter] %s failed: %s", operation, exc)
                raise CuratorInferenceError(f"gemini_{type(exc).__name__}") from exc

        if not raw_text or not raw_text.strip():
            raise CuratorInferenceError("empty_output")

        parsed = _parse_json(raw_text)
        if not isinstance(parsed, Mapping):
            raise CuratorInferenceError("parse_error")
        return parsed

    async def _async_call(self, prompt: str) -> str:
        from gemini_webapi import GeminiClient  # type: ignore

        if self._client is None:
            self._client = GeminiClient(
                secure_1psid=self.psid,
                secure_1psidts=self.psidts,
                timeout=int(self.timeout),
            )
            await self._client.init(auto_refresh=False)

        resp = await self._client.generate_content(prompt)
        return getattr(resp, "text", str(resp))
