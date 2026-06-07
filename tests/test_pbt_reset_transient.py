# -*- coding: utf-8 -*-
"""
tests/test_pbt_reset_transient.py
==================================

Property 3: Reset — Thành công xoá trạng thái transient degraded
------------------------------------------------------------------

Mục đích: xác nhận rằng sau một chuỗi transient error, một lần gọi thành công
PHẢI reset hoàn toàn trạng thái transient degraded:
- `_transient_streak == 0`
- `_transient_cooldown_until == 0.0`
- `debug_status()["degraded_cause"] != "transient"`
- `debug_status()["transient_streak"] == 0`

Test 1 — Reset sau chuỗi transient dưới ngưỡng (không bật cooldown)
Test 2 — Reset sau khi cooldown hết hạn và thành công
Test 3 — Property-based: sinh ngẫu nhiên k lỗi transient (k < threshold) rồi 1 success

**Validates: Requirements 2.5**
"""

from __future__ import annotations

import json
import os
import sys
import time
from unittest.mock import patch

import pytest
import requests
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from runtime.private_mind_model_adapter import (
    PrivateMindModelAdapterConfig,
    RuntimePrivateMindModelAdapter,
)
from cortex.private_mind.contracts import EvidenceDossier


# ---------------------------------------------------------------------------
# Helpers — Fake provider clients
# ---------------------------------------------------------------------------

def _make_http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError with a given HTTP status code."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = {
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }.get(status_code, "Server Error")
    response.url = "https://fake.api/generateContent"
    err = requests.HTTPError(
        f"{status_code} Error: {response.reason} for url: {response.url}",
        response=response,
    )
    return err


class FakeClientTransientThenSuccess:
    """Raises transient HTTP error for the first N calls, then returns valid JSON."""

    def __init__(self, fail_times: int, status_code: int = 503, success_payload: dict | None = None):
        self.call_count = 0
        self.fail_times = fail_times
        self.status_code = status_code
        self.success_payload = success_payload or {
            "claim": "test claim",
            "confidence": 0.8,
            "pressure": 0.2,
            "evidence_ids": [],
        }

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise _make_http_error(self.status_code)
        # Trả JSON hợp lệ
        return {
            "choices": [{"message": {"content": json.dumps(self.success_payload)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }


class FakeClientAlwaysTransient:
    """Always raises HTTP 503 — dùng để build up streak."""

    def __init__(self, status_code: int = 503):
        self.call_count = 0
        self.status_code = status_code

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(self.status_code)


class FakeClientAlwaysSuccess:
    """Always returns valid JSON."""

    def __init__(self, payload: dict | None = None):
        self.call_count = 0
        self.payload = payload or {
            "claim": "success claim",
            "confidence": 0.9,
            "pressure": 0.1,
            "evidence_ids": [],
        }

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {
            "choices": [{"message": {"content": json.dumps(self.payload)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }


class FakeClientMixed:
    """Trả lỗi transient cho danh sách đã cho, sau đó trả JSON thành công."""

    def __init__(self, errors: list, success_payload: dict | None = None):
        """
        errors: list of exceptions to raise in order (after exhausting, return success)
        """
        self.call_count = 0
        self.errors = list(errors)
        self.success_payload = success_payload or {
            "claim": "mixed success",
            "confidence": 0.7,
            "pressure": 0.3,
            "evidence_ids": [],
        }

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        if self.errors:
            exc = self.errors.pop(0)
            raise exc
        return {
            "choices": [{"message": {"content": json.dumps(self.success_payload)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 15, "total_tokens": 20},
        }


def _adapter_with_fake_client(
    fake_client,
    transient_max_retries: int = 0,
    transient_cooldown_threshold: int = 3,
    transient_cooldown_seconds: float = 60.0,
) -> RuntimePrivateMindModelAdapter:
    """
    Tạo adapter với provider=gemini, enabled=True, inject fake client.

    transient_max_retries=0 để mỗi lần gọi _tracked_chat_json() chỉ gọi
    client đúng 1 lần — dễ kiểm soát streak mà không cần patch time.sleep.
    """
    config = PrivateMindModelAdapterConfig(
        provider="gemini",
        enabled=True,
        api_key="fake-key-for-testing",
        transient_max_retries=transient_max_retries,
        transient_cooldown_threshold=transient_cooldown_threshold,
        transient_cooldown_seconds=transient_cooldown_seconds,
    )
    adapter = RuntimePrivateMindModelAdapter(config=config, llm_service=None, logger=None)
    adapter._provider_client = fake_client
    return adapter


def _simple_messages() -> list[dict[str, str]]:
    return [{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "{}"}]


def _simple_dossier() -> EvidenceDossier:
    return EvidenceDossier(dossier_id="test-reset-property3")


# ---------------------------------------------------------------------------
# Test 1 — Reset sau chuỗi transient dưới ngưỡng (Req 2.5)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_errors,status_code", [
    (1, 503),
    (2, 500),
    (2, 429),
])
def test_success_resets_transient_streak_below_threshold(n_errors, status_code):
    """
    **Validates: Requirements 2.5**

    Gọi adapter N lần với HTTP transient error (N < threshold=3 để không bật cooldown),
    sau đó gọi 1 lần thành công.

    Assert:
    - _transient_streak == 0
    - _transient_cooldown_until == 0.0
    - debug_status()["degraded_cause"] != "transient"
    - debug_status()["transient_streak"] == 0
    """
    # transient_max_retries=0: mỗi lần _tracked_chat_json gọi client đúng 1 lần
    # → N lần fail sẽ làm streak = N; threshold=3 nên N<3 không bật cooldown
    with patch("time.sleep"):
        # Fake client: fail n_errors lần, rồi thành công
        fake = FakeClientTransientThenSuccess(
            fail_times=n_errors,
            status_code=status_code,
        )
        adapter = _adapter_with_fake_client(
            fake,
            transient_max_retries=0,
            transient_cooldown_threshold=3,
        )

        # Gọi N lần với transient error
        for i in range(n_errors):
            result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
            assert result.ok is False, f"Round {i+1}: expected ok=False for transient error"
            assert result.error_kind == "transient", (
                f"Round {i+1}: expected error_kind='transient', got {result.error_kind!r}"
            )

        # Xác nhận streak đã tăng lên (nhưng chưa bật cooldown)
        status_before = adapter.debug_status()
        assert status_before["transient_streak"] == n_errors, (
            f"Expected transient_streak={n_errors} before success, "
            f"got {status_before['transient_streak']}"
        )
        assert status_before["transient_cooldown_until"] == 0.0, (
            "Cooldown should NOT be active yet (streak < threshold=3)"
        )

        # Gọi 1 lần thành công — reset phải xảy ra
        success_result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
        assert success_result.ok is True, (
            f"Expected ok=True for success call, got ok={success_result.ok}, "
            f"error={success_result.error!r}"
        )

    # Assert: trạng thái transient đã được reset hoàn toàn
    assert adapter._transient_streak == 0, (
        f"Expected _transient_streak=0 after success, got {adapter._transient_streak}"
    )
    assert adapter._transient_cooldown_until == 0.0, (
        f"Expected _transient_cooldown_until=0.0 after success, "
        f"got {adapter._transient_cooldown_until}"
    )

    status = adapter.debug_status()
    assert status["transient_streak"] == 0, (
        f"Expected debug_status transient_streak=0, got {status['transient_streak']}"
    )
    assert status["degraded_cause"] != "transient", (
        f"Expected degraded_cause != 'transient' after success reset, "
        f"got degraded_cause={status['degraded_cause']!r}"
    )
    assert status["transient_cooldown_until"] == 0.0, (
        f"Expected transient_cooldown_until=0.0 in debug_status, "
        f"got {status['transient_cooldown_until']}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Reset sau khi cooldown hết hạn và thành công (Req 2.5)
# ---------------------------------------------------------------------------

def test_success_after_expired_cooldown_resets_state():
    """
    **Validates: Requirements 2.5**

    Kịch bản:
    1. Tạo transient streak >= threshold (=3) để bật cooldown.
    2. Giả lập cooldown hết hạn (set `adapter._transient_cooldown_until = time.time() - 1`).
    3. Gọi 1 lần thành công.

    Assert:
    - cooldown đã reset (_transient_cooldown_until == 0.0)
    - transient_streak == 0
    - degraded_cause == ""
    """
    with patch("time.sleep"):
        # Dùng client luôn fail để build streak đến threshold
        fail_client = FakeClientAlwaysTransient(status_code=503)
        adapter = _adapter_with_fake_client(
            fail_client,
            transient_max_retries=0,
            transient_cooldown_threshold=3,
            transient_cooldown_seconds=60.0,
        )

        # Gọi 3 lần để streak = 3 và kích hoạt cooldown
        for i in range(3):
            result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
            assert result.ok is False

        # Xác nhận cooldown đã bật
        status_with_cooldown = adapter.debug_status()
        assert status_with_cooldown["transient_streak"] >= 3, (
            f"Expected streak >= 3 after 3 failures, got {status_with_cooldown['transient_streak']}"
        )
        assert status_with_cooldown["transient_cooldown_until"] > 0, (
            "Expected transient_cooldown_until > 0 after streak >= threshold"
        )
        assert status_with_cooldown["degraded_cause"] == "transient", (
            f"Expected degraded_cause='transient' when cooldown active, "
            f"got {status_with_cooldown['degraded_cause']!r}"
        )

        # Giả lập cooldown hết hạn: đặt thời điểm quá khứ
        adapter._transient_cooldown_until = time.time() - 1.0

        # Thay client bằng client thành công
        success_client = FakeClientAlwaysSuccess()
        adapter._provider_client = success_client

        # Gọi 1 lần thành công
        success_result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    assert success_result.ok is True, (
        f"Expected ok=True for success call after expired cooldown, "
        f"got ok={success_result.ok}, error={success_result.error!r}"
    )

    # Assert: trạng thái transient đã reset hoàn toàn
    assert adapter._transient_streak == 0, (
        f"Expected _transient_streak=0 after success, got {adapter._transient_streak}"
    )
    assert adapter._transient_cooldown_until == 0.0, (
        f"Expected _transient_cooldown_until=0.0 after success, "
        f"got {adapter._transient_cooldown_until}"
    )

    status = adapter.debug_status()
    assert status["transient_streak"] == 0, (
        f"Expected transient_streak=0 in debug_status, got {status['transient_streak']}"
    )
    assert status["transient_cooldown_until"] == 0.0, (
        f"Expected transient_cooldown_until=0.0 in debug_status, "
        f"got {status['transient_cooldown_until']}"
    )
    assert status["degraded_cause"] == "", (
        f"Expected degraded_cause='' after full reset, got {status['degraded_cause']!r}"
    )
    assert status["api_degraded"] is False, (
        f"Expected api_degraded=False after success reset, got {status['api_degraded']}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Property-based: sinh ngẫu nhiên k lỗi transient rồi 1 success (Req 2.5)
# ---------------------------------------------------------------------------

# Chiến lược sinh k ∈ {1, 2} (dưới ngưỡng mặc định 3)
_k_errors_st = st.integers(min_value=1, max_value=2)

# Chiến lược sinh loại lỗi transient
_transient_error_st = st.sampled_from([
    500, 502, 503, 504, 429,
])

# Chiến lược sinh JSON payload hợp lệ cho lần thành công
_success_payload_st = st.fixed_dictionaries({
    "claim": st.text(min_size=1, max_size=60),
    "confidence": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "pressure": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "evidence_ids": st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=2),
})


@given(
    k=_k_errors_st,
    status_code=_transient_error_st,
    success_payload=_success_payload_st,
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_property_k_transient_errors_then_success_resets_state(k, status_code, success_payload):
    """
    **Validates: Requirements 2.5**

    Property 3 (Reset): sinh ngẫu nhiên k ∈ {1, 2} lỗi transient (k < threshold=3)
    rồi 1 lần gọi thành công với JSON hợp lệ.

    Assert sau success:
    - transient_streak == 0
    - transient_cooldown_until == 0.0
    - degraded_cause == ""
    - debug_status()["transient_streak"] == 0
    """
    with patch("time.sleep"):
        # Xây dựng danh sách errors: k lần HTTP 5xx/429
        errors = [_make_http_error(status_code) for _ in range(k)]

        # Fake client: k lỗi transient, sau đó thành công với payload ngẫu nhiên
        fake = FakeClientMixed(errors=errors, success_payload=success_payload)

        adapter = _adapter_with_fake_client(
            fake,
            transient_max_retries=0,   # không retry để kiểm soát chính xác streak
            transient_cooldown_threshold=3,  # ngưỡng > k nên không bật cooldown
        )

        # k lần gọi với transient error
        for i in range(k):
            result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
            assert result.ok is False, (
                f"Expected ok=False for transient error #{i+1} (HTTP {status_code})"
            )
            assert result.error_kind == "transient", (
                f"Expected error_kind='transient' for HTTP {status_code}, "
                f"got {result.error_kind!r}"
            )

        # Xác nhận streak đã tích lũy đúng
        assert adapter._transient_streak == k, (
            f"Expected _transient_streak={k} before success, got {adapter._transient_streak}"
        )

        # 1 lần gọi thành công
        success_result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    # Sau success: tất cả trạng thái transient phải reset
    assert success_result.ok is True, (
        f"Expected ok=True for success call, got ok={success_result.ok}, "
        f"error={success_result.error!r}"
    )

    assert adapter._transient_streak == 0, (
        f"Property 3 violated: _transient_streak != 0 after success. "
        f"k={k}, status={status_code}, got streak={adapter._transient_streak}"
    )
    assert adapter._transient_cooldown_until == 0.0, (
        f"Property 3 violated: _transient_cooldown_until != 0.0 after success. "
        f"k={k}, status={status_code}, got cooldown_until={adapter._transient_cooldown_until}"
    )

    status = adapter.debug_status()
    assert status["transient_streak"] == 0, (
        f"Property 3 violated: debug_status transient_streak != 0. "
        f"k={k}, status={status_code}, got {status['transient_streak']}"
    )
    assert status["degraded_cause"] == "", (
        f"Property 3 violated: degraded_cause != '' after success reset. "
        f"k={k}, status={status_code}, got {status['degraded_cause']!r}"
    )
