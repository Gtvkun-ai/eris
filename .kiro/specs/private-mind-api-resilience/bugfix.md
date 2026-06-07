# Bugfix Requirements Document

## Introduction

Vòng nhận thức PrivateMind gọi Gemini API (`provider=gemini`, `model=gemma-4-26b-a4b-it`,
base `https://generativelanguage.googleapis.com/v1beta`) cho hai việc: đánh giá fragment
(`evaluate_fragment`) và tổng hợp phán đoán (`synthesize_judgment`). Theo log runtime
ngày 2026-06-07, các cuộc gọi này thất bại vì **lỗi vận chuyển thoáng qua (transient transport)**:

- `[PrivateMind API] synthesis failed error=HTTPError:500 Client Error: Internal Server Error ...:generateContent`
- `[PrivateMind API] fragment failed evaluator=future_bias_evaluator error=ReadTimeout: ... (read timeout=28.0)`
- `[PrivateMind API] synthesis failed error=ReadTimeout: ... (read timeout=28.0)`

Loop không crash: rule fallback vẫn tạo `fragments=4 concerns=4 judgment=yes`. Nhưng
`surface=no`, Eris im lặng (`should_speak=False`, `body_only=True`, `mode=force_llm` rồi
`llm_declined`). Nghĩa là nhận thức do model dẫn dắt bị **suy giảm âm thầm** mỗi khi Gemini
trả HTTP 5xx hoặc time out.

Đây là lỗi **KHÁC** với lỗi `invalid_json` đã vá trước đó (xem `tongquat.md` "Runtime resolution 2026-06-07").
Trường hợp `invalid_json` đã có cooldown 120s + salvage JSON. Lỗi hiện tại là **lỗi vận chuyển thoáng qua**
(HTTP 5xx, ReadTimeout, lỗi mạng kết nối) mà hiện **chưa có retry/backoff/circuit-breaker** nào xử lý.

Trong `src/runtime/private_mind_model_adapter.py`, `_tracked_chat_json()` và `_maybe_enter_json_cooldown()`
chỉ đặc xử cho `invalid_json`; mọi lỗi khác (gồm transient) chỉ reset `_invalid_json_streak` rồi trả `None`.
Tầng vận chuyển `GeminiClient.create_chat_completion` trong `src/llm/client.py` thực hiện một lần
`requests.post` duy nhất, không retry: 5xx ném `HTTPError`, quá hạn ném `ReadTimeout`.

**Định nghĩa lỗi vận chuyển thoáng qua (transient)** trong phạm vi tài liệu này: lỗi xảy ra ở
tầng gọi provider trước khi có nội dung hợp lệ, gồm HTTP 5xx (500/502/503/504), HTTP 429 (rate limit),
và các lỗi mạng/timeout (`ReadTimeout`, `ConnectTimeout`, `Timeout`, `ConnectionError`).
KHÔNG bao gồm `invalid_json` (đã có cơ chế riêng) và các lỗi cấu hình cố định
(ví dụ `missing_provider_client`, `unsupported_provider`, HTTP 4xx không phải 429 như 400/401/403).

## Bug Analysis

### Current Behavior (Defect)

Hành vi hiện tại khi một cuộc gọi PrivateMind API gặp lỗi vận chuyển thoáng qua:

1.1 WHEN một cuộc gọi `evaluate_fragment`/`synthesize_judgment` nhận HTTP 5xx (vd 500) THEN hệ thống không thử lại, trả `None` ngay sau một lần gọi và để rule fallback chạy

1.2 WHEN một cuộc gọi `evaluate_fragment`/`synthesize_judgment` bị `ReadTimeout` ở mức read timeout 28.0s THEN hệ thống không thử lại, trả `None` ngay và để rule fallback chạy

1.3 WHEN một lỗi vận chuyển thoáng qua xảy ra (5xx/429/timeout/lỗi mạng) THEN `_tracked_chat_json()` reset `_invalid_json_streak` về 0 và KHÔNG kích hoạt bất kỳ cooldown/circuit-breaker nào, nên mỗi tick kế tiếp lại gọi API và chịu cùng độ trễ/lỗi

1.4 WHEN lỗi vận chuyển thoáng qua xảy ra lặp lại trên cả 4 evaluator và synthesis trong một tick THEN hệ thống vẫn đánh dấu `judgment=yes` (từ deterministic fallback) nhưng `surface=no` và Eris im lặng, không có tín hiệu rõ ràng phân biệt "suy giảm do transient" với hoạt động bình thường

1.5 WHEN nhận thức bị suy giảm bởi transient error THEN `debug_status().api_degraded` chỉ phản ánh chung chung qua `last_error` mà không phân loại được nguyên nhân là transient (so với `invalid_json`), khiến quan sát viên khó chẩn đoán

### Expected Behavior (Correct)

Hành vi đúng cho cùng các điều kiện trên:

2.1 WHEN một cuộc gọi `evaluate_fragment`/`synthesize_judgment` nhận HTTP 5xx (hoặc 429) THEN hệ thống SHALL thử lại có giới hạn với backoff trước khi chấp nhận thất bại và rơi xuống rule fallback

2.2 WHEN một cuộc gọi `evaluate_fragment`/`synthesize_judgment` bị `ReadTimeout`/`ConnectTimeout`/`ConnectionError` THEN hệ thống SHALL thử lại có giới hạn với backoff (và áp dụng/điều chỉnh ngưỡng timeout phù hợp) trước khi chấp nhận thất bại

2.3 WHEN số lần lỗi vận chuyển thoáng qua liên tiếp đạt ngưỡng cấu hình THEN hệ thống SHALL vào trạng thái cooldown/circuit-breaker cho transient (tương tự cơ chế `invalid_json`) để tạm ngưng gọi API trong một khoảng thời gian thay vì tiếp tục gọi mỗi tick

2.4 WHEN trạng thái transient cooldown đang active THEN hệ thống SHALL bỏ qua việc gọi provider, trả `None` ngay (không tốn thời gian chờ network) để rule fallback chạy, và không ghi log cảnh báo lặp lại gây nhiễu

2.5 WHEN cooldown transient hết hạn THEN hệ thống SHALL thử gọi API trở lại, và nếu thành công SHALL reset bộ đếm lỗi transient cùng trạng thái degraded

2.6 WHEN nhận thức bị suy giảm bởi transient error THEN `debug_status()` SHALL phơi bày trạng thái degraded có phân loại nguyên nhân transient (phân biệt với `invalid_json`), gồm bộ đếm lỗi transient và thời điểm cooldown hết hạn, để loop và quan sát viên nhận diện được

### Unchanged Behavior (Regression Prevention)

Hành vi hiện có phải được giữ nguyên cho các input KHÔNG kích hoạt lỗi transient:

3.1 WHEN cuộc gọi API trả JSON hợp lệ (không lỗi) THEN hệ thống SHALL CONTINUE TO parse và trả mapping fragment/judgment như hiện tại, reset `_last_error` và `_invalid_json_streak` về trạng thái sạch

3.2 WHEN cuộc gọi API gặp `invalid_json` THEN hệ thống SHALL CONTINUE TO chạy retry nóng hơn + salvage JSON + cooldown 120s sau streak 3 lần đúng như cơ chế đã vá, không bị thay đổi bởi logic transient mới

3.3 WHEN lỗi là cấu hình cố định (`missing_provider_client`, `unsupported_provider`, HTTP 4xx ngoài 429) THEN hệ thống SHALL CONTINUE TO trả `None` ngay mà không retry (vì retry không thể tự khỏi), giữ nguyên hành vi hiện tại

3.4 WHEN provider là `llama_server` hoặc qua `llm_service` injected THEN hệ thống SHALL CONTINUE TO hoạt động đúng như hiện tại; logic resilience mới không được làm hỏng đường đi này

3.5 WHEN adapter trả `None` vì bất kỳ lý do gì THEN `private_mind_loop.tick()` SHALL CONTINUE TO chạy rule evaluator fallback, cập nhật concern store, tạo deterministic judgment và không crash loop

3.6 WHEN API hoạt động bình thường THEN số lần gọi, độ trễ trung bình, thống kê token trong `debug_status()` SHALL CONTINUE TO được đếm và phơi bày chính xác như hiện tại

## Bug Condition & Properties (Phương pháp Bug Condition)

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X = một lần gọi PrivateMind API (evaluate_fragment hoặc synthesize_judgment)
  OUTPUT: boolean

  // Đúng khi cuộc gọi gặp lỗi vận chuyển thoáng qua,
  // KHÔNG phải invalid_json và KHÔNG phải lỗi cấu hình cố định.
  RETURN isTransientTransportError(X.error)
         // gồm: HTTP 5xx (500/502/503/504), HTTP 429,
         // ReadTimeout, ConnectTimeout, Timeout, ConnectionError
END FUNCTION
```

### Property — Fix Checking

```pascal
// Với mọi cuộc gọi gặp lỗi transient:
FOR ALL X WHERE isBugCondition(X) DO
  result ← F'(X)
  ASSERT retried_with_backoff(result)            // đã thử lại có giới hạn + backoff
  ASSERT (eventual_success(result) OR none_returned(result))  // hoặc khỏi, hoặc trả None sạch
  ASSERT no_crash(result)                          // loop không chết
  ASSERT after_threshold_streak ⇒ transient_cooldown_active   // chạm ngưỡng thì circuit-breaker bật
  ASSERT debug_status.api_degraded_classified = "transient"   // tín hiệu degraded có phân loại
END FOR
```

### Property — Preservation Checking

```pascal
// Với mọi cuộc gọi KHÔNG gặp lỗi transient (JSON hợp lệ, invalid_json, lỗi cấu hình cố định):
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)   // hành vi sau khi vá giống hệt trước khi vá
END FOR
```

**Định nghĩa:**
- **F**: adapter trước khi vá — transient error chỉ reset streak rồi trả `None`, không retry/cooldown.
- **F'**: adapter sau khi vá — transient error được retry + backoff + transient cooldown/circuit-breaker + tín hiệu degraded có phân loại.
- **Counterexample**: `synthesize_judgment(...)` khi Gemini trả HTTP 500 hoặc `ReadTimeout(28.0)` — hiện trả `None` ngay không retry, dẫn tới `surface=no` và Eris im lặng.
