# Greeting preset của Eris

Thư mục này chứa metadata cho **32 lời chào mở đầu** theo tone, tình huống và thời điểm trong ngày.

- `manifest.json`: catalog chuẩn của runtime.
- `render_queue.csv`: hàng đợi để render TTS theo lô.
- `lines_vi.txt`: danh sách câu đọc nhanh.
- Các file WAV chưa được tạo giả. Render đúng giọng Eris rồi đặt theo tên
  `greet_*.wav` trong manifest.
- Thiếu hoặc hỏng WAV thì runtime tự fallback sang TTS live.

## Chế độ greeting

Mặc định nên giữ:

```powershell
$env:ERIS_STARTUP_GREETING_MODE="hybrid"
```

- `hybrid`: không có chủ đề động thì dùng preset; còn project/vòng lặp dang dở thì Qwen viết.
- `preset`: luôn ưu tiên catalog 32 câu.
- `llm`: luôn để Qwen viết greeting.
- `silent` hoặc `off`: không chào khi startup.

Biến cũ `ERIS_GREETING_PRESETS` vẫn được giữ để tương thích, nhưng `hybrid` và
`preset` là nguồn quyết định chính. Điều này ngăn một file `.env` cũ vô tình kéo
runtime trở lại câu greeting deterministic nhạt.


## Nguyên tắc neo của câu mở đầu

Catalog này đã được viết lại theo `StartupAnchorGate`:

- Không có task thật thì không nói “vào việc”, “giao tôi phần khó nhất” hoặc “tiếp đoạn trước”.
- Không có event thật thì không gán người dùng đang “gây chuyện”, đang bận hay đang nhớ Eris.
- Cá tính đến từ thái độ của Eris: khó tính, kiềm chế, trêu khô, hơi lười. Không đến từ bối cảnh bịa.
- Mỗi câu phải chịu được câu hỏi ngược “cụ thể là cái gì?”. Nếu runtime không thể chỉ vào một anchor, câu bị loại hoặc rewrite.
- Khi preset bị rewrite, audio asset cũ bị bỏ để tránh WAV đọc một câu khác với subtitle.

## Định dạng audio khuyến nghị

- WAV PCM 16-bit mono.
- 24 kHz hoặc sample rate ổn định của backend hiện tại.
- Cắt khoảng lặng dài ở đầu/cuối.
- Loudness giữa 32 file nên tương đương.

```powershell
$env:ERIS_AUDIO_ASSET_ROOT="C:\duong-dan\toi\repo"
```

Lịch sử chống lặp mặc định:

```text
memory_core/greeting_preset_history.json
```

Sau khi sửa `render_queue.csv`, Godot sẽ tự tạo lại các file `.translation` và
`.import`; không cần lưu các file sinh tự động đó trong gói source.
