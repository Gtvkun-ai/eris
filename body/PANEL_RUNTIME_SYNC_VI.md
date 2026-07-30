# Panel Runtime Sync — Architecture C v7 + Live2D Affect/Idle

Bản này chuyển panel khỏi giả định cũ rằng `emotion_debug` là nguồn trạng thái
chính. Contract ưu tiên hiện tại:

1. `eris.stage` v2 cho trạng thái sân khấu và lifecycle TTS.
2. `affect_state` cho khí sắc sống, thought pressure và confidence.
3. `identity_runtime` cho panel identity/depth.
4. `emotion_debug` và `depth_v2` chỉ là compatibility fallback.

## Panel Khí sắc & hiện diện

Panel đọc trực tiếp:

- `data.affect.valence/arousal/curiosity/irritation/...`
- `data.thought_pressure`
- `data.confidence`
- `data.diary_updated`
- `source`
- `thinking_started` / `thinking_finished`
- `audio_playback_started` / `audio_playback_done`
- `stage_segment` / `show_plan`

Nội dung inner diary hoặc chain-of-thought không được đưa sang UI. Panel chỉ nhận
metadata và vector số.

## ACK panel

`identity_runtime` là contract chính. `depth_v2` được chấp nhận như alias legacy,
nhưng không còn là điều kiện bắt buộc nếu identity runtime đã có dữ liệu.

## Tương thích

Các payload V4/V5 cũ vẫn được đọc. Nếu chỉ có `identity_runtime`, parser tự dựng
một EmotionDebug tối thiểu để UI không trắng.

## Sửa semantics hiển thị

- Trục valence đã sửa theo contract runtime: `-1` tiêu cực ở trái, `+1` tích cực ở phải.
- Chế độ dễ đọc không còn suy diễn “romcom” từ các key legacy; nó tóm tắt stage, activation, cognitive tension, social energy và fatigue.
- Bốn thanh chính dùng trực tiếp các trục affect hiện hành, không phụ thuộc `mood_inertia`/`distance` legacy.
- Maintenance reset xóa cả cache `RuntimePresence`, tránh panel dựng lại state cũ ngay sau reset.
