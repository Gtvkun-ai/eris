# Gemma Executive Cortex v53 Clean

## Mục tiêu

Bản v53 xóa mô hình hai authority song song. Gemma 4 31B là authority duy nhất quyết định trajectory hội thoại và chọn capability theo ID chính xác. DeepSeek tiếp tục sở hữu các lane chuyên biệt như Observer, Inner, Seed và Surface. Runtime chỉ giữ state cơ học, permission, concurrency, claim atomic và execution evidence.

Không có shadow router, không giữ legacy semantic fallback và không dùng phrase/regex marker để ánh xạ câu người dùng sang capability.

## Quyền sở hữu

| Thành phần | Quyền |
|---|---|
| DeepSeek Observer | Mô tả sự kiện và các cách hiểu có thể có |
| DeepSeek Inner | Suy nghĩ riêng, relationship digest, user hypothesis |
| DeepSeek Seed | Sinh premise mở chuyện |
| Gemma Executive | Chọn trajectory, affordance, semantic target và capability ID |
| Runtime Governor | Timing, permission, risk, concurrency, stale revision |
| DeepSeek Surface | Viết lời public từ semantic target đã chọn |
| Runtime executor | Thực thi đúng capability ID và trả evidence |

## Luồng autonomous

```text
perception + discourse + DeepSeek lane digests
                    ↓
Affordance Collector.peek()
  continuation / arc / agenda / reminder / seed / scene
                    ↓
Gemma Executive deliberation
  silence | body_only | select_affordance | discover/invoke capability
                    ↓
Runtime atomic claim đúng affordance_id + revision
                    ↓
Initiative Governor
                    ↓
Grounding preflight
                    ↓
DeepSeek Surface
                    ↓
commit + TTS
```

Các nguồn chỉ được `peek`; không nguồn nào được `claim_due()` trước khi Gemma chọn. Nếu affordance stale hoặc revision đã đổi, runtime fail-closed thành im lặng. Runtime không tự lấy candidate tiếp theo theo priority cũ.

## Luồng chat trực tiếp

```text
user turn
   ↓
Gemma Executive nhận capability index theo effect/domain
   ↓ khi cần
bounded capability retrieval (tối đa 8 contract đang sống)
   ↓
Gemma chọn exact capability_id trong tập đã được offer
   ↓
DeepSeek planner/surface xử lý nội dung, không có quyền chọn tool
   ↓
Runtime validate ID, availability, risk, permission và input
   ↓
ActionExecutor thực thi
   ↓
verified ActionExecutionResult sở hữu public truth
```

Nếu capability thực thi thành công hoặc thất bại với result xác minh được, result đó ghi đè lời model. Điều này ngăn trường hợp runtime vừa đọc màn hình thành công nhưng lời public vẫn nói “tôi không thể nhìn thấy”.

## Capability discovery không dùng marker

Mỗi `CapabilityDefinition` phải khai báo:

- `id`
- `description_vi`
- `effect`: `observe`, `read`, `write`, `control` hoặc `inspect`
- `risk_level`
- runtime availability và permission metadata

Gemma ban đầu chỉ thấy index effect/domain. Khi yêu cầu discovery, runtime trả tối đa 8 capability phù hợp và đang sống. Gemma chỉ được chọn một `capability_id` nằm trong tập đã offer. Runtime không đọc lại câu user để đổi sang tool khác.

Các marker/authority đã xóa:

- `actions/router.py` và toàn bộ `ActionRouter` bootstrap plumbing
- capability phrase/example lists
- action alias map trong capability registry/executor
- `resolve_intention(text)` và `execute_intention(text)`
- legacy social liveness fallback và rollout flag
- pre-claim priority continuation → arc → agenda
- DeepSeek planner tool selection authority
- alias tool trong `llm/service.py`, ví dụ `volume_up → set_volume`
- full registry dump vào Gemma

Các parser tag sân khấu như `(cười nhẹ)` vẫn tồn tại vì chỉ bóc stage motion khỏi lời public; chúng không chọn capability và không tham gia semantic authority.

## Failure policy

- Gemma unavailable hoặc output invalid trong autonomous flow: im lặng, không gọi legacy selector.
- Gemma unavailable trong chat trực tiếp: chat vẫn có thể trả lời, nhưng không được tự khẳng định capability không có căn cứ.
- Affordance stale: im lặng.
- Capability ID không nằm trong tập đã offer: reject.
- Capability unavailable: reject với runtime reason.
- Autonomous tool có side effect: reject; chỉ read-only auto-call được phép.
- State revision đổi trong lúc model chạy: discard quyết định cũ.

## Executive state

Gemma giữ `ExecutiveState` trong phiên gồm phase, trajectory, preferred lane và điều kiện xem xét lại. State này hiện là session-memory, chưa persist qua restart. Runtime facts và affordance revision vẫn là nguồn sự thật, nên state cũ không được vượt qua stale guard.

## Cấu hình

```text
ERIS_EXECUTIVE_CORTEX_ENABLED=1
ERIS_EXECUTIVE_MODEL=gemma-4-31b-it
ERIS_EXECUTIVE_TIMEOUT_S=18
```

Gemma dùng Gemini key pool hiện có. DeepSeek worker ownership không thay đổi.

## Kiểm thử

- 38 test sát Executive/authority passed.
- Compile toàn bộ module liên quan passed.
- Regression rộng: 725 passed, 5 failed.
- 5 failure đều do archive nguồn thiếu bốn module `tools.*` được import bởi `tests/test_pdf_inference_refactor.py`:
  - `tools.report_pdf_acceptance`
  - `tools.evaluate_semantic_paraphrases`
  - `tools.audit_remote_inference_paths`
  - `tools.audit_semantic_authority_paths`

Không có credential trong archive để thực hiện live Gemini call; transport và policy được kiểm bằng fake client/key pool.

## Giới hạn còn lại

Capability selection đã typed và exact theo ID. Tuy nhiên một số handler cũ vẫn nhận `action_input` dạng chuỗi thay vì JSON schema riêng cho từng tool. Runtime không reinterpret capability ID, nhưng validation tham số chưa đồng nhất hoàn toàn. Đây là boundary cũ còn lại, không phải semantic router, và nên được chuyển từng handler sang typed arguments ở phiên bản sau thay vì đại tu đồng thời với authority cutover.
