# Boundary Eris Desktop / Eris Code — V80

Eris Desktop và Eris Code là hai runtime độc lập. **GitPilot là coding owner duy nhất trong VS Code.**

## Eris Desktop sở hữu

- identity / companion behavior;
- long-term memory;
- desktop/environment observation;
- coding observation journal;
- technical flow interpretation từ V79;
- Engineering Mentor V80: skill projection + teaching policy + supervision dialogue.

Desktop **không** sở hữu coding task state, tool approval hoặc workspace mutation.

## Eris Code sở hữu

- VS Code UI và editor observation;
- GitPilot process/session lifecycle;
- render plan/tool/test/review/approval event;
- normalize GitPilot SSE thành `CodingObservation` nhỏ.

## GitPilot sở hữu

- Explorer / Planner / Coder / Reviewer;
- local file/git/shell tools;
- patch/write/test/review;
- permission/approval gate;
- coding provider/model.

## Eris Link v2

Khi bật, V79 dùng loopback service ở `127.0.0.1:8767`. Link mặc định tắt để tránh mở project-memory/telemetry endpoint ngoài ý muốn.

```text
Desktop -> Code: GET /v1/context
Code -> Desktop: POST /v1/coding/observations
Desktop local read: GET /v1/coding/journal, /v1/coding/flow, /v1/mentor/state
```

`POST /v1/coding/observations` là **telemetry append-only**, không phải generic RPC. Route coding-control cố ý không tồn tại.

Desktop OFF vẫn là trạng thái hợp lệ; extension timeout/fail-silent với Eris Link và không được làm GitPilot task fail.

Tắt link khi cần:

```text
ERIS_CODE_OBSERVER_LINK_ENABLED=0
```

hoặc VS Code setting:

```text
erisCode.erisLink.enabled=false
```

## Hard rules

1. Eris Code không launch Eris Desktop.
2. Eris Desktop không launch/stop/redirect GitPilot qua Eris Link.
3. Eris Desktop không approve tool thay user.
4. Eris Desktop không nhận raw source-code result chỉ để "quan sát cho nhiều".
5. Không log hidden chain-of-thought.
6. V80 có adaptive teaching mức cơ bản nhưng vẫn read-only đối với coding.
7. Skill user không được suy giảm chỉ vì GitPilot fail hoặc user giao việc cho AI.
8. V81 mới sở hữu teach-back/practice/misconception tracking dài hạn.
