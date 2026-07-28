# ERIS Voice Director v3 + ElevenLabs

Voice Director v3 chỉnh **cách đọc và một tín hiệu phụ rất ngắn**, không chia câu hay viết lại lời thoại.

## Contract

```json
{
  "reason": "dry playful reassurance",
  "delivery": {
    "style": "dry_tease",
    "emphasis": ["biết cách"],
    "speed": 0.99,
    "energy": 0.43,
    "warmth": 0.68,
    "pitch": "slightly_low",
    "vocalization": "small_laugh",
    "vocalization_position": "suffix"
  }
}
```

Các giá trị `vocalization` hợp lệ:

```text
none
soft_hum
gentle_ack
small_laugh
soft_sigh
curious_hm
soft_surprise
```

Director không được:

- trả nhiều segment hoặc chia transcript thành nhiều clip;
- sửa, dịch, thêm hoặc bỏ nội dung chính;
- tạo pause/dead air riêng;
- tự viết ElevenLabs tag hoặc chuỗi sound effect;
- quyết định bật/tắt lời nói.

Validator chỉ nhận đúng một `delivery`. Cue lạ bị đổi thành `none`; vị trí lạ bị chuẩn hóa về `prefix` hoặc `suffix`.

## Luồng ElevenLabs

```text
Public transcript sạch
        ↓
STYLE chọn delivery + tối đa một cue
        ↓
StageOutputPipeline giữ nguyên một StageFrame
        ↓
Renderer chèn cue vào text nội bộ
        ↓
ElevenLabs nhận đúng một HTTP request
        ↓
Một WAV, một lần playback
```

Renderer dùng:

- `small_laugh` → `[laughs]`
- `soft_sigh` → `[sighs]`
- `soft_hum` → `Ừm…` / `ん…` / `Mm…`
- `gentle_ack` → `Ừ.` / `うん。` / `Mm-hm.`
- `curious_hm` → `Hửm?` / `ん？` / `Hm?`
- `soft_surprise` → `Ồ.` / `へえ。` / `Oh.`

Các token trên chỉ đi vào TTS payload. Chúng không được ghi vào UI hay memory.

## File chính

- `runtime/voice_director.py`: prompt, enum cue và validator single-take.
- `runtime/stage_output.py`: giữ cue trong metadata nhưng không tạo segment/pause.
- `runtime/tts_engine.py`: render cue bên trong cùng payload ElevenLabs.
- `tests/test_voice_director_elevenlabs.py`: kiểm tra cue chỉ xuất hiện một lần và chỉ có một HTTP request.
