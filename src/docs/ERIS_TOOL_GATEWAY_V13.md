# ERIS Tool Gateway V13 — thay luồng capability Root cũ

## Phạm vi

Patch này **thay đường điều phối RootAgent trong phiên chat**, không viết lại Subject Core, SandboxWorld hay các handler desktop/project. Các handler và schema thấp hơn vẫn được tái sử dụng để giữ quyền/kiểm chứng.

**Bị loại khỏi đường Root production:**

- Root step `use_capability` với enum `tutor | work | research | action`.
- `ActionCapability` adapter (Root → action) và `WorkCapability` (Root → legacy `agent_harness`) trong `AIChatOrchestrator._run_v12`.
- Yêu cầu một tác vụ coding one-shot `project_execute_task` qua Root. Tool này đã bị đánh dấu `callable=False`.
- Phụ thuộc vào `powers/*/SKILL.md` để Root có thể gọi công cụ. Bộ não không cần skill loader cũ.

**Vẫn giữ:**

- `actions/capability_registry.py`: nguồn dữ liệu ID / mô tả / typed input schema.
- `actions/capability_runtime.py`: trạng thái thực tế (`available`) từ runtime.
- `actions/executor.py`: cầu typed tool → Subject Core → SandboxWorld; **không gọi `_execute_unchecked` từ gateway**.
- `runtime/conversation/context.py` (receipt/evidence): Writer vẫn cần chứng cứ theo `event_id`, `generation`, `run_id`. `ToolReceiptLedger` cung cấp một registry trống, chỉ ghi receipt, không route lệnh.
- `TutorCapability` và `ResearchCapability`: **domain intelligence** không phát public speech; được đăng ký như tool có schema qua gateway.
- `runtime/capabilities/work.py` và `action.py`: giữ file legacy vì các entry khác / tests vẫn có thể import. Chúng **không còn được dựng/gọi từ Root production**. Muốn xóa toàn cục phải migrate cả IDE/legacy tests và hợp đồng `WorkResult` từ coordinator riêng.

## Luồng V13

```text
User turns / runtime observation
        |
        v
RootAgent LLM --(tool_discover: query, group)--> ToolGateway.live_catalog
        |                                       - dynamic availability
        |                                       - only callable IDs
        |                                       - no old one-shot work
        +--(tool_describe: exact ID)------------> exact typed schema
        |
        +--(tool_call: exact ID, typed args)----> ToolGateway
                                                    |
                              availability recheck + validation (fail closed)
                                                    |
                              +---------------------+----------------------+
                              |                                            |
                      OS/project tool                              Domain-only tool
                    ActionExecutor                                  Tutor / Research
                              |                                            |
                        Subject Core                            advice / start / snapshot
                              |                                            |
                         SandboxWorld                                     |
                              +---------------------+----------------------+
                                                    |
                                       normalized execution receipt
                                      completed / dispatched / started /
                                           failed / unavailable
                                                    |
                           RootAgent observes evidence -> final move/no_reply
                                                    |
                              RuntimeWriter / ClaimEvidence checks receipts
```

Root vẫn là nơi **quyết định chọn công cụ**. Gateway chỉ trả inventory/schema, kiểm tra hợp lệ và thực thi ID model chỉ định. Không thêm intent classifier, keyword planner, ngữ nghĩa song song hay agent loop thứ hai. Tìm kiếm lexical trong `discover` là **retrieval**, không tự route hay gọi tool.

## Hợp đồng JSON giữa model và runtime

```json
{"kind":"tool_discover","query":"đọc file project"}
{"kind":"tool_describe","tool_id":"project_read_file"}
{"kind":"tool_call","tool_id":"project_read_file","arguments":{"path":"README.md"}}
{"kind":"move","intent":"Trình bày điều đọc được","say":"...","delivery":"rõ ràng","after":"wait_user"}
```

Root payload chứa `tool_inventory` (số tool available, nhóm tool). Danh sách thực tế thay đổi theo runtime, không nhúng vĩnh viễn vào system prompt. Muốn gọi tool, model phải discover/describe; trước mỗi call gateway kiểm tra lại availability và schema. Tool `context_only`, retired, unknown ID không thể gọi.

## Quy tắc kết quả

- `completed`: executor xác nhận action observed hoặc domain tool đã **trả kết quả**. Với action side effect, dùng evidence từ executor; không tự nâng cấp dispatch thành observed.
- `dispatched`: hệ thống đã gửi yêu cầu hành động nhưng **chưa chứng minh tác động đã hoàn tất**; Writer không được nói như đã hoàn thành.
- `started`: tác vụ nghiên cứu bất đồng bộ vừa bắt đầu, **không phải kết quả nghiên cứu**.
- `failed`, `invalid`, `unavailable`, `duplicate`: không phải evidence thành công, không được suy diễn là thực thi xong.

Mọi tool result chỉ được đưa vào receipt ledger khi có `conversation_run_id`. Writer chỉ chấp nhận receipt cùng đúng `event_id/session_id/generation/run_id`. `__root_tool_gateway` là dependency private, không serialize object Python vào model.

## Cách đưa patch vào project

1. Sao lưu branch hiện tại hoặc tạo branch `refactor/tool-gateway-v13`.
2. Giải nén ZIP patch tại thư mục chứa **`src/`** của ERIS, chọn ghi đè các file trùng.
3. Kiểm tra diff, đặc biệt `src/runtime/conversation/agent.py` và `src/runtime/ai_orchestrated/orchestrator.py`.
4. Ở repo root, chạy:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     src/tests/conversation/test_tool_gateway_v13.py \
     src/tests/conversation/test_root_decision_v12.py \
     src/tests/conversation/test_root_parallel_tools_v12.py \
     src/tests/conversation/test_root_dynamic_budget_v12.py \
     src/tests/conversation/test_root_session_bootstrap_v12.py \
     src/tests/conversation/test_root_choice_freedom_v12.py \
     src/tests/conversation/test_eris02_root_agency.py \
     src/tests/conversation/test_capability_boundaries_v12.py
   ```

5. Chạy ERIS trên Windows với Subject Core và Sandbox thật. Thử một yêu cầu read-only (`get_local_time`, `project_list_files`), một action desktop được cấp quyền (`launch_app`), một call có đối số sai, một action bị disable và một flow sửa code/verify trong workspace test riêng.

### Những gì đã kiểm thử

- Unit test mock/fail-closed cho dynamic discovery, schema, availability recheck, dedup, batch, preemption, receipt.
- E2E Root (fake model + fake ActionExecutor) theo luồng discover → describe → execute → final.
- `ActionExecutor` thật **không có SubjectCore/Sandbox** trả failed, không thực thi trái phép.

### Chưa được kiểm thử/không cam kết

- DeepSeek thực sự chọn đúng tool qua nhiều câu hỏi tự nhiên; cần integration run với LLM thật.
- Chạy app, xử lý tệp và permission thật trên Windows; môi trường kiểm thử patch là Linux, không có OS service ERIS.
- Việc thực thi một tác vụ coding dài tự động; Root hiện gọi **các primitive nhỏ** qua loop có trần 8–12 bước, không thay cho long-running agent/task scheduler.
- Bộ test toàn repo; một số test legacy liên quan trực tiếp V12 đã được cập nhật sang protocol mới, các bộ còn lại phải chạy sau merge.

## Rollback

Khôi phục từ Git hoặc branch backup, nhất là hai file Root/Orchestrator. Không đổi định dạng DB hoặc config, không cần migration dữ liệu.
