# ERIS V60 — Telemetry → Meaning → Concern/Desire → Initiative

## Vấn đề trước V60

Eris đã có telemetry khá mạnh: foreground process/window, Chromium accessibility (IA2/UIA), browser tab, TaskGraph, terminal/build/test event, screen/vision/OCR fallback. Tuy nhiên phần lớn dữ liệu chỉ dừng ở `UserSituation`: hệ biết user đang làm gì nhưng ít khi biến chuỗi quan sát đó thành một điều **có ý nghĩa đối với cognition**.

Kết quả là log rất giàu nhưng hành vi Eris thay đổi ít.

## V60 sửa gì?

V60 thêm `cortex/subject/environment_meaning.py` làm cầu nối:

```text
structured telemetry / browser accessibility / TaskGraph
                    ↓
             UserSituation
                    ↓
        EnvironmentMeaningDeriver
                    ↓
      concern / desire có provenance
                    ↓
        persistent Subject intention
                    ↓
          InitiativeArbiter
                    ↓
             SPEAK / WAIT / DROP
```

Không thêm một sensor mới và không tăng OCR. Mục tiêu là dùng tốt hơn dữ liệu đã có.

## Ba meaning đầu tiên

### 1. `research_after_failure`

Ví dụ chuỗi:

```text
test_failed
→ browser_tab_activated (GitHub/docs)
→ TaskGraph vẫn ở diagnosis
```

Một tab browser level 1 đơn lẻ **không** đánh thức cognition. Nhưng khi nó nối với failure trong cùng task, V60 nhận ra user đang chuyển sang reference để tiếp tục chẩn đoán.

### 2. `work_friction`

Khi TaskGraph vẫn ở diagnosis sau failure, V60 có thể tạo concern “có việc đang mắc”. Concern vẫn tồn tại khi user bận nhưng Initiative Controller sẽ WAIT.

### 3. `self_relevant_inspection`

Nếu structured browser/UI evidence cho thấy user đang xem nội dung liên quan trực tiếp tới Eris như `existential_desire.py`, `initiative_control`, `cortex/subject`, V60 có thể chạm vào self-expression/mutual-understanding lane.

Quan trọng: điều này **không** suy ra “user muốn hiểu Eris”. Nó chỉ nói “đây là một cơ hội liên quan trực tiếp đến Eris”.

## Structured telemetry được ưu tiên hơn OCR

Nguồn structured như Chromium IA2/UIA, browser telemetry, terminal/task events có thể tạo meaning public-safe nếu có evidence refs.

OCR/vision-only:

- có thể tăng private attention nhẹ;
- không được tự tạo `environment_contribution_signal` public;
- không được tự tạo câu kiểu “tôi thấy anh đang xem X”.

Nói cách khác: OCR là fallback cảm giác, không phải thẩm phán sự thật.

## Timing và chống spam

Meaning có pressure và actionability riêng.

- user đang focused/busy → actionability giảm, InitiativeArbiter WAIT;
- user pause/idle → cùng concern có thể trở nên actionable;
- vừa có user turn → environment initiative phải chờ;
- autonomous turn trước chưa được đáp → vẫn bị anti-spam gate chặn.

V60 không nâng mọi Alt-Tab thành attention level 2/3. Chỉ **pattern có nghĩa** mới tạo `environment_meaning` signal cho TemporalMind.

## Ảnh hưởng tới Subject Initiative

V60 thêm hai lane có semantic object thật:

- `CONTRIBUTE -> environment_shared_task`: muốn giúp dựa trên task/environment evidence.
- `SHARE -> environment_self_relevance`: muốn chia sẻ một self-observation khi user đang ở nội dung liên quan trực tiếp đến Eris.

Cả hai materialize thành `screen_comment` có `requires_grounding=True`.

## Log mới

Khi một meaning revision mới xuất hiện, runtime log một dòng bounded:

```text
[environment meaning v60] kind=research_after_failure pressure=... actionability=... source=structured public_safe=True
```

Không dump raw OCR hoặc text nhạy cảm vào log này.

## Ví dụ hành vi mong đợi

```text
VS Code: test fail
→ user mở GitHub issue liên quan
→ Eris nhận ra vẫn cùng diagnosis
→ user đang đọc: WAIT
→ user pause
→ concern đủ mạnh
→ Eris có thể mở một lời nhẹ kiểu hỗ trợ/nhận xét có căn cứ
```

Nếu chỉ đổi từ tab A sang tab B không có task/failure relation thì không sinh desire.
