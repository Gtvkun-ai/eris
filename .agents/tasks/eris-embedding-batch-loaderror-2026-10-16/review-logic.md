# Batch hoá recall qua `embed_documents` + health signal cho embedding load-fail

Thay đổi chuyển hai đường recall (`UserEpisodeStore.search`, `ProfileContextCompiler.compile`) từ gọi `embed_document` từng candidate trong vòng lặp sang gom tất cả rồi gọi `embed_documents` MỘT LẦN, đồng thời biến lỗi load model im lặng thành một health signal `logger.error` phát đúng một lần (cờ `_load_failed_signaled` + trường mới trong `debug_status()`). Mục tiêu là giảm số lần encode (N→1 mỗi lượt recall) mà không đổi công thức scoring, và làm lỗi embedding quan sát được thay vì bị nuốt. Đường batch đi qua `_embed_many → _encode_with_cache` nên cache cross-turn giữ nguyên; mọi nhánh provider hỏng (None, không callable, sai độ dài, row rỗng/None) đều rơi về `dense=0.0` + lexical thay vì raise. Phạm vi gói gọn trong 3 file source + 3 file test; đường GHI memory (`add`/`compact`/`scrub_evidence`/`save`) không bị chạm.

Watch for:
- `_ensure_loaded` có nhánh `else: logger.debug(...)` thực tế không bao giờ chạy vì `if self._load_error: return False` short-circuit trước khi vào lại `try` (confirmed, non-blocking).
- Health signal "đúng một lần" chống lại lặp tuần tự, nhưng hai first-call đồng thời về lý thuyết có thể log hai lần (possible, non-blocking).

**Verdict**: APPROVED

## High-level view

Bất biến fail-soft còn nguyên: khi load model lỗi, `_ensure_loaded` trả `False` và `_embed_many` trả list tuple rỗng, không raise ở cả ba API public, nên chat/recall vẫn chạy lexical. Lỗi không còn bị nuốt — `logger.error` phát một lần nhờ cờ `_load_failed_signaled`, và `debug_status()` thêm trường cùng tên phản ánh trạng thái; chữ ký public chỉ được mở rộng (thêm key), không bị phá.

Ngữ nghĩa scoring không đổi. Hai công thức trọng số (`episode_store`: `lexical*0.50 + phrase*0.20 + dense*0.20 + importance*0.08 + recency*0.02`; `context_compiler`: `trust*0.34 + domain*0.23 + lexical*0.18 + dense*0.13 + scope*0.08 + recency*0.04`) giữ nguyên từng hệ số. Thay đổi duy nhất là nguồn vector dense: từ `embed_document` từng-cái sang `embed_documents` gom-một-lần, với `_cosine_vec` sao lại đúng phép cosine cũ. Map vector→document đúng thứ tự vì `texts`/`docs` được dựng theo đúng trật tự `items`/`records` và batch trả về cùng trật tự.

Cache cross-turn an toàn vì batch vẫn chui qua `_encode_with_cache`/`_vector_cache` của `EmbeddingIndex`; document đã encode ở lượt trước là cache-hit, chỉ text chưa cache mới encode. Nhánh fallback phủ đủ: provider None, thiếu `embed_documents` callable, sai độ dài, hoặc trả row rỗng/None đều cho `dense=0.0` và recall lexical, không crash.

Có vài quan sát không chặn: một nhánh `logger.debug` chết trong `_ensure_loaded`, `_dense_similarity` giờ không còn caller production (giữ cho tương thích), và một cửa sổ đua rất hẹp cho health log dưới first-call đồng thời. Không mục nào phá bất biến được yêu cầu.

<details>
<summary>Issues (3)</summary>

1. **Nhánh debug chết trong `_ensure_loaded`** — `else: logger.debug(...)` không reachable do `if self._load_error: return False` chặn trước khi vào lại `try`; có thể bỏ để khỏi gây hiểu nhầm là có đường log lần hai. Non-blocking.
2. **`_dense_similarity` thành dead code production** — sau batch hoá, `compile` không còn gọi nó; `git grep` xác nhận không còn caller nào trong `src/` và không có test. Giữ cho tương thích là chấp nhận được nhưng nên gắn chú thích hoặc dọn sau. Non-blocking.
3. **Cửa sổ đua của health signal** — "log đúng một lần" dựa vào cờ không khoá; hai first-call `_ensure_loaded` đồng thời (ví dụ curator lane chạy nền) về lý thuyết có thể cùng qua `if not self._load_failed_signaled` và log hai lần. Non-blocking, chỉ ảnh hưởng độ ồn log, không ảnh hưởng recall.

</details>

<details>
<summary>Details</summary>

### Fail-soft khi load model lỗi giữ nguyên ở cả ba API

`_ensure_loaded` khi `_load_model()` ném lỗi vẫn set `_load_error`, không re-raise, trả `False`. `_embed_many` thấy `False` thì trả `[() for _ in texts]`, nên `embed_query`/`embed_document` trả `()` và `embed_documents` trả list `()` (confirmed — `embedding_index.py`, `_embed_many` + `_ensure_loaded`). Hai consumer coi vector rỗng là `dense=0.0`: trong `episode_store`, `_cosine(q_vec, ())` rơi vào `len(a) != len(b)` → `0.0`; trong `context_compiler`, `_cosine_vec` cũng bắt độ dài lệch → `0.0`. Không có đường nào đẩy exception lên caller, nên chat không sập (confirmed). Test `test_load_fail_returns_empty_vector_without_raising` khoá đúng ba giá trị trả về này.

### Health signal phát một lần + `debug_status` phản ánh trạng thái

Lỗi load giờ đi qua `logger.error` thay vì `logger.warning` và chỉ phát khi `not self._load_failed_signaled`, sau đó set cờ. Đảm bảo "một lần" thực ra đến từ hai lớp: cờ `_load_failed_signaled`, và quan trọng hơn là short-circuit `if self._load_error: return False` ở đầu `_ensure_loaded` — sau lần fail đầu, các lượt sau thoát trước khi vào lại khối `try`. Hệ quả: nhánh `else: logger.debug(...)` trong khối except là **dead code** trong luồng bình thường (confirmed — không có đường nào reset `_load_error` trong một instance; `clear_cache` chỉ xoá vector cache). Không gây hại, nhưng nên biết là nó không bao giờ chạy.

`debug_status()` thêm key `load_failed_signaled` và vẫn giữ `loaded`/`load_error`. Đây là mở rộng additive, không đổi hay bỏ key cũ, nên không phá caller đọc dict. Test `test_debug_status_reflects_load_failure` và `test_health_signal_logged_exactly_once` khoá `loaded=False`, `load_error` khác rỗng, cờ `True`, và đúng một record ERROR dù gọi embed ba lần.

Một cửa sổ đua hẹp: `EmbeddingIndex` không khoá, nên hai luồng cùng gọi `_ensure_loaded` lần đầu (trước khi `_load_error` được set) về lý thuyết có thể cùng qua cổng cờ và log hai lần (possible). Đây là mô hình đồng thời sẵn có của class (`_vector_cache` cũng truy cập không nguyên tử), hậu quả tối đa là log lặp một nhịp, không ảnh hưởng recall hay scoring — không chặn.

### Batch hoá không đổi ngữ nghĩa scoring

Điểm cốt lõi của review: công thức và trọng số không đổi, chỉ đổi nguồn vector dense.

Trong `episode_store.search`, dòng tính điểm giữ nguyên từng hệ số:

```python
score = lexical * 0.50 + phrase * 0.20 + dense * 0.20 + episode.importance * 0.08 + _recency(episode.ended_at) * 0.02
```

`dense` vẫn là `max(0.0, _cosine(q_vec, <vector>))`; chỉ khác chỗ `<vector>` lấy từ `d_vecs[idx]` (batch) thay vì `embed_document(text)` (per-item). `texts` được dựng một lần theo đúng trật tự `items`, `embed_documents(texts)` trả về cùng trật tự, và vòng lặp dùng `d_vecs[idx]` với cùng `idx` của `items` → không lệch vector↔document (confirmed). Hàm `_cosine` chỉ được bọc thêm `try/except (TypeError, ValueError)`; phần `dot/na/nb` và `return dot/(na*nb)` không đổi, nên giá trị cosine cho input hợp lệ y hệt trước.

Trong `context_compiler.compile`, `docs = [f"{record.path}: {record.value}" ...]` trùng đúng chuỗi document mà `_dense_similarity` cũ dựng, nên vector sinh ra giống hệt. `_cosine_vec` sao lại nguyên phép cosine cũ (`dot`, `na`, `nb`, `max(0.0, ...)`). `_score` đổi tham số từ `q_vec` sang `dense` đã tính sẵn, công thức `trust*0.34 + domain*0.23 + lexical*0.18 + dense*0.13 + scope*0.08 + recency*0.04` không đổi. Điều kiện bật dense cũng bảo toàn: cũ là `_dense_similarity(...) if q_vec else 0.0`, mới là `if q_vec:` ở tầng compile rồi `dense_scores[i] if q_vec else 0.0` — cùng phép kiểm truthiness trên `q_vec` (khi load-fail `embed_query` trả `()` falsy → dense=0.0 toàn bộ). `_score` là API private; đổi chữ ký không phá hợp đồng public.

### Đường batch giữ cache cross-turn

`embed_documents → _embed_many → _encode_with_cache` (confirmed — `embedding_index.py`). `_encode_with_cache` chỉ encode `uncached_indices` rồi nạp vào `_vector_cache` theo `_cache_key` (namespace model/role), nên document đã gặp ở lượt trước là cache-hit, chỉ text mới mới tốn encode. Batch không tạo đường mã hoá song song bỏ qua cache. `test_embed_documents_cache_hit_cross_turn` stub `_encode` để đếm text thực encode và ép `_loaded=True`: lượt 1 encode `["alpha","beta"]`, lượt 2 với `["alpha","gamma"]` chỉ encode thêm `"gamma"`, `cache_size` 2→3 — chứng minh cache-hit đi qua đúng `_encode_with_cache`/`_vector_cache` chứ không phải mock giả.

### Nhánh fallback batch phủ đủ các dạng provider hỏng

`episode_store` chỉ batch khi `q_vec is not None and callable(embed_documents)`; `embedding_index=None` → `getattr` trả `None` → không callable → `d_vecs=None` → lexical. `context_compiler._dense_similarities` chặn `self.embedding_index is None or not callable(embed_many)` → `[0.0]*len`. Cả hai giữ `len()` check TRONG biên `try`: provider trả generator/None không `len()` được thì rơi về 0.0 thay vì raise (confirmed — comment và code khớp). Row rỗng `()` hoặc `None` lẫn trong list đúng độ dài cũng bị `_cosine`/`_cosine_vec` bắt (`len` lệch hoặc `TypeError`) → 0.0. Các test `..._empty_vector_batch_falls_back_to_lexical`, `..._malformed_row_is_fail_soft`, `..._bad_length...`/`..._batch_length_mismatch...`, `..._none_index...`, `..._no_batch_index...` phủ từng dạng và khẳng định recall vẫn trả kết quả (lexical) không crash.

Lưu ý non-obvious: khi load-fail, `q_vec` ở `episode_store` là `()` (không phải None), nên code vẫn gọi `embed_documents(texts)` một lần — call này nội bộ short-circuit qua `_ensure_loaded=False` và trả toàn `()`, cho `dense=0.0`. Vẫn ít hơn N call như bản cũ.

### Phạm vi: không chạm đường ghi memory

Diff chỉ sửa `search`/`_cosine` trong `episode_store.py`; `add`, `compact`, `scrub_evidence`, `load`, `save`, `_trim`, `_find_same_session` không đổi (confirmed). `context_compiler` chỉ đổi đường đọc (`compile`/`_score`/`_dense_similarities`). `embedding_index` đổi `__init__`/`debug_status`/`_ensure_loaded`. Không file nào thuộc observe_turn/dream/digest bị đụng, không thêm dependency torch/transformers (diff không có manifest/requirements), khớp ràng buộc "chỉ sửa 3 file".

### `_dense_similarity` thành dead code

Sau batch hoá, `_dense_similarity` (single) không còn caller trong `compile`. `git grep "_dense_similarity"` trên `src/` của worktree chỉ ra hai chỗ: định nghĩa hàm và một tham chiếu trong docstring của `_dense_similarities` — không caller production nào khác, không test bao phủ (confirmed). Giữ cho tương thích không phá ngữ nghĩa, nhưng là bề mặt chết; nên gắn chú thích rõ hoặc dọn ở lần sau.

</details>

<details>
<summary>File map</summary>

- `src/memory/embedding_index.py` — thêm cờ `_load_failed_signaled`, đổi warning→error một lần trong `_ensure_loaded`, thêm key vào `debug_status()`.
- `src/memory/living_user/context_compiler.py` — `compile` gom document gọi `_dense_similarities` một lần; `_score` nhận `dense` thay `q_vec`; tách `_cosine_vec`; giữ `_dense_similarity` cho tương thích.
- `src/memory/living_user/episode_store.py` — `search` gom candidate gọi `embed_documents` một lần với guard độ dài; `_cosine` bọc fail-soft `TypeError/ValueError`.
- `src/tests/test_embedding_index_health.py` — (mới) health một lần, debug_status, cache-hit cross-turn.
- `src/tests/test_context_compiler_batch.py` — (mới) batch một lần + các nhánh fallback.
- `src/tests/test_episode_store_batch.py` — (mới) batch một lần + các nhánh fallback.

Diff đầy đủ: `git -C <worktree> diff main...HEAD`.

</details>
