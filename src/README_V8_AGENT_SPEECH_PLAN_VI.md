# V8 — Agent owns long-term speech plan

## File quan trọng

- `runtime/agent_loop/contracts.py`
- `runtime/agent_loop/speech_plan.py`
- `runtime/agent_loop/runtime.py`
- `runtime/agent_loop/reasoner.py`
- `runtime/agent_loop/director.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/ai_orchestrated/self_turn_pipeline.py`
- `runtime/public_output_runtime.py`
- `runtime/runtime_status.py`
- `tests/test_agent_speech_plan_v8.py`

## Luật chính

```text
Agent chọn nội dung + plan dài hạn.
Runtime chỉ persist/wake.
Writer viết câu.
TTS phát nguyên văn.
```

Runtime không được tự chọn thread, tự cắt câu, tự phát continuation cache.

## UI

- Eris • đang suy nghĩ…
- Eris • đang chuẩn bị nói…
- Eris • đang nói…
- Eris • đang chờ bạn
- Eris • còn một ý…

## Test

```bash
PYTHONPATH=. pytest -q tests/test_agent_speech_plan_v8.py
```
