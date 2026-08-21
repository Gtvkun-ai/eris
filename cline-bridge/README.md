# eris-cline-bridge

Sidecar Node.js nhỏ làm cầu nối giữa **Eris Brain (Python)** và **Cline SDK (@cline/core)**.

## Kiến trúc

```
Eris Python Backend
        │
        │ HTTP POST /task
        ▼
  cline-bridge (Node.js, port 7832)
        │
        │ @cline/core LocalRuntimeHost
        ▼
  Cline Agent Loop
  (tool loop, file ops, terminal, diff)
        │
        │ events → POST callback URL hoặc stdout
        ▼
  Eris Python Backend nhận events
        │
        ▼
  Eris WebSocket → VS Code Extension
```

## Setup

```bash
cd cline-bridge
npm install
npm run build       # tạo dist/bridge.js
npm start           # chạy bridge ở port 7832
```

## Env vars

| Var | Default | Mô tả |
|-----|---------|-------|
| `ERIS_BRIDGE_PORT` | `7832` | Port HTTP server |
| `ERIS_CALLBACK_URL` | (none) | URL Python nhận events qua POST |
| `ERIS_BRIDGE_TOKEN` | (none) | Bearer token bảo vệ API |

## API

### `POST /task`

Bắt đầu CodingTask mới (non-blocking).

```json
{
  "task_id": "task_abc123",
  "goal": "fix bug X in module Y",
  "workspace_path": "/path/to/repo",
  "task_mode": "inspect",
  "repo_context": { "context_pack": "...", "confidence": 0.9 },
  "model": "claude-sonnet-4-5"
}
```

Response `202`:
```json
{ "task_id": "task_abc123", "status": "running" }
```

### `GET /task/:id`

Poll trạng thái + 50 events gần nhất.

### `POST /task/:id/control`

```json
{ "action": "stop" }
```

### `GET /health`

```json
{ "status": "ok", "activeTasks": 1 }
```

## Python usage

```python
from runtime.agent_harness.cline_bridge_client import ClineBridgeClient

bridge = ClineBridgeClient()
bridge._ensure_started()  # start process nếu chưa chạy

if bridge.is_available():
    # Shadow mode: chạy song song với agent loop cũ
    result = bridge.run_task_shadow(
        task_id="task_abc",
        goal="explain how this module works",
        workspace_path="/path/to/repo",
        task_mode="inspect",
        on_event=lambda e: print(e),  # nhận realtime events
    )
    print(result)
```

## Phase map

| Phase | Cline làm | graph_builder.py |
|-------|-----------|-----------------|
| **A** (hiện tại) | chạy song song, không làm gì | vẫn primary |
| **B** | xử lý inspect tasks | chỉ execute tasks |
| **C** | xử lý cả execute tasks | bypass |
| **D** | primary | xóa |
