from __future__ import annotations

"""Phân loại lỗi provider dùng chung cho LLM/TTS/localizer."""

from enum import StrEnum
from typing import Any


class ProviderErrorKind(StrEnum):
    RATE_LIMIT = "rate_limit"
    KEY_REVOKED = "key_revoked"
    PROJECT_PERMISSION = "project_permission"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE_SHAPE = "invalid_response_shape"
    TRANSIENT_SERVER = "transient_server"
    UNKNOWN = "unknown"


def classify_provider_error(exc: Exception | str, *, status_code: int | None = None) -> ProviderErrorKind:
    text = _error_text(exc).lower()
    code = status_code if status_code is not None else _status_from_exception(exc)
    if code == 429 or "resource_exhausted" in text or "quota" in text and "exceeded" in text:
        return ProviderErrorKind.RATE_LIMIT
    if "api key was reported as leaked" in text or "reported as leaked" in text or "api_key_invalid" in text:
        return ProviderErrorKind.KEY_REVOKED
    if code in (401, 403):
        if any(m in text for m in ("permission_denied", "permission denied", "api has not been used", "disabled", "not enabled", "forbidden")):
            return ProviderErrorKind.PROJECT_PERMISSION
        return ProviderErrorKind.KEY_REVOKED
    if any(marker in text for marker in ("audio parts hợp lệ", "không trả audio parts", "nonetype") ):
        return ProviderErrorKind.INVALID_RESPONSE_SHAPE
    if code in (500, 502, 503, 504) or "unavailable" in text:
        return ProviderErrorKind.TRANSIENT_SERVER
    if code is not None and 400 <= code < 500:
        return ProviderErrorKind.INVALID_REQUEST
    return ProviderErrorKind.UNKNOWN


def _status_from_exception(exc: Any) -> int | None:
    for attr in ("code", "status_code", "status"):
        try:
            value = getattr(exc, attr, None)
            if value is not None:
                return int(value)
        except (AttributeError, TypeError, ValueError, OverflowError):
            pass
    response = getattr(exc, "response", None)
    try:
        value = getattr(response, "status_code", None)
        if value is not None:
            return int(value)
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    return None


def _error_text(exc: Any) -> str:
    parts = [str(exc or "")]
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(str(response.text or ""))
        except (AttributeError, TypeError, ValueError, OverflowError):
            pass
    return " ".join(parts)
