# Eris Deep Environment V2 — implementation batch 2026-08-10

> **Đã có batch V3:** xem `DEEP_ENVIRONMENT_V3_IMPLEMENTATION.md`. Các mục IA2-first, GSMTC event subscription, ConPTY thật, RegionMemory critical path và Stage F initiative đã được làm tiếp.

Batch này chuyển phần runtime quan trọng từ “pixel đổi thì đánh thức cognition” sang native/semantic-first, đồng thời giữ rollback path để không phá V1.

## Đã triển khai

- `native/process_resolver.py`: HWND → PID → process name/path/window class bằng quyền query tối thiểu.
- `native/windows_event_broker.py`: `SetWinEventHook` cho foreground/focus/selection/name/value/show/hide/reorder; skip own process, coalesce callback.
- `native/uia_event_client.py`: bounded per-HWND cache, password hard-block, không walk desktop root.
- `native/chromium_accessibility.py`: no-extension Chromium semantic adapter với UIA fallback; tab selection/title/topology, không giả vờ có DOM/network/cookies.
- `native/clipboard_monitor.py`: `WM_CLIPBOARDUPDATE`, metadata-only, không đọc plaintext mặc định.
- `native/filesystem_monitor.py`: `ReadDirectoryChangesW` cho workspace được cấu hình, chỉ emit relative path/action/extension.
- `native/media_monitor.py`: GSMTC contract/fail-closed khi Windows Runtime binding không có.
- `native/conpty_session.py`: owned-terminal event contract; exact exit code chỉ cho process do Eris launch.
- `runtime/ai_orchestrated/environment_event_bus.py`: typed normalized event, TTL, coalescing, privacy filtering.
- `runtime/ai_orchestrated/region_memory.py`: semantic region identity + stability/mechanical/semantic EMA.
- `runtime/ai_orchestrated/task_graph.py`: Phase A/B TaskGraph deterministic + temporal continuity, không gọi LLM trên raw firehose.
- `runtime/privacy/environment_policy.py`: OFF/METADATA/SEMANTIC/CONTENT_EPHEMERAL/CONTENT_ALLOWED, hard-block password/UAC/credential, messaging metadata-only.
- `DesktopSemanticRuntime.observe_events(...)`: structured event path, TaskGraph projection và `UserSituation`.
- `self_turn_pipeline.py`: `UserSituation.max_attention_level` trở thành wake authority khi `ERIS_SEMANTIC_WAKE_GATE_ENABLED=1`; raw `mechanical_delta` chỉ còn rollback/body cue.
- `telemetry/system.py`: `foreground_hwnd`, `foreground_pid`, `active_process`, `active_window_title`, `window_class`, `focus_changed`, `interaction_state`.
- `screen/active_window_provider.py`: populate PID/process/window class/path.
- `screen/windows_uia_reader.py`: per-HWND cached subtree, password hard-stop.
- `screen/ocr_worker.py`: triggered/reconciliation mode thay fixed OCR poll, structured coverage suppresses OCR, disk cache fingerprint-only mặc định.
- `runtime/browser_bridge_server.py`: browser bridge legacy mặc định off.
- `tools/deep_environment_acceptance.py`: replay typed events và đo mechanical false wake / sensitive leak.

## Feature flags / rollback

- `ERIS_NATIVE_EVENTS_ENABLED=1`
- `ERIS_UIA_EVENTS_ENABLED=1`
- `ERIS_CHROMIUM_IA2_ENABLED=1` (adapter hiện dùng UIA fallback trong Python; IA2 COM native có thể cắm vào cùng contract sau)
- `ERIS_SEMANTIC_EVENT_BUS_ENABLED=1`
- `ERIS_TASK_GRAPH_ENABLED=1`
- `ERIS_SEMANTIC_WAKE_GATE_ENABLED=1`
- `ERIS_OCR_TRIGGERED_MODE=1`
- `ERIS_CLIPBOARD_MONITOR_ENABLED=1`
- `ERIS_WORKSPACE_WATCH_PATHS=<path1;path2...>` trên Windows dùng `os.pathsep`.
- `ERIS_BROWSER_BRIDGE_ENABLED=0` mặc định.
- `ERIS_OCR_CACHE_RAW_TEXT=0` mặc định.

Rollback nhanh cho behavior cũ:

```text
ERIS_SEMANTIC_WAKE_GATE_ENABLED=0
ERIS_OCR_TRIGGERED_MODE=0
```

## Chưa giả vờ hoàn thành

- Signed `uiAccess=true` helper cần build/sign/install Windows executable riêng. Python source không thể tự biến thành UIAccess đáng tin cậy.
- IA2-first COM traversal sâu chưa được ship trong batch này; adapter giữ contract no-extension và UIA fallback. Không có claim exact URL/network/DOM cho mọi tab.
- GSMTC event subscription phụ thuộc binding/package Windows Runtime thực tế và cần E2E trên máy Windows.
- ConPTY transport thật chưa thay thế shell runner; contract chỉ đảm bảo exact semantics cho process Eris sở hữu.

## Test

Focused Deep Environment + architecture regression: `94 passed` trong môi trường build này.

Full suite của archive không sạch từ trước: sau khi bỏ 3 test không collect được vì archive thiếu các module `tools.*`, còn `937 passed / 12 failed`; các failure còn lại nằm ở module/test ngoài batch Deep Environment (đường dẫn body archive, DeepSeek worker role, executive cortex, memory GC, grounding). Xem log trong `DEEP_ENVIRONMENT_TEST_STATUS.txt`.
