# ERIS V43 — Event-Driven Mood Dynamics

## Mục tiêu

V43 hoàn tất phần V42 cố ý để lại: mood không được chỉ tồn tại như một vector gần như đứng yên rồi writer tự diễn cảm xúc bằng câu chữ.

Luồng mới:

```text
CognitiveEvent
     ↓
Affective appraisal
     ↓
PersistentInternalState
     ↓
AffectiveVoiceState
     ↓
chat + autonomous Surface + TTS/panel + Live2D/body
```

Nguyên tắc: **event làm mood đổi; scheduler tick chỉ làm mood phai dần**. Personality quyết định nền chậm và hình dạng biểu đạt, không được quyết định current mood thay cho event.

## 1. Không tạo mood store thứ ba

`PersistentInternalState` vẫn là current mood authority. V43 chỉ thêm `affective_state` bên trong chính state này để giữ:

- các trục phụ chưa có field sẵn: `delight`, `sadness`, `anxiety`, `playfulness`, `yearning`, `embarrassment`;
- `impulse` ngắn hạn sau event;
- provenance tối thiểu: event nào vừa làm state đổi, lúc nào, strength bao nhiêu.

Không có database mood mới, không có một service khác giữ “mood thật” song song.

## 2. Ba tốc độ cảm xúc

V43 tách ba nhịp:

1. **Impulse**: dư chấn vài chục giây đến vài phút, ví dụ vừa bị chọc cười hoặc vừa bị sửa.
2. **Current mood**: nằm trong `PersistentInternalState`, phai theo phút/giờ.
3. **Slow disposition**: `PersonalityProfile.mood`, chỉ là điểm nền mà current mood hồi về từ từ.

Personality không reset event affect ngay. Một Eris vốn kín vẫn có thể vui rõ nếu current state thật sự vui.

## 3. User turn tác động trước public writer

Direct chat ingest user turn thành `CognitiveEvent.from_user_turn()` trước khi project `AffectiveVoiceState` cho câu trả lời hiện tại.

Event ID dựa trên `turn_id`:

```text
cogevt:user:<turn_id>
```

Retry cùng lượt không được làm mood nhảy lần hai.

V43 tái dùng `SocialAppraisalEngine` hiện có để tạo tín hiệu typed như playful / affection / irritation / boundary / correction. Đây là appraisal cục bộ về **ý nghĩa interaction đối với Eris**, không phải fact kiểu “user chắc chắn đang vui”.

Regression có test đúng câu từng xuất hiện trong log V40:

```text
hí hí. chắc thế
```

Sau normalize thành `hi hi`, playful signal vẫn phải được nhận ra. Writer không còn được tự “hí hí” trong khi state vẫn playfulness thấp.

## 4. Relationship điều biến biên độ, không bịa cảm xúc

Cùng một event playful không có cùng biên độ ở mọi trạng thái quan hệ. Trust / playful safety / rupture chỉ modulate response delta.

Nếu event không có playful/affection/boundary signal, relationship không được tự tạo một mood mới từ hư không.

## 5. Internal cognitive event chỉ nudge nhẹ

Seed / internal thought dùng cùng `CognitiveEvent` identity của V42. Curiosity event có thể nudge `curiosity/arousal` nhẹ.

Một thought bình thường không tự được phép tạo delight/sadness/playfulness. Surface prose không đi ngược vào affect runtime, nên không có vòng:

```text
Surface nói thơ → mood đổi → seed mới → Surface lại nói thơ
```

## 6. Tick nền chỉ decay

`mental_process_runtime` gọi affect decay trước khi evolve mental processes. Không tạo CognitiveEvent mới.

Decay giữ inertia:

- impulse phai nhanh;
- current mood phai chậm hơn;
- current mood hồi về slow disposition, không reset về một tone cố định ở tick kế tiếp.

## 7. Một projection dùng chung cho text, TTS và body

`effective_affect_values()` là projection chung cho V43 current mood + impulse.

Nó được dùng bởi:

- `AffectiveVoiceState` cho direct chat và autonomous Surface;
- emotion debug payload dùng cho delivery/TTS/panel;
- Live2D affect bridge;
- body bias payload.

Mục tiêu là tránh ba consumer tự copy hệ số rồi vài version sau có ba Eris với ba nhiệt độ khác nhau.

## 8. Mood bias cognition rất nhẹ trước Neuro

V43 thêm `affective_selection_bias()` như một projection typed, không phải policy quyết định action:

- curiosity cao có thể tăng nhẹ epistemic value của proposal khám phá/question/association;
- playfulness cao chỉ giúp candidate vốn đã playful hấp dẫn hơn một chút;
- social energy thấp/fatigue tăng cost của speech;
- irritation cao chỉ làm repair/correction/contradiction nổi hơn.

Bias này không được đổi `action_kind`, không được nới grounding và không được biến mood thành quyền nói. Neuro vẫn là authority cuối. Baseline bình thường cho bias gần 0 để không âm thầm retune toàn hệ.

## 9. AffectiveVoiceState V43

Version:

```text
eris.affective_voice.v43.event_driven_mood
```

Ngoài các trục cũ, debug projection có:

- `embarrassment`;
- `affect_event_kind`;
- `affect_event_age_seconds`;
- `affect_impulse_strength`.

Prompt vẫn chỉ nói rằng affect hiện tại là authority cho delivery/cadence/energy. Nó không ra lệnh “hãy vui”, “hãy lạnh”, “hãy ấm kín”.

## 10. Mood không phải sensor và không đổi sự thật

Affect chỉ được tác động cách biểu đạt và một phần state nội tại. Nó không được:

- tạo claim về user;
- tạo claim môi trường;
- nới claim-domain contract V42;
- giảm epistemic threshold chỉ vì Eris đang bực/vui.

Grounding và semantic authority của V42 được giữ nguyên.

## 11. Log nên xem khi test thật

Tìm:

```text
[affect event] applied id=... origin=user kind=user_turn strength=... labels=... delta=...
[affect state] valence=... arousal=... curiosity=... social=... irritation=... play_pressure=... impulse_play=... impulse_delight=...
[affective voice] channel=chat ...
[affective voice] channel=autonomous ...
```

Behavior tốt:

1. user playful rõ → `play/delight/valence` tăng ngay ở cùng turn;
2. boundary/irritation → play/social energy giảm, irritation tăng;
3. vài phút yên → impulse giảm dần, không reset ngay;
4. cùng turn retry → không có affect event thứ hai;
5. seed curiosity có thể nudge curiosity nhưng không tự tạo “vui”;
6. chat và autonomous đọc cùng state;
7. Live2D/TTS không còn bình thản nếu text writer vừa nhận playful impulse.

## 12. File chính thay đổi

- `cortex/affective_dynamics.py` — state transition, decay, slow disposition và shared effective projection.
- `runtime/affective_dynamics_runtime.py` — event ingress/idempotency/runtime owner.
- `cortex/cognitive_event.py` — user-turn CognitiveEvent identity.
- `cortex/internal_state.py` — persist `affective_state` trong current state.
- `runtime/ai_orchestrated/orchestrator.py` — user affect event trước current chat writer.
- `runtime/active_concern_runtime.py` — cùng seed CognitiveEvent nudge affect đúng một lần.
- `runtime/mental_process_runtime.py` — background decay, không fake event.
- `runtime/affective_voice_state.py` — V43 current authority + shared projection.
- `runtime/public_output_runtime.py` — emotion/TTS/panel đọc effective affect.
- `runtime/live2d_affect_bridge.py` + `runtime/stage_protocol_adapter.py` — stage/body đọc cùng state.
- `runtime/body_bias.py` — body payload mang affect hiện tại.
- `runtime/subject_proposals.py` + `self_turn_pipeline.py` — typed affective selection bias trước Neuro.
- `tests/test_v43_event_driven_affect.py` — regression V43.

## 13. Deploy

Sau khi copy source V43 vào repo thật:

```bat
src\tools\prepare_v43_runtime.bat
```

Kỳ vọng:

```text
[V43 PREFLIGHT] PASS: eris.affect.v43.event_driven | eris.affective_voice.v43.event_driven_mood | eris.cognition.v42.event_driven
```

## 14. Phạm vi cố ý không mở thêm

V43 không thêm outcome learning, associative memory mới, humanizer, phrase blacklist hay một “emotion LLM”. Sau V43 nên test cả V42 cognition + V43 mood trong cùng một session trước khi mở thêm cơ chế mới.
