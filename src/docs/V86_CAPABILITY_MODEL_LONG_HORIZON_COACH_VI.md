# V86 — Capability Model & Long-Horizon Coach

## Mục tiêu

V85 đã giúp Eris tự hiệu chỉnh khi dạy sai. V86 biến những state rời rạc đó thành một bảng thống kê dễ hiểu để user biết **Eris đang ước lượng mình tới đâu và dựa vào bằng chứng gì**.

Luồng:

```text
V79 CodingObservation
 + V80/V81 skill + learning
 + V82 tool literacy
 + V85 calibration
          ↓
CapabilityProjectionService
          ↓
capability_panel_ack
          ↓
Panel “Năng lực kỹ thuật”
```

`CapabilityProjectionService` là read-model deterministic. Không có model call hay tool execution.

## Quy tắc evidence

Một skill chỉ được hiện % khi:

- có ít nhất 2 bằng chứng;
- confidence >= 0.16.

Không đạt gate thì UI ghi **Chưa đủ dữ liệu**. Đây là invariant quan trọng để panel không biến default `0.5` của model thành “50% năng lực”.

## Nhóm thống kê

- **Gỡ lỗi**: định vị lỗi, call-flow, root cause.
- **Kiến trúc**: ranh giới hệ thống/ownership.
- **Kiểm chứng**: targeted test + diff review.
- **Vận hành AI**: task scoping + evidence review.
- **Công cụ**: trạng thái unobserved/introduced/demonstrated/familiar từ V82.

## Thống kê AI 30 ngày

V86 chỉ đếm signal đã tồn tại trong Mentor model, ví dụ:

- grounded hypothesis;
- verification intent;
- learning intent;
- blind execution request.

Không đọc lại raw chat để “chấm thái độ”. `overreliance_risk` được hiển thị rõ là chỉ số rủi ro riêng, không phải điểm năng lực.

## Xu hướng

Mỗi ngày tối đa một snapshot được append vào:

`<ERIS_HOME>/mentor/capability_history.jsonl`

Trend chỉ xuất hiện khi có snapshot từ ngày trước. Gọi refresh nhiều lần cùng ngày vẫn phải báo **Chưa đủ lịch sử** nếu đây là ngày đầu.

## Coach dài hạn

Recommendation deterministic, tối đa 3 mục. Mỗi mục bắt buộc có:

- tiêu đề;
- ưu tiên;
- thời hạn;
- lý do evidence-based;
- một practice nhỏ;
- success signal.

Coach không tự tạo homework scheduler và không block GitPilot.

## UI

Panel Godot nằm trong `UdpListener.CapabilityPanel.cs`, được mở từ menu **Năng lực kỹ thuật**. Panel read-only; không có packet `set_skill`, `set_score` hay control API.

## Boundary bảo mật/authority

V86 không thay ownership:

```text
GitPilot = code/test/review
Eris Mentor = hiểu/dạy/hiệu chỉnh
V86 = thống kê + đề xuất dài hạn
```

Không thêm coding authority cho Eris.
