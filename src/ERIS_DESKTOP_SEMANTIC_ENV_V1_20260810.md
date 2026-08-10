# ERIS Desktop Semantic Environment V1 — 2026-08-10

## Mục tiêu

Nâng đường perception từ `OCR changed -> autonomous wake` thành một pipeline có nghĩa hơn:

`OCR / window / process / browser / idle / observer -> DesktopSemanticRuntime -> UserSituation -> TemporalMind / planner`.

Runtime mới không thu raw keystroke và không persist timeline xuống disk. Text ở surface private/sensitive không được copy vào timeline.

## Thành phần mới

### `runtime/ai_orchestrated/desktop_semantics.py`

- `DesktopSemanticEvent`: event có kind/category/confidence/novelty/importance/attention level/provenance.
- `DesktopSemanticRuntime`: fusion giữa screen delta, foreground telemetry, browser URL, idle state, BackgroundObserver và ActivitySession.
- `UserSituation`: projection nhỏ cho planner gồm activity, task hint, phase, focused app/process/object, last action/outcome, attention state, interruption cost và recent environment events.
- OCR counter/clock/progress churn được phân loại `mechanical_screen_delta` và không đánh thức cognition nặng.
- Error signal được observer xác nhận có thể trở thành `possible_error_visible` level 3.

### Foreground telemetry có cấu trúc

Telemetry bổ sung:

- `active_window_title`
- `active_process`
- `window_class`
- `foreground_hwnd`
- `focus_changed`
- `interaction_state`

`active_app` cũ vẫn giữ semantics cũ để tránh phá compatibility; semantic consumers ưu tiên `active_process`.

`screen/active_window_provider.py` cũng lấy process name của foreground HWND khi Windows/psutil hỗ trợ.

## Nối vào autonomous loop

`SelfTurnPipeline` tạo `user_situation` mỗi tick và đưa vào planner snapshot.

- `user_busy=true` khi `attention_state=focused` và `interruption_cost >= 0.70`.
- Commentary cadence dùng semantic delta thay vì raw OCR delta.
- TemporalMind nhận `environment_event` khi có semantic event level >= 2.
- Window switch đơn thuần chỉ là scene update yếu.
- Legacy external attention pressure bị attenuate khi chỉ có mechanical OCR delta; internal drive không bị giảm.
- Relational tick đọc `user_busy`, nhờ vậy social initiative có xu hướng chờ khi user đang tập trung.

## Privacy / epistemic boundary

- Không raw keylogging.
- Không persist DesktopActivityTimeline xuống memory/disk.
- Private/sensitive surface chỉ tạo event redacted, không giữ changed OCR text.
- `UserSituation` là private planning hint. Public claim về nội dung màn hình vẫn phải qua `vision_grounding`.
- Activity/task inference ưu tiên planner annotation / BackgroundObserver. Nếu thiếu thì chỉ dùng broad context hint, không tuyên bố exact user intent.

## Validation

Targeted regression: 124/124 pass.

Broad suite trên archive mới: 925 pass, 12 fail. Đối chiếu archive trước patch: 920 pass, cùng đúng 12 fail. Các failure còn lại là lỗi/precondition có sẵn trong archive (thiếu `tools.*`, thiếu body C# ngoài src, và một số test legacy khác), không phát sinh từ Desktop Semantic Environment V1.
