# V39 — Affective Voice State dùng chung cho chat và autonomous Surface

## Mục tiêu

V38 làm voice mềm hơn nhưng vẫn còn một lỗi kiến trúc: personality/prompt có thể vô tình đặt sẵn một **nhiệt độ cảm xúc cố định** như “ấm kín”, “restrained”, “calm”, “not bubbly”. Khi đó mood có tồn tại trong runtime nhưng public writer lại bị prompt kéo về cùng một giọng.

V39 đổi authority:

```text
PersistentInternalState + PersonalityProfile.mood + RelationshipState
                         ↓
                AffectiveVoiceState
                         ↓
              ┌──────────┴──────────┐
              ↓                     ↓
       Direct Chat Writer     Autonomous Surface
```

**Mood/affect hiện tại quyết định hướng và cường độ cảm xúc. Personality chỉ định hình cách biểu hiện.** Guardedness chỉ điều chỉnh mức tự bộc lộ, không được tự động biến Eris thành lạnh, nhỏ giọng hay ít vui.

## Những thay đổi quan trọng

### 1. Một state biểu đạt dùng chung

File mới: `runtime/affective_voice_state.py`.

State gom các tín hiệu runtime đang có sẵn, không tạo một “mood hệ thứ ba”:

- valence, arousal, curiosity, social energy;
- attachment, tenderness, irritation, fatigue;
- delight, sadness, anxiety, playfulness, yearning;
- social guardedness, disclosure selectivity, directness, dry humor;
- familiarity, closeness, playful safety, boundary safety, rupture;
- `expressive_drive`, affiliation, withdrawal;
- trajectory/delta của affect giữa các sample có ý nghĩa.

Tracker chỉ nhớ sample trước để đo trajectory. Nó không sở hữu cảm xúc và không thay PersistentInternalState.

### 2. Direct chat đọc AffectiveVoiceState thật

`runtime/ai_orchestrated/orchestrator.py` project state ngay trước public reply. Affective block được đặt trước personality summary để prompt budget kỹ thuật không cắt mất mood sống.

Runtime log có dạng:

```text
[affective voice] channel=chat version=eris.affective_voice.v39.state_authority valence=... arousal=... curiosity=... social=... delight=... play=... irritation=... sadness=... expressive=... trajectory=...
```

### 3. Autonomous Surface đọc cùng state

`self_turn_pipeline.py` đưa đúng state vào planner snapshot. `surface_intent.py` chuyển nó cho Surface và ghi cùng schema log với `channel=autonomous`.

Surface chỉ được dùng affect để thay đổi **delivery/cadence/energy/edge/disclosure**. Affect không được tạo fact mới, không được đổi motive và không phải sensor evidence.

### 4. INFJ là hàm biểu đạt, không phải tone preset

Voice contract mới bỏ authority kiểu:

- “ấm kín làm nền”;
- “emotionally restrained” như default;
- “not bubbly” như trần cảm xúc;
- technical task = lạnh hơn;
- neutral = tự động `guarded_warm`.

Thay vào đó:

- vui thật → được sáng và sống động hơn;
- tò mò thật → cadence mở và exploratory hơn;
- bực thật → câu được có cạnh;
- buồn/mệt → năng lượng được hạ;
- playful thật → humor/nhịp được mở nếu relationship cho phép;
- neutral thật → neutral, không tự bịa warm/cold mood.

Personality vẫn quyết định **cách** Eris vui/bực/thương/tò mò: mức disclosure, directness, dry humor, cách giữ continuity và khoảng cách quan hệ.

### 5. TTS/localizer cũng không kéo mood về baseline

`tts_engine.py`, `speech_localizer.py`, `speech_persona_polish.py` được đổi để giữ nhiệt độ cảm xúc của source/performance state. Delivery hint không còn là lệnh “làm ấm mọi câu”.

Các constraint tình huống cụ thể vẫn còn. Ví dụ boundary/low-affordance có thể yêu cầu câu low-pressure hoặc restrained vì **tình huống**, không phải vì INFJ mặc định phải như vậy.

## Logging nên kiểm khi chạy thật

Trong cùng một session, tìm cả hai:

```text
[affective voice] channel=chat ...
[affective voice] channel=autonomous ...
```

Khi mood thay đổi, `valence/arousal/delight/play/irritation/sadness/expressive/trajectory` phải thay đổi tương ứng. Nếu state thay đổi nhưng văn vẫn cùng nhịp, lỗi nằm ở realization. Nếu log state không đổi dù mood runtime đã đổi, lỗi nằm ở projection/state ownership.

## Deploy

Sau khi copy source V39 vào repo thật, chạy một lần:

```bat
src\tools\prepare_v39_runtime.bat
```

Kỳ vọng:

```text
[V39 PREFLIGHT] PASS: eris.affective_voice.v39.state_authority | eris.voice.v39.affect_authoritative
```

Script xóa `.pyc/__pycache__` cũ trước khi compile để tránh lỗi source/bytecode lệch phiên bản.

## Regression đã chạy trong working tree

- Focused affect/Surface/TTS/personality: 118 test (sau khi dọn các preset phụ).
- Bộ rộng chat/personality/Surface/autonomous/seed/voice: 184 test.

Artifact cuối còn được giải nén vào thư mục sạch và chạy lại regression + preflight trước khi phát hành. Kết quả artifact được ghi trong file notes phát hành bên ngoài ZIP.

## Kết quả validation artifact phát hành

Artifact cuối được đóng không kèm `.pyc`, `__pycache__`, `.pytest_cache`, sau đó giải nén sang thư mục sạch và kiểm lại:

- cache/bytecode có sẵn trong ZIP: `0`;
- V39 import/preflight: **PASS**;
- bộ regression rộng chạy từ artifact: **184/184 PASS**;
- unified patch kiểm bằng `git apply --check` trên V38 sạch: **PASS**.
