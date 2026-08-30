# Eris Link v2 — context + coding observation

V79 giữ Eris Desktop và Eris Code là **hai runtime độc lập**. Link chỉ là loopback interoperability boundary, không phải shared agent runtime.

## 1. Desktop -> Eris Code: context evidence

```text
GET /v1/context?workspace=<absolute-workspace-root>
```

Eris Code có thể lấy environment/project memory rồi đưa vào task dưới dạng observation. Đây là evidence, không phải coding command.

## 2. Eris Code -> Desktop: telemetry append-only

```text
POST /v1/coding/observations
Content-Type: application/json
```

Payload dùng schema `eris.coding.observation.v1` và chỉ chứa dữ kiện quan sát được:

```json
{
  "schema": "eris.coding.observation.v1",
  "source": "eris-code/gitpilot",
  "task_id": "gp_...",
  "session_id": "...",
  "workspace": "C:/repo",
  "actor": "explorer",
  "event_type": "tool_started",
  "tool": "Read local file",
  "files": ["runtime/shadow.py"],
  "at": 0
}
```

Không gửi raw `read_file` result, terminal spam, hidden chain-of-thought hoặc provider secret. `phase_summary` chỉ là output explicit mà Explorer/Planner/Coder/Reviewer đã chủ động trả về.

## 3. Debug/read endpoints

```text
GET /v1/coding/journal?task_id=<id>&limit=120
GET /v1/coding/flow?task_id=<id>
GET /v1/mentor/state
```

Các endpoint này chỉ đọc journal/snapshot trong Desktop. `mentor/state` là audit projection V80; không có API chỉnh skill hoặc ép teaching mode.

## Boundary bắt buộc

Không tồn tại các route sau qua Eris Link:

```text
coding/control
coding/approve
coding/terminal
coding/write-file
coding/select-model
```

Nếu Desktop tắt, Eris Code bỏ qua telemetry và GitPilot tiếp tục coding bình thường. Nếu Eris Code tắt, Desktop vẫn hoạt động như trước.
