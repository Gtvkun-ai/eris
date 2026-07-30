# INNER DIARY PANEL V10

## Phạm vi

Khôi phục panel **Inner Diary** với năm thẻ cũ, nhưng nối vào contract có owner rõ ràng thay vì lấy Identity telemetry rồi đổi tên.

## Nguồn dữ liệu

Panel ưu tiên:

```text
inner_diary.sections
inner_diary.memory_echo
inner_diary.writer
inner_diary_contract.writer
```

Fallback cũ chỉ dùng khi digest chưa có `inner_diary.sections`.

## Năm thẻ

- Suy nghĩ hiện tại
- Suy nghĩ tương lai
- Đang bận tâm
- Phân tích gần đây
- Muốn nói

Các badge lần lượt là `NOW`, `NEXT`, `CONCERN`, `REFLECTION`, `UNSAID`. Chúng là nhóm hiển thị diary, không phải key runtime giả.

## Writer và freshness

Dòng trạng thái hiển thị:

- `LIVE` hoặc `CACHE`;
- tuổi snapshot;
- role và model của DeepSeek worker đang viết diary.

Cache chính:

```text
user://inner_diary_state.json
```

Panel vẫn đọc `user://inner_state_panel.json` để migrate dữ liệu bản v9.

## Memory Echo

Card Memory Echo chỉ đọc `inner_diary.memory_echo`. Khi có dữ liệu, panel hiển thị provenance gồm `source` và `evidence_id`. Không lấy open loop làm ký ức.

## Không thay đổi

- Emotion Panel
- Emotion debug console
- Identity Runtime panel
- Memory Panel
- Chat và Live2D controls
