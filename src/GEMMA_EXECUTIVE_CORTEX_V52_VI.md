# Gemma Executive Cortex V52

## Mục tiêu

Bản vá đặt **Gemma 4 31B** vào giữa các worker DeepSeek hiện có và runtime cơ học.
Gemma không thay Observer, Inner, Seed hay Surface. Nó chọn nhịp kế tiếp, chọn
candidate semantic, có thể im lặng/body-only, và được phép kiểm tra tối đa một
capability read-only đang sống trước khi quyết định.

## Luồng mới

```text
DeepSeek Observer / Inner / Seed / agenda candidates
                         +
runtime blackboard / recent public history / live capability contracts
                         |
                         v
               Gemma Executive Cortex
                         |
       silence | body-only | candidate | read-only tool probe
                         |
                         v
              deterministic governor
                         |
                         v
                 DeepSeek Surface
```

## Tool discovery không dựa marker

`runtime/ai_orchestrated/executive_tools.py` dựng catalog trực tiếp từ:

- `actions.capability_registry.iter_public_capabilities()`
- `actions.capability_runtime.refresh_runtime_capabilities(owner=...)`
- contract metadata của cognitive/environment/project runtime

Gemma nhận tên capability, mô tả, availability, permission, risk và JSON input
schema. Không cần liệt kê mọi cách người dùng có thể nói "tạo file", "nhìn màn
hình" hoặc các đồng nghĩa khác.

Chỉ capability `available`, risk thấp và permission read-only mới có
`auto_callable=true`. Tool có side effect vẫn bị runtime từ chối.

## Phân quyền

- **DeepSeek Observer/Inner/Seed**: tạo diễn giải và candidate theo lane.
- **Gemma Executive Cortex**: chọn trajectory và semantic target.
- **Runtime governor**: timing, reply baton cứng, permission, concurrency.
- **DeepSeek Surface**: viết public wording.
- **ActionExecutor**: thực thi tool và trả evidence thật.

Gemma có thể giải phóng một reply baton chỉ khi đó là invitation xã hội optional,
candidate thuộc lane social áp lực thấp, không có structured engagement và quyết
định có confidence/risk đạt ngưỡng. Task question, safety confirmation và required
engagement vẫn là biên cứng.

## Cấu hình

```env
ERIS_EXECUTIVE_CORTEX_ENABLED=1
ERIS_EXECUTIVE_MODEL=gemma-4-31b-it
ERIS_EXECUTIVE_TIMEOUT_S=18
# Tuỳ chọn nếu không dùng provider profile / Gemini key pool:
ERIS_EXECUTIVE_API_KEY=...
ERIS_EXECUTIVE_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Client Executive dùng Gemini key pool hiện có (`get_key_pool("gemini")`). Nếu
không có credential hoặc khởi tạo lỗi, hệ thống fail closed về selector legacy;
các DeepSeek worker không bị đổi model hay fallback ngầm.

## File chính

- `runtime/ai_orchestrated/executive_cortex.py`
- `runtime/ai_orchestrated/executive_tools.py`
- `runtime/ai_orchestrated/self_turn_pipeline.py`
- `runtime/ai_orchestrated/social_initiative.py`
- `runtime/ai_orchestrated/bootstrap.py`
- `runtime/ai_orchestrated/model_router.py`
- `llm/process_manager.py`
- `llm/service.py`
- `vision.py`
- `tests/test_gemma_executive_cortex_v52.py`

## Kiểm thử

- Compile toàn bộ `llm`, `runtime`, `actions`, `vision.py`: đạt.
- Nhóm test kiến trúc liên quan: **205 passed**.
- Suite rộng sau khi bỏ qua ba test collection phụ thuộc thư mục `tools/` không
  có trong archive nguồn: **715 passed, 5 failed**.
- Năm lỗi còn lại đều là `ModuleNotFoundError` cho các module `tools.*` cũng
  không có trong archive nguồn, không phát sinh từ bản vá Executive Cortex.

Chưa thực hiện live API call tới Gemini vì archive không kèm credential dùng thử.
