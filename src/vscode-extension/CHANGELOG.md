# Changelog

## 0.21.0 — V90 Companion Observation Bridge

- Eris Desktop và coding agent vẫn tách runtime/authority, nhưng không còn tách nhận thức.
- Thêm `CompanionWorkspaceObserver`: editor focus, file save/create/delete/rename, diagnostics và terminal command result. Không gửi raw source content.
- Prompt user gửi coding agent được mirror riêng thành `user_intent`; đây là passive observation duy nhất được phép đi vào skill model.
- Thêm nguồn telemetry `workspace`, `user`, `external-agent` bên cạnh `gitpilot`.
- Thêm command bridge nội bộ `erisCode.companion.observeExternalAgent` để coding extension khác có thể phát normalized observation mà Eris không cần sở hữu/control agent đó.
- Desktop dựng `eris.companion.workspace.v1`: active file, recent files/commands, diagnostics, current intent/task/agent status.
- Mentor V90 đọc companion context và học từ explicit user intent trong coding extension; file save/focus/terminal không tự trở thành evidence skill.
- Eris Link thêm read-only `GET /v1/companion/state`. Không thêm route control/approve/write.
- Telemetry transport đổi sang bounded queue 160 event, ưu tiên user intent + agent lifecycle để Desktop OFF không tạo backpressure.
- Project Trajectory V88 đọc backward-compatible journal V79 thiếu `source`; ingress mới vẫn yêu cầu source rõ ràng.

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
