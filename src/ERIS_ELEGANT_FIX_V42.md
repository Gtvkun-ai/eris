# ERIS Elegant Runtime Fix V42

## Mục tiêu

Bản vá này giảm nhiễm context giữa các lane DeepSeek Web, bảo đảm user turn trực tiếp luôn có public reply, giới hạn context theo loại lượt và ngăn cùng một public turn bị commit nhiều lần.

## Thay đổi chính

### 1. DeepSeek Web session isolation

`llm/client.py` không còn dùng nguyên `ERIS_RUNTIME_SESSION_ID` cho mọi request.

- Chỉ các lane hội thoại được giữ session: `chat_main`, `chat`, `chat_tool_required`, `directive`, `autonomous`.
- Lane nền như `memory_digest`, `post_observer`, `private_mind`, `tutor_background` không gửi `X-Session-ID`; Whale2API sẽ dùng one-shot session và auto-delete.
- Session key được tách theo runtime session, inference lane, router purpose, response contract và system-contract fingerprint ổn định.
- Dynamic grounding/memory không làm đổi session key mỗi turn vì fingerprint chỉ lấy contract paragraph đầu.

Biến môi trường:

```text
ERIS_WEB_SESSION_MODE=isolated   # mặc định
ERIS_WEB_SESSION_MODE=off        # không giữ session Web
ERIS_WEB_SESSION_MODE=legacy     # hành vi cũ, dùng chung ERIS_RUNTIME_SESSION_ID
ERIS_WEB_SESSION_PERSISTENT_LANES=chat_main,chat,autonomous
```

### 2. Route-aware public context compiler

Module mới: `runtime/public_reply_context.py`.

- Greeting/acknowledgement không còn kéo memory archive và grounding dump vào prompt.
- Technical turn ưu tiên grounding/discourse, bỏ relationship decoration.
- Relational turn ưu tiên personality/relationship, memory chỉ được cấp ngân sách nhỏ nếu không có contextual ambiguity.
- Có hard total cap và thứ tự drop theo authority.
- Runtime lưu thống kê gần nhất tại `host.last_public_context_compilation`.

### 3. Direct reply obligation

Module mới: `runtime/reply_obligation.py`.

- Semantic frame có `must_answer=true` không được kết thúc bằng `text=""` hoặc `should_speak=false`.
- Exact greeting/acknowledgement dùng degraded local reply an toàn.
- Grounding retry thất bại vẫn trả minimal repair thay vì im lặng.
- Autonomous lane vẫn có thể im lặng vì contract của nó không đi qua direct-user enforcement.

### 4. Idempotent public turn transaction

Module mới: `runtime/public_turn_transaction.py`.

- Chat và autonomous commit dùng idempotency key ổn định.
- Cùng key chỉ thực hiện history/ledger/body side effects một lần trong process.
- Concurrent duplicate commit chờ transaction đang chạy thay vì phát thêm bubble/TTS.
- Registry có giới hạn 512 record để không phình vô hạn.

## File thay đổi

- `llm/client.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `runtime/public_reply_context.py` mới
- `runtime/reply_obligation.py` mới
- `runtime/public_turn_transaction.py` mới
- `tests/test_elegant_runtime_hardening.py` mới

## Kiểm thử

- Targeted regression: qua toàn bộ.
- Full Python suite: `464 passed`, `2 failed`.
- Hai failure không liên quan bản vá; archive đầu vào không chứa:
  - `body/UdpListener.SettingsPanel.cs`
  - `body/UdpListener.MemoryPanel.cs`
- `py_compile` qua cho toàn bộ file Python được thay đổi.
- Go test của Whale2API không chạy được trong môi trường đóng mạng vì Go yêu cầu tải toolchain `go1.26.0` từ `proxy.golang.org`.
- Ruff không có trong môi trường Python hiện tại.

## Gợi ý rollout

1. Chạy mặc định `ERIS_WEB_SESSION_MODE=isolated`.
2. Quan sát log `last_public_context_compilation` và số lượng session trên Whale2API.
3. Nếu cần rollback tức thời, đặt `ERIS_WEB_SESSION_MODE=legacy`.
4. Không thêm background lane vào persistent list trừ khi lane đó thật sự cần continuation qua nhiều request.
