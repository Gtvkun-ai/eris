# Kiến trúc Eris Code V79

## Invariant

1. GitPilot là coding owner duy nhất trong VS Code.
2. Eris Desktop không phải dependency của extension.
3. Extension không launch Eris Desktop.
4. Local workspace đi qua GitPilot multi-agent SSE, không downgrade âm thầm sang direct LLM.
5. Approval authority thuộc GitPilot `ApprovalGate`; extension chỉ render và forward quyết định user.
6. V79 chỉ mirror **observable coding facts** sang Desktop; Desktop không có đường điều khiển task.

## Module tối thiểu

```text
GitPilotClient
GitPilotRuntimeManager
CodingObservation normalizer
TerminalContextObserver
ErisObserverBridge (best-effort)
ChatPanel / ChatParticipant
```

Không thêm Eris Planner, Eris Coder, Eris Reviewer, patch engine hay terminal agent.

## Observation spine

```text
GitPilot AgentEventBus
        ↓ SSE
Eris Code
        ↓ normalize + sanitize
CodingObservation
        ↓ best-effort loopback
Eris Desktop
        ↓
CodingObservationService
        ↓
CodingFlowInterpreter + JSONL journal
```

Các event quan trọng:

```text
task_started
phase_changed
phase_summary
tool_started / tool_finished
file_changed
approval_requested / approval_resolved
test_result / diagnostics
task_completed / failed / cancelled
```

`phase_summary` là output explicit của specialist. V79 không scrape verbose CrewAI logs hoặc hidden chain-of-thought.

## Flow findings hiện có

Interpreter chỉ cảnh báo pattern có evidence tương đối chắc:

- `patch_before_inspection`
- `repeated_same_failure`
- `repeated_test_failure`
- `scope_expansion`
- `no_structured_verification`
- `review_not_observed`

V79 **không tự hành động** dựa trên finding. V80 Mentor mới quyết định có nên giải thích/gợi ý/dạy user hay không.
