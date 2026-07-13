# Greeting preset của Eris

Thư mục này chứa metadata cho **32 lời chào mở đầu** theo tone và tình huống.

- `manifest.json`: danh sách câu, emotion, motion, prosody và tên file WAV.
- Các file WAV chưa được nhét giả vào repo. Hãy render đúng giọng Eris rồi đặt
  theo tên `greet_*.wav` ghi trong manifest.
- Nếu file WAV chưa tồn tại hoặc hỏng, runtime tự fallback sang TTS live.

## Định dạng audio khuyến nghị

- WAV PCM 16-bit mono
- 24 kHz hoặc sample rate mà backend hiện tại dùng ổn định
- Không có khoảng lặng dài ở đầu/cuối
- Loudness giữa 32 file nên tương đương nhau

## Công tắc

```powershell
$env:ERIS_GREETING_PRESETS="1"
$env:ERIS_AUDIO_ASSET_ROOT="C:\duong-dan\toi\repo"
```

Tắt preset và quay lại Qwen/TTS live hoàn toàn:

```powershell
$env:ERIS_GREETING_PRESETS="0"
```

Lịch sử chống lặp mặc định lưu tại:

```text
memory_core/greeting_preset_history.json
```
