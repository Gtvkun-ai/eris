# Private Mind API Resilience Bugfix Design

## Overview

Vòng nhận thức PrivateMind gọi Gemini API qua `RuntimePrivateMindModelAdapter` để đánh
giá fragment và tổng hợp phán đoán. Khi Gemini trả **lỗi vận chuyển thoáng qua** (HTTP 5xx,
HTTP 429, `ReadTimeout`/`ConnectTimeout`/`Timeout`/`ConnectionError`), adapter hiện tại chỉ
gọi một lần, bắt `Exception`, gói thành chuỗi `f"{type(exc).__name__}:{exc}"`, reset
`_invalid_json_streak` rồi trả `None`. Hệ quả: không retry, không backoff, không
circuit-breaker; mỗi tick lại gọi lại và chịu cùng độ trễ 28s, khiến nhận thức do model dẫn
dắt **suy giảm âm thầm** (`surface=no`, Eris im lặng).

Chiến lược vá là **tối thiểu và phẫu thuật**, đặt toàn bộ logic resilience ở **tầng adapter**
(không sửa `src/llm/client.py`, không đụng đường đi `llama_server`/`llm_service` về mặt ngữ
nghĩa cho input không-transient), gồm bốn mảnh ghép song song với cơ chế `invalid_json` đã có:

1. **Phân loại lỗi đáng tin cậy**: thay vì so khớp chuỗi, gắn một trường phân loại
   (`error_kind`) vào `PrivateMindModelResult` được suy ra trực tiếp từ *kiểu exception* và
   *HTTP status code*.
2. **Retry có giới hạn + backoff** cho lỗi transient, nằm *bên trong* (innermost) so với
   vòng hot-retry `invalid_json` hiện có, để hai cơ chế không xung đột.
3. **Transient cooldown/circuit-breaker** với bộ đếm và mốc thời gian riêng
   (`_transient_streak`, `_transient_cooldown_until`), song song với
   `_invalid_json_streak`/`_json_cooldown_until`.
4. **Fast-fail** khi transient cooldown active (mirror `_json_cooldown_active()` early-return)
   và **mở rộng `debug_status()`** để phân loại nguyên nhân degraded.

## Glossary

- **Bug_Condition (C)**: Điều kiện kích hoạt lỗi — một lần gọi PrivateMind API gặp lỗi vận
  chuyển thoáng qua (transient transport error).
- **Property (P)**: Hành vi mong muốn cho input thỏa C — được retry có giới hạn + backoff, và
  nếu vẫn hỏng tới ngưỡng thì bật transient cooldown, đồng thời phơi bày tín hiệu degraded
  có phân loại.
- **Preservation**: Hành vi hiện có phải giữ nguyên cho mọi input KHÔNG thỏa C (JSON hợp lệ,
  `invalid_json`, lỗi cấu hình cố định, đường đi `llama_server`/`llm_service`).
- **Transient transport error**: HTTP 5xx (500/502/503/504), HTTP 429, và lỗi mạng/timeout
  (`ReadTimeout`, `ConnectTimeout`, `Timeout`, `ConnectionError`). Là lỗi tầng vận chuyển
  xảy ra TRƯỚC khi có nội dung hợp lệ.
- **Fixed-config error**: Lỗi cấu hình cố định không tự khỏi khi retry — `missing_provider_client`,
  `unsupported_provider`, HTTP 4xx ngoài 429 (400/401/403...).
- **`_tracked_chat_json()`**: Hàm trong `src/runtime/private_mind_model_adapter.py` bọc một
  lần gọi, đo latency/token, cập nhật bộ đếm và quản lý cooldown.
- **`_chat_json()`**: Hàm chứa vòng hot-retry riêng cho `invalid_json` (re-prompt với nhiệt
  độ cao hơn + repair prompt).
- **`_chat_json_once()`**: Hàm điều phối tới `llm_service` / `llama_server` / provider remote.
- **`_provider_chat_json()` / `_llama_server_chat_json()`**: Hàm thực hiện gọi mạng và hiện
  trả `error=f"{type(exc).__name__}:{exc}"` khi bắt exception.
- **`error_kind`**: Trường phân loại mới trên `PrivateMindModelResult` (`""` | `"invalid_json"`
  | `"transient"` | `"fixed_config"`).

## Bug Details

### Bug Condition

Lỗi xuất hiện khi một cuộc gọi `evaluate_fragment`/`synthesize_judgment` gặp lỗi vận chuyển
thoáng qua. `_provider_chat_json()` (hoặc `_llama_server_chat_json()` / nhánh `llm_service`)
bắt exception và trả về `PrivateMindModelResult(ok=False, error="HTTPError:500 ...")`. Hiện
tại lỗi này (a) **không được retry**, (b) **không kích hoạt cooldown nào**, và (c) **không
được phân loại** tách khỏi `invalid_json`, nên `_tracked_chat_json()` chỉ reset
`_invalid_json_streak` rồi trả `None`.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ApiCall (evaluate_fragment hoặc synthesize_judgment)
  OUTPUT: boolean

  RETURN isTransientTransportError(input.raisedException)
         // HTTPError với status IN {500, 502, 503, 504, 429}
         //   OR exception IN {ReadTimeout, ConnectTimeout, Timeout, ConnectionError}
         AND NOT isInvalidJson(input)          // invalid_json đã có cơ chế riêng
         AND NOT isFixedConfigError(input)      // missing_provider_client / unsupported_provider / 4xx khác
END FUNCTION
```

### Examples

- `synthesize_judgment(...)` khi Gemini trả HTTP 500 → hiện trả `None` ngay sau 1 lần gọi
  (mong đợi: retry + backoff, rồi nếu vẫn hỏng thì đếm streak; chạm ngưỡng thì cooldown).
- `evaluate_fragment("future_bias_evaluator", ...)` bị `ReadTimeout(read timeout=28.0)` →
  hiện trả `None` ngay (mong đợi: retry có giới hạn với backoff trước khi bỏ cuộc).
- 3 tick liên tiếp đều gặp HTTP 503 → hiện mỗi tick vẫn gọi và chờ ~28s (mong đợi: sau
  khi streak chạm ngưỡng, transient cooldown bật và các tick kế tiếp fast-fail trả `None`
  ngay, không chờ network, không log lặp).
- Edge case: HTTP 400 (Bad Request) → KHÔNG phải transient; phải trả `None` ngay không retry,
  giữ nguyên hành vi (đây là fixed-config error).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Khi API trả JSON hợp lệ: parse và trả mapping fragment/judgment như hiện tại; reset
  `_last_error` và `_invalid_json_streak` về sạch (Req 3.1).
- Khi gặp `invalid_json`: vòng hot-retry (nhiệt độ cao hơn + repair prompt) + salvage JSON +
  cooldown 120s sau streak 3 vẫn chạy y nguyên, không bị logic transient can thiệp (Req 3.2).
- Khi gặp fixed-config error (`missing_provider_client`, `unsupported_provider`, HTTP 4xx
  ngoài 429): trả `None` ngay không retry (Req 3.3).
- Đường đi `llama_server` và `llm_service` injected vẫn hoạt động đúng như hiện tại (Req 3.4).
- `private_mind_loop.tick()` vẫn chạy rule fallback khi adapter trả `None`, không crash (Req 3.5).
- Khi API bình thường: số lần gọi, latency trung bình, thống kê token trong `debug_status()`
  vẫn được đếm và phơi bày chính xác (Req 3.6).

**Scope:**
Mọi input KHÔNG thỏa bug condition (không phải transient transport error) phải hoàn toàn
không bị ảnh hưởng bởi bản vá này, gồm:
- Cuộc gọi trả JSON hợp lệ.
- Cuộc gọi `invalid_json` (đi theo cơ chế cũ).
- Cuộc gọi fixed-config error.
- Mọi cuộc gọi qua `llama_server` hoặc `llm_service` injected khi không gặp transient error.

> Hành vi đúng mong muốn cho input thỏa bug condition được định nghĩa ở mục
> **Correctness Properties** (Property 1). Mục này chỉ liệt kê những gì KHÔNG được thay đổi.

## Hypothesized Root Cause

Dựa trên mô tả lỗi và đọc mã nguồn, nguyên nhân gốc gồm:

1. **Thiếu hoàn toàn lớp resilience cho transport**: `GeminiClient.create_chat_completion`
   trong `src/llm/client.py` thực hiện đúng một `requests.post`, 5xx ném `HTTPError`, quá
   hạn ném `ReadTimeout`. Adapter cũng chỉ gọi một lần qua `_provider_chat_json()` — không
   có retry/backoff/circuit-breaker cho transient ở bất kỳ tầng nào.

2. **Phân loại lỗi không đáng tin cậy**: `_provider_chat_json()`/`_llama_server_chat_json()`
   gói lỗi thành chuỗi `f"{type(exc).__name__}:{exc}"`. Trong `_tracked_chat_json()`, chỉ
   chuỗi đúng bằng `"invalid_json"` được xử lý đặc biệt; mọi chuỗi khác (gồm transient) rơi
   vào nhánh `else` và reset streak. Không có cơ chế nhận diện 5xx/429/timeout, và việc dựa
   vào so khớp chuỗi là mong manh (định dạng message có thể đổi).

3. **`_tracked_chat_json()` chỉ có một loại cooldown**: cooldown hiện tại
   (`_json_cooldown_until` + `_maybe_enter_json_cooldown()`) chỉ phục vụ `invalid_json`.
   Không có streak/cooldown riêng cho transient, nên lỗi transient lặp lại không bao giờ
   "ngắt mạch".

4. **`debug_status()` không phân loại nguyên nhân degraded**: `api_degraded` chỉ là
   `bool(self._last_error or self._json_cooldown_active())`, và `private_mind_loop._model_api_status()`
   suy ra trạng thái bằng cách kiểm tra chuỗi `"invalid_json" in last_error`. Không có tín
   hiệu phân biệt "degraded do transient" với "degraded do invalid_json".

## Correctness Properties

Property 1: Bug Condition - Transient transport error được retry/backoff/circuit-breaker

_For any_ cuộc gọi PrivateMind API mà bug condition thỏa (`isBugCondition` trả true — lỗi vận
chuyển thoáng qua: HTTP 5xx/429, ReadTimeout/ConnectTimeout/Timeout/ConnectionError), adapter
sau khi vá SHALL thử lại có giới hạn với backoff trước khi chấp nhận thất bại; nếu vẫn hỏng
thì tăng `_transient_streak`, và khi streak chạm ngưỡng cấu hình SHALL bật transient cooldown
(các tick kế tiếp fast-fail trả `None` ngay, không chờ network, không log lặp); đồng thời
`debug_status()` SHALL phơi bày `degraded_cause="transient"` cùng `transient_streak` và
`transient_cooldown_until`. Loop không bao giờ crash; kết quả cuối cùng hoặc thành công
hoặc trả `None` sạch cho rule fallback.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6**

Property 2: Preservation - Input không-transient giữ nguyên hành vi

_For any_ cuộc gọi mà bug condition KHÔNG thỏa (`isBugCondition` trả false — JSON hợp lệ,
`invalid_json`, fixed-config error, hoặc đường đi `llama_server`/`llm_service` không gặp
transient error), adapter sau khi vá (F') SHALL cho cùng kết quả quan sát được như adapter
trước khi vá (F): cùng giá trị trả về (mapping hoặc `None`), cùng tiến trình `invalid_json`
hot-retry + salvage + cooldown 120s, cùng việc reset streak, và cùng số liệu calls/latency/token.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

Property 3: Reset - Thành công xóa trạng thái transient degraded

_For any_ cuộc gọi thành công (trả mapping hợp lệ) sau một chuỗi transient error, adapter sau
khi vá SHALL reset `_transient_streak` về 0, xóa `_transient_cooldown_until`, và `debug_status()`
SHALL không còn báo `degraded_cause="transient"`.

**Validates: Requirements 2.5**

## Fix Implementation

### Changes Required

Mọi thay đổi nằm trong `src/runtime/private_mind_model_adapter.py`. **Không sửa**
`src/llm/client.py`. `src/runtime/private_mind_loop.py` chỉ được mở rộng (đọc thêm field),
không đổi ngữ nghĩa fallback.

**File**: `src/runtime/private_mind_model_adapter.py`

1. **Thêm trường phân loại vào `PrivateMindModelResult`**
   - Thêm `error_kind: str = ""` với giá trị thuộc `{"", "invalid_json", "transient", "fixed_config"}`.
   - Mục đích: phân loại đáng tin cậy, không phụ thuộc so khớp chuỗi `error`.

2. **Thêm hàm phân loại exception `_classify_transport_exception(exc) -> str`**
   - Nhập một exception, trả `"transient"` hoặc `"fixed_config"`.
   - Quy tắc (theo *kiểu* và *status*, không theo message):
     - `requests.HTTPError` (hoặc bất kỳ exception có `.response`): lấy
       `response.status_code`; nếu IN `{500, 502, 503, 504, 429}` → `"transient"`; nếu là
       4xx khác → `"fixed_config"`; 5xx khác → `"transient"`.
     - `requests.exceptions.Timeout` / `ReadTimeout` / `ConnectTimeout` /
       `ConnectionError` → `"transient"`.
     - `urllib.error.HTTPError` (đường llama_server): dùng `.code` với cùng quy tắc status.
     - `urllib.error.URLError`, `socket.timeout`, `TimeoutError` → `"transient"`.
     - Mặc định (không nhận diện được) → `"fixed_config"` (an toàn: không retry vô cớ).
   - Import bổ sung ở đầu file: `import socket`, `import urllib.error`, và `import requests`
     (chỉ dùng cho `isinstance`/đọc status; nếu muốn tránh phụ thuộc cứng có thể dùng
     `getattr(exc, "response", None)` + tên class, nhưng `requests` đã là dependency của
     `src/llm/client.py` nên import trực tiếp là chấp nhận được).

3. **Gắn `error_kind` tại các điểm bắt exception**
   - Trong `_provider_chat_json()`, `_llama_server_chat_json()`, và nhánh `llm_service` của
     `_chat_json_once()`: khi `except Exception as exc`, đặt
     `error_kind=_classify_transport_exception(exc)` (vẫn giữ `error=f"{type(exc).__name__}:{exc}"`
     để log/quan sát không đổi).
   - `missing_provider_client` và `unsupported_provider`: đặt `error_kind="fixed_config"`.
   - Trường hợp `invalid_json`/`invalid_json_cooldown`: đặt `error_kind="invalid_json"`
     (hoặc giữ `""` cho cooldown; phân loại chính nằm ở `error`).

4. **Thêm retry transient (innermost) bằng `_chat_json_with_transient_retry()`**
   - Hàm mới bọc `_chat_json_once(...)`: gọi một lần; nếu `result.error_kind == "transient"`
     thì lặp lại tối đa `config.transient_max_retries` lần, mỗi lần `time.sleep(backoff)` với
     backoff tăng dần (ví dụ `transient_backoff_base * (2 ** attempt)`, cận trên hợp lý).
   - Trả về kết quả thành công đầu tiên, hoặc kết quả transient cuối cùng nếu hết lượt.
   - **`_chat_json()` đổi để gọi `_chat_json_with_transient_retry()` thay cho
     `_chat_json_once()`** tại cả hai chỗ (lần gọi đầu và lần hot-retry `invalid_json`).
     Nhờ vậy: retry transport (innermost) và hot-retry `invalid_json` (outer) tách bạch,
     không xung đột — vì `invalid_json` không bao giờ được phân loại là `"transient"`.
   - Backoff phải bị chặn nhỏ (retry ít, backoff ngắn) để không kéo dài tick quá lâu so với
     `timeout_seconds=28`. Có thể truyền timeout rút gọn cho các lần retry để giảm tổng độ trễ.

5. **Thêm transient streak + cooldown (song song invalid_json)**
   - Trong `__init__`: thêm `self._transient_streak = 0` và `self._transient_cooldown_until = 0.0`.
   - Thêm `_transient_cooldown_active()` (mirror `_json_cooldown_active()`).
   - Thêm `_maybe_enter_transient_cooldown()` (mirror `_maybe_enter_json_cooldown()`): nếu
     `_transient_streak >= config.transient_cooldown_threshold` và chưa cooldown thì đặt
     `_transient_cooldown_until = time.time() + config.transient_cooldown_seconds` và log
     **một lần** mức warning.

6. **Cập nhật `_tracked_chat_json()`**
   - Early-return song song: ở đầu hàm, ngoài `_json_cooldown_active()`, thêm
     `if self._transient_cooldown_active(): self._last_error = "transient_cooldown"; return PrivateMindModelResult(ok=False, error="transient_cooldown", error_kind="transient")`.
     (fast-fail, không gọi network — Req 2.4).
   - Nhánh xử lý kết quả:
     - `result.ok`: reset `_invalid_json_streak = 0`, `_transient_streak = 0`,
       `_transient_cooldown_until = 0.0`, `_last_error = ""` (Req 2.5, 3.1).
     - `result.error_kind == "transient"`: `_transient_streak += 1`; gọi
       `_maybe_enter_transient_cooldown()`; reset `_invalid_json_streak = 0`.
     - `result.error == "invalid_json"`: giữ nguyên nhánh cũ (`_invalid_json_streak += 1`,
       `_maybe_enter_json_cooldown()`); reset `_transient_streak = 0`.
     - `error == "invalid_json_cooldown"` / `"transient_cooldown"`: không đụng streak.
     - Còn lại (fixed-config): reset `_invalid_json_streak = 0` và `_transient_streak = 0`
       (giữ nguyên tinh thần "streak phải liên tiếp").

7. **Suppress log lặp trong `evaluate_fragment`/`synthesize_judgment`**
   - Đổi điều kiện log từ `if result.error != "invalid_json_cooldown"` sang kiểm tra tập
     `if result.error not in {"invalid_json_cooldown", "transient_cooldown"}` (Req 2.4: không
     log cảnh báo lặp gây nhiễu khi đang cooldown).

8. **Mở rộng `debug_status()`**
   - Thêm `degraded_cause`: suy từ trạng thái — `"transient"` nếu
     `_transient_cooldown_active()` hoặc `_last_error == "transient_cooldown"` hoặc lỗi gần
     nhất là transient; `"invalid_json"` nếu `_json_cooldown_active()` hoặc `_last_error`
     liên quan invalid_json; ngược lại `""`. (Lưu `error_kind` gần nhất qua một field
     `self._last_error_kind` để phân loại chính xác thay vì so chuỗi.)
   - Thêm `transient_streak`: `self._transient_streak`.
   - Thêm `transient_cooldown_until`: `round(float(self._transient_cooldown_until or 0.0), 3)`.
   - Giữ nguyên toàn bộ field cũ (`api_degraded`, `calls`, `ok_calls`, `usage`, ...) — chỉ
     bổ sung, không xóa/đổi (Req 3.6). `api_degraded` cập nhật thành
     `bool(self._last_error or self._json_cooldown_active() or self._transient_cooldown_active())`.

9. **Thêm field cấu hình env-driven vào `PrivateMindModelAdapterConfig`**
   - `transient_max_retries` ← `ERIS_PRIVATE_MIND_TRANSIENT_RETRIES` (mặc định `2`).
   - `transient_backoff_base` ← `ERIS_PRIVATE_MIND_TRANSIENT_BACKOFF` (giây, mặc định `0.5`).
   - `transient_cooldown_threshold` ← `ERIS_PRIVATE_MIND_TRANSIENT_THRESHOLD` (mặc định `3`).
   - `transient_cooldown_seconds` ← `ERIS_PRIVATE_MIND_TRANSIENT_COOLDOWN` (giây, mặc định `60`).
   - Dùng `_as_float`/`int` với cận dưới hợp lý (giống các field hiện có).

10. **(Tùy chọn, mở rộng nhẹ) `private_mind_loop._model_api_status()`**
    - Đọc thêm `status.get("degraded_cause")` để phơi bày phân loại lên metadata dossier
      (`api_degraded_cause`). Không đổi logic fallback của `tick()`. Đây là tiện ích quan sát,
      không bắt buộc cho tính đúng của bản vá.

## Testing Strategy

### Validation Approach

Hai pha: trước hết **làm lộ counterexample** chứng minh bug trên code CHƯA vá (transient
error không được retry/cooldown), sau đó **xác minh bản vá** retry/backoff/cooldown đúng cho
input transient và **bảo toàn** hành vi cho input không-transient. Tất cả test dùng client
giả lập (fake/mock) để mô phỏng HTTP 5xx/429/timeout — không gọi mạng thật.

### Exploratory Bug Condition Checking

**Goal**: Làm lộ counterexample chứng minh bug TRƯỚC khi vá, xác nhận/bác bỏ root cause.

**Test Plan**: Inject một fake provider client vào adapter qua `llm_service` hoặc qua
`_provider_client` để `create_chat_completion` ném `requests.HTTPError(response.status_code=500)`
hoặc `requests.exceptions.ReadTimeout`. Đếm số lần client được gọi và quan sát cooldown/
`debug_status`. Chạy trên code CHƯA vá để thấy:

**Test Cases**:
1. **HTTP 500 không retry** (sẽ fail trên code chưa vá): fake ném HTTPError 500; assert
   client được gọi >1 lần (mong đợi sau vá) — chưa vá chỉ gọi 1 lần.
2. **ReadTimeout không retry** (sẽ fail trên code chưa vá): fake ném ReadTimeout; assert có
   retry.
3. **Không có circuit-breaker** (sẽ fail trên code chưa vá): gọi nhiều lần liên tiếp đều 503;
   assert `_transient_cooldown_active()` bật sau ngưỡng — chưa vá thì không bao giờ bật.
4. **Edge — HTTP 400** (vẫn pass cả trước/sau vá): fake ném HTTPError 400; assert KHÔNG retry,
   trả `None` ngay (phân loại fixed_config).

**Expected Counterexamples**:
- Client chỉ được gọi đúng 1 lần khi gặp 500/timeout; `debug_status` không có
  `transient_streak`/`transient_cooldown_until`; mỗi tick lại chịu độ trễ đầy đủ.
- Xác nhận root cause: thiếu lớp retry và thiếu phân loại transient.

### Fix Checking

**Goal**: Với mọi input thỏa bug condition, hàm sau khi vá cho hành vi mong đợi.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := chat_json_fixed(input)
  ASSERT retried_with_backoff(result)                       // client gọi 1..(1+max_retries) lần
  ASSERT eventual_success(result) OR none_returned(result)  // khỏi, hoặc None sạch
  ASSERT no_crash(result)
  ASSERT after_threshold_streak ⇒ transient_cooldown_active // chạm ngưỡng thì circuit-breaker bật
  ASSERT debug_status().degraded_cause = "transient"
END FOR
```

### Preservation Checking

**Goal**: Với mọi input KHÔNG thỏa bug condition, hàm sau khi vá cho cùng kết quả như trước khi vá.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT chat_json_original(input) = chat_json_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing được khuyến nghị cho preservation vì nó sinh
nhiều ca tự động trên miền input (JSON hợp lệ ngẫu nhiên, output `invalid_json` ngẫu nhiên,
mã lỗi 4xx ngẫu nhiên), bắt được edge case mà unit test thủ công bỏ sót, và bảo đảm mạnh rằng
hành vi không đổi cho mọi input không-buggy. So sánh được thực hiện giữa một snapshot của hành
vi F (chụp lại trước khi vá) và F' (sau khi vá).

**Test Plan**: Quan sát hành vi trên code CHƯA vá cho JSON hợp lệ, `invalid_json`, và 4xx,
rồi viết property-based test chốt lại hành vi đó và chạy trên code đã vá.

**Test Cases**:
1. **JSON hợp lệ**: fake trả JSON hợp lệ → cùng mapping, `invalid_json_streak`/`transient_streak`
   reset, calls/latency/token đếm đúng.
2. **invalid_json**: fake trả content không-JSON → vẫn chạy hot-retry + salvage + cooldown 120s
   sau streak 3, không bị logic transient can thiệp.
3. **Fixed-config (4xx ngoài 429)**: fake ném HTTPError 401/403 → trả `None` ngay, không retry.
4. **llama_server / llm_service**: với input không-transient, kết quả và số liệu giống hệt
   trước khi vá.

### Unit Tests

- `_classify_transport_exception`: bảng tham số cho HTTPError {400,401,403,429,500,502,503,504},
  ReadTimeout/ConnectTimeout/ConnectionError/Timeout, URLError/socket.timeout → đúng nhãn.
- `_transient_cooldown_active()` / `_maybe_enter_transient_cooldown()`: bật đúng ngưỡng, hết
  hạn đúng thời gian.
- `_tracked_chat_json()` fast-fail khi transient cooldown active: trả `None` ngay, không gọi
  client, không log lặp.
- `debug_status()` chứa `degraded_cause`, `transient_streak`, `transient_cooldown_until` và
  giữ nguyên field cũ.

### Property-Based Tests

- **Fix**: sinh ngẫu nhiên (loại transient ∈ {5xx, 429, timeout, connection}, số lần lỗi liên
  tiếp k) → assert số lần gọi client bị chặn bởi `1 + max_retries`, và `transient_streak`/
  cooldown bật đúng khi k ≥ threshold; loop không crash.
- **Preservation**: sinh ngẫu nhiên kịch bản không-transient (JSON hợp lệ / invalid_json /
  4xx khác / provider llama_server) → assert kết quả và side-effect (streak, calls, token)
  của F' khớp F.
- **Reset**: sinh chuỗi (vài transient error) rồi một success → assert `transient_streak=0`,
  `transient_cooldown_until=0`, `degraded_cause` không còn `"transient"`.

### Integration Tests

- `private_mind_loop.tick()` với adapter inject fake provider 503 lặp lại: assert loop vẫn tạo
  fragments/concerns/judgment qua rule fallback, không crash, và sau ngưỡng thì các tick fast-fail
  (không tốn ~28s mỗi tick).
- Chuyển từ trạng thái transient-degraded sang phục hồi: sau khi cooldown hết hạn và một call
  thành công, tick tiếp theo dùng lại model bình thường.
- `debug_status()` xuyên suốt loop phơi bày `degraded_cause="transient"` để quan sát viên chẩn
  đoán, phân biệt rõ với `invalid_json`.
