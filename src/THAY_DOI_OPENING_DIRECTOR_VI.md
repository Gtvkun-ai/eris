# Ghi chú thay đổi: Opening Director V26

Đã triển khai Opening Director hybrid đa nhịp theo tài liệu thiết kế:

- Thêm typed contract cho input, plan, surface và history.
- Thêm move catalog cấp hành vi, scoring/cooldown và deterministic fallback.
- Thêm hard safety/grounding gate trước model và surface validator sau model.
- Tích hợp vào startup orchestrator trước Surface Writer, giữ single public writer,
  cancellation và guard greeting của V25.
- Thêm beat-level prosody/performance, giữ display tiếng Việt tách khỏi TTS tiếng Nhật.
- Chỉ mở social agenda/follow-up khi plan có beat `reply_bearing`.
- Thêm telemetry `eris.opening.*`, history redaction và settings schema V15.
- Bump runtime contract lên `ai_orchestrated.v26.contextual_multibeat_opening`.
- Thêm test regression, catalog checker và evaluator không gọi model.

Mọi file mới và phần logic mới đều có chú thích/docstring tiếng Việt.
