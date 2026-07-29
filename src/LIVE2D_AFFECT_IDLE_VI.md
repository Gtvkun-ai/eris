# Live2D affect bridge và idle director

## Mục tiêu

Bản này tách điều khiển hình thể thành ba lớp:

1. **Affect nền** từ `PersistentInternalState` và private mind.
2. **Emotion/motion tạm thời** của câu đang nói hoặc lúc đang suy nghĩ.
3. **Idle director** tạo vi chuyển động có lịch khi Eris im lặng.

Không có raw chain-of-thought, nội dung DeepSeek hoặc prose của Inner Diary được gửi sang renderer. Runtime chỉ phát vector số đã clamp.

## Event mới: `affect_state`

```json
{
  "protocol": "eris.stage",
  "version": 2,
  "type": "affect_state",
  "source": "private_mind:deepseek:autonomous",
  "data": {
    "affect": {
      "valence": 0.21,
      "arousal": 0.28,
      "curiosity": 0.64,
      "boredom": 0.08,
      "social_energy": 0.35,
      "attachment": 0.43,
      "irritation": 0.09,
      "protectiveness": 0.22,
      "confidence": 0.71,
      "fatigue": 0.16,
      "tenderness": 0.34,
      "cognitive_tension": 0.27
    },
    "thought_pressure": 0.42,
    "confidence": 0.76,
    "diary_updated": true
  }
}
```

`runtime/live2d_affect_bridge.py` bucket hóa state và rate-limit event để các drift rất nhỏ không tạo bão UDP.

## Luồng ảnh hưởng

- Mỗi public turn phát snapshot affect trước `stage_segment`.
- Mỗi private-mind tick chụp lại affect **sau** mutation/synthesis rồi phát event.
- Nguồn event có provider, ví dụ `private_mind:deepseek:autonomous`.
- Emotion của lời thoại được ưu tiên trong lúc nói.
- Sau khi audio kết thúc, emotion tạm thời decay trong khoảng vài chục giây rồi hòa về affect nền.
- Affect cũ không bị giữ vô hạn: sau một khoảng yên lặng dài, renderer fade dần về baseline.

## Mapping hình thể

Affect chỉ dùng biên nhỏ:

- `valence`, `tenderness`, `attachment` làm mềm `ParamMouthForm` và mí.
- `irritation`, valence âm và `cognitive_tension` hạ mày, giảm độ mở mắt.
- `curiosity` tạo nhướng lệch một bên mày, nghiêng đầu và nhìn hơi lên.
- `fatigue`, `boredom` hạ mí và làm đầu trầm hơn.
- `thought_pressure` chỉ tăng nhẹ pose suy tư; không kích animation lớn.

Emotion explicit như `annoyed_soft`, `curious`, `warm_soft` vẫn có quyền ưu tiên cao hơn khi đang nói.

## Idle director

`live2d_body/idle.py` không random mỗi frame. Nó lên lịch từng gesture có ease-in/ease-out:

- liếc trái hoặc phải;
- nghiêng đầu nhẹ;
- soften;
- ponder khi private mind vừa có áp lực suy nghĩ;
- slow blink;
- vi dao động nền rất nhỏ giữa các gesture.

Khi đang nói, gesture idle bị dừng. Khi đang `thinking`, chỉ giữ mức vi động tác thấp để tránh giành sân với pose suy nghĩ.

## Biến môi trường

- `ERIS_LIVE2D_AFFECT_BRIDGE=1`: bật cầu affect.
- `ERIS_LIVE2D_AFFECT_MIN_INTERVAL_SEC=1.5`: khoảng tối thiểu giữa hai event.
- `ERIS_LIVE2D_AFFECT_HEARTBEAT_SEC=45`: gửi lại state không đổi sau thời gian này.

## File chính

- `runtime/live2d_affect_bridge.py`
- `runtime/stage_protocol_adapter.py`
- `runtime/private_mind_loop.py`
- `runtime/public_output_runtime.py`
- `live2d_body/affect.py`
- `live2d_body/idle.py`
- `live2d_body/stage_state.py`
- `live2d_body/renderer.py`

## Kiểm tra

- Test chuyên biệt Live2D/affect/idle: 17 passed.
- Phần còn lại của archive: 501 passed, 8 lỗi nền đã có trong source gốc.
- Các lỗi nền gồm module `tools.*` và file `body/*.cs` không được đóng gói, cùng một test ElevenLabs thất bại y hệt trên archive gốc.
