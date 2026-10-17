# Nhiệm vụ 1 — Xóa 2 lane mồ côi: kết quả verify

Ngày: 2026-10-17. Workspace chính `c:/Users/Gtvkun/Documents/GitHub/eris`
(không dùng worktree). Chỉ sửa `src/` chính; bỏ qua `.worktrees/`.

## Bối cảnh đã đọc trước khi sửa

- `docs/knowledge/2026-10-14-eris-runtime-lessons.md`
- `.agents/tasks/eris-nonroot-lanes/nonroot-lanes-status-report.md`

Cảnh báo phương pháp (import/flag/config bật KHÔNG chứng minh lane được gọi)
được tuân thủ: đã kiểm call site thật bằng grep trước khi xóa.

## A) Companion MODEL routing — grep call site trước khi sửa

Grep `src/**/*.py` cho `route_companion_turn|CompanionModelRouter|CompanionRoutingPolicy|CompanionRouteDecision`:

- `src/runtime/companion_model_routing.py` — chính là định nghĩa (file nguồn).
- `src/runtime/ai_orchestrated/orchestrator.py:26` — chỉ **import** `route_companion_turn`;
  grep toàn orchestrator KHÔNG thấy nó được **gọi** (không có call site production).
- `src/tests/test_companion_model_routing_v36.py` — test gọi `route_companion_turn` /
  `CompanionRoutingPolicy`.
- `src/tests/test_elegant_runtime_hardening.py` — hai test dùng `route_companion_turn`
  chỉ để tạo một `route` cho `compile_public_reply_context` (compiler này CÒN SỐNG,
  đọc `route.reasons` phòng thủ, nhận cả `route=None`).
- `src/tests/test_settings_schema_v13.py` — import `CompanionRoutingPolicy` cho một
  test đọc `from_runtime()`.

Xác nhận KHÔNG nhầm với `AdaptiveCompanionService` (`src/runtime/adaptive_companion.py`):
không đụng tới file đó.

Ghi chú về `runtime_settings_store.py`: store production còn các field config
`companion_*` và migration v12→v13 đặt chúng; các field này chỉ được đọc bởi
`CompanionRoutingPolicy.from_runtime()` (code mồ côi). Sau khi xóa, các field trở
thành default trơ, KHÔNG có reader — không đổi hành vi user thấy. KHÔNG sửa
`runtime_settings_store.py` vì đó là quyết định sản phẩm khác (và sẽ phá
test migration `test_v12_settings_migrate_companion_routing_defaults`, vốn test
hành vi migration của store chứ không phải routing mồ côi).

## B) BackgroundLivingUserObserverService — grep call site trước khi sửa

Grep `src/**/*.py` cho `BackgroundLivingUserObserverService` / `background_living_user_observer`:

- `src/runtime/background_living_user_observer.py` — file nguồn.
- `src/runtime/coordinator_shutdown.py:146` — chỉ là `getattr(self, "background_living_user_observer", None)`
  phòng thủ trong vòng lặp shutdown; attribute này KHÔNG được set ở bất kỳ đâu
  trong production (đã grep xác nhận). Không có constructor production.
- `src/tests/test_background_living_user_observer.py` — một test khởi tạo service
  trực tiếp; một test khác (`test_curator_lane_is_not_shed_during_active_chat`)
  chỉ kiểm `lane_policy("memory_curator")` (regression guard curator required/
  concurrency=1 được tài liệu tri thức yêu cầu GIỮ) — KHÔNG phụ thuộc service.

## File đã xóa

- `src/runtime/companion_model_routing.py` (toàn bộ nội dung chỉ phục vụ companion
  model routing: `route_companion_turn`, `CompanionRoutingPolicy`,
  `CompanionRouteDecision`, `CompanionModelRouter` + helper riêng).
- `src/runtime/background_living_user_observer.py` (toàn bộ:
  `BackgroundLivingUserObserverService`, `BackgroundLivingUserObserverConfig`,
  `build_background_living_user_observer_service`, ...).

## File đã sửa

- `src/runtime/ai_orchestrated/orchestrator.py` — gỡ dòng import mồ côi
  `from runtime.companion_model_routing import route_companion_turn`. Giữ nguyên
  import `compile_public_reply_context` (compiler còn sống, ngoài phạm vi).
- `src/runtime/coordinator_shutdown.py` — gỡ `"background_living_user_observer"`
  khỏi tuple vòng lặp shutdown, còn lại `("background_memory_digest",)`.
- `src/tests/test_background_living_user_observer.py` — gỡ import + test khởi tạo
  service mồ côi; GIỮ `test_curator_lane_is_not_shed_during_active_chat`.
- `src/tests/test_companion_model_routing_v36.py` — gỡ import mồ côi + 7 test gọi
  trực tiếp `route_companion_turn`/`CompanionRoutingPolicy`; GIỮ hai test test
  router production (`test_runtime_public_writer_passes_route_thinking_to_deepseek`,
  `test_deepseek_default_escalation_client_reuses_main_key`) — chúng không phụ
  thuộc symbol đã xóa.
- `src/tests/test_elegant_runtime_hardening.py` — thay `route = route_companion_turn(...)`
  bằng stub `route = {"reasons": (...)}` (compiler chỉ đọc `reasons`), giữ nguyên
  ý định test budget của `compile_public_reply_context`.
- `src/tests/test_settings_schema_v13.py` — gỡ import `CompanionRoutingPolicy` +
  test `test_companion_routing_policy_reads_live_settings`; GIỮ test migration
  `test_v12_settings_migrate_companion_routing_defaults` (test store production).

## Lệnh verify đã chạy (nguyên văn) + kết quả

Venv repo: `c:/Users/Gtvkun/Documents/GitHub/eris/.venv` — Python 3.12.10.

1. py_compile hai file production đã sửa:

```
.\.venv\Scripts\python.exe -m py_compile src/runtime/ai_orchestrated/orchestrator.py src/runtime/coordinator_shutdown.py
```
Kết quả: EXIT 0 (PASS, không lỗi biên dịch).

2. Import thật hai module đã sửa:

```
$env:PYTHONPATH="src;."
.\.venv\Scripts\python.exe -c "import runtime.ai_orchestrated.orchestrator; import runtime.coordinator_shutdown; print('IMPORT_OK')"
```
Kết quả: in `IMPORT_OK`, EXIT 0 (PASS — không gãy import sau khi xóa).

3. pytest các test liên quan (companion, living_user/curator, orchestrator/compiler, settings):

```
.\.venv\Scripts\python.exe -m pytest src/tests/test_background_living_user_observer.py src/tests/test_companion_model_routing_v36.py src/tests/test_elegant_runtime_hardening.py src/tests/test_settings_schema_v13.py -q
```
Kết quả: `13 passed in 1.10s` (PASS).

## Grep cuối cùng chứng minh không còn tham chiếu gãy

Grep `src/**/*.py`:

- `route_companion_turn|CompanionModelRouter|CompanionRoutingPolicy|CompanionRouteDecision|BackgroundLivingUserObserverService|background_living_user_observer`
  → **No matches found**.
- `companion_model_routing|build_background_living_user_observer_service|BackgroundLivingUserObserverConfig`
  → **No matches found**.

Không còn import/tham chiếu gãy nào tới hai lane mồ côi trong `src/`.
