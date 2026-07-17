# Patch đồng bộ bubble và TTS cho Scripted Take

## Lỗi đã sửa

1. `StageDispatcher._dispatch_inline()` gộp nhiều segment thành một audio nhưng giữ `display_text` của segment đầu. Với beat mở đầu `Khoan. Có những...`, bubble chỉ hiện `Khoan.` trong khi TTS đọc toàn đoạn.
2. Inline dispatcher ép mọi nhóm về `segment_id = 0`. Nhóm sau Tutor trùng ID nhóm trước nên bị `ScriptedTakeRuntime` chống phát trùng loại bỏ. Audio vẫn được phát nhưng payload bubble không còn được publish.
3. Sentence splitter tổng quát tự xé một beat kịch bản thành nhiều bubble dù JSON đã mô tả beat đó như một nhịp đạo diễn duy nhất.
4. Take quay gọi Tutor/provider thật dù đã có `fallback_answer`, khiến nhịp diễn có thể treo hàng chục giây khi mạng timeout.

## Hành vi mới

- Inline group giữ `segment_id` thật của frame đầu, không tái chế ID 0.
- `display_text`, `tts_text` và `memory_text` của inline audio dùng cùng transcript đã gộp.
- Mỗi text beat trong JSON mặc định là một bubble và một nhịp TTS nguyên tử.
- Chỉ tách câu khi beat chủ động đặt `split_text: true`.
- Take có `profile: recording` mặc định dùng `cached_answer` hoặc `fallback_answer`; chỉ gọi Tutor thật khi đặt `live_lookup: true`.
- Take `Những Điều Eris Chưa Biết #01` đã khóa `live_lookup: false` để quay ổn định.

## File thay đổi

- `runtime/stage_dispatcher.py`
- `runtime/scripted_take.py`
- `takes/nhung_dieu_eris_chua_biet_01.json`
- `tests/test_scripted_take.py`

## Kiểm tra

- `tests/test_scripted_take.py`: 17 test đạt.
- Scripted take + stage dispatcher/contracts/ownership/transformers + TTS events: 32 test đạt.
- `python -m compileall -q runtime tests`: đạt.

## Giới hạn kiểm chứng

Patch đã được kiểm tra ở tầng Python/runtime và contract payload. Chưa build/chạy trực tiếp Body Godot trong môi trường đóng gói này. Không cần sửa Body cho nguyên nhân đã thấy trong log vì payload bubble bị mất ngay từ runtime Python trước khi tới Godot.
