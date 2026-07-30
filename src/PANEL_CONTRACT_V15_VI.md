# PANEL CONTRACT V15

## Identity control protocol

Request:

```json
{
  "type": "identity_control",
  "request_id": "uuid-or-client-id",
  "action": "set_learning | snapshot | reset_mood | reset_relationship | reset_discovery",
  "enabled": true
}
```

`enabled` chỉ dùng cho `set_learning`.

Response:

```json
{
  "type": "identity_control_ack",
  "parse_mode": "identity_control_ack",
  "identity_control_ack": {
    "request_id": "uuid-or-client-id",
    "action": "set_learning",
    "ok": true,
    "result": "...",
    "data": {}
  }
}
```

### Ownership

- `set_learning`, `reset_mood`, `reset_relationship`: identity reducer/state event path.
- `snapshot`: identity consolidator.
- `reset_discovery`: discovery runtime.

Panel không được ghi trực tiếp các store tương ứng và không được dùng debug command làm API quản trị chính.

## Identity runtime panel contract

`identity_runtime.controls` công bố:

```json
{
  "schema": "eris.identity_control.v1",
  "transport": "identity_control",
  "actions": {
    "set_learning": {"owner": "identity_reducer", "fields": ["enabled"]},
    "snapshot": {"owner": "identity_consolidator", "fields": []},
    "reset_mood": {"owner": "identity_reducer", "fields": []},
    "reset_relationship": {"owner": "identity_reducer", "fields": []},
    "reset_discovery": {"owner": "discovery_runtime", "fields": []}
  }
}
```

UI phải dùng `discovery_runtime.initiative` cho trạng thái chủ động. Không tạo `speech_drive` giả từ mood, defense hoặc discovery candidate.

## Inner state panel contract

`private_mind_digest` công bố:

- `schema: eris.inner_state.panel.v1`
- `generated_at`
- `authority`
- `latest_intention`
- `open_loops`
- `active_conflict`
- `activated_defenses`
- `active_motives`
- `value_choice`
- `discovery`
- `expression`

`authority.memory_echo` hiện là `not_provided_by_this_contract`. UI không được gắn nhãn memory recall cho open loop hoặc discovery data.

Transport compaction phải giữ `schema`, `generated_at` và `authority` để panel có thể hiển thị provenance/freshness đúng.

## Tutor persistence wording

Research stage không đồng nghĩa với phần trăm hoàn thành. UI chỉ được thông báo persistence khi event có cờ xác nhận tương ứng.

## Compatibility

- Debug command cũ vẫn tồn tại cho developer tooling.
- Identity Panel mới không phụ thuộc debug command.
- Private mind packet legacy vẫn có thể được panel đọc ở chế độ LEGACY.
