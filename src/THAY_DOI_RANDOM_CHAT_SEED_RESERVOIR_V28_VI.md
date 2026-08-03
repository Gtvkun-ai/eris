# Random Chat Seed Reservoir V28

## Luồng mới

```text
DS2API 6015 / role=seed
        ↓  chạy nền
RandomChatSeedGenerator
        ↓
RandomChatSeedReservoir (session-local, typed, bounded)
        ↓  atomic lease khi autonomous có quyền nói
Initiative Governor
        ↓
DS2API 6012 / role=surface
        ↓
Public commit + TTS
```

Seed worker không còn dùng `surface_client`, companion hay critic làm fallback. Nếu port 6015 hoặc role `seed` không sẵn sàng, reservoir tắt và random chat im thay vì tạo câu presence chung chung.

## Tích lũy

Reservoir mặc định giữ 4 seed, tối đa 7. Producer chạy daemon và nạp dần theo quota `shared`, `user_led`, `eris_led`, `experimental`. Seed phụ thuộc hội thoại gần đây bị vô hiệu khi user phát biểu; seed từ user memory hoặc self memory của Eris có thể sống lâu hơn trong TTL.

## Critical path

`SocialInitiativeEngine` chỉ gọi `reservoir.claim()`. Lệnh này không có network I/O. Seed được lease trong 45 giây:

- Governor hoặc Surface chưa phát được: trả seed vào kho.
- User chen lời: trả seed hoặc vô hiệu nếu đã stale.
- Public commit thành công: consume lease và ghi outcome vào affinity store.

## Cấu hình chính

```env
ERIS_DS2API_PORTS=6011,6012,6013,6014,6015
ERIS_DS_SEED_BASE_URL=http://127.0.0.1:6015/v1
ERIS_DS_SEED_API_KEY=
ERIS_DS_SEED_JSONL=1
ERIS_DS_SEED_DROP_IF_BUSY=1

ERIS_RANDOM_CHAT_SEED_RESERVOIR_ENABLED=1
ERIS_RANDOM_CHAT_SEED_TARGET_SIZE=4
ERIS_RANDOM_CHAT_SEED_MAX_SIZE=7
ERIS_RANDOM_CHAT_SEED_GENERATE_INTERVAL_SEC=12
ERIS_RANDOM_CHAT_SEED_RESERVOIR_TTL_SEC=600
ERIS_RANDOM_CHAT_SEED_LEASE_TTL_SEC=45
ERIS_RANDOM_CHAT_SEED_WORKER_TIMEOUT_SEC=35
```

Khi reservoir bật và seed URL là localhost, startup tự bổ sung port seed vào danh sách daemon kể cả cấu hình cũ chỉ ghi 6011–6014.
