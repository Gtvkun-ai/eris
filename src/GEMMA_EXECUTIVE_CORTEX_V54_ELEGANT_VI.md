# Gemma Executive Cortex v54 Elegant

## Mục tiêu

v54 hoàn tất ba ranh giới còn dang dở ở v53:

1. `ExecutiveState` không còn chỉ là ghi chú prompt. Policy do Gemma tạo ra thực sự quyết định khi nào autonomous deliberation được mở lại.
2. Runtime không cắt catalog theo thứ tự registry hay `top 8`. Gemma tự shortlist capability theo `capability_goal`; runtime chỉ lọc các ràng buộc cơ học.
3. Capability call dùng exact `capability_id` và JSON arguments được validate bằng schema. Chuỗi legacy chỉ được tạo tại execution boundary cho các handler cũ.

Không có shadow router, semantic alias, marker phrase hoặc fallback authority song song.

## Quyền sở hữu

```text
DeepSeek Observer / Inner / Seed / conversation sources
                         │
                         ▼
                 Affordance Collector
                  chỉ peek, chưa claim
                         │
                         ▼
                Gemma 4 31B Executive
       trajectory + policy + affordance/capability ID
                         │
                         ▼
                   Runtime Kernel
 atomic claim + availability + schema + permission + execution
                         │
                         ▼
                  DeepSeek Surface
                    public wording
```

- DeepSeek workers tạo observation, private reflection, premise và wording.
- Gemma là semantic authority duy nhất cho bước tiếp theo.
- Runtime không diễn giải lại ý định. Runtime chỉ kiểm sự thật cơ học và thực thi exact ID.
- Surface không được đổi semantic target hoặc tự chọn tool.

## 1. Executive policy điều khiển nhịp thật

Gemma trả policy typed:

```json
{
  "phase": "quiet_presence",
  "trajectory": "allow_topic_to_rest",
  "reconsider_on": ["new_user_turn", "strong_seed"],
  "review_after_seconds": 90
}
```

`ExecutiveState` lưu:

- `phase`
- `trajectory`
- `reconsider_on`
- `review_due_at`
- `preferred_lane`
- `retry_not_before`

`SelfTurnPipeline._should_deliberate()` chuyển runtime facts thành event typed, ví dụ:

- `structured_due`
- `followup_due`
- `open_discourse`
- `meaningful_scene_change`
- `activity_event`
- `strong_seed`
- `discovery_ready`
- `internal_pressure`
- `affordance_changed`

Sau đó nó gọi `ExecutiveCortex.should_reconsider()`.

Nếu event không nằm trong policy và timer chưa đến hạn, Gemma không được gọi lại. Các probe interval và soft-silence heuristic cũ đã bị xóa khỏi authority path.

Nếu Gemma/transport trả kết quả không hợp lệ, runtime đặt retry backoff và fail-closed thành silence. Lỗi API không còn tạo vòng gọi dồn dập hoặc quay về selector cũ.

## 2. Semantic capability retrieval do Gemma sở hữu

### Bước A: yêu cầu discovery

Gemma tạo mục tiêu semantic:

```json
{
  "action": "discover_capabilities",
  "capability_goal": "đọc nội dung có nghĩa đang hiển thị trên màn hình",
  "required_effect": "observe",
  "capability_domain": "environment",
  "maximum_risk": "low"
}
```

### Bước B: runtime chỉ hard-filter

Runtime lọc theo:

- capability đang registered và available
- exposure cho Executive
- effect/domain được yêu cầu
- risk ceiling

Runtime không xếp hạng theo keyword, synonym hay thứ tự registry và không cắt `top 8`.

### Bước C: Gemma shortlist compact cards

Nếu tập còn lớn hơn sáu tool, Gemma nhận compact semantic cards gồm exact ID, title, description, effect, domain, risk và constraints. Gemma trả tối đa sáu `capability_ids`.

Runtime chỉ chấp nhận ID có trong tập vừa offer. ID bịa hoặc stale bị reject, không được alias hay “sửa giúp”.

### Bước D: chỉ materialize schema của shortlist

Gemma chỉ nhận full input schema cho các ID đã shortlist, rồi chọn một exact ID và arguments phù hợp schema.

```json
{
  "action": "select_capability",
  "capability_id": "read_visible_ui_text",
  "capability_arguments": {
    "scope": "active_window"
  }
}
```

## 3. Typed arguments và compatibility boundary

`actions/capability_registry.py` khai schema input cho toàn bộ 38 system capability IDs hiện có.

Ví dụ:

```json
{
  "capability_id": "set_volume",
  "input_schema": {
    "type": "object",
    "properties": {
      "level": {
        "type": "integer",
        "minimum": 0,
        "maximum": 100
      }
    },
    "required": ["level"],
    "additionalProperties": false
  }
}
```

Trước executor:

1. Exact ID phải nằm trong offer đã xác minh.
2. Arguments phải qua `validate_capability_arguments()`.
3. Permission/risk policy phải cho phép.
4. Chỉ tại execution boundary, `encode_capability_arguments()` mới chuyển JSON typed sang định dạng chuỗi mà một số handler cũ còn yêu cầu.

Adapter này là cơ học theo exact capability ID. Nó không đổi capability, không suy đoán user intent và không chứa semantic alias.

## 4. Interactive chat

Direct user chat dùng `eris.interactive_executive_directive.v2`.

Khi cần tool/capability:

```text
user turn
    ↓
Gemma semantic discovery + shortlist + exact selection
    ↓
runtime schema/permission validation
    ↓
exact tool execution
    ↓
verified result trở thành public truth
    ↓
DeepSeek viết câu trả lời
```

DeepSeek planner không được chọn tool. Runtime không đọc lại user text để đổi tool.

## 5. Failure semantics

- Invalid Gemma response: silence + bounded retry backoff.
- Stale affordance/state revision: reject, không tự lấy candidate khác.
- Invented capability ID: reject.
- Invalid arguments: reject trước executor.
- Autonomous side-effect tool không được tự chạy nếu permission policy không cho phép.
- Tool result đã verified có quyền cao hơn lời dự kiến của model.

## Những thứ cố ý vẫn deterministic

- concurrency và atomic claim
- state revision/cancellation
- TTS lifecycle
- availability/permission/risk
- JSON schema validation
- exact duplicate protection
- execution và evidence commit

Marker sân khấu/avatar không phải semantic tool routing nên không thuộc phạm vi xóa.

## Kiểm thử

- 25 test v54 tập trung vào Executive authority, policy, semantic shortlist, exact-ID và typed arguments: passed.
- Regression rộng, loại các test phụ thuộc package `tools.*` không có trong archive nguồn: 703 passed.
- `test_pdf_inference_refactor.py`: 28 passed, 5 failed; cả năm lỗi chỉ do bốn module `tools.*` không có trong archive.
- Full collection còn lỗi ở các test yêu cầu `tools.package_source` và `tools.evaluate_social_plan_activation`, cũng là thiếu hụt của archive nguồn.
- Compile toàn bộ module liên quan: passed.

Không có live Gemini call vì gói nguồn không chứa credential thử nghiệm. Model transport được kiểm bằng fake clients/pools và contract tests.

## Hạn chế còn lại

Một số execution handler cũ vẫn nhận chuỗi. v54 cô lập tương thích này tại exact execution boundary thay vì để planner/runtime semantic layer dùng chuỗi. Việc chuyển từng handler sang nhận object typed trực tiếp có thể làm dần mà không thay đổi authority model.
