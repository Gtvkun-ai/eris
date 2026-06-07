# -*- coding: utf-8 -*-
"""
tests/test_unit_resilience.py
==============================

Unit tests cho các thành phần resilience — Task 5
--------------------------------------------------

Kiểm tra trực tiếp:
1. `_classify_transport_exception` — bảng tham số
2. `_transient_cooldown_active()` / `_maybe_enter_transient_cooldown()` — ngưỡng/thời gian
3. `_tracked_chat_json()` fast-fail khi transient cooldown active
4. `debug_status()` có các field mới và giữ field cũ

**Validates: Requirements 2.3, 2.4, 2.6, 3.6**
"""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.error

import pytest
import requests
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.private_mind_model_adapter import (
    PrivateMindModelAdapterConfig,
    RuntimePrivateMindModelAdapter,
    _classify_transport_exception,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError với status code cho trước."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }.get(status_code, "Error")
    response.url = "https://fake.api/test"
    return requests.HTTPError(
        f"{status_code} Error: {response.reason}",
        response=response,
    )


def _make_adapter(
    *,
    transient_cooldown_threshold: int = 3,
    transient_cooldown_seconds: float = 60.0,
    transient_max_retries: int = 0,  # mặc định 0 để test không bị retry làm rối
) -> RuntimePrivateMindModelAdapter:
    config = PrivateMindModelAdapterConfig(
        provider="gemini",
        enabled=True,
        api_key="fake-key",
        transient_max_retries=transient_max_retries,
        transient_backoff_base=0.0,
        transient_cooldown_threshold=transient_cooldown_threshold,
        transient_cooldown_seconds=transient_cooldown_seconds,
    )
    return RuntimePrivateMindModelAdapter(config=config)


class FakeClientRaisesHTTPError:
    """Client giả lập — ném HTTPError với status code cho trước."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise make_http_error(self.status_code)


class FakeClientRaisesTimeout:
    """Client giả lập — ném ReadTimeout."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise requests.exceptions.ReadTimeout("read timeout=28.0")


class FakeClientReturnsJson:
    """Client giả lập — trả về JSON hợp lệ."""

    def __init__(self, content: str = '{"claim":"ok","confidence":0.8,"pressure":0.2,"evidence_ids":[]}'):
        self.content = content
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {"choices": [{"message": {"content": self.content}}], "usage": {"total_tokens": 10}}


# ---------------------------------------------------------------------------
# Section 1 — _classify_transport_exception parametrize
# Validates: Requirement 2.6 (phân loại đáng tin cậy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc,expected_kind", [
    # requests.HTTPError với các status khác nhau
    (make_http_error(400), "fixed_config"),
    (make_http_error(401), "fixed_config"),
    (make_http_error(403), "fixed_config"),
    (make_http_error(404), "fixed_config"),
    (make_http_error(429), "transient"),
    (make_http_error(500), "transient"),
    (make_http_error(502), "transient"),
    (make_http_error(503), "transient"),
    (make_http_error(504), "transient"),
    # requests timeout / connection
    (requests.exceptions.ReadTimeout(), "transient"),
    (requests.exceptions.ConnectTimeout(), "transient"),
    (requests.exceptions.ConnectionError(), "transient"),
    (requests.exceptions.Timeout(), "transient"),
    # stdlib
    (socket.timeout(), "transient"),
    (TimeoutError(), "transient"),
    # urllib
    (urllib.error.URLError("network unreachable"), "transient"),
    # Unknown exception — an toàn: không retry vô cớ
    (ValueError("random error"), "fixed_config"),
    (KeyError("missing"), "fixed_config"),
])
def test_classify_transport_exception(exc, expected_kind):
    """
    **Validates: Requirements 2.6**

    _classify_transport_exception phải phân loại đúng cho từng loại exception.
    Phân loại dựa trên *kiểu* và *HTTP status code*, không dựa trên message.
    """
    result = _classify_transport_exception(exc)
    assert result == expected_kind, (
        f"_classify_transport_exception({type(exc).__name__}) trả '{result}', "
        f"expected '{expected_kind}'"
    )


# ---------------------------------------------------------------------------
# Section 2 — Cooldown thresholds và timing
# Validates: Requirement 2.3 (transient streak/cooldown)
# ---------------------------------------------------------------------------

class TestTransientCooldownThresholds:
    """Kiểm tra _maybe_enter_transient_cooldown() và _transient_cooldown_active()."""

    def test_cooldown_not_active_initially(self):
        """Khi mới tạo adapter, transient cooldown không active."""
        adapter = _make_adapter()
        assert adapter._transient_cooldown_active() is False

    def test_cooldown_active_when_cooldown_until_in_future(self):
        """
        **Validates: Requirements 2.3**
        _transient_cooldown_active() trả True khi _transient_cooldown_until ở tương lai.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() + 3600.0
        assert adapter._transient_cooldown_active() is True

    def test_cooldown_not_active_when_cooldown_until_zero(self):
        """
        **Validates: Requirements 2.3**
        _transient_cooldown_active() trả False khi _transient_cooldown_until == 0.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = 0.0
        assert adapter._transient_cooldown_active() is False

    def test_cooldown_not_active_when_cooldown_until_in_past(self):
        """
        **Validates: Requirements 2.3**
        _transient_cooldown_active() trả False khi _transient_cooldown_until đã qua.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() - 1.0  # 1 giây trước
        assert adapter._transient_cooldown_active() is False

    def test_maybe_enter_cooldown_activates_at_threshold(self):
        """
        **Validates: Requirements 2.3**
        _maybe_enter_transient_cooldown() bật cooldown khi streak == threshold.
        """
        adapter = _make_adapter(transient_cooldown_threshold=3, transient_cooldown_seconds=60.0)
        adapter._transient_streak = 3  # đạt đúng ngưỡng

        adapter._maybe_enter_transient_cooldown()

        assert adapter._transient_cooldown_active() is True
        assert adapter._transient_cooldown_until > time.time()

    def test_maybe_enter_cooldown_not_activated_below_threshold(self):
        """
        **Validates: Requirements 2.3**
        _maybe_enter_transient_cooldown() không bật khi streak < threshold.
        """
        adapter = _make_adapter(transient_cooldown_threshold=3)
        adapter._transient_streak = 2  # chưa đến ngưỡng

        adapter._maybe_enter_transient_cooldown()

        assert adapter._transient_cooldown_active() is False
        assert adapter._transient_cooldown_until == 0.0

    def test_maybe_enter_cooldown_not_activated_when_already_active(self):
        """
        Không reset cooldown_until nếu cooldown đang active (idempotent).
        """
        adapter = _make_adapter(transient_cooldown_threshold=3, transient_cooldown_seconds=60.0)
        adapter._transient_streak = 5
        first_until = time.time() + 100.0
        adapter._transient_cooldown_until = first_until  # đã active

        adapter._maybe_enter_transient_cooldown()

        # cooldown_until không được cập nhật lại
        assert adapter._transient_cooldown_until == first_until

    def test_cooldown_duration_respected(self):
        """
        **Validates: Requirements 2.3**
        Cooldown duration được đặt đúng theo config.transient_cooldown_seconds.
        """
        cooldown_seconds = 120.0
        adapter = _make_adapter(transient_cooldown_threshold=1, transient_cooldown_seconds=cooldown_seconds)
        adapter._transient_streak = 1

        before = time.time()
        adapter._maybe_enter_transient_cooldown()
        after = time.time()

        # cooldown_until phải nằm trong [before+cooldown, after+cooldown]
        assert adapter._transient_cooldown_until >= before + cooldown_seconds
        assert adapter._transient_cooldown_until <= after + cooldown_seconds + 0.1

    def test_cooldown_activates_above_threshold(self):
        """
        _maybe_enter_transient_cooldown() cũng bật khi streak > threshold.
        """
        adapter = _make_adapter(transient_cooldown_threshold=3)
        adapter._transient_streak = 5  # vượt ngưỡng

        adapter._maybe_enter_transient_cooldown()

        assert adapter._transient_cooldown_active() is True


# ---------------------------------------------------------------------------
# Section 3 — fast-fail khi transient cooldown active
# Validates: Requirement 2.4 (fast-fail không gọi network, không log lặp)
# ---------------------------------------------------------------------------

class TestTrackedChatJsonFastFail:
    """Kiểm tra _tracked_chat_json() fast-fail khi transient cooldown active."""

    def test_fast_fail_when_cooldown_active_returns_error(self):
        """
        **Validates: Requirements 2.4**

        Khi transient cooldown active, _tracked_chat_json() trả ngay với
        error="transient_cooldown" mà không gọi client.
        """
        adapter = _make_adapter()
        fake_client = FakeClientRaisesTimeout()
        adapter._provider_client = fake_client
        # Đặt cooldown cho tương lai
        adapter._transient_cooldown_until = time.time() + 3600.0

        result = adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        assert result.ok is False
        assert result.error == "transient_cooldown"

    def test_fast_fail_client_not_called(self):
        """
        **Validates: Requirements 2.4**

        Khi transient cooldown active, client KHÔNG được gọi.
        """
        adapter = _make_adapter()
        fake_client = FakeClientRaisesTimeout()
        adapter._provider_client = fake_client
        adapter._transient_cooldown_until = time.time() + 3600.0

        adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        assert fake_client.call_count == 0, (
            f"Client bị gọi {fake_client.call_count} lần trong khi transient cooldown active. "
            "Fast-fail phải trả ngay mà không gọi network."
        )

    def test_fast_fail_calls_counter_not_incremented(self):
        """
        **Validates: Requirements 2.4**

        Khi fast-fail, bộ đếm _calls KHÔNG được tăng (vì không thực sự gọi API).
        """
        adapter = _make_adapter()
        fake_client = FakeClientRaisesTimeout()
        adapter._provider_client = fake_client
        adapter._transient_cooldown_until = time.time() + 3600.0

        calls_before = adapter._calls
        adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )
        calls_after = adapter._calls

        assert calls_after == calls_before, (
            f"_calls tăng từ {calls_before} lên {calls_after} khi fast-fail. "
            "Fast-fail không nên tính là một lần gọi API."
        )

    def test_fast_fail_error_kind_is_transient(self):
        """
        **Validates: Requirements 2.4, 2.6**

        Kết quả fast-fail phải có error_kind='transient'.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() + 3600.0

        result = adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        assert result.error_kind == "transient"

    def test_fast_fail_sets_last_error(self):
        """
        **Validates: Requirements 2.4**

        Fast-fail cập nhật _last_error thành 'transient_cooldown'.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() + 3600.0

        adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        assert adapter._last_error == "transient_cooldown"

    def test_evaluate_fragment_returns_none_when_cooldown_active(self):
        """
        **Validates: Requirements 2.4**

        evaluate_fragment() trả None khi transient cooldown active,
        và KHÔNG log warning lặp.
        """

        class FakeLogger:
            def __init__(self):
                self.warnings = []
            def warning(self, msg, *args):
                self.warnings.append((msg, args))

        logger = FakeLogger()
        adapter = _make_adapter()
        adapter.logger = logger
        adapter._transient_cooldown_until = time.time() + 3600.0
        from cortex.private_mind.contracts import EvidenceDossier
        dossier = EvidenceDossier(dossier_id="test.fast.fail")

        result = adapter.evaluate_fragment("intent_evaluator", dossier)

        assert result is None
        # Không được log warning khi đang trong transient cooldown
        assert all("transient_cooldown" not in str(w) for w in logger.warnings), (
            f"Log lặp khi transient cooldown active: {logger.warnings}"
        )


# ---------------------------------------------------------------------------
# Section 4 — debug_status() fields
# Validates: Requirement 2.6, 3.6
# ---------------------------------------------------------------------------

class TestDebugStatusFields:
    """Kiểm tra debug_status() có đủ các field mới và giữ các field cũ."""

    NEW_FIELDS = {"degraded_cause", "transient_streak", "transient_cooldown_until"}
    LEGACY_FIELDS = {
        "api_degraded", "calls", "ok_calls", "failed_calls",
        "invalid_json_streak", "json_cooldown_until", "last_error", "usage",
    }

    def test_debug_status_has_new_fields(self):
        """
        **Validates: Requirements 2.6**

        debug_status() phải có các field mới: degraded_cause, transient_streak,
        transient_cooldown_until.
        """
        adapter = _make_adapter()
        status = adapter.debug_status()

        for field_name in self.NEW_FIELDS:
            assert field_name in status, (
                f"debug_status() thiếu field mới '{field_name}'. "
                f"Keys hiện có: {sorted(status.keys())}"
            )

    def test_debug_status_preserves_legacy_fields(self):
        """
        **Validates: Requirements 3.6**

        debug_status() phải giữ nguyên toàn bộ các field cũ.
        """
        adapter = _make_adapter()
        status = adapter.debug_status()

        for field_name in self.LEGACY_FIELDS:
            assert field_name in status, (
                f"debug_status() bị mất field cũ '{field_name}'. "
                f"Keys hiện có: {sorted(status.keys())}"
            )

    def test_debug_status_api_degraded_true_when_transient_cooldown(self):
        """
        **Validates: Requirements 2.6**

        api_degraded phải là True khi transient cooldown active.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() + 3600.0

        status = adapter.debug_status()

        assert status["api_degraded"] is True, (
            f"api_degraded phải là True khi transient cooldown active, nhưng là {status['api_degraded']}"
        )

    def test_debug_status_degraded_cause_transient_when_cooldown_active(self):
        """
        **Validates: Requirements 2.6**

        degraded_cause phải là 'transient' khi transient cooldown active.
        """
        adapter = _make_adapter()
        adapter._transient_cooldown_until = time.time() + 3600.0

        status = adapter.debug_status()

        assert status["degraded_cause"] == "transient", (
            f"degraded_cause phải là 'transient' khi cooldown active, nhưng là '{status['degraded_cause']}'"
        )

    def test_debug_status_transient_streak_reflects_state(self):
        """
        **Validates: Requirements 2.6**

        transient_streak phải phản ánh đúng giá trị _transient_streak.
        """
        adapter = _make_adapter()
        adapter._transient_streak = 5

        status = adapter.debug_status()

        assert status["transient_streak"] == 5

    def test_debug_status_transient_cooldown_until_reflects_state(self):
        """
        **Validates: Requirements 2.6**

        transient_cooldown_until phải phản ánh _transient_cooldown_until (rounded).
        """
        adapter = _make_adapter()
        future = time.time() + 3600.0
        adapter._transient_cooldown_until = future

        status = adapter.debug_status()

        assert abs(status["transient_cooldown_until"] - future) < 0.01, (
            f"transient_cooldown_until={status['transient_cooldown_until']!r} "
            f"không khớp với expected ~{future}"
        )

    def test_debug_status_degraded_cause_empty_when_no_error(self):
        """
        **Validates: Requirements 2.6**

        degraded_cause phải là '' khi không có lỗi nào.
        """
        adapter = _make_adapter()

        status = adapter.debug_status()

        assert status["degraded_cause"] == "", (
            f"degraded_cause phải là '' khi adapter không có lỗi, nhưng là '{status['degraded_cause']}'"
        )

    def test_debug_status_api_degraded_false_when_no_error(self):
        """
        **Validates: Requirements 3.6**

        api_degraded phải là False khi adapter không có lỗi nào và không có cooldown.
        """
        adapter = _make_adapter()

        status = adapter.debug_status()

        assert status["api_degraded"] is False

    def test_debug_status_usage_field_has_subkeys(self):
        """
        **Validates: Requirements 3.6**

        Field 'usage' phải là dict với các subkey: prompt_tokens, completion_tokens,
        total_tokens.
        """
        adapter = _make_adapter()
        status = adapter.debug_status()

        usage = status.get("usage")
        assert isinstance(usage, dict), f"'usage' phải là dict, nhưng là {type(usage)}"
        for subkey in ("prompt_tokens", "completion_tokens", "total_tokens"):
            assert subkey in usage, f"'usage' thiếu subkey '{subkey}'"

    def test_debug_status_degraded_cause_transient_after_transient_error(self):
        """
        **Validates: Requirements 2.6**

        Sau khi gặp transient error, degraded_cause phải là 'transient'.
        """
        adapter = _make_adapter(transient_max_retries=0)
        fake_client = FakeClientRaisesHTTPError(500)
        adapter._provider_client = fake_client

        # Gọi và chờ lỗi transient
        adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        status = adapter.debug_status()
        assert status["degraded_cause"] == "transient", (
            f"Sau lỗi HTTP 500, degraded_cause phải là 'transient', "
            f"nhưng là '{status['degraded_cause']}'"
        )

    def test_debug_status_degraded_cause_invalid_json_after_json_error(self):
        """
        **Validates: Requirements 2.6**

        Sau khi gặp invalid_json, degraded_cause phải là 'invalid_json'.
        """
        adapter = _make_adapter(transient_max_retries=0)

        class FakeClientReturnsInvalidJson:
            def create_chat_completion(self, **kwargs):
                return {"choices": [{"message": {"content": "not valid json at all"}}], "usage": {}}

        adapter._provider_client = FakeClientReturnsInvalidJson()

        # Gọi để trigger invalid_json (hot-retry cũng fail → lưu invalid_json)
        adapter._tracked_chat_json(
            [{"role": "user", "content": "test"}],
            max_tokens=128,
        )

        status = adapter.debug_status()
        assert status["degraded_cause"] == "invalid_json", (
            f"Sau lỗi invalid_json, degraded_cause phải là 'invalid_json', "
            f"nhưng là '{status['degraded_cause']}'"
        )
