# Changelog

## 0.20.0 — V79 Coding Observation Spine

- Release hardening: xóa source legacy `ErisClient` / `ErisServiceManager`; build sạch `dist/` trước mỗi compile.
- VSIX packager dùng allowlist và chỉ nhận `dist/extension.js`, nên stale JS từ build cũ không thể lọt vào release.
- Normalize GitPilot SSE thành `CodingObservation` nhỏ, có actor/task/workspace/tool/file/test/review evidence.
- Thêm `phase_summary` explicit cho Explorer/Planner/Coder/Reviewer; không log hidden chain-of-thought.
- Eris Link v2 nhận telemetry append-only tại `/v1/coding/observations`.
- Desktop thêm journal + `CodingFlowInterpreter` read-only.
- Phát hiện patch-before-inspection, retry cùng lỗi, test fail lặp, scope expansion, thiếu verification/review.
- Telemetry best-effort: Desktop OFF không được làm task GitPilot fail.
- Không thêm coding agent/tool/patch engine mới vào Eris.

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
