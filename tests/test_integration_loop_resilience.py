# -*- coding: utf-8 -*-
"""
tests/test_integration_loop_resilience.py
==========================================

Integration tests cho private_mind_loop.tick() với fake provider 503 liên tiếp
và kiểm tra phục hồi sau cooldown.

Task 6: Integration tests cho `private_mind_loop.tick()`

Covers:
- Test 1: Loop không crash khi adapter lặp 503 (Req 3.5)
- Test 2: Sau ngưỡng circuit-breaker, các tick fast-fail (Req 2.4)
- Test 3: Phục hồi sau cooldown hết hạn (Req 2.5)
- Test 4: debug_status() phân biệt transient vs invalid_json (Req 2.6)

**Validates: Requirements 1.4, 2.4, 2.5, 3.5**
"""

from __future__ import annotations

import os
import sys
import time

import pytest
import requests
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.private_mind_model_adapter import (
    PrivateMindModelAdapterConfig,
    RuntimePrivateMindModelAdapter,
)
from runtime.private_mind_loop import PrivateMindLoop, PrivateMindLoopConfig
from cortex.private_mind import (
    ConcernStore,
    EvidenceDossierBuilder,
    GemmaInnerSynthesizer,
    MiniEvaluatorPipeline,
    StateMutationBus,
    SurfaceValve,
    ThoughtContinuityStore,
    UserModelStore,
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
        503: "Service Unavailable",
        500: "Internal Server Error",
        429: "Too Many Requests",
        400: "Bad Request",
    }.get(status_code, "Error")
    response.url = "https://fake.api/generateContent"
    return requests.HTTPError(
        f"{status_code} Error: {response.reason}",
        response=response,
    )


class FakeClientAlways503:
    """Provider client luôn ném HTTP 503."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(503)


class FakeClientReturnsValidJson:
    """Provider client trả JSON hợp lệ (fragment-compatible)."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"claim":"User wants architecture work","confidence":0.82,"pressure":0.7,"evidence_ids":[]}'
                    }
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
        }


class FakeClientReturnsInvalidJson:
    """Provider client trả nội dung không phải JSON."""

    def __init__(self):
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        return {
            "choices": [{"message": {"content": "This is not valid JSON at all!!!"}}],
            "usage": {},
        }


def _make_adapter_with_client(fake_client, *, transient_cooldown_threshold: int = 3) -> RuntimePrivateMindModelAdapter:
    """Create adapter with provider=gemini, thresholds cho test nhanh."""
    config = PrivateMindModelAdapterConfig(
        provider="gemini",
        enabled=True,
        api_key="fake-key-for-integration-test",
        transient_max_retries=0,          # không retry để test nhanh
        transient_backoff_base=0.0,
        transient_cooldown_threshold=transient_cooldown_threshold,
        transient_cooldown_seconds=3600.0,  # 1 giờ — sẽ giả lập hết hạn bằng cách đặt trực tiếp
    )
    adapter = RuntimePrivateMindModelAdapter(config=config)
    adapter._provider_client = fake_client
    return adapter


def _make_loop(adapter) -> PrivateMindLoop:
    """Create PrivateMindLoop với adapter được inject và không cần file/LTM thật."""
    config = PrivateMindLoopConfig(
        enabled=True,
        min_interval_seconds=0.0,    # không throttle để test dễ gọi tick()
        log_ticks=False,
    )
    concern_store = ConcernStore(path=None)  # in-memory, không ghi file
    dossier_builder = EvidenceDossierBuilder()
    # Tắt cổng relevance: test này drive tick lặp lại với cùng dossier để dồn
    # streak 503 vào adapter — nó kiểm tra circuit breaker của adapter, không phải cổng.
    evaluator_pipeline = MiniEvaluatorPipeline(model_adapter=adapter, relevance_gate_enabled=False)
    synthesizer = GemmaInnerSynthesizer(model_adapter=adapter, min_fragments_for_model=3)
    mutation_bus = StateMutationBus()
    surface_valve = SurfaceValve()

    # Cô lập MỌI persistence khỏi đĩa thật: nếu không, loop dùng
    # ThoughtContinuityStore.from_env() (ghi/đọc memory_core/thought_stream.jsonl)
    # và UserModelStore mặc định -> (1) test flaky vì số fragment self_followup phụ
    # thuộc state cũ trên đĩa, (2) test làm BẨN memory_core/ thật bằng dữ liệu test,
    # (3) I/O đĩa làm tick chậm. path=None => hoàn toàn in-memory.
    continuity_store = ThoughtContinuityStore(path=None)
    user_model_store = UserModelStore(path=None)

    loop = PrivateMindLoop(
        config=config,
        concern_store=concern_store,
        dossier_builder=dossier_builder,
        evaluator_pipeline=evaluator_pipeline,
        synthesizer=synthesizer,
        mutation_bus=mutation_bus,
        surface_valve=surface_valve,
        continuity_store=continuity_store,
        user_model_store=user_model_store,
        model_adapter=adapter,
        logger=None,
    )
    return loop


def _tick(loop: PrivateMindLoop):
    """Helper: gọi tick() với force=True để bỏ qua min_interval."""
    return loop.tick(
        user_text="test integration resilience",
        channel="test",
        force=True,
    )


# ---------------------------------------------------------------------------
# Test 1 — Loop không crash khi adapter lặp 503 (Req 3.5)
# ---------------------------------------------------------------------------

class TestLoopNocrashWith503:
    """
    **Validates: Requirements 3.5**

    private_mind_loop.tick() với adapter 503 liên tiếp:
    - Không raise exception
    - Rule fallback vẫn tạo fragments và result
    """

    def test_tick_does_not_raise_on_repeated_503(self):
        """
        **Validates: Requirements 3.5**

        Gọi tick() N lần với adapter luôn ném 503.
        Loop không được raise exception dù mọi API call đều fail.
        """
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake)
        loop = _make_loop(adapter)

        # Gọi nhiều tick — không được raise
        for _ in range(5):
            try:
                result = _tick(loop)
            except Exception as exc:
                pytest.fail(
                    f"loop.tick() raised {type(exc).__name__}: {exc} "
                    f"khi adapter gặp HTTP 503 liên tiếp. "
                    f"Loop phải không crash theo Req 3.5."
                )

    def test_tick_returns_result_not_none_via_rule_fallback(self):
        """
        **Validates: Requirements 3.5**

        Khi adapter trả None (do 503), rule fallback của MiniEvaluatorPipeline
        vẫn tạo fragments. tick() trả PrivateMindTickResult (không phải None).
        """
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake)
        loop = _make_loop(adapter)

        result = _tick(loop)

        # Loop phải trả result, không phải None (config.enabled=True)
        assert result is not None, (
            "tick() trả None khi adapter gặp 503. "
            "Với config.enabled=True và force=True, tick() phải trả PrivateMindTickResult."
        )

    def test_tick_does_not_fabricate_fragments_when_api_fails(self):
        """
        **Validates: Requirements 3.5**

        Thiết kế hiện tại của MiniEvaluatorPipeline KHÔNG có rule fallback
        (xem docstring cortex/private_mind/mini_evaluators.py): khi mọi mini-evaluator
        gọi API thất bại (503), tick đó không có fragment nào — pipeline KHÔNG bịa
        fragment bằng rule. Resilience do pool key dự phòng + cooldown lo, không phải
        bằng cách bịa nội tâm. Loop vẫn phải sống (trả result, không raise).
        """
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake)
        loop = _make_loop(adapter)

        result = _tick(loop)

        assert result is not None
        # Không có rule fallback => không fragment nào được bịa ra khi API chết.
        assert len(result.fragments) == 0, (
            f"tick() bịa {len(result.fragments)} fragment khi adapter fail (503). "
            f"Theo thiết kế no-fallback, API chết phải cho 0 fragment, không fabricate."
        )

    def test_tick_last_error_set_after_503(self):
        """
        **Validates: Requirements 1.4, 3.5**

        Sau khi adapter gặp 503, debug_status() phải phơi bày last_error != ''.
        Cho thấy loop nhận diện và ghi nhận tình trạng API.
        """
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake)
        loop = _make_loop(adapter)

        _tick(loop)

        status = adapter.debug_status()
        assert status.get("last_error", "") != "", (
            f"Sau khi 503, debug_status()['last_error'] phải != '' nhưng là ''.\n"
            f"debug_status = {status}"
        )

    def test_tick_degraded_cause_is_transient_after_503(self):
        """
        **Validates: Requirements 1.4, 2.6**

        Sau khi adapter gặp 503, debug_status()['degraded_cause'] phải là 'transient'.
        Loop phơi bày tín hiệu phân loại để quan sát viên chẩn đoán.
        """
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake)
        loop = _make_loop(adapter)

        _tick(loop)

        status = adapter.debug_status()
        assert status.get("degraded_cause") == "transient", (
            f"Sau khi 503, degraded_cause phải là 'transient' nhưng là '{status.get('degraded_cause')}'.\n"
            f"debug_status = {status}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Sau ngưỡng circuit-breaker, các tick fast-fail (Req 2.4)
# ---------------------------------------------------------------------------

class TestCircuitBreakerFastFail:
    """
    **Validates: Requirements 2.4**

    Sau khi transient streak vượt ngưỡng:
    - debug_status()['degraded_cause'] == 'transient'
    - Các tick kế tiếp fast-fail (không gọi client thêm)
    """

    def test_circuit_breaker_activates_after_threshold(self):
        """
        **Validates: Requirements 2.4**

        Gọi đủ tick để vượt threshold (3), sau đó kiểm tra
        debug_status()['degraded_cause'] == 'transient'.
        """
        threshold = 3
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        # Gọi đủ tick vượt ngưỡng
        for _ in range(threshold + 1):
            _tick(loop)

        status = adapter.debug_status()
        assert status.get("degraded_cause") == "transient", (
            f"Sau {threshold + 1} tick với 503, degraded_cause phải là 'transient' "
            f"nhưng là '{status.get('degraded_cause')}'.\n"
            f"debug_status = {status}"
        )

    def test_circuit_breaker_cooldown_active_after_threshold(self):
        """
        **Validates: Requirements 2.4**

        Sau ngưỡng, adapter._transient_cooldown_active() phải trả True.
        """
        threshold = 3
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        assert adapter._transient_cooldown_active() is True, (
            f"Sau {threshold + 1} lần 503, _transient_cooldown_active() phải là True "
            f"nhưng là {adapter._transient_cooldown_active()}. "
            f"transient_streak={adapter._transient_streak}, "
            f"transient_cooldown_until={adapter._transient_cooldown_until}"
        )

    def test_subsequent_ticks_fast_fail_no_client_calls(self):
        """
        **Validates: Requirements 2.4**

        Sau khi circuit breaker bật, tick tiếp theo không gọi client thêm
        (fast-fail không tốn network call).
        """
        threshold = 3
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        # Gọi đủ tick để bật circuit breaker
        for _ in range(threshold + 1):
            _tick(loop)

        assert adapter._transient_cooldown_active() is True, "Circuit breaker chưa bật, test setup lỗi"

        # Ghi nhận số lần đã gọi client
        calls_before_fast_fail = fake.call_count

        # Gọi thêm N tick trong khi cooldown active
        fast_fail_ticks = 3
        for _ in range(fast_fail_ticks):
            _tick(loop)

        calls_after_fast_fail = fake.call_count

        assert calls_after_fast_fail == calls_before_fast_fail, (
            f"Sau khi circuit breaker bật, client bị gọi thêm "
            f"{calls_after_fast_fail - calls_before_fast_fail} lần (expected 0). "
            f"Fast-fail phải trả ngay mà không gọi network. "
            f"Calls before={calls_before_fast_fail}, after={calls_after_fast_fail}"
        )

    def test_loop_still_produces_result_during_fast_fail(self):
        """
        **Validates: Requirements 2.4, 3.5**

        Khi fast-fail, loop vẫn không crash và vẫn tạo result qua rule fallback.
        """
        threshold = 3
        fake = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        # Tick trong trạng thái fast-fail
        try:
            result = _tick(loop)
        except Exception as exc:
            pytest.fail(
                f"tick() raised {type(exc).__name__}: {exc} trong trạng thái fast-fail. "
                f"Loop phải không crash ngay cả khi circuit breaker active."
            )

        assert result is not None, "tick() trả None trong fast-fail state; expected PrivateMindTickResult"


# ---------------------------------------------------------------------------
# Test 3 — Phục hồi sau cooldown hết hạn (Req 2.5)
# ---------------------------------------------------------------------------

class TestRecoveryAfterCooldownExpiry:
    """
    **Validates: Requirements 2.5**

    Sau khi cooldown hết hạn:
    - Thay client bằng client thành công
    - Gọi tick — adapter nhận diện thành công và reset degraded_cause
    """

    def test_adapter_resets_after_cooldown_expires_and_success(self):
        """
        **Validates: Requirements 2.5**

        Giả lập hết cooldown bằng cách đặt _transient_cooldown_until về quá khứ,
        sau đó thay bằng client thành công.
        Tick tiếp theo phải reset degraded_cause về ''.
        """
        # Bước 1: bật circuit breaker
        threshold = 3
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        assert adapter._transient_cooldown_active() is True, "Circuit breaker chưa bật, test setup lỗi"
        assert adapter.debug_status()["degraded_cause"] == "transient", (
            "degraded_cause không phải 'transient' trước recovery, test setup lỗi"
        )

        # Bước 2: giả lập cooldown hết hạn
        adapter._transient_cooldown_until = time.time() - 1.0  # đã qua 1 giây

        assert adapter._transient_cooldown_active() is False, "Cooldown vẫn active sau khi set về quá khứ"

        # Bước 3: thay client bằng client trả thành công
        fake_success = FakeClientReturnsValidJson()
        adapter._provider_client = fake_success

        # Bước 4: gọi tick để trigger success call
        _tick(loop)

        # Kiểm tra: adapter phải nhận diện thành công và reset
        assert fake_success.call_count > 0, (
            "Client thành công không được gọi sau khi cooldown hết hạn."
        )

    def test_transient_streak_reset_after_success(self):
        """
        **Validates: Requirements 2.5**

        Sau khi success call, _transient_streak phải reset về 0.
        """
        threshold = 3
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        # Giả lập cooldown hết hạn
        adapter._transient_cooldown_until = time.time() - 1.0
        # Thay client bằng client thành công
        fake_success = FakeClientReturnsValidJson()
        adapter._provider_client = fake_success

        _tick(loop)

        assert adapter._transient_streak == 0, (
            f"Sau success call, _transient_streak phải là 0 "
            f"nhưng là {adapter._transient_streak}. "
            f"Success phải reset transient state theo Req 2.5."
        )

    def test_transient_cooldown_until_cleared_after_success(self):
        """
        **Validates: Requirements 2.5**

        Sau khi success call, _transient_cooldown_until phải là 0.0.
        """
        threshold = 3
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        # Giả lập cooldown hết hạn
        adapter._transient_cooldown_until = time.time() - 1.0
        fake_success = FakeClientReturnsValidJson()
        adapter._provider_client = fake_success

        _tick(loop)

        assert adapter._transient_cooldown_until == 0.0, (
            f"Sau success call, _transient_cooldown_until phải là 0.0 "
            f"nhưng là {adapter._transient_cooldown_until}."
        )

    def test_degraded_cause_cleared_after_recovery(self):
        """
        **Validates: Requirements 2.5**

        Sau khi success call, debug_status()['degraded_cause'] phải trở về ''.
        """
        threshold = 3
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        for _ in range(threshold + 1):
            _tick(loop)

        assert adapter.debug_status()["degraded_cause"] == "transient"

        # Giả lập cooldown hết hạn + thay client
        adapter._transient_cooldown_until = time.time() - 1.0
        fake_success = FakeClientReturnsValidJson()
        adapter._provider_client = fake_success

        _tick(loop)

        status = adapter.debug_status()
        assert status.get("degraded_cause") != "transient", (
            f"Sau recovery, degraded_cause vẫn là 'transient'. "
            f"debug_status = {status}"
        )

    def test_loop_uses_model_after_recovery(self):
        """
        **Validates: Requirements 2.5, 1.4**

        Sau recovery, adapter được gọi trở lại (không bị block bởi cooldown).
        Số lần gọi client thành công > 0.
        """
        threshold = 2
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503, transient_cooldown_threshold=threshold)
        loop = _make_loop(adapter)

        # Bật circuit breaker
        for _ in range(threshold + 1):
            _tick(loop)

        assert adapter._transient_cooldown_active() is True

        # Hết cooldown + thay client
        adapter._transient_cooldown_until = time.time() - 1.0
        fake_success = FakeClientReturnsValidJson()
        adapter._provider_client = fake_success
        calls_before = fake_success.call_count

        _tick(loop)

        assert fake_success.call_count > calls_before, (
            f"Sau recovery, adapter không gọi client thành công. "
            f"Calls sau tick = {fake_success.call_count}, before = {calls_before}"
        )


# ---------------------------------------------------------------------------
# Test 4 — debug_status() phân biệt transient vs invalid_json (Req 2.6)
# ---------------------------------------------------------------------------

class TestDebugStatusDifferentiatesTransientVsInvalidJson:
    """
    **Validates: Requirements 2.6, 1.4**

    Hai adapter với lỗi khác nhau phải có degraded_cause khác nhau.
    """

    def test_transient_adapter_has_transient_cause(self):
        """
        **Validates: Requirements 2.6**

        Adapter gặp transient error (HTTP 503) phải có degraded_cause='transient'.
        """
        fake_503 = FakeClientAlways503()
        adapter_transient = _make_adapter_with_client(fake_503)
        loop_transient = _make_loop(adapter_transient)

        _tick(loop_transient)

        status = adapter_transient.debug_status()
        assert status.get("degraded_cause") == "transient", (
            f"Adapter gặp 503 phải có degraded_cause='transient', "
            f"nhưng có '{status.get('degraded_cause')}'.\n"
            f"debug_status = {status}"
        )

    def test_invalid_json_adapter_has_invalid_json_cause(self):
        """
        **Validates: Requirements 2.6**

        Adapter gặp invalid_json error phải có degraded_cause='invalid_json'.
        """
        fake_invalid_json = FakeClientReturnsInvalidJson()
        config = PrivateMindModelAdapterConfig(
            provider="gemini",
            enabled=True,
            api_key="fake-key",
            transient_max_retries=0,
            transient_backoff_base=0.0,
            transient_cooldown_threshold=3,
            transient_cooldown_seconds=3600.0,
        )
        adapter_invalid_json = RuntimePrivateMindModelAdapter(config=config)
        adapter_invalid_json._provider_client = fake_invalid_json
        loop_invalid_json = _make_loop(adapter_invalid_json)

        _tick(loop_invalid_json)

        status = adapter_invalid_json.debug_status()
        assert status.get("degraded_cause") == "invalid_json", (
            f"Adapter gặp invalid_json phải có degraded_cause='invalid_json', "
            f"nhưng có '{status.get('degraded_cause')}'.\n"
            f"debug_status = {status}"
        )

    def test_degraded_causes_are_different_between_two_adapters(self):
        """
        **Validates: Requirements 2.6, 1.4**

        Adapter gặp transient error và adapter gặp invalid_json error
        phải có degraded_cause KHÁC NHAU.
        """
        # Adapter 1: transient (HTTP 503)
        fake_503 = FakeClientAlways503()
        adapter_transient = _make_adapter_with_client(fake_503)
        loop_transient = _make_loop(adapter_transient)
        _tick(loop_transient)

        # Adapter 2: invalid_json
        fake_invalid_json = FakeClientReturnsInvalidJson()
        config = PrivateMindModelAdapterConfig(
            provider="gemini",
            enabled=True,
            api_key="fake-key",
            transient_max_retries=0,
            transient_backoff_base=0.0,
            transient_cooldown_threshold=3,
            transient_cooldown_seconds=3600.0,
        )
        adapter_invalid_json = RuntimePrivateMindModelAdapter(config=config)
        adapter_invalid_json._provider_client = fake_invalid_json
        loop_invalid_json = _make_loop(adapter_invalid_json)
        _tick(loop_invalid_json)

        status_transient = adapter_transient.debug_status()
        status_invalid_json = adapter_invalid_json.debug_status()

        cause_transient = status_transient.get("degraded_cause")
        cause_invalid_json = status_invalid_json.get("degraded_cause")

        assert cause_transient != cause_invalid_json, (
            f"Hai adapter với lỗi khác nhau phải có degraded_cause khác nhau, "
            f"nhưng cả hai đều là '{cause_transient}'.\n"
            f"status_transient = {status_transient}\n"
            f"status_invalid_json = {status_invalid_json}"
        )

    def test_transient_cause_is_not_invalid_json(self):
        """
        **Validates: Requirements 2.6**

        Rõ ràng xác nhận: adapter gặp 503 KHÔNG được báo degraded_cause='invalid_json'.
        """
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503)
        loop = _make_loop(adapter)

        _tick(loop)

        status = adapter.debug_status()
        assert status.get("degraded_cause") != "invalid_json", (
            f"Adapter gặp 503 không được báo degraded_cause='invalid_json'. "
            f"degraded_cause = '{status.get('degraded_cause')}'"
        )

    def test_loop_digest_exposes_degraded_cause_via_debug_api(self):
        """
        **Validates: Requirements 1.4, 2.6**

        loop.digest()['debug_api'] phải chứa degraded_cause khi adapter bị degraded.
        Phơi bày cho quan sát viên qua loop.digest().
        """
        fake_503 = FakeClientAlways503()
        adapter = _make_adapter_with_client(fake_503)
        loop = _make_loop(adapter)

        _tick(loop)
        digest = loop.digest()

        debug_api = digest.get("debug_api", {})
        assert isinstance(debug_api, dict), f"digest['debug_api'] phải là dict, nhưng là {type(debug_api)}"
        assert "degraded_cause" in debug_api, (
            f"digest['debug_api'] phải chứa 'degraded_cause'. "
            f"debug_api keys = {sorted(debug_api.keys())}"
        )
        assert debug_api["degraded_cause"] == "transient", (
            f"digest['debug_api']['degraded_cause'] phải là 'transient' sau 503, "
            f"nhưng là '{debug_api.get('degraded_cause')}'."
        )
