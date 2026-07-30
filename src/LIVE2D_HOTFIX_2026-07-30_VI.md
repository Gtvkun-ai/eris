# Live2D hotfix: blink và lip-sync

## Triệu chứng

- Model mở mắt liên tục hoặc chớp rất thiếu tự nhiên.
- Audio vẫn phát nhưng `ParamMouthOpenY` không chuyển động.

## Nguyên nhân

1. Renderer cache object trả về từ `GetParameter()` lúc load model rồi đọc lại
   `.value` ở các frame sau. Object này có thể chỉ là snapshot, nên giá trị
   auto-blink mới do `model.Update()` tạo ra bị ghi đè bằng giá trị cũ.
2. Event sân khấu đi backend -> Godot (UDP 4242) -> Live2D (UDP 4252). Nếu
   frontend chưa forward `audio_playback_started`, model vẫn render nhưng không
   bao giờ vào trạng thái speaking.

## Sửa

- Cache parameter index, đọc giá trị mí hiện tại bằng
  `model.GetParameterValue(index)` sau `model.Update()`.
- `StageEventBus` mirror trực tiếp event `eris.stage` sang UDP 4252. Godot vẫn
  nhận event như cũ.
- Live2D dedupe theo `event_id`, nên bản direct mirror và bản Godot forward
  không khởi động lip-sync hai lần.

## Biến môi trường

- `ERIS_LIVE2D_DIRECT_MIRROR=1` (mặc định bật)
- `ERIS_LIVE2D_MIRROR_HOST=127.0.0.1`
- `ERIS_LIVE2D_PORT=4252`

## Kiểm tra

- 28 test Live2D chuyên biệt: passed.
- 38 test Live2D + protocol + public turn + TTS: passed.
- Toàn archive: 567 passed; 8 lỗi nền do archive thiếu `body/*.cs`, `tools/*`
  và một test ElevenLabs cũ, không liên quan hotfix.
