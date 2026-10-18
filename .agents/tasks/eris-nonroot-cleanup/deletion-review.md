# Review: Xóa 2 lane mồ côi (companion model routing + background living user observer)

Commit `8548f714` gỡ hai module runtime không có call site production: `companion_model_routing.py` (318 dòng) và `background_living_user_observer.py` (221 dòng). Đi kèm là gỡ một dòng import mồ côi ở orchestrator, gỡ một phần tử tuple getattr phòng thủ ở coordinator_shutdown, và dọn các test chỉ phục vụ hai lane đó. Cách tiếp cận đúng với cảnh báo phương pháp trong tài liệu tri thức: coder grep call site thật trước khi xóa, không suy từ "import tồn tại" ra "lane được gọi".

Watch for: không có blocker. Toàn bộ nghi ngờ trong brief đã được kiểm độc lập và sạch — không còn tham chiếu gãy (confirmed), `AdaptiveCompanionService` + test không bị đụng (confirmed), `coordinator_shutdown.py` không còn nhánh chết (confirmed), các test bị xóa chỉ thuộc hai lane mồ côi (confirmed), và test lane sống (curator regression, router production) được giữ nguyên (confirmed).

**Verdict**: APPROVED

## High-level view

Việc xóa nằm gọn trong commit `8548f714`, không phải trong working tree (working tree có thay đổi tutor/learning_core không liên quan, nằm ngoài phạm vi review này). Diff của commit khớp từng dòng với `task1-verification.md`.

Hai module bị xóa đều mồ côi. `route_companion_turn` chỉ được import ở `orchestrator.py` (dòng import duy nhất, không có call site) và được gỡ sạch. `background_living_user_observer` chỉ xuất hiện như một nhánh `getattr(... None)` phòng thủ trong vòng lặp shutdown; sau khi gỡ, vòng lặp còn `("background_memory_digest",)` — một tuple một phần tử hợp lệ, reader `background_memory_digest` còn nguyên, không có NameError hay nhánh chết.

Biên với lane sống được giữ đúng. `AdaptiveCompanionService` (companion stance policy — khác hẳn companion model routing) và test `test_adaptive_companion_integration_v91.py` không bị commit này chạm vào. Regression guard curator (`lane_policy("memory_curator")` optional=False, concurrency=1 — tài liệu tri thức yêu cầu giữ) được bảo toàn. Hai test router production (writer→deepseek, escalation client) được giữ và không phụ thuộc symbol đã xóa.

Test `test_elegant_runtime_hardening.py` thay lời gọi `route_companion_turn(...)` bằng stub dict `{"reasons": (...)}`. Thay thế này trung thực về hành vi: `compile_public_reply_context` chỉ đọc `route` qua `_route_reasons`, hàm này nhận cả Mapping (`.get("reasons")`) lẫn object (`.reasons`) lẫn `None`; không đọc `tier`/`thinking_mode`. Ý định test (gating budget/archive theo reason) được giữ nguyên.

Bằng chứng verify đầy đủ và tái lập được: có py_compile, có import thật, có pytest. Review đã chạy lại tập test focused và grep độc lập để xác nhận.

<details>
<summary>Issues (0)</summary>

Không có finding. Không blocker, không nit cần sửa trước khi ship.

</details>

<details>
<summary>Details</summary>

### Phạm vi thực tế của thay đổi: commit 8548f714, không phải working tree

Khi mở repo, `git status` cho thấy working tree có một loạt file đã sửa (tutor, learning_core, các test conversation) nhưng KHÔNG thấy việc xóa hai lane mồ côi. Lý do: việc xóa đã được commit thành `8548f714` (HEAD), và hai file nguồn không còn tồn tại trong workspace chính (chỉ còn trong `.worktrees/`, nằm ngoài phạm vi). Các thay đổi working tree hiện tại là công việc khác, không thuộc nhiệm vụ này.

Vì vậy review bám vào `git show 8548f714`. Diff của commit khớp chính xác danh sách file và số dòng trong `task1-verification.md`: xóa `companion_model_routing.py` (-318), `background_living_user_observer.py` (-221); sửa `orchestrator.py` (-1), `coordinator_shutdown.py`, bốn file test; thêm `task1-verification.md`. (confirmed)

### Không còn tham chiếu gãy trong src/

`git grep -n -E "route_companion_turn|CompanionModelRouter|CompanionRoutingPolicy|CompanionRouteDecision|BackgroundLivingUserObserverService|background_living_user_observer|companion_model_routing|build_background_living_user_observer_service|BackgroundLivingUserObserverConfig" HEAD -- src/` trả về exit code 1 (no match). Kiểm bằng `git grep` tại HEAD loại trừ `.worktrees/` một cách tự nhiên vì worktree không phải tracked tree của HEAD chính. Grep tool của editor cũng trả no match. Dòng `from runtime.companion_model_routing import route_companion_turn` ở `orchestrator.py:26` đã được gỡ; import `compile_public_reply_context` (compiler còn sống) được giữ. (confirmed)

### coordinator_shutdown.py: tuple một phần tử, không nhánh chết

```python
for background_name in ("background_memory_digest",):
    background_service = getattr(self, background_name, None)
    if background_service is not None:
        try:
            background_service.stop()
        except Exception as exc:
            self.logger.debug("[%s] stop error: %s", background_name, exc)
```

Phần tử `"background_living_user_observer"` đã bị gỡ khỏi tuple. Vòng lặp còn một phần tử hợp lệ, giữ nguyên cơ chế getattr phòng thủ cho `background_memory_digest` (reader này vẫn còn). Không để lại tên biến treo, không NameError, không nhánh code chết. (confirmed)

### AdaptiveCompanionService và test không bị đụng

`git log` cho `src/runtime/adaptive_companion.py` và `src/tests/test_adaptive_companion_integration_v91.py` dừng ở commit `0ae42eb0` (feature V91), không phải `8548f714`. `git show 8548f714 --stat` không liệt kê file nào tên `adaptive_companion`. Coder không nhầm companion stance policy (còn sống) với companion model routing (đã xóa). Đây đúng là điểm dễ nhầm mà brief lo ngại, và nó sạch. (confirmed)

### Các test bị xóa/sửa: chỉ chạm lane mồ côi, giữ lane sống

- `test_companion_model_routing_v36.py`: gỡ import mồ côi + 7 test gọi trực tiếp `route_companion_turn`/`CompanionRoutingPolicy`. GIỮ `test_runtime_public_writer_passes_route_thinking_to_deepseek` và `test_deepseek_default_escalation_client_reuses_main_key` — cả hai test đường production (`AIRuntimeModelRouter.generate_public_reply`, `RemoteModelProcessManager.build_escalation_client`), đọc lại file xác nhận không import symbol đã xóa. (confirmed)
- `test_background_living_user_observer.py`: gỡ test khởi tạo service mồ côi. GIỮ `test_curator_lane_is_not_shed_during_active_chat` — test này kiểm `lane_policy("memory_curator")` (optional=False, max_concurrency=1), chính là regression guard curator mà tài liệu tri thức (mục 2) yêu cầu giữ. Nó không phụ thuộc service đã xóa. (confirmed)
- `test_settings_schema_v13.py`: gỡ import `CompanionRoutingPolicy` + test `test_companion_routing_policy_reads_live_settings`, và gỡ luôn import `get_runtime_settings_store`/`reset_runtime_settings_store_for_tests` không còn dùng. GIỮ `test_v12_settings_migrate_companion_routing_defaults` — dùng `RuntimeSettingsStore._migrate_payload`, một method store production. File còn lại không tham chiếu symbol đã gỡ (grep xác nhận). (confirmed)
- `test_elegant_runtime_hardening.py`: thay `route = route_companion_turn(...)` bằng stub `{"reasons": (...)}`. `_route_reasons` trong `public_reply_context.py` chỉ đọc khóa/attr `reasons` và chấp nhận Mapping/object/None, nên stub trung thực về hành vi; ý định test gating budget được giữ. (confirmed)

Quyết định KHÔNG sửa `runtime_settings_store.py` (giữ các field config `companion_*` dạng default trơ không còn reader) là hợp lý: đó là quyết định sản phẩm riêng, và sửa sẽ phá test migration `test_v12_settings_migrate_companion_routing_defaults`. Không đổi hành vi user thấy. (confirmed)

### Bằng chứng verify: đủ và tái lập được

`task1-verification.md` liệt kê nguyên văn ba lớp bằng chứng: py_compile hai file production đã sửa (EXIT 0), import thật hai module (`IMPORT_OK`, EXIT 0), và pytest tập test liên quan (`13 passed in 1.10s`). Không có chuyện "skip test vì thiếu môi trường". Review đã chạy lại tập pytest focused một cách độc lập trong venv repo và nhận `13 passed in 1.02s` — khớp. Grep cuối trong file verify cũng được tái lập bằng `git grep` tại HEAD. Không thiếu bằng chứng, không cần chạy lại full suite. (confirmed)

</details>

<details>
<summary>File map</summary>

Thay đổi thuộc commit `8548f714` (không phải working tree). Xem đầy đủ: `git show 8548f714`.

- `src/runtime/companion_model_routing.py` — XÓA toàn bộ (lane model routing mồ côi).
- `src/runtime/background_living_user_observer.py` — XÓA toàn bộ (observer nền mồ côi).
- `src/runtime/ai_orchestrated/orchestrator.py` — gỡ dòng import `route_companion_turn`.
- `src/runtime/coordinator_shutdown.py` — gỡ phần tử tuple `background_living_user_observer` trong vòng lặp shutdown.
- `src/tests/test_background_living_user_observer.py` — gỡ test service mồ côi; giữ regression curator lane.
- `src/tests/test_companion_model_routing_v36.py` — gỡ 7 test symbol đã xóa; giữ 2 test router production.
- `src/tests/test_elegant_runtime_hardening.py` — thay lời gọi route bằng stub dict reasons.
- `src/tests/test_settings_schema_v13.py` — gỡ test policy mồ côi + import thừa; giữ test migration store.
- `.agents/tasks/eris-nonroot-cleanup/task1-verification.md` — THÊM bằng chứng verify.

</details>
