# Kiến trúc Eris Code V78

## Invariant

1. GitPilot là coding owner duy nhất trong VS Code.
2. Eris Desktop không phải dependency của extension.
3. Extension không launch Eris Desktop.
4. Local workspace phải đi qua GitPilot multi-agent SSE, không âm thầm downgrade sang direct LLM.
5. Approval authority thuộc GitPilot `ApprovalGate`; extension chỉ render và forward quyết định user.
6. Eris Desktop chỉ cung cấp observation/context read-only khi user bật link.

## Module tối thiểu

```text
GitPilotClient
GitPilotRuntimeManager
TerminalContextObserver
ErisObserverBridge (optional)
ChatPanel / ChatParticipant
```

Không thêm Eris Planner, Eris Coder, Eris Reviewer, patch engine hay terminal agent. Nếu GitPilot đã có tool thì tái sử dụng tool GitPilot.

## Local team adapter

Patch backend V78 chỉ thêm adapter nối `Session.folder_path/repo_root` vào `WorkspaceManager.attach_local_workspace()` và CrewAI sequence của GitPilot. GitHub-only role như PR manager không chạy ở local mode.

```text
local_git/folder session
        ↓
WorkspaceInfo (current tree)
        ↓
Explorer  [read/search/git diff]
        ↓
Planner   [read-only]
        ↓
Coder     [read/write/test; ApprovalGate]
        ↓
Reviewer  [read/diff]
        ↓
Validation
```

## Rollback

Desktop legacy AgentHarness mặc định tắt. Chỉ bật tạm bằng:

```text
ERIS_LEGACY_CODING_HARNESS_ENABLED=1
```

Flag này là đường rollback developer-only, không phải fallback production lâu dài.
