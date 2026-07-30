# Kiến trúc DeepSeek Web Utterance cho Eris

## Mục tiêu

Đường public của một lượt chat chỉ có hai hệ thống từ xa bắt buộc:

1. DeepSeek Web qua Whale2API/DS2API tạo một semantic commit hoàn chỉnh.
2. ElevenLabs tổng hợp audio từ speech surface đã commit.

Voice Director từ xa và Speech Localizer từ xa không còn nằm trong runtime public path. Chúng không chỉ làm chậm mà còn tạo thêm semantic authority, khiến mỗi tầng có thể diễn giải lại câu trước đó.

## Một semantic authority

DeepSeek Web trả một `UtteranceSpec` trong cùng JSON với `semantic_frame`, `assistant_act` và `should_speak`:

```json
{
  "semantic_frame": {},
  "assistant_act": {
    "kind": "answer",
    "proposition_mode": "new",
    "confidence": 0.91
  },
  "should_speak": true,
  "utterance": {
    "display": {
      "language": "vi",
      "text": "Tôi đang tính. Nước này không đơn giản."
    },
    "speech": {
      "language": "ja",
      "text": "考えている。この手は単純じゃない。"
    },
    "performance": {
      "preset": "focused",
      "intensity": 0.55,
      "nonverbal": "small_breath"
    },
    "delivery": {
      "priority": "normal",
      "interruptible": true
    }
  }
}
```

`turn_id` do runtime cấp. Model không được tự sở hữu identity của lượt.

Sau khi commit, Stage chỉ được:

- lọc markdown/tag khỏi từng surface;
- compile preset thành metadata Live2D/ElevenLabs;
- fan-out sang UI, body, TTS, memory và telemetry.

Stage không được dịch, viết lại hoặc hỏi model khác về cảm xúc.

## Luồng public

```text
User input / autonomous speech intent
            │
            ▼
PublicLifecycle: COMPOSING
            │
            ▼
DeepSeek Web, một request, deadline 12 giây
            │
            ▼
UtteranceSpec commit bất biến
            │
            ├── DisplayRenderer giữ bubble
            ├── BodyRenderer giữ pose thinking
            ├── VoiceProfileCompiler chạy local
            ├── MemoryRenderer ghi display surface
            └── ElevenLabs bắt đầu synth
                     │
                     ▼
              first audio callback
                     │
                     ├── lifecycle SPEAKING
                     ├── nhả bubble
                     └── lip-sync
```

Bubble vẫn bị giấu đến khi audio bắt đầu, đúng chủ đích sản phẩm. Trong khoảng đó UI không im lặng: lifecycle phát trạng thái thật và Live2D giữ pose suy nghĩ.

## Lifecycle

Các trạng thái hợp lệ:

```text
RECEIVED → COMPOSING → CONTENT_COMMITTED → AUDIO_BUFFERING → SPEAKING → DONE
                       └───────────────────────────────→ DEGRADED
                       └───────────────────────────────→ INTERRUPTED
```

- `RECEIVED`: pulse rất ngắn cho input trực tiếp.
- `COMPOSING`: DeepSeek Web đang tạo semantic commit.
- `CONTENT_COMMITTED`: nội dung đã có nhưng bubble còn bị giữ.
- `AUDIO_BUFFERING`: ElevenLabs đang chuẩn bị audio, body vẫn suy nghĩ.
- `SPEAKING`: first audio đã tới; bubble và lip-sync được phát.
- `DEGRADED`: deadline/TTS/fallback local; nhả text để không mất lượt.
- `INTERRUPTED`: input mới đã supersede lượt cũ.

State machine từ chối regression, ví dụ callback `audio_buffering` đến muộn không thể kéo `SPEAKING` quay ngược.

## Deadline và fallback

Trong mode `ERIS_REMOTE_PROVIDER=deepseek_web`:

- Main semantic request có deadline mặc định 12 giây.
- Không gọi official DeepSeek, Gemini hoặc Groq sau khi Web fail.
- Không lặp lại cùng Main request một lần nữa.
- Không gọi remote wording retry cho grounding failure.
- Candidate không an toàn hoặc hết hạn bị suppress, sau đó runtime dùng degraded local response có đánh dấu.

Điều này giữ P95 có biên rõ. “Fallback” không còn là tên lịch sự cho việc cộng thêm một timeout nữa.

## Performance compiler

`runtime/voice_profile_compiler.py` compile deterministic:

```text
performance.preset + intensity + nonverbal
                    │
                    ▼
voice_plan.delivery
  style / speed / energy / warmth / pitch / vocalization
```

Compiler không truy cập mạng và không thay text. ElevenLabs vẫn nhận metadata theo shape cũ, nên provider/model/voice tuning hiện tại được giữ.

## Post-commit safety rewrite

Một deterministic policy đôi khi buộc phải thay câu sau semantic commit, chẳng hạn stance guard hoặc required-reply repair. Không được chỉ thay tiếng Việt rồi giữ speech Nhật cũ.

`degrade_surface_payload()` sẽ:

- thay cả display và speech bằng cùng surface an toàn;
- dùng cùng language cho hai surface;
- giữ delivery contract hợp lệ;
- gắn `utterance_degraded=true` và reason cụ thể.

Đây là degradation trung thực, không giả vờ rằng runtime đã dịch được câu mới mà không gọi model.

## Autonomous

Autonomous surface cũng trả một bilingual `UtteranceSpec` trong một lần gọi. Lifecycle `COMPOSING` bắt đầu sau khi governor đã duyệt quyền nói, trước khi surface được realize. Vì thế Eris không liên tục làm pose suy nghĩ cho những deliberation kết thúc bằng silence.

Startup online cũng dùng DeepSeek Web. Preset startup chỉ còn là degraded fallback khi Web unavailable.

## Cờ

Bản kiến trúc này không thêm chess fast-path và không hạ depth. Cờ tiếp tục dùng cadence/domain pipeline hiện có. Sự cải thiện trải nghiệm đến từ lifecycle/body feedback và việc loại hai remote call hậu kỳ, không phải ép engine chơi nông hơn.

## Cấu hình chuẩn

```env
ERIS_REMOTE_API_ENABLED=1
ERIS_REMOTE_PROVIDER=deepseek_web
ERIS_DS2API_ENABLED=1
ERIS_DS_BASE_URL=http://127.0.0.1:6011/v1
ERIS_DS_MODEL=deepseek-v4-flash
ERIS_DS_COMPANION_API_KEY=...

ERIS_MAIN_SEMANTIC_DEADLINE_SEC=12
ERIS_CHAT_FORMAT_FALLBACK_ENABLED=0
ERIS_ESCALATION_ENABLED=0
ERIS_COMPANION_ROUTING_ENABLED=0

ERIS_VOICE_DIRECTOR_ENABLED=0
ERIS_TTS_STAGE_LOCALIZE=1
ERIS_TTS_LANGUAGE=ja
ERIS_TTS_SYNC_TEXT=1
ERIS_TTS_TEXT_SYNC_TIMEOUT=30
```

ElevenLabs config được giữ nguyên trong `config/deepseek.env.example`.

## Acceptance

Các invariant quan trọng có test:

- DeepSeek Web provider chỉ dựng companion worker.
- Main Web failure không gọi semantic fallback thứ hai.
- Request có deadline 12 giây.
- Bilingual commit không gọi localizer.
- deterministic voice compiler không gọi mạng.
- lifecycle giữ thinking qua content commit và audio buffering.
- lifecycle không regression sau speaking.
- post-commit rewrite không để display/speech mâu thuẫn.
