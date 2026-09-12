# Eris Link v2 — V90 companion observation

Eris Desktop và Eris Code là hai runtime độc lập. Link là interoperability boundary read-mostly, không phải shared agent runtime.

## Desktop → Eris Code

```text
GET /v1/context?workspace=<absolute-workspace-root>
```

Chỉ cung cấp environment/project-memory context; không phải coding command.

## Eris Code → Desktop

```text
POST /v1/coding/observations
Content-Type: application/json
```

Schema vẫn backward-compatible `eris.coding.observation.v1`, nhưng V90 có các source rõ provenance:

```text
eris-code/gitpilot
eris-code/workspace
eris-code/user
eris-code/external-agent
```

Các event V90 thêm: `workspace_session_started/ended`, `user_intent`, `editor_focus`, `file_saved`, `file_created`, `file_deleted`, `file_renamed`, `terminal_command`.

Không gửi raw `read_file` result, raw source, terminal spam, hidden chain-of-thought hoặc provider secret.

## Read-only diagnostics

```text
GET /v1/coding/journal?task_id=<id>&limit=120
GET /v1/coding/flow?task_id=<id>
GET /v1/companion/state?workspace=<root>
GET /v1/mentor/state
GET /v1/mentor/profile
```

`/v1/companion/state` trả projection nhỏ về workspace hiện tại; không có endpoint set/command tương ứng.

## Boundary bắt buộc

Không tồn tại qua Eris Link:

```text
coding/control
coding/approve
coding/terminal
coding/write-file
coding/select-model
```

Desktop tắt → telemetry best-effort bị bỏ qua và coding tiếp tục. Coding agent tắt/đổi agent → workspace observation vẫn cho Eris awareness cơ bản.
