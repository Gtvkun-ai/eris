# PANEL CONTRACT CLEANUP V9

## Phạm vi

Bản này đồng bộ các panel còn lệch với contract runtime hiện tại. Emotion Panel và debug console của nó được giữ nguyên theo yêu cầu.

## Identity Runtime

- Bỏ card `speech_drive` do UI tự suy diễn.
- Card chủ động đọc trực tiếp `discovery_runtime.initiative`.
- Trạng thái tổng quan không còn hard-code câu mô tả khí sắc.
- Các thao tác quản trị dùng protocol có kiểu `eris.identity_control.v1`:
  - `set_learning`
  - `snapshot`
  - `reset_mood`
  - `reset_relationship`
  - `reset_discovery`
- Panel nhận `identity_control_ack` riêng thay vì dựa vào debug command dạng chuỗi.

## Inner Diary

Phần đổi tên ở v9 đã được thay thế bởi v10. Inner Diary được khôi phục thành tính năng riêng, đọc `eris.inner_diary.v2` và do một DeepSeek worker chuyên trách viết. Xem `INNER_DIARY_PANEL_V10_VI.md`.

## Tutor / Research

- Bỏ phần trăm tiến độ giả được gán cố định theo stage.
- Thay bằng chỉ báo giai đoạn:
  - Xếp lượt
  - Thu thập
  - Kiểm chứng
  - Tổng hợp
  - Hoàn tất
- Chỉ ghi “đã lưu” khi backend xác nhận persistence.
- Giảm lộ tên subsystem nội bộ trong wording giao diện.

## Context menu

- Chuẩn hóa dấu tiếng Việt và nhãn panel.
- Không thay đổi ownership hoặc runtime behavior.

## Không thay đổi

- Emotion Panel.
- Emotion debug console.
- Memory Panel.
- Chat và Live2D controls.
