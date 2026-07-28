# Voice Director v3: ấm hơn, có tiếng đệm, vẫn không chia câu

Voice Director được giữ lại như một lớp diễn xuất nhẹ. Nó không còn quyền cắt câu hoặc dựng timeline, nhưng có thể chọn tối đa một tiếng đệm/nonverbal cue ngắn khi ngữ cảnh thật sự hợp.

## Hành vi

- Một transcript đi vào vẫn tạo **một StageFrame, một request TTS và một clip phát duy nhất**.
- Director chọn `style`, tối đa hai cụm nhấn nhẹ, `speed`, `energy`, `warmth`, `pitch` và một `vocalization` tùy chọn.
- Cue được phép: `soft_hum`, `gentle_ack`, `small_laugh`, `soft_sigh`, `curious_hm`, `soft_surprise` hoặc `none`.
- Cue có vị trí `prefix` hoặc `suffix`; không có vị trí giữa câu và không có pause riêng.
- Director không được sửa chữ, dịch lại, đổi dấu câu, tạo `segments`, thêm SSML/raw sound-effect text hoặc quyết định `should_speak`.
- Cue chỉ tồn tại ở lớp TTS. `display_text` và `memory_text` giữ nguyên.
- Với ElevenLabs, cười/thở dài dùng audio tag trong **cùng payload**; “ừm”, “hửm?”, “ồ” được chèn vào transcript TTS nội bộ.
- `audio_polish` vẫn tắt để tránh cắt đầu/cuối âm tiết hoặc nén khoảng lặng.
- Timeout STYLE mặc định 3 giây, tối đa 6 giây. Quá hạn thì đọc nguyên câu bằng prosody fallback.

## Quy tắc chọn cue

Director được hướng dẫn dùng `none` trong phần lớn lượt nói:

- `soft_hum`: đang cân nhắc nhẹ.
- `gentle_ack`: đồng ý hoặc xác nhận kín đáo.
- `small_laugh`: câu thật sự vui, trêu khô hoặc tự nhận thức hài hước.
- `soft_sigh`: nhẹ nhõm hoặc bực nhẹ, không dùng để chế giễu.
- `curious_hm`: câu hỏi thật sự.
- `soft_surprise`: bất ngờ nhẹ, tích cực.

Không dùng cue cho hướng dẫn kỹ thuật, y tế/an toàn, đau buồn, xin lỗi, ranh giới nghiêm túc hoặc nơi cue có thể nghe như chế giễu.

## Cấu hình

```env
ERIS_VOICE_DIRECTOR_ENABLED=1
ERIS_VOICE_DIRECTOR_TIMEOUT_S=3
ERIS_TTS_AUDIO_POLISH=0
```

Để tắt riêng Director khi chẩn đoán:

```env
ERIS_VOICE_DIRECTOR_ENABLED=0
```
