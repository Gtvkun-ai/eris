# Autonomous Social Initiative V18

## Mục tiêu

V18 sửa hai lỗi từ runtime thực tế:

1. ERIS có thể im rất lâu vì runtime chỉ cho nói khi đã có screen/memory/discovery anchor.
2. Một raw window title hoặc OCR delta có thể bị dùng như screen fact, dẫn đến câu sai kiểu coi `Brave` và chủ đề `moc3` là cùng một sự vật.

## Luồng mới

```text
Background cognition
    observer / inner / critic / memory
                 │
                 ▼
      Typed Cognitive Blackboard v2
                 │
                 ▼
      Social Initiative Worker
      DeepSeek role=surface
      chỉ đề xuất desire + topic
                 │
                 ▼
        Runtime Initiative Governor
        user-busy / baton / cooldown /
        budget / duplicate / privacy
                 │
        ┌────────┼───────────┐
        ▼        ▼           ▼
      NO_OP   BODY_ONLY   SPEECH_INTENT
                              │
                              ▼
                     Surface Realizer
                     cùng role=surface
                     chỉ viết wording
                              │
                              ▼
                    Grounding Validator
                              │
                              ▼
                         TTS + Live2D
```

## Trách nhiệm

### Social Initiative Worker

Sở hữu:

- ERIS có ý muốn mở chủ đề gì;
- speech act;
- mức relevance, confidence, urgency;
- social check-in, casual curiosity, playful prompt, random chat;
- lựa chọn một factual anchor đã tồn tại trong blackboard.

Không sở hữu:

- timing;
- quyền phát;
- câu public cuối;
- raw chain-of-thought;
- raw Inner Diary;
- tự cấp screen/memory evidence.

Contract: `eris.social_speech_candidate.v1`.

### Runtime Initiative Governor

Chỉ kiểm:

- user đang bận hoặc đang nhập chat;
- assistant đang chờ user trả lời;
- cooldown;
- hourly budget;
- semantic repeat;
- privacy và provenance.

Governor không tự nghĩ topic. Khi production truyền `candidate=None`, governor trả `NO_OP` hoặc `BODY_ONLY`.

### Surface Realizer

Nhận `eris.speech_intent.v1` đã được governor duyệt và viết tối đa hai câu. Nó không được đổi topic owner, evidence scope hoặc quyết định im/nói.

## Liveness

- Soft silence mặc định: `180s`.
- Hard silence opportunity mặc định: `600s`.
- Khi tới nhịp, Social Initiative Worker được đánh thức để đề xuất chủ đề.
- Nếu worker lỗi, initiative service có thể tạo một typed social candidate trung tính.
- Candidate fallback chưa phải câu nói. Governor vẫn có thể hoãn vì user busy/cooldown/baton.

Biến môi trường:

```env
ERIS_SOCIAL_INITIATIVE_TIMEOUT_SEC=3
ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC=180
ERIS_SOCIAL_INITIATIVE_HARD_SILENCE_SEC=600
ERIS_SOCIAL_INITIATIVE_PROBE_INTERVAL_SEC=90
```

## Một worker, hai contract

V18 không tạo thêm role DeepSeek mới. Cùng role `surface` xử lý:

1. social candidate;
2. public wording.

Hai nhiệm vụ tách bằng schema và prompt riêng. Mặc định Surface dùng chung DS2API gateway/account pool đã cấu hình:

```env
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=1
```

Đặt `0` khi thực sự muốn account/key riêng.

## Screen grounding

Raw window title, OCR text và mechanical delta chỉ được dùng để:

- biết màn hình vừa đổi;
- tạo body-only gesture;
- quyết định có cần refresh vision nền.

Chúng không tự tạo screen speech anchor. Screen candidate chỉ hợp lệ khi:

- `VisionGroundingReport.recommendation == "speak"`;
- có grounded claim chưa stale;
- có evidence ID;
- candidate copy đúng evidence ID đó.

Local fallback không viết screen comment. Nếu Surface unavailable, ERIS chỉ body gesture.

## Background observer

Autonomous loop dùng observer frame đã cache. Refresh observer chạy daemon thread và không giữ self-turn chờ. Log latency mới:

```text
[autonomous latency] perception=... context=... snapshot=... candidate=... total_to_governor=...
```

Candidate log:

```text
[social initiative] source=... kind=... anchor=... confidence=... relevance=... reason=...
```

Nhờ vậy một khoảng chờ dài có owner rõ ràng, thay vì biến mất giữa hai timestamp như một bí ẩn mang tính tổ chức.
