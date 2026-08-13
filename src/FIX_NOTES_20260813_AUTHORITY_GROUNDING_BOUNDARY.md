# ERIS hotfix 2026-08-13 — authority, grounding, bounded realization, durable closure

Bản này áp trên `src(20260813-104058).zip` và bao gồm luôn conversation-rhythm hotfix trước đó.

## 1. Semantic winner không còn bị autonomous review cướp

- `runtime/mind_loop.py`
- Cognitive review vẫn được phép sửa evidence/cost/uncertainty trên frame mới.
- Proposal đã được semantic commit chọn được khóa theo `selected_proposal_ref`.
- Review chỉ mở lại competition khi proposal biến mất, coalition không còn hợp lệ, hoặc `commitment_conflict >= 0.95`.
- Review bình thường tạo commit mới có `source=...:review_lock` và `review_conditions += semantic_winner_locked`.
- `cortex/subject/service.py` log/decision trace giờ ghi cả `selected_coalition_id` và `selected_proposal_ref` để audit winner rõ ràng.

## 2. Grounding phân biệt current-world với internal/past conversation

- `runtime/grounding_surface_gate.py`
- Bỏ regex quá rộng coi mọi từ `âm thanh` là current sensor claim.
- Generic sound chỉ bị bắt khi có cấu trúc perception hiện tại (`tôi đang nghe...`, tiếng ... ngoài/trong phòng/lúc này...).
- `SpeechIntent` có `claim_scope` typed: `current_environment`, `past_conversation`, `memory`, `internal_interpretation`, `runtime_context`.
- Surface gate dùng `claim_scope`; retrospective/internal interpretation không bị đòi sensor evidence chỉ vì chứa danh từ tri giác.
- Explicit `tôi đang thấy/nghe...` vẫn bị guard nếu không có evidence.

## 3. Zombie expression commitment được bounded

- `runtime/expression_urge_runtime.py`
- Surface failure được phân loại `transient`, `reformulatable`, `bounded`.
- Duplicate/grounding/claim wording failure: backoff 1 lần, lần semantic failure tiếp theo retire public attempt.
- Provider/transport failure: exponential backoff, tối đa 5 attempt rồi retire public attempt.
- Trong backoff, urge không đánh thức public self-turn và không project thành affordance.
- Retire chỉ đóng expression projection; MentalMaterial/ActiveConcern vẫn sống private.
- Evidence/development mới thật sự có thể reopen một semantic family với failure counter reset.

## 4. Topic closure sống qua restart

- Thêm `runtime/public_topic_boundary.py`.
- Explicit closure (`đi vào dĩ vãng`, `đừng nhắc nữa`, `đổi chủ đề`, `move on`,...) tạo fingerprint nhỏ trong `memory/core/public_topic_boundaries.json`.
- MentalMaterial/ExpressionUrge kiểm tra store này trước public projection.
- Private cognition/rumination vẫn tồn tại.
- Nếu user tự nhắc lại topic đã đóng, boundary được reopen.
- Boundary mặc định có TTL 30 ngày để tránh biến closure cũ thành luật vĩnh viễn.
- `reset_private_mind`/factory-reset tương ứng xóa store này.

## 5. DangerZone preview không còn spam token/manifest

- `body/UdpListener.SettingsDanger.cs`
  - in-flight guard;
  - debounce 1.5 giây;
  - reuse preview/token còn hiệu lực cho cùng action/options.
- `runtime/maintenance_service.py`
  - preview cùng digest được coalesce 2.5 giây ở backend;
  - reuse cùng confirmation token/preview id;
  - cache được kiểm tra trước khi scan affected paths.

## 6. Conversation rhythm hotfix trước đó vẫn được giữ

- explicit topic closure trong `ConversationHandoff`;
- old material/urge mất public floor sau closure;
- foreground user event đã trả lời không được thành reply autonomous thứ hai;
- `UNDERSTAND_USER` có thể materialize thành `user_probe` khi hợp lý;
- Surface được hướng dẫn bridge tự nhiên khi chuyển topic và trả lời trực tiếp khi user hỏi lại/repair.

## Regression

Bộ test tập trung vào các subsystem bị sửa: **93 passed**.

Có chạy full-suite. Failure đầu tiên là `tests/runtime_scenarios/test_long_runtime_scenarios.py::test_long_engagement_survives_fifteen_minutes_and_restart` (`foreground["kind"]` thiếu). Test này được chạy lại trên source gốc `src(20260813-104058).zip` và fail y hệt, nên không phải regression của hotfix này.
