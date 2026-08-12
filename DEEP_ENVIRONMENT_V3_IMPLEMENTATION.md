# Eris Deep Environment V3 — batch tiếp theo 2026-08-10

Batch này tiếp tục bám PDF *Eris Deep Environment trên Windows: telemetry native, semantic desktop và suy luận task không cần browser extension*. Mục tiêu là lấp các khoảng trống còn lại của V2, không đổi hướng kiến trúc sang một lớp semantic đứng riêng.

## Những phần đã làm tiếp

### 1. Chromium IA2-first thật, UIA fallback

- Thêm `native/ia2_accessibility.py`.
- Đường Windows ưu tiên:

```text
AccessibleObjectFromWindow(OBJID_CLIENT)
  -> IAccessible
  -> IServiceProvider
  -> QueryService(IID_IAccessible2)
  -> bounded accessibility tree
```

- `native/chromium_accessibility.py` bây giờ thử IA2 trước; chỉ fallback UIA khi IA2/provider không khả dụng.
- Event source phân biệt `chromium_ia2` và `chromium_uia`.
- Không claim DOM/network/cookies/JavaScript state.
- Không giới hạn tab ở 10; snapshot giới hạn theo node budget, không hard-code tab count.
- Omnibox nếu đọc được chỉ chuyển thành `active_domain`; raw URL/path/query không đi vào event bus.

### 2. UIA event + cache được wire vào production

- `native/uia_event_client.py` có COM MTA listener thread riêng.
- Cache theo HWND; event chỉ invalidate, không scan accessibility tree ngay callback.
- Có UIA focus/property/structure handler khi package `uiautomation` expose API tương ứng.
- Có reconciliation TTL để recover event bị mất.
- Password control là hard block.
- Thêm `native/uia_semantic_adapter.py`: WinEvent được enrich thành `editor_focused`, `dialog_candidate`, `blocking_dialog`, `ui_tab_activated`, `control_*` trên consumer tick.
- `self_turn_pipeline.py` đã wire adapter này vào production; WinEvent callback vẫn giữ nhẹ.

### 3. RegionMemory thực sự nằm trên critical path

- `DesktopSemanticRuntime` nhận và cập nhật `RegionMemory` cho từng normalized event.
- Identity ưu tiên `process/pid/hwnd/provider/role`, không dùng bounding box làm identity chính.
- Visual/OCR candidate level >= 2 phải có region tồn tại và fingerprint ổn định đủ mẫu trước khi được phép nâng cognition wake.
- Structured native event mạnh vẫn bypass stability gate như thiết kế PDF.

### 4. TaskGraph giàu hơn

- Thêm graph edge: `USES`, `FOLLOWS`, `MODIFIES`, `TESTS`, `RESEARCHES`, `RETURNS_TO`, `RESOLVES`.
- Confidence tách thành:
  - `structured_source_quality`
  - `temporal_continuity`
  - `semantic_similarity`
  - `cross_source_agreement`
  - `outcome_link_strength`
  - `contradiction`
- `interruption_cost` dùng event density, recent edit/test, research↔editor transition, phase và idle duration; không cần raw keylog.

### 5. Stage F initiative integration

`UserSituation.interruption_cost`, `busy_score`, `phase` và `max_attention_level` đi vào social/autonomous gate thật:

```text
interruption_cost >= 0.60
OR recent environment attention >= 2
OR active work phase + busy_score >= 0.70
    -> suppress social check-in / commentary / relational outreach
```

Task vừa hoàn tất + interruption cost giảm thì gate tự mở lại. Hàm `environment_social_gate(...)` là pure function để test trực tiếp.

### 6. GSMTC event-driven

- `native/media_monitor.py` có background asyncio loop cho `GlobalSystemMediaTransportControlsSessionManager`.
- Subscribe session/playback/media/timeline change event khi `winsdk` khả dụng.
- Có sanity refresh thấp tần số để recover event mất, không OCR player UI.
- Mặc định chỉ giữ `source_app` + playback/session state.
- `title/artist/timeline` chỉ bật khi `ERIS_MEDIA_CONTENT_METADATA=1`, đúng privacy table của PDF.

### 7. ConPTY thật cho terminal do Eris sở hữu

- `native/conpty_session.py` dùng `CreatePseudoConsole`, `STARTUPINFOEX`, `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`, `CreateProcessW` trên Windows.
- Exact command start/finish/exit code chỉ áp dụng cho process do `OwnedTerminalSession` launch.
- Không attach arbitrary terminal đang chạy.
- Non-Windows CI dùng subprocess fallback để test semantic contract.

### 8. Filesystem overlapped I/O

- `native/filesystem_monitor.py` chuyển sang `ReadDirectoryChangesW` + `FILE_FLAG_OVERLAPPED`.
- Có stop event/CancelIoEx; không cần `stat()` polling.
- Chỉ watch workspace được cấu hình và chỉ emit relative path/action/extension.

### 9. UIAccess broker hẹp

Thêm `native/uiaccess_broker/`:

- `protocol.py`: chỉ cho `ping`, `window_metadata`, `accessibility_metadata`.
- `client.py`: local Windows AF_PIPE.
- `server.py`: chỉ accessibility metadata; password hard block; không OCR/memory/LLM/command execution.
- `eris-uiaccess-broker.manifest`: `uiAccess="true"`, `asInvoker`.
- `build_uiaccess_broker.ps1`: build + code-sign bằng certificate do operator cung cấp.
- `README_VI.md`: yêu cầu cài executable đã ký trong Program Files/protected location.

**Lưu ý:** source đã có broker/build path nhưng archive này không thể tự tạo certificate hợp lệ hoặc ký executable thay người vận hành.

### 10. Privacy scope có cấu hình thật

Ngoài default bảo thủ, `EnvironmentPolicy` đọc được:

- `ERIS_ENVIRONMENT_PRIVACY_OVERRIDES` — JSON mapping app/domain/workspace substring -> scope.
- `ERIS_CONTENT_EPHEMERAL_DOMAINS`.
- `ERIS_CONTENT_ALLOWED_WORKSPACES`.

Không có config thì browser vẫn SEMANTIC, messaging METADATA, password/UAC/credential/banking OFF.

### 11. Acceptance tooling

`tools/deep_environment_acceptance.py` bây giờ report được các target PDF nếu dataset có label/latency metadata:

- event→semantic p95
- foreground transition p95
- structured event precision
- false wake/min
- OCR calls/min + reduction so baseline
- task top-1 accuracy
- task-switch false positive
- interrupt precision
- sensitive payload leaks
- screen-noise deliberations

Metric không có dữ liệu được đánh `NO_DATA`, không tự điền số đẹp mắt.

Thêm `tools/deep_environment_windows_e2e.py` để chạy trên Windows thật. Probe không dump title/tab/accessibility text; nó kiểm tra provider availability, app coverage, IA2/UIA path, Chromium tab count, GSMTC, UIAccess broker và optional ConPTY smoke.

## Dependency Windows tùy chọn

File mới: `requirements-deep-environment-windows.txt`

```text
comtypes
uiautomation
winsdk
```

Linux CI không cần ba package này.

## Feature flags mới/bổ sung

```text
ERIS_MEDIA_MONITOR_ENABLED=1
ERIS_MEDIA_CONTENT_METADATA=0
ERIS_UIACCESS_BROKER_ENABLED=0
ERIS_UIACCESS_BROKER_AUTHKEY=<injected by launcher>
ERIS_ENVIRONMENT_PRIVACY_OVERRIDES={...}
ERIS_CONTENT_EPHEMERAL_DOMAINS=learn.microsoft.com,...
ERIS_CONTENT_ALLOWED_WORKSPACES=<path1;path2...>
```

Các rollback flag V2 vẫn giữ nguyên:

```text
ERIS_SEMANTIC_WAKE_GATE_ENABLED=0
ERIS_OCR_TRIGGERED_MODE=0
```

## Test trong môi trường build này

Focused Deep Environment + architecture regression:

```text
106 passed
```

Mechanical acceptance smoke:

```text
mechanical_events=80
mechanical_wakes=0
sensitive_payload_leaks=0
screen_noise_deliberations=0
```

Full archive vẫn có 3 collection blockers có sẵn do thiếu `tools.package_source` và `tools.evaluate_social_plan_activation`. Khi bỏ 3 file đó:

```text
950 passed, 12 failed
```

12 failure còn lại là các lỗi/archive gap ngoài Deep Environment (body path expectation, DeepSeek role `research`, executive_cortex local variable, memory GC legacy method, một số legacy `tools.*`, grounding regression).

## Phần còn cần chạy ngoài môi trường này để gọi là nghiệm thu Windows hoàn tất

1. Cài Windows optional deps và chạy `tools/deep_environment_windows_e2e.py` trên máy Windows thật.
2. Scripted scenarios với Chrome/Edge, VS Code, Windows Terminal, Explorer, Task Manager và media app.
3. Thu latency/CPU dataset để xác nhận các target p95/CPU trong PDF.
4. Build, ký và cài `eris-uiaccess-broker.exe` bằng certificate hợp lệ rồi chạy elevated Task Manager scenario.
5. Calibrate task model trên dataset cá nhân có label để xác nhận `task_top1_accuracy > 85%` thay vì coi heuristic CI là benchmark.

Những mục này cần Windows/runtime/certificate/dataset thực tế; source code không nên giả vờ đã đo nếu chưa chạy.
