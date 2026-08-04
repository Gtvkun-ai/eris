# GEMMA EXECUTIVE CORTEX V55 — PRODUCTION ELEGANT

## Mục tiêu

V55 hoàn tất các ranh giới còn dang dở của V54 mà không thêm semantic authority thứ hai:

- DeepSeek Observer, Inner và Seed tạo nhận định hoặc affordance.
- Gemma 4 31B là authority duy nhất chọn trajectory, affordance và capability ID.
- Runtime chỉ công bố fact, lọc hard constraint, validate, claim, permission và execute.
- DeepSeek Surface sở hữu câu public cuối.

Không có shadow router, marker fallback hay alias capability để “dịch hộ” quyết định của Gemma.

## Luồng autonomous

```text
runtime facts + scored events
          ↓
DeepSeek affordance sources (peek only)
          ↓
Gemma Executive policy gate
          ↓
silence | body_only | exact affordance | exact capability
          ↓
atomic claim + governor + permission
          ↓
DeepSeek Surface
          ↓
typed capability-claim guard
          ↓
public commit / TTS
```

## Luồng direct chat có capability

```text
user turn
   ↓
Gemma interactive directive, không sửa conversation policy
   ↓
semantic capability goal + hard filters
   ↓
Gemma shortlist exact IDs
   ↓
Gemma chọn exact capability_id + JSON arguments
   ↓
runtime schema validation
   ↓
Decision.capability_arguments
   ↓
ActionExecutor.execute_capability()
   ↓
legacy handler adapter tại exact execution boundary
   ↓
verified result + DeepSeek wording
```

## Thay đổi chính

### 1. Interactive state tách khỏi conversation policy

`plan_interactive()` trả `InteractiveExecutiveDirective` tạm thời và không gọi `_update_state()`.
Một câu hỏi kỹ thuật về tool không thể đổi `phase`, `trajectory`, `reconsider_on`, `review_due_at` hay `preferred_lane` của autonomous conversation.

### 2. Executive policy thực sự có persistence

`ExecutiveState` được lưu dưới schema `eris.executive_state.v2`.

- Runtime policy dùng clock được inject, kể cả monotonic clock.
- Persistence dùng wall-clock riêng.
- Khi restart, deadline wall-clock được đổi lại sang clock domain mới.
- State quá cũ bị bỏ.
- Failure backoff không được persist qua restart.

### 3. Runtime chỉ phát factual scored events

Scheduler không còn tự đổi tên fact thành kết luận như `meaningful_scene_change` hoặc `strong_seed`.
Nó phát envelope:

```json
{
  "kind": "scene_delta",
  "strength": 0.72,
  "source": "ambient_screen_tracker",
  "revision": 42,
  "metadata": {}
}
```

Gemma policy định nghĩa threshold bằng `ReviewCondition {kind, minimum_strength}`.

### 4. Capability contracts hoàn chỉnh 46/46

Mọi `CapabilityDefinition` có input contract rõ ràng.
Tám sensor/context capability được khai:

- `exposure="context_only"`
- `callable=false`
- `mode="context_only"`

Chúng vẫn cung cấp context nhưng không xuất hiện như executable tool cho Gemma.
Import-time invariant chặn registry nếu definition và contract lệch nhau.

### 5. Typed arguments xuyên qua planning và execution

`Decision` có `capability_arguments: dict | None`.
Runtime giữ JSON object đến `ActionExecutor.execute_capability()`.
Executor validate theo exact capability contract rồi mới encode một lần tại legacy handler boundary.
Không model, planner hay router nào được chuyển nghĩa bằng chuỗi.

### 6. Exact ID, không alias semantic

Parser chỉ nhận exact capability ID.
System-action aliases đã bị xóa.
Parameter normalization bên trong một capability, ví dụ tên app trong `launch_app`, vẫn là adapter tham số và không đổi capability.

### 7. Typed self-capability claim guard

Public reply bắt buộc có `self_capability_claims`:

```json
{
  "capability_id": "read_visible_ui_text",
  "state": "available | unavailable | uncertain",
  "basis": "..."
}
```

Guard chỉ kiểm exact ID với live registry và verified executive directive.
Nó không parse câu chữ để chọn tool.
Claim mâu thuẫn bị fail-closed trước public commit.

## Invariants

1. Collect trước, claim sau.
2. Chỉ Gemma chọn semantic trajectory và exact capability ID.
3. Runtime không reinterpret user text sau Gemma.
4. DeepSeek planner không chọn tool.
5. Capability không được offer thì không thể invoke.
6. Arguments sai schema bị reject trước executor.
7. Autonomous side-effect capability không tự chạy.
8. Interactive capability planning không làm bẩn autonomous policy.
9. State revision hoặc affordance stale thì không lấy phương án kế tiếp ngầm.
10. Capability claim trái runtime fact không được public commit.

## Kiểm thử

- 33 test V55 authority, persistence, event envelope, contracts và claim guard: passed.
- 153 test sát Architecture C, direct chat và public schema: passed.
- Regression rộng: 739 passed.
- 5 test còn fail và 3 file test không collect do source gốc thiếu package `tools.*`:
  - `tools.package_source`
  - `tools.evaluate_social_plan_activation`
  - `tools.report_pdf_acceptance`
  - `tools.evaluate_semantic_paraphrases`
  - `tools.audit_remote_inference_paths`
  - `tools.audit_semantic_authority_paths`
- Compile toàn source: passed.
- Chưa thực hiện live Gemini call vì archive không có credential thử nghiệm.

## Giới hạn còn lại

Các handler cũ bên dưới `ActionExecutor` vẫn nhận chuỗi. V55 cô lập việc chuyển JSON sang chuỗi tại exact execution boundary; đây không còn là semantic routing. Có thể migrate từng handler sang `Mapping[str, Any]` mà không đổi authority model.

Live soak test với Gemma 4 31B vẫn cần để đo silence ratio, policy churn, JSON validity, shortlist stability và initiative quality. Đây là kiểm nghiệm vận hành, không phải một lớp kiến trúc còn thiếu.
