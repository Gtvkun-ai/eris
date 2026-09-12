# Eris Code Architecture — V91

## Boundary chính

Eris Code là coding product độc lập. Runtime path chỉ gồm **VS Code ↔ Eris Code ↔ GitPilot**.
Không có Eris Link, Desktop observer, project-context fetch từ Desktop hay telemetry push sang Desktop.
Eris Desktop là companion riêng; nếu user muốn Eris xem code/diff/log thì user chủ động đưa chúng cho Eris qua kênh của Eris.


## Ghi chú lịch sử / phần còn lại

# Kiến trúc Eris Code V90

## Invariant

1. GitPilot/coding agent vẫn là coding owner; Eris Desktop không có quyền sửa workspace hay approve tool.
2. Eris Desktop không phải dependency của extension; Desktop tắt thì coding vẫn chạy.
3. **Tách authority, không tách nhận thức**: Eris nhận observation từ agent + workspace + user intent.
4. Passive workspace metadata không được tự suy thành năng lực hay authorship của user.
5. Eris không cần phụ thuộc GitPilot cụ thể: agent khác có thể đẩy normalized event qua adapter command.

## Companion Observation Bridge

```text
                         USER
                          │
             ┌────────────┴────────────┐
             │                         │
       VS Code workspace          Coding agent
   focus/save/diagnostics        GitPilot/agent khác
       terminal result                │
             │                         │
             └──── Companion Observation ────┘
                          │
                    Eris Link v2
                          │
                    Eris Desktop
                          │
       ┌──────────────────┴─────────────────┐
       │                                    │
CodingFlowInterpreter          CompanionWorkspaceInterpreter
(agent task quality)           (what is happening now)
       │                                    │
       └──────────── Engineering Mentor ────┘
```

## Eris nhìn thấy gì

- `user_intent`: prompt user vừa gửi coding agent (redact + giới hạn độ dài);
- agent task/phase/tool/file/test/reviewer telemetry nếu adapter có;
- active editor path;
- file save/create/delete/rename metadata;
- diagnostics count;
- terminal command + exit status ngắn;
- current task/agent status.

Eris **không** đọc raw source chỉ để quan sát, không scrape chain-of-thought và không coi save/focus là bằng chứng user tự viết code.

## Hai lớp state

`CodingFlowInterpreter` vẫn chỉ đánh giá task agent có evidence rõ như patch-before-inspection, retry cùng lỗi, thiếu verification/review. Workspace event không được phép tạo false finding.

`CompanionWorkspaceInterpreter` trả projection `eris.companion.workspace.v1` để Eris biết user đang ở đâu, repo vừa đổi gì và agent đang ở trạng thái nào, kể cả khi không có GitPilot flow.

## External-agent adapter

Coding extension khác có thể gọi command nội bộ:

```text
erisCode.companion.observeExternalAgent
```

với normalized observation. Eris chỉ nhận telemetry; command này không cấp quyền điều khiển agent.
