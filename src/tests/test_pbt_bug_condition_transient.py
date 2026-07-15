# -*- coding: utf-8 -*-
"""
tests/test_pbt_bug_condition_transient.py
=========================================

Exploratory Bug Condition Tests — Task 1
-----------------------------------------

Mục đích: làm lộ bug condition — transient transport error (HTTP 5xx/429,
ReadTimeout/ConnectTimeout/ConnectionError) KHÔNG được retry và KHÔNG có
circuit-breaker trong RuntimePrivateMindModelAdapter TRƯỚC KHI vá.

CÁC TEST 1, 2, 3 PHẢI FAIL trên code chưa vá — thất bại chứng minh bug tồn tại.
Test 4 PHẢI PASS cả trước và sau khi vá (edge-case preservation: HTTP 400).

**Validates: Requirements 1.1, 1.2, 1.3**
"""

from __future__ import annotations

import os
import sys

import pytest
import requests
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.private_mind_model_adapter import PrivateMindModelAdapterConfig, RuntimePrivateMindModelAdapter
from cortex.private_mind.contracts import EvidenceDossier


# ---------------------------------------------------------------------------
# Helpers — Fake provider clients
# ---------------------------------------------------------------------------

def _make_http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError with a given HTTP status code."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = {
        400: "Bad Request",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }.get(status_code, "Error")
    response.url = "https://fake.api/generateContent"
    err = requests.HTTPError(
        f"{status_code} Error: {response.reason} for url: {response.url}",
        response=response,
    )
    return err


class FakeProviderClientHTTP500:
    """Always raises HTTP 500 — records how many times it was called."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(500)


class FakeProviderClientReadTimeout:
    """Always raises ReadTimeout — records how many times it was called."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise requests.exceptions.ReadTimeout("read timeout=28.0")


class FakeProviderClientHTTP503:
    """Always raises HTTP 503 — records how many times it was called."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(503)


class FakeProviderClientHTTP400:
    """Always raises HTTP 400 — records how many times it was called."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(400)


def _adapter_with_fake_client(fake_client) -> RuntimePrivateMindModelAdapter:
    """Create adapter with provider=gemini, enabled=True, and inject a fake client."""
    config = PrivateMindModelAdapterConfig(
        provider="gemini",
        enabled=True,
        api_key="fake-key-for-testing",
    )
    adapter = RuntimePrivateMindModelAdapter(config=config, llm_service=None, logger=None)
    adapter._provider_client = fake_client
    return adapter


def _simple_dossier() -> EvidenceDossier:
    return EvidenceDossier(dossier_id="test-dossier-bug-condition")


# ---------------------------------------------------------------------------
# Test 1 — HTTP 500 không retry
# PHẢI FAIL trên code chưa vá (client chỉ gọi 1 lần; expected > 1)
# ---------------------------------------------------------------------------

def test_http_500_should_retry_but_does_not_on_unpatched_code():
    """
    **Validates: Requirements 1.1**

    Khi evaluate_fragment gặp HTTP 500, adapter PHẢI thử lại (retry) ít nhất 1 lần
    (tức là gọi client > 1 lần).

    Code CHƯA vá chỉ gọi 1 lần rồi trả None ngay → test này FAIL.
    Sau khi vá, client được gọi >= 2 lần → test PASS.
    """
    fake = FakeProviderClientHTTP500()
    adapter = _adapter_with_fake_client(fake)
    dossier = _simple_dossier()

    result = adapter.evaluate_fragment("intent_evaluator", dossier)

    # Kết quả phải là None (không thành công sau retry)
    assert result is None, f"Expected None but got {result!r}"

    # BUG CONDITION: code chưa vá chỉ gọi đúng 1 lần
    # Sau khi vá, phải gọi > 1 lần (retry có giới hạn)
    assert fake.call_count > 1, (
        f"BUG DETECTED: HTTP 500 không được retry. "
        f"Client chỉ được gọi {fake.call_count} lần (expected > 1). "
        f"Counterexample: adapter gọi client đúng {fake.call_count} lần khi gặp HTTP 500, "
        f"chứng tỏ không có retry. Mỗi tick chịu độ trễ ~28s mà không có cơ chế phục hồi."
    )


# ---------------------------------------------------------------------------
# Test 2 — ReadTimeout không retry
# PHẢI FAIL trên code chưa vá (client chỉ gọi 1 lần; expected > 1)
# ---------------------------------------------------------------------------

def test_read_timeout_should_retry_but_does_not_on_unpatched_code():
    """
    **Validates: Requirements 1.2**

    Khi synthesize_judgment bị ReadTimeout, adapter PHẢI thử lại ít nhất 1 lần
    (tức là gọi client > 1 lần).

    Code CHƯA vá không retry → test này FAIL.
    Sau khi vá, client được gọi >= 2 lần → test PASS.
    """
    fake = FakeProviderClientReadTimeout()
    adapter = _adapter_with_fake_client(fake)
    dossier = _simple_dossier()

    # synthesize_judgment cần fragments; dùng tuple rỗng — chỉ quan tâm behavior mạng
    result = adapter.synthesize_judgment(dossier, fragments=())

    assert result is None, f"Expected None but got {result!r}"

    # BUG CONDITION: code chưa vá chỉ gọi đúng 1 lần
    assert fake.call_count > 1, (
        f"BUG DETECTED: ReadTimeout không được retry. "
        f"Client chỉ được gọi {fake.call_count} lần (expected > 1). "
        f"Counterexample: ReadTimeout(read timeout=28.0) gây ra None ngay sau {fake.call_count} lần gọi, "
        f"không có retry/backoff. Mỗi tick bị timeout đầy đủ ~28s."
    )


# ---------------------------------------------------------------------------
# Test 3 — Không có circuit-breaker sau ngưỡng lỗi liên tiếp
# PHẢI FAIL trên code chưa vá (không có _transient_cooldown_active)
# ---------------------------------------------------------------------------

def test_no_circuit_breaker_after_repeated_503_on_unpatched_code():
    """
    **Validates: Requirements 1.3**

    Sau khi gọi adapter >= 3 lần liên tiếp đều gặp HTTP 503, adapter PHẢI bật
    transient cooldown (circuit-breaker). Biểu hiện:
    - adapter._transient_cooldown_active() trả True, HOẶC
    - debug_status() có key 'transient_streak' >= 3, HOẶC
    - debug_status() có key 'transient_cooldown_until' > 0

    Code CHƯA vá không có cơ chế này → test này FAIL.
    Sau khi vá, circuit-breaker bật đúng ngưỡng → test PASS.
    """
    fake = FakeProviderClientHTTP503()
    adapter = _adapter_with_fake_client(fake)
    dossier = _simple_dossier()

    # Gọi liên tiếp đủ để vượt ngưỡng circuit-breaker (ngưỡng mặc định = 3)
    threshold_calls = 4
    for _ in range(threshold_calls):
        adapter.evaluate_fragment("intent_evaluator", dossier)

    status = adapter.debug_status()

    # Kiểm tra 1: _transient_cooldown_active() method tồn tại và trả True
    has_cooldown_method = hasattr(adapter, "_transient_cooldown_active")
    cooldown_active = has_cooldown_method and adapter._transient_cooldown_active()

    # Kiểm tra 2: debug_status() có transient_streak
    has_transient_streak = "transient_streak" in status
    transient_streak_ge_threshold = has_transient_streak and status["transient_streak"] >= 3

    # Kiểm tra 3: debug_status() có transient_cooldown_until > 0
    has_cooldown_until = "transient_cooldown_until" in status
    cooldown_until_set = has_cooldown_until and status["transient_cooldown_until"] > 0

    # Ít nhất một trong các dấu hiệu circuit-breaker phải có
    circuit_breaker_active = cooldown_active or transient_streak_ge_threshold or cooldown_until_set

    assert circuit_breaker_active, (
        f"BUG DETECTED: Không có circuit-breaker sau {threshold_calls} lần HTTP 503 liên tiếp. "
        f"Counterexample: "
        f"_transient_cooldown_active exists={has_cooldown_method}, active={cooldown_active}; "
        f"transient_streak in debug_status={has_transient_streak}, value={status.get('transient_streak')}; "
        f"transient_cooldown_until in debug_status={has_cooldown_until}, value={status.get('transient_cooldown_until')}; "
        f"debug_status keys={sorted(status.keys())}. "
        f"Hệ quả: mỗi tick vẫn gọi API và chịu timeout ~28s, không có fast-fail."
    )


# ---------------------------------------------------------------------------
# Test 4 — HTTP 400 KHÔNG retry (edge case preservation)
# PHẢI PASS cả trước và sau khi vá
# ---------------------------------------------------------------------------

def test_http_400_should_not_retry_fixed_config_error():
    """
    **Validates: Requirements 3.3 (Preservation)**

    HTTP 400 là fixed-config error — KHÔNG được retry.
    Client phải được gọi đúng 1 lần, adapter trả None.

    Test này PASS cả trên code chưa vá và sau khi vá.
    Đây là edge case preservation: bản vá KHÔNG được retry 4xx không phải 429.
    """
    fake = FakeProviderClientHTTP400()
    adapter = _adapter_with_fake_client(fake)
    dossier = _simple_dossier()

    result = adapter.evaluate_fragment("intent_evaluator", dossier)

    assert result is None, f"Expected None for HTTP 400 but got {result!r}"

    # HTTP 400 là lỗi cấu hình cố định — KHÔNG được retry
    assert fake.call_count == 1, (
        f"REGRESSION: HTTP 400 không được retry nhưng client bị gọi {fake.call_count} lần. "
        f"Fixed-config error (4xx không phải 429) phải trả None ngay sau 1 lần gọi."
    )
