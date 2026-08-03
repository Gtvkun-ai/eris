# Ghi chú kiến trúc: bốn trọng tâm public speech

Tài liệu này mô tả đúng bốn thay đổi được khóa trong bản chỉnh sửa. Không mở
thêm lane mới, không “tiện tay” đại tu phần khác. Kỷ luật phạm vi, một phát minh
hiếm hoi nhưng hữu ích.

## 1. Một quyền tạo public intent

- `IntentPlanner` sở hữu public intent của chat.
- `SocialInitiative` sở hữu public intent autonomous.
- `InitiativeController` chỉ là governor: kiểm baton, busy, cooldown, budget,
  duplicate và provenance; không tự nghĩ topic, không viết câu.
- `SurfaceIntentEngine` chỉ nhận intent có `owner` thuộc allow-list
  `intent_planner | social_initiative`, sau đó viết wording.
- `PrivateMind`, `PrivateLife`, inner diary và tutor chỉ cung cấp state, memory
  hoặc semantic context. Queue speech cũ của PrivateMind/PrivateLife mặc định bị
  khóa bằng `architecture.private_cognition_surface_export=false`.

## 2. Không fallback chéo âm thầm

- Seed/random-chat worker không có seed hợp lệ thì im.
- Surface unavailable hoặc lỗi schema thì pipeline trả body-only/silence.
- Companion, critic và observer không được giả làm Surface.
- Generic social liveness fallback cũ mặc định tắt.
- Các đường cũ vẫn còn sau feature flag để rollback có chủ đích:
  - `surface_cross_worker_fallback`
  - `legacy_social_fallback_enabled`
  - `private_cognition_surface_export`

## 3. Tắt lane không dùng khỏi startup mặc định

Các lane sau không được tạo client/thread ở startup mặc định:

- local/open-model/style legacy (`legacy_model_lanes_enabled=false`).
- Inner diary model call (`inner_diary_model_enabled=false`); renderer local vẫn
  dựng diary từ state hiện có.
- Tutor/research nền (`background_tutor_enabled=false`).
- Social fallback worker cũ.
- `ERIS_FORCE_LOCAL_GGUF` đổi mặc định từ bật sang tắt.

Code chưa bị xóa. Bật lại phải là quyết định config rõ ràng, không phải side
effect vì một client khác đang có sẵn.

## 4. Khóa race và trace

- Candidate từ continuation/arc/agenda được atomic claim trước model call.
- `SpeechIntent` mang `trace_id`, `generation_epoch` và `claim_token`.
- `generation_epoch` dùng `turn_seq` của lần claim; kết quả cũ bị chặn bởi các
  user-input preemption checks và speech epoch trong TTS.
- User input được kiểm tra trước deliberation, trước Surface, sau Surface và ngay
  trước public commit.
- Trace JSONL dùng cùng `trace_id` xuyên các stage:

  `candidate -> governor -> surface -> tts -> outcome`

- Trace chỉ ghi ID, enum và metadata phẳng; không ghi raw OCR, private context hay
  prompt đầy đủ.

## Feature flags mặc định

```json
{
  "architecture": {
    "private_cognition_surface_export": false,
    "surface_cross_worker_fallback": false,
    "legacy_model_lanes_enabled": false,
    "inner_diary_model_enabled": false,
    "background_tutor_enabled": false,
    "legacy_social_fallback_enabled": false,
    "event_trace_enabled": true
  }
}
```

## Phụ lục refactor cấu trúc

- Cortex heartbeat đã được gom vào `runtime/ai_orchestrated/cortex/` theo bốn
  lớp: contract, dependency composition, policy và runtime pipeline.
- `runtime/ai_orchestrated/cortex_runtime.py` chỉ còn là compatibility import;
  không còn logic hoặc class riêng.
- Dependency mặc định dùng `core.di.resolve_dependency()`, chỉ thay dependency
  khi giá trị inject là `None`; object hợp lệ nhưng falsey không còn bị nuốt.
- Tên nội bộ gắn với một model cụ thể đã đổi sang `LocalModel`/`OpenModel`.
  Chuỗi provider cũ chỉ nằm ở `llm/model_catalog.py` để giữ tương thích cấu hình.
