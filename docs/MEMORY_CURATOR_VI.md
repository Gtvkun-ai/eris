# Memory Curator: Gemma ghi, Qwen gom, DeepSeek dọn

## Mục tiêu

Bản vá này tách đúng trách nhiệm của từng model:

- **Gemma/profile model** tiếp tục trích xuất memory từ lượt chat.
- **Qwen3-Embedding-0.6B** chỉ tìm record gần nghĩa và gom cụm duplicate.
- **DeepSeek worker `critic`** đánh giá cluster, đề xuất `archive`, `weaken` hoặc `merge`.
- **Validator deterministic** trong `UserProfileStore` mới được ghi thay đổi thật.

DeepSeek không được tạo fact mới, đổi path, sửa value hoặc xóa memory do người dùng
đã sửa/xác nhận qua authority ledger.

## Chu kỳ chạy

Daemon `runtime.memory_gc_service.MemoryGCService` chạy mặc định mỗi **600 giây**
khi runtime idle. Nếu version của living profile không đổi, nó bỏ qua các chu kỳ kế
tiếp và chỉ rà lại tối đa một lần mỗi ngày.

## Thiết lập đề xuất

Chép các biến sau vào file env runtime đang thực sự được nạp:

```env
ERIS_EMBEDDING_ENABLED=1
ERIS_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
ERIS_MEMORY_GC_ENABLED=1
ERIS_MEMORY_GC_INTERVAL_SEC=600
ERIS_MEMORY_GC_ALLOW_MODEL_FALLBACK=0
ERIS_MEMORY_GC_LIVING_LIMIT=40
ERIS_MEMORY_GC_LIVING_DUPLICATE_COSINE=0.86
ERIS_LIVING_USER_HISTORY_SNAPSHOTS=8
```

Đảm bảo worker critic đã có cấu hình:

```env
ERIS_DS_CRITIC_BASE_URL=http://127.0.0.1:6014/v1
ERIS_DS_CRITIC_API_KEY=<key đang dùng>
ERIS_DS_CRITIC_JSONL=1
```

## Các file chính

- `runtime/memory_gc_service.py`: scheduler 10 phút, lấy đúng critic worker.
- `memory/living_user/curator.py`: candidate selection, Qwen clustering, prompt critic và validator.
- `memory/living_user/store.py`: apply operation theo record ID và compact history.
- `config/memory.env.example`: cấu hình mẫu.

## Hành vi an toàn

Các record sau được bảo vệ khỏi curator:

- Evidence có prefix `authority:`.
- Source `user_authority_*`.
- Rule deterministic như `behavior_rule`.
- Path đang có correction/confirm/move-scope trong authority ledger.

Rule deterministic chỉ tự archive hai loại chắc chắn:

1. Value `null` hoặc rỗng.
2. `open_loops.*` tự mô tả rằng việc đã hoàn tất.

Mọi trường hợp còn lại phải qua DeepSeek critic và validator.

## Log kiểm tra

Sau mỗi lượt, log có dạng:

```text
[memory_gc] run #N maintenance=True semantic_drop=... living(applied=... archive=... weaken=... merge=...)
```

`memory_gc_service.last_result` cũng chứa các trường:

- `living_reviewed`
- `living_applied`
- `living_archived`
- `living_weakened`
- `living_merged`
- `living_history_removed`
