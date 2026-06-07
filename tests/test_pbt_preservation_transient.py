# -*- coding: utf-8 -*-
"""
tests/test_pbt_preservation_transient.py
=========================================

Preservation Checking Tests — Task 2
--------------------------------------

Mục đích: chốt lại hành vi baseline cho các input KHÔNG thỏa bug condition
(không phải transient transport error) bằng property-based tests (hypothesis).

Theo phương pháp **observation-first**: quan sát hành vi trên code CHƯA vá
rồi chốt lại bằng property test. Tất cả các test này PHẢI PASS trên code
chưa vá — xác nhận baseline cần bảo toàn. Các test này sẽ chạy lại sau
khi vá (task 3.12) để xác nhận không có regression.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import requests
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

from runtime.private_mind_model_adapter import (
    PrivateMindModelAdapterConfig,
    RuntimePrivateMindModelAdapter,
)
from cortex.private_mind.contracts import EvidenceDossier


# ---------------------------------------------------------------------------
# Helpers — Fake clients
# ---------------------------------------------------------------------------

class FakeClientValidJSON:
    """Always returns a valid JSON payload as the LLM response."""

    def __init__(self, json_payload: dict):
        self.call_count = 0
        self.payload = json_payload

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {
            "choices": [{"message": {"content": json.dumps(self.payload)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }


class FakeClientNonJSON:
    """Always returns non-JSON content."""

    def __init__(self, content: str = "This is not JSON"):
        self.call_count = 0
        self.content = content

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {
            "choices": [{"message": {"content": self.content}}],
            "usage": {"total_tokens": 5},
        }


def _make_http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError with a given HTTP status code."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
    }.get(status_code, "Client Error")
    response.url = "https://fake.api/generateContent"
    err = requests.HTTPError(
        f"{status_code} Error: {response.reason} for url: {response.url}",
        response=response,
    )
    return err


class FakeClientHTTP4xx:
    """Always raises an HTTP 4xx error (non-429 — fixed-config error)."""

    def __init__(self, status_code: int):
        self.call_count = 0
        self.status_code = status_code

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(self.status_code)


def _adapter_with_provider_client(fake_client) -> RuntimePrivateMindModelAdapter:
    """Create adapter with provider=gemini and inject a fake _provider_client."""
    config = PrivateMindModelAdapterConfig(
        provider="gemini",
        enabled=True,
        api_key="fake-key-for-testing",
    )
    adapter = RuntimePrivateMindModelAdapter(config=config, llm_service=None, logger=None)
    adapter._provider_client = fake_client
    return adapter


def _adapter_with_llm_service(fake_service) -> RuntimePrivateMindModelAdapter:
    """Create adapter with injected llm_service (provider=llama_server path bypassed)."""
    config = PrivateMindModelAdapterConfig(
        provider="llama_server",
        enabled=True,
    )
    adapter = RuntimePrivateMindModelAdapter(config=config, llm_service=fake_service, logger=None)
    return adapter


def _simple_messages() -> list[dict[str, str]]:
    return [{"role": "system", "content": "Return JSON"}]


# ---------------------------------------------------------------------------
# Strategies — hypothesis generators
# ---------------------------------------------------------------------------

# Sinh JSON payload hợp lệ giả lập output đánh giá fragment
_fragment_payload_st = st.fixed_dictionaries({
    "claim": st.text(min_size=1, max_size=80),
    "confidence": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "pressure": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "evidence_ids": st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=3),
})

# Sinh JSON payload hợp lệ giả lập output tổng hợp judgment
_judgment_payload_st = st.fixed_dictionaries({
    "dominant_judgment": st.text(min_size=1, max_size=120),
    "confidence": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "pressure": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "evidence_ids": st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=3),
})

# Sinh nội dung không-JSON (prose, markdown, số, ký tự ngẫu nhiên)
_non_json_content_st = st.one_of(
    st.text(min_size=1, max_size=200).filter(lambda s: not s.strip().startswith("{")),
    st.just("This is plain prose and not JSON at all."),
    st.just("# Markdown heading\nSome bullet:\n- item 1\n- item 2"),
    st.just("```python\nprint('hello')\n```"),
    st.just("   "),
    st.just("Sure! Here is the analysis: The user seems distressed."),
)

# Sinh mã HTTP 4xx ngoài 429 — fixed-config errors
_fixed_config_4xx_st = st.sampled_from([400, 401, 403, 404])


# ---------------------------------------------------------------------------
# Test 1 — JSON hợp lệ vẫn được parse đúng (Req 3.1)
# PHẢI PASS trên code chưa vá
# ---------------------------------------------------------------------------

@given(payload=_fragment_payload_st)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_valid_json_parsed_correctly_preservation(payload):
    """
    **Validates: Requirements 3.1**

    Khi API trả JSON hợp lệ, adapter PHẢI:
    - Trả mapping (không None)
    - Bộ đếm calls = 1, ok_calls = 1 (mỗi lần gọi độc lập)
    - _invalid_json_streak == 0 (không có lỗi JSON nào)
    - api_degraded == False
    - Thống kê token được đếm đúng (> 0 sau khi có usage)

    Baseline này phải được bảo toàn sau khi vá.
    """
    fake = FakeClientValidJSON(payload)
    adapter = _adapter_with_provider_client(fake)

    result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    # Kết quả phải là mapping hợp lệ, không None
    assert result.ok is True, f"Expected ok=True but got ok={result.ok}, error={result.error!r}"
    assert isinstance(result.parsed, dict), f"Expected dict but got {type(result.parsed)}"

    # Client phải được gọi đúng 1 lần (JSON hợp lệ không cần hot-retry)
    assert fake.call_count == 1, f"Expected call_count=1 but got {fake.call_count}"

    # Bộ đếm stats
    status = adapter.debug_status()
    assert status["calls"] == 1, f"Expected calls=1 but got {status['calls']}"
    assert status["ok_calls"] == 1, f"Expected ok_calls=1 but got {status['ok_calls']}"
    assert status["invalid_json_streak"] == 0, (
        f"Expected invalid_json_streak=0 but got {status['invalid_json_streak']}"
    )
    assert status["api_degraded"] is False, (
        f"Expected api_degraded=False but got {status['api_degraded']}"
    )

    # Token được đếm (fake client trả usage 10+20=30 tokens)
    assert status["usage"]["total_tokens"] == 30, (
        f"Expected total_tokens=30 but got {status['usage']['total_tokens']}"
    )


@given(payload=_judgment_payload_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_valid_json_resets_last_error_preservation(payload):
    """
    **Validates: Requirements 3.1**

    Sau một lần gọi thành công, _last_error phải được reset về "".
    Baseline: hành vi reset trạng thái lỗi khi JSON hợp lệ.
    """
    fake = FakeClientValidJSON(payload)
    adapter = _adapter_with_provider_client(fake)

    # Giả lập trạng thái lỗi trước đó
    adapter._last_error = "some_previous_error"

    result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    assert result.ok is True
    status = adapter.debug_status()
    assert status["last_error"] == "", (
        f"Expected last_error='' after success, but got {status['last_error']!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — invalid_json vẫn chạy hot-retry + cooldown (Req 3.2)
# PHẢI PASS trên code chưa vá
# ---------------------------------------------------------------------------

@given(content=_non_json_content_st)
@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
def test_invalid_json_triggers_hot_retry_preservation(content):
    """
    **Validates: Requirements 3.2**

    Khi API trả content không-JSON, adapter PHẢI:
    - Thực hiện hot-retry (gọi client 2 lần: lần đầu + 1 lần retry)
    - Trả None (result.ok=False)
    - error == "invalid_json"
    - Nhiệt độ lần retry cao hơn lần đầu

    Đây là hành vi hot-retry hiện có của _chat_json() — phải được bảo toàn.
    """
    # Skip nội dung trắng vì có thể không gây hot-retry
    assume(content.strip())

    fake = FakeClientNonJSON(content)
    adapter = _adapter_with_provider_client(fake)

    result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    # Kết quả phải là lỗi invalid_json (sau hot-retry cũng không hợp lệ)
    assert result.ok is False, f"Expected ok=False but got ok={result.ok}"
    assert result.error == "invalid_json", (
        f"Expected error='invalid_json' but got error={result.error!r}"
    )

    # Hot-retry: client phải được gọi 2 lần (lần đầu + 1 lần retry nóng hơn)
    assert fake.call_count == 2, (
        f"Expected call_count=2 (hot-retry) but got {fake.call_count} for content={content!r}"
    )

    # Streak tăng lên 1
    status = adapter.debug_status()
    assert status["invalid_json_streak"] == 1, (
        f"Expected invalid_json_streak=1 but got {status['invalid_json_streak']}"
    )


def test_invalid_json_cooldown_activates_after_three_streaks_preservation():
    """
    **Validates: Requirements 3.2**

    Sau 3 lần invalid_json liên tiếp, json_cooldown PHẢI bật (120s).
    Lần thứ 4 phải fast-fail với error="invalid_json_cooldown" — không gọi client.

    Baseline: hành vi cooldown invalid_json hiện có phải được bảo toàn sau khi vá.
    """
    fake = FakeClientNonJSON("This is definitely not JSON content.")
    adapter = _adapter_with_provider_client(fake)

    # 3 lần invalid_json để kích hoạt cooldown
    for i in range(3):
        result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
        assert result.ok is False
        assert result.error == "invalid_json", f"Round {i+1}: expected invalid_json, got {result.error!r}"

    status = adapter.debug_status()
    assert status["invalid_json_streak"] == 3, (
        f"Expected streak=3 after 3 invalid_json calls, got {status['invalid_json_streak']}"
    )
    assert status["json_cooldown_until"] > 0, (
        "Expected json_cooldown_until > 0 after streak=3, but got 0 (cooldown not activated)"
    )
    assert status["api_degraded"] is True, "Expected api_degraded=True when cooldown active"

    # Client bị gọi 6 lần tổng (mỗi lần có 2 hot-retry attempts)
    assert fake.call_count == 6, f"Expected 6 calls (3 rounds x 2 hot-retry), got {fake.call_count}"

    # Lần thứ 4: fast-fail, không gọi client thêm
    result4 = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
    assert result4.ok is False
    assert result4.error == "invalid_json_cooldown", (
        f"Expected error='invalid_json_cooldown' but got {result4.error!r}"
    )
    assert fake.call_count == 6, (
        f"Expected call_count still 6 (fast-fail, no new calls), but got {fake.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 3 — HTTP 4xx ngoài 429 không retry (Req 3.3)
# PHẢI PASS trên code chưa vá
# ---------------------------------------------------------------------------

@given(status_code=_fixed_config_4xx_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_fixed_config_4xx_no_retry_preservation(status_code):
    """
    **Validates: Requirements 3.3**

    Khi provider ném HTTPError với status ∈ {400, 401, 403, 404} (fixed-config errors),
    adapter PHẢI:
    - Trả None (result.ok=False)
    - Gọi client đúng 1 lần (không retry)
    - Không kích hoạt cooldown

    Baseline: hành vi hiện tại cho fixed-config errors phải được bảo toàn sau khi vá.
    Bản vá KHÔNG được thêm retry cho 4xx ngoài 429.
    """
    fake = FakeClientHTTP4xx(status_code)
    adapter = _adapter_with_provider_client(fake)

    result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    # Kết quả phải là lỗi (không parse được)
    assert result.ok is False, (
        f"Expected ok=False for HTTP {status_code} but got ok={result.ok}"
    )

    # Client chỉ được gọi 1 lần — fixed-config error KHÔNG retry
    assert fake.call_count == 1, (
        f"REGRESSION: HTTP {status_code} (fixed-config) should not be retried. "
        f"Client was called {fake.call_count} times (expected exactly 1)."
    )

    # Không có cooldown
    status = adapter.debug_status()
    assert status["json_cooldown_until"] == 0.0, (
        f"Expected json_cooldown_until=0.0 for HTTP {status_code}, got {status['json_cooldown_until']}"
    )


@given(status_code=_fixed_config_4xx_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_fixed_config_4xx_via_evaluate_fragment_returns_none(status_code):
    """
    **Validates: Requirements 3.3**

    Kiểm tra qua evaluate_fragment() API: HTTP 4xx ngoài 429 trả None,
    client gọi đúng 1 lần (thông qua lớp _chat_json + _chat_json_once).
    """
    fake = FakeClientHTTP4xx(status_code)
    adapter = _adapter_with_provider_client(fake)
    dossier = EvidenceDossier(dossier_id="test-preservation-4xx")

    result = adapter.evaluate_fragment("intent_evaluator", dossier)

    assert result is None, (
        f"Expected None for HTTP {status_code} but got {result!r}"
    )

    # _chat_json() hot-retry chỉ chạy khi error == "invalid_json".
    # Vì error != "invalid_json", KHÔNG có hot-retry — client gọi đúng 1 lần.
    assert fake.call_count == 1, (
        f"Expected call_count=1 for HTTP {status_code} (no retry for fixed-config), "
        f"but got {fake.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 4 — llm_service injected với JSON hợp lệ (Req 3.4)
# PHẢI PASS trên code chưa vá
# ---------------------------------------------------------------------------

@given(payload=_fragment_payload_st)
@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
def test_llm_service_injected_valid_json_preservation(payload):
    """
    **Validates: Requirements 3.4**

    Khi llm_service được inject và create_chat_completion trả JSON hợp lệ:
    - Adapter phải trả mapping đúng (result.ok=True)
    - calls = 1, ok_calls = 1
    - Không lỗi

    Đường đi llm_service injected phải hoạt động đúng như hiện tại — không bị
    logic resilience transient mới can thiệp (sau khi vá).
    """
    fake = FakeClientValidJSON(payload)
    # Inject qua llm_service (không phải _provider_client)
    adapter = _adapter_with_llm_service(fake)

    result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    assert result.ok is True, f"Expected ok=True but got ok={result.ok}, error={result.error!r}"
    assert isinstance(result.parsed, dict)

    # llm_service path: create_chat_completion gọi 1 lần
    assert fake.call_count == 1, f"Expected call_count=1 but got {fake.call_count}"

    status = adapter.debug_status()
    assert status["calls"] == 1
    assert status["ok_calls"] == 1
    assert status["invalid_json_streak"] == 0
    assert status["api_degraded"] is False


@given(payload=_judgment_payload_st)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_llm_service_injected_synthesize_judgment_preservation(payload):
    """
    **Validates: Requirements 3.4**

    synthesize_judgment qua llm_service injected trả đúng mapping,
    không crash, thống kê đúng.
    """
    fake = FakeClientValidJSON(payload)
    adapter = _adapter_with_llm_service(fake)
    dossier = EvidenceDossier(dossier_id="test-preservation-llm-service")

    result = adapter.synthesize_judgment(dossier, fragments=())

    # synthesize_judgment trả None nếu parsed dict thiếu required fields,
    # nhưng kết quả đúng (không crash) và calls tăng.
    # Điều quan trọng là không exception và stats được cập nhật.
    status = adapter.debug_status()
    assert status["calls"] == 1, f"Expected calls=1 but got {status['calls']}"
    # Nếu result không None thì phải là dict
    if result is not None:
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test bổ sung — Stats không thay đổi khi cooldown active (Req 3.1, 3.6)
# ---------------------------------------------------------------------------

def test_calls_counter_not_incremented_during_cooldown_preservation():
    """
    **Validates: Requirements 3.1 (stats accuracy)**

    Khi json_cooldown active, _tracked_chat_json() fast-fail ngay mà không
    gọi client. Bộ đếm _calls phải KHÔNG tăng trong trạng thái cooldown.

    Baseline phải được bảo toàn: fast-fail không tính vào stats calls/ok_calls.
    """
    fake = FakeClientNonJSON("not json at all")
    adapter = _adapter_with_provider_client(fake)

    # Kích hoạt cooldown qua 3 lần invalid_json
    for _ in range(3):
        adapter._tracked_chat_json(_simple_messages(), max_tokens=256)

    calls_before_cooldown = adapter.debug_status()["calls"]
    assert calls_before_cooldown == 3

    # Giờ cooldown active: các lần gọi tiếp theo fast-fail
    for _ in range(3):
        result = adapter._tracked_chat_json(_simple_messages(), max_tokens=256)
        assert result.error == "invalid_json_cooldown"

    status = adapter.debug_status()
    # Khi cooldown active, _tracked_chat_json() fast-fail TRƯỚC khi tăng _calls.
    # Baseline: calls chỉ đếm các lần thực sự gọi API, không đếm fast-fail.
    assert status["calls"] == 3, (
        f"Expected calls=3 (only pre-cooldown calls counted) but got {status['calls']}"
    )
    # Client không được gọi thêm khi cooldown
    assert fake.call_count == 6, (
        f"Expected fake.call_count=6 (3 rounds x 2 hot-retry) but got {fake.call_count}"
    )
