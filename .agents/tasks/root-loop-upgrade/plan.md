# Implementation Plan — Root agent-loop upgrade (Kiro-style)

Nâng cấp `RuntimeModelRootAgent.decide()` trong `src/runtime/conversation/agent.py` bằng 3 cải tiến: self-verify trước finalize, parallel non-finalize tool trong một iteration, và trần bước động. Model nền là DeepSeek Whale; nhãn `inference_tier="subconscious_4b"` KHÔNG đổi. Biên công khai `ConversationDecision = NoReply | NextConversationMove` bất biến.

Tất cả đường dẫn tuyệt đối tính theo worktree: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\root-loop-upgrade`.

## Bối cảnh đã khảo sát (grounded)

- `agent.py::RuntimeModelRootAgent.decide()` là vòng `for step_index in range(self.max_root_steps)`: gọi `self._root_session.ask(...)` → nếu `None` rơi về one-shot `invoke(...)` → parse `kind` → finalize (`move`/`no_reply`) hoặc chạy tool (`use_capability`/`recall_memory`/`continue_thinking`/`set_note`/`clear_note`) rồi `continue`. `still_active()` được check đầu mỗi vòng và ngay sau khi model trả.
- Finalize `move` xảy ra ở nhánh: `if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say")))`. Đây là điểm chèn self-verify.
- `_root_session.ask()` BỊ KHÓA vào `ROOT_STEP_SCHEMA` (truyền cố định). Mọi schema khác (verify/batch) phải đi qua one-shot `router.invoke_structured_worker(client, system=, payload=, schema=, name=, max_tokens=, reasoning_effort=, inference_tier="subconscious_4b", cognitive_lane=, priority=, temperature=)` — chữ ký đã xác nhận trong `src/runtime/ai_orchestrated/model_router.py:1597`.
- RÀNG BUỘC TEST HIỆN CÓ (phải giữ xanh): `test_root_choice_freedom_v12.py::test_root_understands_one_principle_allows_multiple_actions_without_new_form` assert `len(ROOT_STEP_SCHEMA["oneOf"]) == 7`; `test_eris02_root_agency.py::test_root_step_schema_has_internal_actions_but_public_move_contract_unmodified` assert tập kind == đúng 7 kind hiện có và move chỉ có 5 field. => **KHÔNG thêm kind mới vào `ROOT_STEP_SCHEMA`.** Verify và batch dùng SCHEMA RIÊNG qua one-shot invoke.
- Kernel (`kernel.py`) sau `agent.decide()` tự re-check `generation`/`active_run_id`; `__root_run_active` = `current_run.generation == state.generation and current_run.active_run_id == run_id`. Hợp đồng preempt: `decide()` trả `NoReply(reason="root_turn_preempted")` khi `still_active()` False. Không được phá.
- Fingerprint dedup: `prior_actions` set chứa `"memory:<query>"` và `"cap:<name>:<json-args>"`. Phải tái dùng nguyên vẹn trong batch.
- `continue_thinking` đếm `reflection_count`, giới hạn `> 2`. Phải giữ khi batch.
- Fake router test pattern: `_Router`/`FakeRouter` có `executive_client = object()` và `invoke_structured_worker(_client, **kwargs)` trả lần lượt từ hàng đợi `results`/`steps`. `still_active` được bơm qua `runtime_context["__root_run_active"]`.
- Lệnh test (đã xác nhận chạy, baseline 25 passed): `python -m pytest src/tests/conversation/<file> -q` từ gốc worktree (pytest.ini đặt `pythonpath = src .`, `testpaths = src/tests`).

## Quyết định thiết kế (rationale ngắn)

1. **Verify = sub-call one-shot, schema riêng `VERIFY_SCHEMA`** (không thêm kind vào `ROOT_STEP_SCHEMA`). Lý do: giữ 2 test schema-shape xanh; verify là bước meta trên một move đã có, không phải một action loop bình thường. Đánh đổi: thêm đúng 1 lượt model mỗi lần finalize move (độ trễ tăng — xem mục Độ trễ). Fail-soft dễ: lỗi/raw rác → dùng move gốc.
2. **Batch = schema riêng `ROOT_BATCH_STEP_SCHEMA` chỉ dùng khi gọi qua one-shot `invoke`** cho non-finalize. Lý do tương tự: không phá `ROOT_STEP_SCHEMA`. Để model BIẾT có thể batch, bổ sung mô tả vào system prompt (một câu) và cho phép phần tử `batch` trong schema one-shot. `_root_session.ask()` vẫn trả single action (schema cũ) — batch chỉ kích hoạt trên nhánh fallback one-shot HOẶC khi raw trả về `kind=batch`. Đánh đổi: batch không khả dụng khi session warm-up đang chạy ngon (ask trả single); chấp nhận được vì batch là tối ưu, không bắt buộc. Finalize (`move`/`no_reply`) KHÔNG BAO GIỜ trong batch.
   - Phương án B đã cân nhắc & loại: thêm `kind=batch` vào `ROOT_STEP_SCHEMA` → phá 2 test. Loại.
3. **Trần động**: giữ `max_root_steps` clamp 2..12 làm trần CỨNG; nâng default 6→8. Thêm bộ đếm `no_progress_streak`: nếu một step tạo tool_result mới toàn `duplicate`/`empty`/`failed`/`limit_reached` thì +1, nếu có result "mới có nghĩa" (status khác các giá trị trên, và khác result trước đó) thì reset về 0. `no_progress_streak >= 2` → ép finalize sớm (degraded nếu user_turn, no_reply nếu không). `still_active()` vẫn check mỗi bước.

## Độ trễ tăng thêm

Self-verify thêm đúng 1 model round-trip (one-shot, `max_tokens` nhỏ ~400) mỗi lần finalize một `move`. `no_reply` KHÔNG verify → autonomous/continuation im lặng không chịu phí. Verify tối đa 1 lần/finalize (nếu verify trả move khác thì dùng luôn, không verify tiếp) → trần phí là +1 round-trip. Batch GIẢM số round-trip (gộp N tool vào 1 lượt kế), bù lại phần nào. Trần động không thêm phí; nó cắt sớm nên có thể giảm phí.

## Thứ tự công việc (mỗi mục một commit riêng)

- [ ] 1. **Cải tiến 1 — Self-verify trước khi finalize `move`.**
      Thêm `VERIFY_SCHEMA` (module-level: oneOf của 3 kind `confirm` / `revise`(có intent/say/delivery/after) / `withdraw`). Tách nhánh finalize move trong `decide()` thành gọi helper mới `self._verify_move(...)`: helper build payload gồm intent/say/delivery/after + recent_history + câu hỏi tự kiểm (đạt intent? lặp recent_history? hợp affect/relationship/personality? vi phạm điều user vừa cấm như hỏi ngược?), gọi one-shot `invoke_structured_worker(client, schema=VERIFY_SCHEMA, name="eris_root_self_verify_v12", max_tokens=400, inference_tier="subconscious_4b", cognitive_lane="root_conversation", reasoning_effort="low", temperature=0.2)`. Trả: confirm→move gốc; revise→`NextConversationMove.from_mapping` của move mới (KHÔNG verify tiếp); withdraw→`NoReply(reason="withdrawn_after_self_verify")`. Trước và sau verify check `still_active()` → `NoReply("root_turn_preempted")`. Fail-soft: exception/raw không phải Mapping/kind lạ → trả move gốc. Verify TỐI ĐA 1 lần/finalize. Log `[root-agent] self_verify step=%d outcome=confirm|revise|withdraw` (chỉ loại, không nội dung). Lưu ý: nhánh finalize move hiện gồm cả đường implicit (`event.kind=="user_turn" and (intent or say)`) — cả hai đi qua verify.
      Files: `src/runtime/conversation/agent.py`, `src/tests/conversation/test_root_self_verify_v12.py` (mới)
      Verify: `python -m pytest src/tests/conversation/test_root_self_verify_v12.py src/tests/conversation/test_root_decision_v12.py src/tests/conversation/test_eris02_root_agency.py src/tests/conversation/test_root_choice_freedom_v12.py -q` — tất cả xanh (test cũ không hồi quy).

- [ ] 2. **Cải tiến 2 — Parallel non-finalize tool trong một iteration.**
      Thêm `ROOT_BATCH_STEP_SCHEMA` (module-level: như `ROOT_STEP_SCHEMA` cộng một kind `batch` với `actions: [<non-finalize>]`, min 1 max 4; non-finalize = recall_memory/use_capability/continue_thinking/set_note/clear_note). Trong `decide()`: khi `raw.get("kind")=="batch"`, tách phần thực thi tool hiện có thành helper `self._run_single_action(raw, ...) -> dict|None` (trả tool_result dict hoặc None nếu là finalize) và dùng lại cho cả single-step lẫn từng phần tử batch. Lặp qua `actions` (tối đa 4): mỗi action check `still_active()` giữa chừng (preempt→`NoReply("root_turn_preempted")`), áp dụng dedup `prior_actions`, `continue_thinking` vẫn +`reflection_count` (không lách giới hạn 2), lỗi một action ghi vào tool_results chứ không dừng cả batch. Gom hết tool_results rồi `continue` sang vòng model kế. Nếu bất kỳ phần tử nào là move/no_reply (schema cấm, nhưng phòng thủ) → bỏ qua phần tử đó. Để model biết có thể batch: thêm MỘT câu vào system prompt + chỉ truyền `ROOT_BATCH_STEP_SCHEMA` trên nhánh one-shot `invoke` (nhánh `ask()` vẫn `ROOT_STEP_SCHEMA`).
      Files: `src/runtime/conversation/agent.py`, `src/tests/conversation/test_root_parallel_tools_v12.py` (mới)
      Verify: `python -m pytest src/tests/conversation/test_root_parallel_tools_v12.py src/tests/conversation/test_eris02_root_agency.py src/tests/conversation/test_root_choice_freedom_v12.py -q` — xanh (giữ assert `len(ROOT_STEP_SCHEMA["oneOf"]) == 7`).

- [ ] 3. **Cải tiến 3 — Trần bước động.**
      Nâng default `max_root_steps` 6→8 (giữ clamp 2..12). Thêm theo dõi tiến triển trong vòng `decide()`: sau mỗi step có tool_result, phân loại "có nghĩa" vs "trì trệ" (duplicate/empty/failed/limit_reached/unavailable). Giữ `no_progress_streak`; +1 khi step chỉ tạo result trì trệ hoặc trùng result trước, reset 0 khi có result mới có nghĩa. `no_progress_streak >= 2` → thoát loop và trả degraded (user_turn) hoặc `NoReply("no_progress")` (khác). Khi đang tiến triển, cho dùng tới trần cứng. `still_active()` giữ nguyên mỗi bước.
      Files: `src/runtime/conversation/agent.py`, `src/tests/conversation/test_root_dynamic_budget_v12.py` (mới)
      Verify: `python -m pytest src/tests/conversation/test_root_dynamic_budget_v12.py src/tests/conversation/test_root_decision_v12.py src/tests/conversation/test_eris02_root_agency.py -q` — xanh.

- [ ] 4. **Regression toàn cục conversation.**
      Chạy toàn bộ suite hội thoại để chắc không hồi quy biên public/kernel/single-writer.
      Files: (không sửa)
      Verify: `python -m pytest src/tests/conversation -q` — tất cả xanh.

## 9 kịch bản test bắt buộc → ánh xạ test mới

1. Verify confirm giữ nguyên move → `test_self_verify_confirm_keeps_move` (FEAT-001).
2. Verify revise dùng move mới, KHÔNG verify tiếp → `test_self_verify_revise_uses_new_move_without_reverify` (FEAT-001).
3. Verify withdraw → NoReply → `test_self_verify_withdraw_becomes_no_reply` (FEAT-001).
4. Verify lỗi/timeout/rác → dùng move gốc (fail-soft) → `test_self_verify_failsoft_keeps_original_move` (FEAT-001).
5. Preempt giữa verify → NoReply(root_turn_preempted) → `test_self_verify_preempt_returns_preempted` (FEAT-001).
6. Batch non-finalize chạy hết, gom tool_results, 1 lượt model kế → `test_batch_runs_all_non_finalize_actions` (FEAT-002).
7. Batch dedup + continue_thinking vẫn đếm reflection + preempt giữa batch + fail-soft một action → `test_batch_respects_dedup_reflection_preempt_failsoft` (FEAT-002).
8. No-progress 2 bước liên tiếp → ép finalize sớm → `test_no_progress_streak_forces_early_finalize` (FEAT-003).
9. Đang tiến triển (result mới khác) → được dùng tới trần cứng → `test_progress_allows_up_to_hard_ceiling` (FEAT-003).

(no_reply không verify được kiểm trong FEAT-001 như một assertion phụ của kịch bản 3/4.)
