# Vá đồng bộ Scripted Take và khóa quyền sân khấu

Patch này chép **sau** hai patch:

1. `eris_performer_director_patch_src79.zip`
2. `eris_human_reaction_arc_patch_src79.zip`

Không cần sửa thêm Godot ngoài `eris_body_take_patch_body40.zip` đã phát trước đó.

## Lỗi gốc đã sửa

- `StageEventBus.emit()` gửi UDP thật, nhưng ScriptedTake từng gọi nó ngay khi TTS còn synthesize. Vì vậy body timeline/bubble có thể xuất hiện rất lâu trước âm thanh.
- `segment_id` từng quay lại 0 sau mỗi nhóm thoại. Các đoạn sau Tutor có thể đụng ID với câu mở đầu.
- `audio_start` từng được emit trước khi backend playback mở thiết bị âm thanh.
- Autonomous không biết Scripted Take đang giữ sân khấu, nên vẫn có thể surface và tranh queue TTS/bubble.
- Callback playback đến muộn sau cancel có thể làm một segment cũ xuất hiện lại.

## Hành vi mới

- Segment chỉ công bố khi playback backend báo thiết bị đã bắt đầu phát.
- Text, motion và body timeline cùng bước lên sân khấu tại một mốc.
- ID segment tăng liên tục trong toàn bộ take.
- Scripted Take giữ `StageOwnership` và chặn mọi output `autonomous` đến khi hoàn tất/hủy.
- Chat hoặc `force_speak` của user hủy take trước khi chạy lượt mới.
- Event muộn từ take đã hủy/thay thế bị loại.

## Kiểm tra nhanh

Chạy:

```text
take takes/nhung_dieu_eris_chua_biet_01.json
```

Trong log, khi take đang chạy không được có câu autonomous public chen giữa. Nếu một cycle autonomous cũ đã bắt đầu trước take, output của nó sẽ bị chặn với log:

```text
[stage ownership] suppressed channel=autonomous ...
```
