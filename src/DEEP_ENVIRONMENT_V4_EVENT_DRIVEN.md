# Eris Deep Environment V4 — semantic event-driven

Patch này tập trung đúng blocker còn lại của acceptance PDF: structured event đã vào bus đúng nhưng trước đây chỉ được `DesktopSemanticRuntime.observe_events(...)` consume khi self-turn chạy. Vì self-turn có nhịp ngủ/cooldown riêng, `native event -> UserSituation` có thể bị kéo lên nhiều giây dù native sensor không chậm.

## Thay đổi chính

1. Thêm `runtime/ai_orchestrated/semantic_environment_worker.py`.
   - Daemon thread riêng consume structured event ngay sau `EnvironmentEventBus.publish()`.
   - UIA enrichment chạy trên worker, không dereference accessibility object trong WinEvent callback.
   - Chromium IA2/UIA diff được trigger từ native Chromium event, không chờ self-turn poll 15 giây.
   - `DesktopSemanticRuntime`, `RegionMemory` và `TaskGraph` dùng chung một runtime lock để tránh race.
   - Event attention level >= 2 chỉ đánh thức autonomous loop; initiative governor vẫn quyết định nói/im lặng.

2. `self_turn_pipeline.py` không còn drain semantic bus trên perception tick.
   - Self-turn chỉ đọc `UserSituation` đã được worker xử lý.
   - Structured attention được consume đúng một lần, tránh event cũ wake lặp lại.
   - Presence/social cooldown không chặn perception khi còn structured attention level >= 2 chưa consume.

3. Sửa observability latency.
   - `environment_source_to_ingress_ms`: timestamp nguồn -> callback Eris.
   - `environment_bus_publish_duration_ms`: thời gian thật của `bus.publish()` bằng monotonic clock.
   - `environment_ingress_to_semantic_ms`: callback Eris -> `UserSituation` hoàn tất.
   - `environment_source_to_semantic_ms`: timestamp nguồn -> `UserSituation` hoàn tất.
   - Giữ alias `environment_event_to_bus_ms` và `environment_event_to_semantic_ms` để probe/dashboard cũ không gãy.

4. Chromium event-triggered refresh mang timestamp của native trigger sang event browser semantic để latency không tự đẹp số bằng cách bắt đầu đồng hồ sau IA2/UIA poll.

5. Shutdown dừng native producers trước rồi mới dừng semantic worker.

## Test trong môi trường build patch

```text
pytest -q tests/test_deep_environment_native_v2.py tests/test_desktop_semantic_environment_v1.py tests/test_architecture_c_runtime_regressions.py
=> 108 passed
```

Micro-benchmark worker 200 mechanical events trong môi trường build:

```text
environment_ingress_to_semantic p95 ~ 6 ms
```

Con số trên chỉ xác nhận kiến trúc worker không tự tạo backlog trong môi trường build. Nó **không thay thế** Windows acceptance. Sau khi chép patch sang Windows phải chạy `run_eris.bat` và đo lại `logs/eris_observability.jsonl`.

## Việc cần chạy lại trên Windows

1. Rebuild full pyc/package bằng pipeline build hiện có.
2. Chạy `run_eris.bat` với Chrome/Edge, VS Code, Windows Terminal, Explorer, Task Manager và media app đang mở.
3. Đo lại:
   - `environment_source_to_semantic_ms` p95 < 250 ms.
   - `foreground_to_user_situation_ms` p95 < 200 ms.
   - `environment_false_wake_mechanical_total = 0` trong workload noise.
4. Chạy lại IA2 strict + UIA fallback + ConPTY smoke và scripted scenario matrix.

Nếu source timestamp của một provider không dùng wall clock tương thích với `time.time()`, hãy ưu tiên `environment_ingress_to_semantic_ms` để debug nội bộ provider đó rồi sửa timestamp tại source; không cộng/trừ số thủ công trong acceptance.
