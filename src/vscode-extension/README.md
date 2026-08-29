# Eris Code — V79

Eris Code là **VS Code shell mỏng dùng GitPilot làm coding brain**. V79 bổ sung Coding Observation Spine để Eris Desktop hiểu GitPilot đã làm gì mà không chen vào execution loop.

## Luồng chính

```text
User
 ↓
Eris Code UI
 ↓
GitPilot
 Explorer → Planner → Coder → Reviewer → Validation
 ↓ SSE
Eris Code observation normalizer
 ↓ best-effort
Eris Desktop journal / flow interpreter
```

## Cài backend trong monorepo

```powershell
powershell -ExecutionPolicy Bypass -File .\services\gitpilot\setup_eris_code_backend.ps1
```

Chạy thủ công khi cần:

```powershell
.\services\gitpilot\run_eris_code_backend.ps1
```

Backend mặc định: `http://127.0.0.1:8000`.

## Local workspace

Git repo dùng `local_git`, folder thường dùng `folder`. Local session đi qua `/api/v2/chat/stream` multi-agent path.

- **Plan / Inspect:** read-only.
- **Ask:** mutation qua `ApprovalGate` GitPilot.
- **Auto:** GitPilot xử lý theo permission mode của nó.

## Eris Link v2

`erisCode.erisLink.enabled=false` mặc định (opt-in). Khi bật, nó vẫn là **best-effort**. Extension không launch Desktop. Nếu Desktop đóng, request localhost fail-silent và task GitPilot vẫn chạy.

V79 gửi sang Desktop các event đã sanitize; không gửi raw `read_file` content hay hidden chain-of-thought.

Muốn tắt:

```text
erisCode.erisLink.enabled=false
```

## Invariant kiểm thử

1. Desktop OFF + VS Code/GitPilot ON → coding đầy đủ.
2. VS Code OFF + Desktop ON → Desktop hoạt động bình thường.
3. Eris Link không có route command/approval/workspace mutation.
4. GitPilot vẫn là coding owner duy nhất.
