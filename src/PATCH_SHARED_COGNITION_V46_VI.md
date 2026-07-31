# Patch Shared Cognition v46

## Mục tiêu

Sửa hiện tượng chat và autonomous hành xử như hai tác nhân khác nhau, đặc biệt ở ba điểm:

1. correction nhân xưng không có hiệu lực ngay và không được lưu bền vững;
2. autonomous chỉ nhận hội thoại như một block text mềm, không có addressing contract chung;
3. screen anchor chọn claim đầu tiên nên danh sách app nền có thể lấn át media đang phát.

## Thay đổi chính

### Shared user-addressing state

- Thêm `runtime/user_addressing_state.py`.
- Lưu state tại `ERIS_HOME/state/user_addressing_state.json`.
- Nhận correction rõ ràng như `tui là nam nghen`, `gọi tôi là anh`, `đừng gọi tôi là chị`.
- State được cập nhật đồng bộ ngay khi append user turn, trước public model call tiếp theo.
- Cùng state được đưa vào chat planner, autonomous planner, memory context và conversation bridge.
- Public surface, TTS và memory surface dùng cùng guard để sửa cách gọi trái với correction đã lưu.

### Memory hot path

- Nối `_ingest_user_turn_via_memory_kernel()` vào chat turn qua `_ingest_user_turn_memory_hot_path()`.
- Vẫn enqueue background digest để semantic extraction sâu chạy sau, nhưng reply hiện tại không phụ thuộc worker nền.
- Nới fallback parser để nhận self-disclosure có tiểu từ cuối câu, ví dụ `tui là nam nghen` và `tôi là nữ mà`.

### Vision grounding và focus

- Khi screenshot đã capture nhưng `grounded_claims=0`, prompt bắt buộc không được nói `tôi thấy` hoặc khẳng định đã thấy bàn cờ/cảnh vật.
- Cognitive blackboard không còn dùng `grounded_claims[0]`.
- Chọn claim bằng salience có evidence binding, ưu tiên title/creator/media state đang phát.
- Claim kiểu inventory nhiều ứng dụng bị giảm điểm khi có media foreground được grounding.
- Anchor chỉ mang evidence refs của claim được chọn, tránh model trộn evidence từ các claim khác.

## Regression tests

Thêm `tests/test_shared_addressing_and_media_focus_v46.py` cho các trường hợp:

- `trước tiên tui là nam nghen` cập nhật state thành `anh`;
- output sai `chị` được sửa trên public surface;
- fallback semantic parser nhận tiểu từ tiếng Việt;
- bài nhạc đang phát được chọn thay cho danh sách Facebook/Zalo/Meet/YouTube/Bandicam.

Kết quả kiểm tra trong archive được cung cấp:

- 584 test pass trong lượt kiểm tra rộng.
- 8 test không chạy xanh do archive đầu vào thiếu thư mục `body/`, thiếu `tools/`, hoặc test ElevenLabs phụ thuộc account/quota cục bộ. Các lỗi này cũng tồn tại ở source đầu vào và không phát sinh từ patch.
