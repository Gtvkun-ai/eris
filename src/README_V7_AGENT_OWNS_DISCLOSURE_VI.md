# V7 — Agent owns disclosure

## Sửa gì?

V6 đã bỏ hard clipping sau writer, nhưng runtime vẫn còn tự chọn số DialogueBeat theo voice/deep/report.
V7 bỏ nốt quyền đó.

### Trước

```text
Agent -> nhiều beat -> Runtime chọn 1/2 beat -> Writer
```

### V7

```text
Agent tự đánh say_now/deferred -> Runtime project nguyên quyết định -> Writer
```

## File chính

- `runtime/agent_loop/director.py`
- `runtime/agent_loop/runtime.py`
- `runtime/agent_loop/reasoner.py`
- `runtime/agent_loop/contracts.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `tests/test_agent_disclosure_authority_v7.py`

## Invariant

> Runtime được validate nhưng không được chọn semantic content thay agent.

Nếu plan sai, runtime trả feedback để agent re-plan. Runtime không tự sửa.

## Test

```text
87 passed
```
