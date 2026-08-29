# Changelog

## 0.19.0 — V78 GitPilot Cutover

- Eris Code độc lập runtime với Eris Desktop; không còn `ErisClient`, `ErisServiceManager`, `run_eris*` hay `eris.service.*`.
- Coding owner duy nhất trong VS Code là GitPilot.
- Local workspace dùng `/api/v2/chat/stream` và GitPilot team thật thay vì direct-LLM fallback.
- Approval/cancel được chuyển về `ApprovalGate` của GitPilot.
- Auto-start ưu tiên `services/gitpilot/.venv` trong monorepo rồi mới fallback `gitpilot` trên PATH.
- Eris Link vẫn optional/read-only; Desktop tắt thì coding vẫn chạy.

## 0.18.0

- Tách Eris Code khỏi Eris Desktop runtime.
- Thêm GitPilot REST client và observer link tùy chọn.
