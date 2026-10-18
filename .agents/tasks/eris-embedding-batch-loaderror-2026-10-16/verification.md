# Verification — Vá nuốt lỗi embedding + batch hóa đường recall

Worktree: `c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\eris-embedding-batch-loaderror`
Branch: `eris-embedding-batch-loaderror`
Interpreter: `c:\Users\Gtvkun\Documents\GitHub\eris\.venv\Scripts\python.exe`
(worktree không có `.venv` riêng, dùng `.venv` của checkout cha).

## Giới hạn môi trường (quan trọng khi đọc kết quả)

`.venv` THIẾU `torch`/`transformers`, model dir rỗng. Do đó `EmbeddingIndex`
thật LUÔN rơi vào nhánh load-fail (vector rỗng). Mọi test ở trạng thái embedding
rỗng đã được kiểm trực tiếp. Trạng thái "embedding chạy thật" được mô phỏng bằng
fake embedding index trả vector thật — KHÔNG cần model thật, theo đúng ràng buộc
"không cài torch/transformers, không tải model". Cả hai trạng thái đều XANH.

## Lệnh đã chạy + kết quả

### 1. Test mới (health + batch episode + batch context_compiler)

```
python -m pytest src/tests/test_embedding_index_health.py \
  src/tests/test_episode_store_batch.py \
  src/tests/test_context_compiler_batch.py -q
```
Kết quả (vòng sửa): **16 passed in 1.24s**.

Chứng minh:
- (a) Khi embedding rỗng (load fail): `embed_document`/`embed_query` trả `()`,
  `embed_documents` trả list `()`; recall vẫn chạy lexical; `debug_status()` có
  `loaded=False`, `load_error` khác rỗng, `load_failed_signaled=True`;
  `logger.error` phát ĐÚNG MỘT LẦN dù gọi embed nhiều lần (không spam).
- (b) Khi có fake index trả vector thật: `embed_documents` được gọi ĐÚNG 1 LẦN
  cho toàn bộ candidate, `embed_document` KHÔNG được gọi trong vòng lặp; scoring
  hợp lý (record/episode khớp query xếp trước).
- Fallback: fake index chỉ có `embed_query`/`embed_document` (không có
  `embed_documents` callable) → không batch, dense=0.0, không crash, vẫn lexical;
  `embedding_index=None` → giữ nhánh fallback cũ; `embed_documents` trả sai độ
  dài → bỏ dense, không crash.

## Sửa theo review (review.json — CHANGES_REQUESTED)

Vòng sửa này giải quyết cả 4 finding của reviewer. Lệnh focused ở mục 1 đã chạy
LẠI sau khi sửa (16 passed, trước là 11).

- **Finding 1 — Malformed batch fallback thu hẹp fail-soft** (safety 1 == logic 1):
  `ProfileContextCompiler._dense_similarities` đã kéo `len(vectors)` và vòng tính
  cosine VÀO TRONG biên `try` (context_compiler.py); provider trả `None`/giá trị
  không `len()` được → rơi về `[0.0]*len`. `UserEpisodeStore._cosine` (episode_store.py)
  bọc phần `float(x)` trong try/except (TypeError/ValueError) → một row hỏng (vd
  `None`) coi như dense=0.0 thay vì raise. Hành vi fail-soft/scoring không đổi:
  khi provider hợp lệ, kết quả y hệt trước.
  Bằng chứng test mới:
  `test_episode_store_batch.py::test_search_malformed_row_is_fail_soft`,
  `test_context_compiler_batch.py::test_compile_malformed_row_is_fail_soft`.
- **Finding 2 — Health test có thể rời biên offline** (safety 2 == logic 4):
  `_fresh_index()` trong `test_embedding_index_health.py` nay PATCH `_load_model`
  trên instance để raise tất định (`RuntimeError`), không truyền identifier rác
  tới `AutoTokenizer/AutoModel.from_pretrained`. Test không còn phụ thuộc việc
  thiếu `transformers` và không chạm model registry/network.
- **Finding 3 — Thiếu test empty-vector đi xuyên recall consumer** (safety 3 ==
  logic 3): thêm case `embed_documents` callable TRẢ vector rỗng (độ dài khớp)
  cho CẢ hai consumer, khẳng định dense=0.0 + recall lexical, không raise:
  `test_episode_store_batch.py::test_search_empty_vector_batch_falls_back_to_lexical`,
  `test_context_compiler_batch.py::test_compile_empty_vector_batch_falls_back_to_lexical`.
- **Finding 4 — Thiếu test cache-hit cross-turn** (logic 2): thêm
  `test_embedding_index_health.py::test_embed_documents_cache_hit_cross_turn`
  stub `_encode` (đếm text thực encode) + ép `_loaded=True`, gọi `embed_documents`
  hai lượt với một document trùng; khẳng định chỉ encode text CHƯA cache và
  `debug_status()["cache_size"]` tăng đúng theo số text duy nhất
  (`_encode_with_cache`/`_vector_cache` được chạm trực tiếp).

### 2. Regression cụm memory (danh sách file cụ thể)

Chạy lại trong vòng sửa, chia 2 batch do shell PowerShell echo từng ký tự làm
lệnh một dòng quá dài bị cắt (không phải test fail):

```
python -m pytest src/tests/test_living_user_memory.py \
  src/tests/test_memory_authority_v41.py \
  src/tests/test_memory_hygiene_v41.py -q
```
Kết quả: **35 passed in 1.98s**.

```
python -m pytest src/tests/test_living_user_memory_v39.py \
  src/tests/test_memory_gc_living_curator.py \
  src/tests/test_memory_open_registry.py \
  src/tests/test_turn_memory_pipeline.py \
  src/tests/test_companion_memory_authority_consolidation.py -q
```
Kết quả: **40 passed in 2.15s**.

Tổng 75 passed (0 failed). Không phá caller `EmbeddingIndex`, không đổi ngữ
nghĩa recall (các test `test_episode_buffer_builds_summary_and_dreams_preferences`,
`test_context_compiler_uses_project_scope_and_domain` vẫn xanh).

## Kết luận

Cả hai trạng thái (embedding rỗng do load-fail; embedding mô phỏng bằng fake
index) đều XANH. Không có test nào đỏ. Bất biến giữ nguyên: fail-soft, công thức
scoring/trọng số không đổi, cache cross-turn nằm trong `EmbeddingIndex` (batch đi
qua `embed_documents` → `_encode_with_cache`), đường ghi memory không bị đụng.
