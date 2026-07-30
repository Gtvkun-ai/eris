# DeepSeek Surface Worker V17 cho ERIS

Bản V17 giữ đúng **một DeepSeek worker `surface`** làm giọng public cho autonomous, nhưng tước khỏi nó quyền quyết định có nên nói hay không. Quyền đó chuyển sang `InitiativeController` deterministic.

## 1. Kiến trúc có chú thích

```text
Background cognition
    observer      # latest_observation typed từ lượt public đã xảy ra
    inner         # tạo public-safe seed, không phát raw thought
    critic        # chỉ đánh dấu reviewed khi deep-observer thực sự chạy
    memory        # chỉ tạo memory anchor khi có evidence/provenance
       │
       ▼
Typed Cognitive Blackboard
    # Chuẩn hóa signal thành contract có kiểu.
    # Không chứa raw chain-of-thought, raw diary hay text riêng tư.
       │
       ▼
Initiative Controller
    # Code thường, không gọi model, chạy ở mức mili-giây.
    # Quyết định đúng một trong ba action:
       │
       ├── NO_OP
       │     # Không có neo public đủ tốt hoặc đang chờ user.
       │
       ├── BODY_ONLY
       │     # Live2D vẫn có phản ứng nhẹ, nhưng không phát lời.
       │
       └── SPEECH
             # Tạo SpeechIntent typed: topic, mode, anchor, evidence.
               │
               ▼
        Surface Worker
        # Chỉ viết wording cho SpeechIntent đã duyệt.
        # Không được đổi speak/silence, mode, topic owner hay evidence.
               │
               ▼
        Grounding Validator
        # Preflight trước model và postflight sau khi có text.
        # Chặn claim màn hình/memory/task không có provenance.
               │
               ▼
          TTS + Live2D
          # Public commit, voice, stage và animation.
```

## 2. Vì sao V17 không còn treo lâu rồi im

Luồng cũ:

```text
Surface model quyết định speak/silence + viết câu
→ InitiativeController mới gate
→ provider timeout/retry
→ có thể cuối cùng vẫn silence
```

Luồng mới:

```text
Controller quyết định trong code
→ chỉ khi SPEECH mới gọi Surface Worker
→ deadline ngắn 4 giây
→ lỗi thì local micro-fallback hoặc BODY_ONLY
→ không gọi Main AI/planner lần hai
```

Một câu small talk optional không còn được quyền giữ cả nhân vật đứng im hàng chục giây. Một nguyên tắc đáng lẽ hiển nhiên, nhưng phần mềm thường cần vài phiên bản để nhớ lại phẩm giá của mình.

## 3. Cấu hình Surface worker

Thêm gateway key riêng trong `config/secrets.json`:

```json
{
  "api_keys": {
    "ERIS_DS_SURFACE_API_KEY": "DAN_GATEWAY_KEY_SURFACE_VAO_DAY"
  }
}
```

Hoặc dùng biến môi trường:

```env
ERIS_DS_SURFACE_API_KEY=DAN_GATEWAY_KEY_SURFACE_VAO_DAY
```

Khuyến nghị bind key này vào một DeepSeek account/pool riêng trong Whale2API.

```env
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=0
```

Không có key riêng thì worker `surface` không khởi tạo. Runtime vẫn không treo: deterministic local fallback hoặc body-only sẽ tiếp quản.

## 4. Cấu hình deadline

```env
ERIS_SURFACE_INTENT_ENABLED=1
ERIS_SURFACE_REALIZER_TIMEOUT_SEC=4
ERIS_SURFACE_LOCAL_FALLBACK_ENABLED=1
ERIS_DS_SURFACE_JSONL=1
ERIS_DS_SURFACE_JSONL_REPAIR_ATTEMPTS=0
ERIS_DS_SURFACE_DROP_IF_BUSY=1
```

Giải thích:

- `ERIS_SURFACE_REALIZER_TIMEOUT_SEC=4`: tổng deadline một call Surface, runtime clamp trong khoảng 2–6 giây.
- `ERIS_SURFACE_LOCAL_FALLBACK_ENABLED=1`: cho phép câu local cực ngắn khi intent đã được controller duyệt nhưng provider lỗi.
- `ERIS_DS_SURFACE_JSONL_REPAIR_ATTEMPTS=0`: Surface không tự gọi thêm một vòng repair, tránh biến deadline 4 giây thành 8–12 giây.
- `ERIS_DS_SURFACE_DROP_IF_BUSY=1`: nếu worker đang xử lý lượt cũ thì bỏ lượt mới ngay và dùng local fallback/body-only, không xếp hàng chờ.

Biến cũ `ERIS_SURFACE_INTENT_TIMEOUT_SEC` chỉ còn phục vụ compatibility shim, production self-turn không dùng đường cũ.

## 5. Ba action của Initiative Controller

### `NO_OP`

Dùng khi:

- không có public anchor;
- đang chờ câu trả lời của user;
- cooldown/budget chặn và không có lý do body-only;
- privacy hoặc provenance không hợp lệ.

### `BODY_ONLY`

Dùng khi:

- user đang bận nhưng màn hình/activity vừa đổi;
- speech bị cooldown nhưng một phản ứng phi ngôn ngữ vẫn hợp lý;
- Surface worker lỗi và không nên phát local text.

Ví dụ Live2D:

- liếc nhẹ;
- nghiêng đầu;
- `quiet_presence`;
- `curious_glance`;
- `small_acknowledge`.

### `SPEECH`

Chỉ xuất hiện khi controller đã chọn một typed anchor thật:

- `conversation`;
- `task`;
- `discovery`;
- `screen/activity`;
- `self` public-safe;
- `presence` khi cadence đến hạn.

## 6. Dấu hiệu đúng trong log

Khởi động:

```text
DeepSeek Web worker san sang: role=surface ...
Mô hình đã sẵn sàng. cognitive_workers=...,surface,...
```

Một lượt nói bình thường:

```text
[initiative] action=speech anchor=presence reason=allowed
[surface worker] realized mode=small_talk confidence=0.84 anchor=presence
[ai autonomous] spoke ...
```

Provider Surface lỗi hoặc timeout:

```text
[surface worker] local fallback mode=small_talk reason=provider_unavailable_or_timeout
```

Nếu không có text fallback phù hợp:

```text
[ai autonomous] silence ... gate=surface_unavailable body_only=1
```

## 7. Ranh giới trách nhiệm

- Observer không viết lời public.
- Inner không phát raw thought.
- Critic không được quyền chặn/nói trực tiếp.
- Memory chỉ cấp evidence có provenance.
- Initiative Controller quyết định action.
- Surface Worker chỉ viết wording.
- Grounding Validator quyết định câu có đủ căn cứ để public hay không.
- TTS và Live2D chỉ thực thi public turn đã commit.
