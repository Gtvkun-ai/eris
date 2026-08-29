# Eris Code — V78

Eris Code là **VS Code shell mỏng dùng GitPilot làm coding brain**. Eris Desktop không còn nằm trên coding execution path.

## Boundary

```text
Eris Desktop (optional)
  └─ observation / project memory read-only
            ↓
Eris Code
  └─ VS Code UI + IDE observation + approval renderer
            ↓
GitPilot
  └─ Explorer → Planner → Coder → Reviewer + tools + provider API
            ↓
Local workspace
```

V78 cố ý không tự viết planner/coder/reviewer/patch engine/terminal agent trong Eris Code. Những việc đó thuộc GitPilot.

## Cài backend trong monorepo

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\services\gitpilot\setup_eris_code_backend.ps1
```

Script tạo `services/gitpilot/.venv` rồi `pip install -e services/gitpilot`. Extension sẽ ưu tiên executable trong venv này.

Chạy thủ công nếu cần:

```powershell
.\services\gitpilot\run_eris_code_backend.ps1
```

Mặc định backend ở `http://127.0.0.1:8000`.

## Local workspace

Eris Code luôn tạo `local_git` session khi folder hiện tại là Git repo, nếu không thì dùng `folder` session. Local session đi qua SSE multi-agent path của GitPilot; Eris Code không gọi `/api/chat/send` làm coding fallback.

Các mode:

- **Plan / Inspect:** read-only.
- **Ask:** mutation phải đi qua `ApprovalGate` GitPilot.
- **Auto:** GitPilot tự approve theo permission mode của chính nó.

## Eris Desktop link

`erisCode.erisLink.enabled=false` mặc định. Khi bật, extension chỉ đọc context từ Desktop. Desktop không được approve tool, sửa workspace hay điều khiển GitPilot qua link này.

## Invariant kiểm thử

1. Desktop OFF + VS Code/GitPilot ON → coding vẫn đầy đủ.
2. VS Code OFF + Desktop ON → Eris Desktop vẫn hoạt động bình thường.
3. Không có source path nào trong extension launch `run_eris*`.
