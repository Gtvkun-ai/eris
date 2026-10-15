# -*- coding: utf-8 -*-
"""Adapter LLM service -> structured living user memory operations.

Không bắt buộc phải bật. Khi model không sẵn sàng, service vẫn chạy bằng semantic
claims và deterministic consolidation. Remote inference chỉ làm giàu profile,
không trở thành điểm chết duy nhất của memory.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


_PROFILE_SYSTEM = """Bạn là bộ tổng hợp living user memory cho ERIS.
Chỉ xuất JSON. Nhiệm vụ là đề xuất patch cho profile người dùng từ evidence đã cho.
Không chẩn đoán tâm lý. Không suy diễn thuộc tính nhạy cảm. Phân biệt:
- explicit: user nói rõ;
- observed: pattern hành vi lặp lại;
- inferred: suy luận thận trọng.
Không chép nguyên văn hội thoại dài. Chỉ giữ thứ giúp tương tác tương lai.
Output: {"operations":[{"op":"add|reinforce|update|weaken|supersede|merge|archive|delete","path":"...","value":...,"old_value":...,"confidence":0..1,"explicitness":"explicit|observed|inferred","sensitivity":"normal|personal|private|sensitive","cardinality":"single|multi","evidence_ids":[...],"reason":"..."}]}"""

_EPISODE_SYSTEM = """Bạn là episode summarizer cho ERIS. Chỉ xuất JSON.
Tóm tắt phiên theo sự kiện, quyết định, outcome, việc còn mở và tín hiệu user.
Không suy diễn thuộc tính nhạy cảm, không kể lại từng câu.
Output: {"title":"...","summary":"...","outcome":"...","topics":[],"entities":[],"decisions":[],"open_loops":[],"user_signals":[],"importance":0..1}"""


class CuratorInferenceError(RuntimeError):
    """Model curator chưa trả được kết quả hợp lệ, cần giữ evidence và retry."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"curator_{status}")


@dataclass(slots=True)
class LlmServiceUserProfileAdapter:
    llm_service: Any
    client: Any = None
    fallback_to_service_client: bool = True
    inference_lane: str = "memory_digest"
    inference_optional: bool = True
    project: str = ""
    credential_pool: str = ""
    timeout_seconds: float = 20.0
    max_tokens: int = 900

    def propose_profile_operations(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return self._call(_PROFILE_SYSTEM, payload, operation="living_user_profile")

    def summarize_episode(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return self._call(_EPISODE_SYSTEM, payload, operation="living_user_episode")

    def _call(self, system_prompt: str, payload: Mapping[str, Any], *, operation: str) -> Mapping[str, Any] | None:
        service = self.llm_service
        client = self.client
        if client is None and self.fallback_to_service_client:
            client = getattr(service, "client", None)
        create = getattr(client, "create_chat_completion", None)
        if not callable(create):
            return None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ]
        try:
            # Import lazy để package memory dùng được trong unit test độc lập runtime.
            from runtime.inference_broker import inference_context
            from runtime.work_keys import stable_work_key
            work_key = stable_work_key(operation, json.dumps(payload, ensure_ascii=False, sort_keys=True)[:4000])
            with inference_context(
                self.inference_lane,
                optional=self.inference_optional,
                timeout_seconds=self.timeout_seconds,
                cancel_scope=f"background:{operation}",
                coalesce_key=work_key,
                idempotency_key=work_key,
                project=self.project,
                credential_pool=self.credential_pool,
                metadata={"operation": operation},
            ):
                response = create(
                    messages=messages,
                    temperature=0.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                    grammar=None,
                    timeout=self.timeout_seconds,
                )
        except Exception as exc:
            # Không biến timeout thành "không có gì đáng nhớ": pipeline cần
            # phân biệt provider lỗi và kết quả operations=[] hợp lệ.
            from llm.provider_errors import classify_provider_error, ProviderErrorKind
            import requests
            if isinstance(exc, requests.Timeout):
                status = "timeout"
            else:
                kind = classify_provider_error(exc)
                status = "timeout" if "timeout" in type(exc).__name__.lower() else (
                    "provider_error" if kind != ProviderErrorKind.UNKNOWN else "provider_error")
            raise CuratorInferenceError(status) from exc
        extractor = getattr(service, "_extract_content", None)
        try:
            content = str(extractor(response) or "") if callable(extractor) else _extract_text(response)
        except Exception as exc:
            raise CuratorInferenceError("parse_error") from exc
        if not content.strip():
            raise CuratorInferenceError("empty_output")
        parsed = _parse_json(content)
        if not isinstance(parsed, Mapping) or not isinstance(parsed.get("operations"), list):
            raise CuratorInferenceError("parse_error")
        return parsed


def _extract_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, Mapping):
        return ""
    direct = response.get("output_text") or response.get("text") or response.get("content")
    if isinstance(direct, str):
        return direct
    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, Mapping):
                message = choice.get("message")
                if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                    return str(message.get("content") or "")
    return ""


def _parse_json(text: str) -> Mapping[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    try:
        value = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(raw[start : end + 1])
        except Exception:
            return None
    return value if isinstance(value, Mapping) else None


__all__ = ["LlmServiceUserProfileAdapter", "CuratorInferenceError"]
