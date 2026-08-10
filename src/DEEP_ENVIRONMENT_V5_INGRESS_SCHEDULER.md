# Deep Environment V5 — ingress scheduler + storm control

Batch V5 tập trung đúng bottleneck đã thấy trên Windows thật: bus publish gần như bằng 0 ms nhưng semantic worker bị ngập bởi `ui_control_changed`, `object_hidden`, `object_shown`, `structure_reordered` và các refresh Chromium quá rộng.

## Thay đổi chính

1. `runtime/ai_orchestrated/environment_ingress_scheduler.py`
   - Priority heap: `CRITICAL`, `NORMAL`, `BACKGROUND`.
   - Coalescing latest-wins theo window/region/object.
   - Backpressure bounded: queue đầy thì loại background trước critical.
   - Stale background tự hết hạn trước khi worker xử lý.
   - `priority` tách hoàn toàn khỏi `attention_level`.

2. `semantic_environment_worker.py`
   - Semantic baseline chạy trước enrichment.
   - Foreground/focus/error không phải chờ UIA/IA2 cross-process call.
   - UIA/Chromium enrichment chạy ở pool hậu xử lý và publish event quay lại cùng bus/scheduler.
   - Thêm metric `environment_callback_to_enqueue_ms`, `environment_semantic_queue_wait_ms`, `environment_semantic_processing_ms`, `environment_enrichment_ms`, `environment_semantic_queue_depth`.

3. `native/chromium_accessibility.py`
   - Có `poll_window(hwnd)` cho hot path.
   - Native trigger chỉ refresh đúng Chromium HWND gây event; `poll_all()` chỉ còn cho reconciliation định kỳ.

4. `native/windows_event_broker.py`
   - Dùng `dwmsEventTime` để ước lượng delay thật từ lúc Windows phát WinEvent tới Python callback.
   - Metric `environment_source_callback_delay_ms` giúp tách provider delay khỏi semantic queue/enrichment.

## Policy đáng chú ý

- `foreground_changed`, `focus_changed`, `browser_tab_activated`, `command_failed/completed`, dialog quan trọng: CRITICAL.
- `file_saved`, `source_modified`, media/clipboard, tab title: NORMAL.
- `structure_reordered`, show/hide churn Chromium, value/name churn, counter/clock/scroll: BACKGROUND + latest-wins/stale nhanh.
- Chromium raw event không chạy generic UIA enrichment kép; IA2-first/UIA fallback riêng chịu trách nhiệm browser semantics.

## Chạy test

```bat
py -m pytest -q tests\test_architecture_c_runtime_regressions.py tests\test_desktop_semantic_environment_v1.py tests\test_deep_environment_native_v2.py tests\test_deep_environment_scheduler_v5.py
```

Baseline trong môi trường build batch này: `115 passed`.

Full suite của source đóng gói ở đây còn 5 lỗi import `tools.*` có sẵn từ archive V4 (`report_pdf_acceptance`, `evaluate_semantic_paraphrases`, `audit_remote_inference_paths`, `audit_semantic_authority_paths`). Các lỗi đó không thuộc Deep Environment V5. Nếu repo Windows của bạn đã có các tool này và trước đó đạt `983 passed`, áp patch V5 lên repo đó rồi chạy full suite lại.

## Chạy acceptance Windows

Sau khi rebuild pyc/package và chạy `run_eris.bat`, parse JSONL:

```bat
py tools\deep_environment_v5_acceptance.py logs\eris_observability.jsonl --last-seconds 30
```

Các target quan trọng:

```text
environment_callback_to_enqueue_p95_ms    < 20
environment_semantic_queue_wait_p95_ms    < 50
environment_semantic_processing_p95_ms    < 100
environment_source_to_semantic_p95_ms     < 250
foreground_to_user_situation_p95_ms       < 200
environment_false_wake_mechanical_total   = 0
runtime status:error                       = 0
```

`environment_enrichment_ms` không bắt buộc phải <250 ms cho mọi IA2/UIA call. Điểm kiến trúc của V5 là enrichment chậm không được giữ foreground/UserSituation critical path. Nếu `source_to_semantic` vẫn cao, nhìn lần lượt `source_callback_delay -> callback_to_enqueue -> queue_wait -> semantic_processing -> enrichment` để biết bottleneck chính xác nằm ở đâu.
