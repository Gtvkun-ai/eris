# DeepSeek Surface Worker V18 cho ERIS

V18 giữ đúng **một DeepSeek worker role `surface`**, nhưng chia nó thành hai contract typed:

1. **Social Initiative**: đề xuất ERIS muốn mở chủ đề gì.
2. **Surface Realizer**: viết câu public sau khi runtime governor cho phép.

Worker không tự quyết timing, cooldown hay quyền chen lời. Runtime cũng không tự nghĩ random chat. Hai bên cuối cùng chịu làm đúng nghề của mình, một sự kiện hiếm nhưng đáng ghi chép.

## 1. Cấu hình mặc định

Surface dùng chung DS2API gateway/account pool đã cấu hình:

```env
ERIS_DS2API_ENABLED=1
ERIS_DS2API_API_KEY=...
ERIS_DS_BASE_URL=http://127.0.0.1:6011/v1
ERIS_DS_MODEL=deepseek-v4-flash
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=1
```

`ERIS_DS_SURFACE_API_KEY` là override tùy chọn. Muốn account riêng:

```env
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=0
ERIS_DS_SURFACE_API_KEY=...
```

Startup đúng:

```text
DeepSeek Web worker san sang: role=surface ...
Surface worker owner: social candidate + public wording
```

## 2. Deadline và liveness

```env
ERIS_SOCIAL_INITIATIVE_TIMEOUT_SEC=3
ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC=180
ERIS_SOCIAL_INITIATIVE_HARD_SILENCE_SEC=600
ERIS_SOCIAL_INITIATIVE_PROBE_INTERVAL_SEC=90
ERIS_SURFACE_REALIZER_TIMEOUT_SEC=4
ERIS_DS_SURFACE_JSONL_REPAIR_ATTEMPTS=0
ERIS_DS_SURFACE_DROP_IF_BUSY=1
ERIS_SURFACE_LOCAL_FALLBACK_ENABLED=1
```

- `soft silence`: bắt đầu cho worker cơ hội nghĩ chủ đề xã hội.
- `hard silence`: initiative service tạo liveness candidate nếu model lỗi/không trả candidate.
- Candidate fallback chưa phải câu nói; governor vẫn có thể hoãn.
- Worker bận thì drop request mới, không xếp hàng sau một micro-line cũ.

## 3. Trách nhiệm

### Social Initiative Worker

Đầu ra `eris.social_speech_candidate.v1` gồm:

- kind;
- topic;
- speech act;
- relevance/confidence/urgency;
- anchor/evidence khi cần grounding;
- tone gợi ý.

Nó không viết câu cuối.

### Runtime Governor

Chỉ kiểm:

- user busy;
- reply baton;
- cooldown;
- budget;
- duplicate;
- privacy;
- provenance.

### Surface Realizer

Nhận `eris.speech_intent.v1`, viết tối đa hai câu, không đổi topic owner hoặc evidence scope.

## 4. Random chat

Các kind sau không cần screen fact:

```text
social_check_in
casual_curiosity
playful_prompt
random_chat
```

Chúng dựa vào public history, personality/identity summary và relationship state đã chuẩn hóa. Không dùng raw Inner Diary hay raw chain-of-thought.

## 5. Screen comment

Screen candidate chỉ hợp lệ khi:

- VisionGroundingReport đề nghị `speak`;
- có grounded claim chưa stale;
- có evidence ID;
- candidate copy đúng evidence ID.

Raw title/OCR delta chỉ được tạo body gesture. Surface local fallback không viết screen comment; worker unavailable thì ERIS body-only.

## 6. Log chẩn đoán

```text
[autonomous latency] perception=... context=... snapshot=... candidate=... total_to_governor=...
[social initiative] source=... kind=... anchor=... confidence=... relevance=... reason=...
[initiative] action=... anchor=... reason=...
[surface worker] realized mode=... confidence=... anchor=...
```
