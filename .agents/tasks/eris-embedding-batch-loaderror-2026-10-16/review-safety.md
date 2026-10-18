# Batch recall embedding với lexical fallback và health signal một lần

Thay đổi gom document embedding của profile và episode thành một batch cho mỗi lượt recall, đồng thời giữ lexical scoring khi model không load hoặc vector trả về rỗng. Lỗi load trở thành trạng thái sticky trên shared `EmbeddingIndex`, phát một log error duy nhất và lộ cờ qua `debug_status()`. Bốn finding của vòng trước đã được xử lý: malformed batch không thoát biên fail-soft, test load-fail không thể chạm model registry, empty-vector được chạy xuyên cả hai consumer, và cache-hit qua nhiều lượt có test trực tiếp. `verification.md` ghi 16 focused test và 75 regression memory test đều qua, đồng thời nói rõ môi trường không có model thật.

Watch for: **confirmed** — không còn finding chặn; các finding cũ về malformed vectors, offline isolation, empty-vector consumer coverage và cache cross-turn đều đã được sửa trong diff cuối.

**Verdict**: APPROVED

## High-level view

Khi model load lỗi, provider trả `()` cho query/document và `[(), …]` cho batch. Context compiler bỏ dense scoring ngay khi query vector rỗng; episode search quy batch vector rỗng về cosine `0.0`, nên cả hai đường tiếp tục lexical recall.

Lần load lỗi đầu đặt `_load_error`, `_load_failed_signaled=True` và phát `logger.error`; các lượt sau dừng ở guard `_load_error` nên không thử lại hay spam log. Production tái sử dụng shared index, log cung cấp signal cho observability, còn `debug_status()` cho phép đọc trạng thái chủ động.

Phạm vi production chỉ gồm ba file memory yêu cầu; ba file còn lại là focused tests. Diff không thêm dependency, đổi model loading, scoring weights hay memory write APIs. Verification phân biệt rõ load-fail thật trong môi trường hiện tại với vector-backed behavior dùng fake index.

<details>
<summary>Issues (0)</summary>

</details>

<details>
<summary>Details</summary>

## Empty-vector và malformed-provider fallback

`ProfileContextCompiler._query_vector()` vật chất hóa load-fail thành `()`, rồi chọn zero-dense trước khi batch profile. Episode search vẫn gọi batch khi `q_vec=()`, nhưng `[(), …]` được `_cosine()` quy về `0.0`; bất đối xứng này không làm thoát exception hay mất lexical recall. Ngoài đường chuẩn đó, context compiler giữ `len(vectors)` và cosine conversion trong biên `try`; episode store bắt lỗi khi lấy/vật chất hóa batch và quy row không iterable hoặc không chuyển được sang float về zero. `embedding_index=None`, `embed_documents` không callable và sai số lượng vector cũng giữ dense ở `0.0`.

## One-shot signal bám theo shared index

Sau exception đầu tiên, `_load_error` khiến `_ensure_loaded()` trả `False` trước model loader. Cùng lần đó, error log ghi model và lexical-only fallback; `debug_status()` trả `loaded=False`, nội dung `load_error` và `load_failed_signaled=True`. Các production consumer lấy provider qua `get_shared_embedding_index()`, nên signal không bị phát lại do tạo index theo từng chat turn.

## Batch mapping không đổi ranking hay write path

Hai consumer tạo document list từ candidate list rồi map vector về bằng cùng index; chuỗi profile `path: value`, chuỗi episode và toàn bộ hệ số scoring giữ nguyên. Batch đi qua `EmbeddingIndex.embed_documents()` → `_encode_with_cache()`, giữ cache namespace theo model/role/text và chỉ encode document chưa có. Diff không chạm `observe_turn`, dream, digest, `UserEpisodeStore.add()`, compact, scrub hay save; cũng không thêm `torch`/`transformers` hoặc sửa `_load_model()`.

## Bằng chứng cho degraded và vector-backed states

`verification.md` ghi focused command trên ba file test đạt `16 passed in 1.24s`. Coverage gồm empty-vector xuyên hai consumer, malformed/missing/mismatched batch, one-shot health signal, fake vector index gọi batch đúng một lần và cache-hit giữa hai lượt; test load-fail patch `_load_model` để không thể resolve model từ mạng.

Hai batch regression memory được ghi `35 passed in 1.98s` và `40 passed in 2.15s`. Review này không chạy lại test theo yêu cầu; kết luận dựa trên diff và bằng chứng lệnh/kết quả, với giới hạn thiếu `torch`/`transformers` được khai báo rõ.

</details>

<details>
<summary>File map</summary>

- `src/memory/embedding_index.py` — giữ load failure fail-soft, phát error signal một lần và lộ health flag.
- `src/memory/living_user/context_compiler.py` — batch profile documents và hạ batch/vector lỗi về zero-dense.
- `src/memory/living_user/episode_store.py` — batch episode documents, giữ lexical fallback và cosine fail-soft.
- `src/tests/test_embedding_index_health.py` — kiểm load-fail, one-shot signal, debug status và cache cross-turn offline.
- `src/tests/test_context_compiler_batch.py` — kiểm profile batch cùng fallback empty/malformed/missing.
- `src/tests/test_episode_store_batch.py` — kiểm episode batch cùng fallback empty/malformed/missing.

Full diff: `git -C c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eris-embedding-batch-loaderror diff main...HEAD --`. Plain worktree diff rỗng vì patch đã nằm trong branch commits.

</details>
