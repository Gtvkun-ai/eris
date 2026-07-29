# DeepSeek Surface Worker cho ERIS

Bản vá thêm một lane DeepSeek Web riêng tên **`surface`**. Lane này dùng để chọn cách ERIS tự biểu hiện trong autonomous rồi viết luôn một micro-line, thay vì gọi planner bằng account companion và sau đó gọi companion thêm lần nữa để viết câu.

## 1. Chỗ cấu hình API key mới

Thêm một gateway key Whale2API riêng vào `config/secrets.json`:

```json
{
  "api_keys": {
    "ERIS_DS_SURFACE_API_KEY": "DAN_GATEWAY_KEY_SURFACE_VAO_DAY"
  }
}
```

Cũng có thể đặt bằng biến môi trường:

```env
ERIS_DS_SURFACE_API_KEY=DAN_GATEWAY_KEY_SURFACE_VAO_DAY
```

Gateway key này nên bind vào **một DeepSeek account riêng** trong Whale2API. Mặc định lane surface không mượn key generic/companion. Chỉ khi chủ động chấp nhận dùng chung mới bật:

```env
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=1
```

Dùng chung key không được khuyến nghị, vì một câu small talk chậm có thể tranh đúng account phục vụ chat chính. Loài người vốn đã đủ giỏi tự tạo nút thắt cổ chai, phần mềm không cần học thêm.

## 2. Các mode surface

Worker có thể chọn đúng một mode trong danh sách runtime cho phép:

- `silence`: im lặng.
- `small_talk`: bắt chuyện đời thường.
- `dry_tease`: khịa khô, không hạ nhục.
- `soft_tease`: trêu nhẹ, có đường lui.
- `inner_thought`: nói một public-safe seed từ PrivateMind/agenda.
- `random_chat`: một ý ngẫu hứng nhưng vẫn có neo thật.
- `continuation`: nối mạch hội thoại đang mở.
- `memory_callback`: gọi lại context đã được cung cấp.
- `task_followup`: bám task/engagement đang hoạt động.
- `screen_comment`: bình luận màn hình khi có evidence tươi.

Model chọn mode và viết câu trong **một request**. Code phía ngoài vẫn kiểm tra evidence, privacy, task active, topic, confidence, semantic cooldown và grounding.

## 3. Luồng autonomous mới

```text
attention/commentary/task/screen/self seed
        ↓
DeepSeek role=surface
        ↓
chọn mode + topic + viết text
        ↓
SurfaceIntentEngine kiểm tra contract
        ↓
InitiativeController + grounding gate
        ↓
parser / stage / TTS / public commit
```

Nếu surface key chưa cấu hình, provider lỗi hoặc JSON không hợp lệ, runtime tự quay về autonomous planner cũ.

## 4. Biến cấu hình

```env
ERIS_SURFACE_INTENT_ENABLED=1
ERIS_SURFACE_INTENT_TIMEOUT_SEC=12
ERIS_DS_SURFACE_JSONL=1
ERIS_DS_SURFACE_ALLOW_SHARED_KEY=0
```

Tắt nhanh lane mới:

```env
ERIS_SURFACE_INTENT_ENABLED=0
```

## 5. Dấu hiệu đúng trong log

Khi khởi động:

```text
DeepSeek Web worker san sang: role=surface ...
Mô hình đã sẵn sàng. cognitive_workers=...,surface,...
```

Khi autonomous cân nhắc:

```text
[surface intent] decision=speak mode=dry_tease confidence=0.82 topic=...
```

Hoặc:

```text
[surface intent] decision=silence reason=...
```

Nếu không thấy `role=surface`, kiểm tra key mới trong `config/secrets.json` và gateway mapping ở Whale2API.

## 6. Quy tắc an toàn quan trọng

- `screen_comment` bị từ chối nếu screen evidence không tươi hoặc privacy bị khóa.
- `task_followup` bị từ chối nếu không có engagement active.
- `inner_thought` bị từ chối nếu không có public-safe self seed.
- Engagement đang chạy không cho surface đổi sang random chat không liên quan.
- User chat đến trong lúc surface đang suy nghĩ thì draft cũ bị bỏ trước khi phát public.
