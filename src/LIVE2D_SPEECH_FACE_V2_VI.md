# Live2D speech face V2 cho Eris

## Mục tiêu

Bản này sửa hai điểm chính: miệng không còn há theo hai sóng sin độc lập với audio, và context biểu diễn của từng câu được dùng đồng thời cho đầu, mắt, lông mày, hướng nhìn và mood miệng.

## Đường lip-sync

1. `runtime/tts_task_manager.py` nhận WAV đã synthesize.
2. `runtime/audio_lip_sync.py` đọc PCM, tính RMS theo khung 40 ms, noise-gate, nén biên và làm mượt attack/release.
3. Envelope gọn `0..0.86` được gắn vào event `audio_start` dưới các field:
   - `audio_envelope`
   - `audio_frame_ms`
   - `audio_duration_ms`
4. `stage_protocol_adapter.py` chuyển event thành `audio_playback_started`.
5. `live2d_body/speech_animation.py` nội suy envelope theo thời gian phát và đổi độ mở `0..1` sang `ParamMouthOpenY` của rig `-1..1`.

Đoạn im lặng trong WAV cho giá trị gần 0 nên miệng khép về `-1`. Khi audio kết thúc hoặc bị hủy, animator dừng và miệng đóng hẳn. Nếu event cũ không có envelope, runtime dùng pseudo-viseme theo cụm nguyên âm và dấu câu thay cho oscillator cũ.

## Tận dụng parameter khuôn mặt

- `ParamAngleX`: head follow và action như `look_away`, `look_down`, `lean_in_small`, `nod_small`; luôn clamp trong `-30..+10` theo phía người xem.
- `ParamEyeLOpen`, `ParamEyeROpen`: mood, squint, slow blink và wink chạy riêng từng mắt, sau đó nhân với auto-blink để không phá chớp mắt gốc.
- `eyeballxl`, `eyeballxr`: cùng một hướng nhìn màn hình được đổi thành hai giá trị trái dấu. Mắt hướng vào sống mũi có biên nhỏ hơn để giảm cảm giác lé.
- `eyebally`, `eyeballyr`: nhận hướng nhìn dọc từ cursor, affect, idle và cue lời nói.
- `ParamBrowLAngle`, `ParamBrowRAngle`: question/curious nhướng lệch, annoyed hạ cả hai, dry tease nhướng nhẹ một bên; không nhướng cả đôi chỉ vì mood vui.
- `ParamMouthForm`: giữ mood nền từ affect/emotion, cộng style của câu và điều chỉnh rất nhẹ theo nhóm nguyên âm.
- `ParamMouthOpenY`: độ mở theo audio thật; đóng nhanh hơn mở để khe giữa âm tiết không bị smoothing nuốt mất.

## Context theo segment

`stage_segment` thường có nhiều dữ liệu biểu diễn hơn `audio_playback_started`. `Live2DStageState` cache context bằng `(turn_id, seq)` rồi merge với envelope lúc audio bắt đầu. Cache giới hạn 24 segment và không cho action như `wink` rò sang turn mới.

Các cue đang được dùng gồm question, exclamation, warm/dry/deadpan/annoyed/quiet/curious/focused, smile/laugh, look away/down, tilt head, lean in, squint, wink, slow blink, nod và shake head.

## Giới hạn

Đây là energy-based lip-sync, không phải phoneme/viseme alignment từ TTS. Model chỉ có `ParamMouthForm` và `ParamMouthOpenY`, nên không thể tạo hình môi chính xác cho từng phụ âm nếu không sửa rig nguồn `.cmo3` hoặc nhận timing phoneme trực tiếp từ nhà cung cấp TTS.
