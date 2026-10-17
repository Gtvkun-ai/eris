# Báo cáo điều tra READ-ONLY: Embedding + Living User Memory + gánh history

Ngày: 2026-10-16. Phạm vi: đọc source trong checkout `c:\Users\Gtvkun\Documents\GitHub\eris`
+ kiểm tra filesystem/venv của chính checkout này. **Không chạy live chat, không
sửa code.** Mọi kết luận ghi rõ: xác minh bằng source/filesystem, hay cần chạy
live mới biết.

---

## Tóm tắt trả lời (đọc trước)

1. **Embedding CÓ được wire vào live chat path, nhưng trong checkout này nó gần
   như chắc chắn degrade về None/empty khi chạy.** Đường dây có thật: runtime →
   `MemoryCognitionCore` → `get_shared_embedding_index()` → truyền vào cả
   `LivingUserMemoryService` lẫn `ProfileContextCompiler`/`UserEpisodeStore`.
   Nhưng `get_shared_embedding_index()` chỉ trả `None` khi `ERIS_EMBEDDING_ENABLED=0`;
   ngược lại nó trả **một instance `EmbeddingIndex` thật** (không None) — model
   load *lazy*. Vấn đề nằm ở lúc load model: trong checkout này **`torch` và
   `transformers` KHÔNG được cài trong `.venv`**, thư mục model local
   `src/paraphrase-multilingual-MiniLM-L12-v2/` **rỗng** (0 file, không có
   `config.json`), và cache dir `embedding_model/` **không tồn tại**. Khi đó
   `_ensure_loaded()` nuốt lỗi, set `_load_error`, và mọi `embed_query/
   embed_document` trả tuple rỗng `()`. Tức là: *đối tượng* embedding không None,
   nhưng *vector* luôn rỗng → về mặt chức năng tương đương không có embedding.

2. **Memory KHÔNG phải khung rỗng.** Living User Memory có admission thật,
   recall theo scope thật, context compiler thật, episode store thật, và trace
   thật. Khi không có embedding, nó degrade *có kiểm soát* về lexical (token
   overlap) + phrase match + trust/domain/recency scoring — vẫn chọn lọc được,
   không sập. Giới hạn: chất lượng recall tiếng Việt thiếu dấu/teencode sẽ kém
   hơn nhiều so với khi có dense vector, vì lexical dựa trên trùng token.

3. **Hệ thống KHÔNG dồn "cả trăm" hội thoại cho Root/Writer.** Client Eris cắt
   cứng: `chat_history` giữ tối đa **64 entry**, và chỉ gửi **32 lượt cuối**
   (`limit=32`) vào payload Root/Writer. Memory context (profile + episode đã nén
   qua context_compiler) *được* inject riêng vào cả Root và Writer. Việc "giữ
   TOÀN BỘ history" ở mục 9 là hành vi của **gateway whale2api** (flatten mảng
   messages client gửi thành một prompt text) — nó chuyển tiếp đúng cái client
   đã cắt còn ≤32, không tự dồn thêm. "Payload phình" ở mục 8 là do reconcile
   receipt 16 entry mỗi lượt, không phải do nhồi hàng trăm lượt.

**Một câu cho user:** embedding hiện *được nối đúng chỗ* nhưng *không thật sự
chạy* trong checkout này (thiếu torch/transformers + model rỗng) nên memory đang
chạy ở chế độ lexical fallback; còn chuyện "dồn cả trăm hội thoại" thì không
đúng ở phía client (cắt còn 32), chỉ có gateway giữ nguyên những gì client gửi.

---

## Bằng chứng theo câu hỏi

### Q1 — Embedding có thật sự chạy được không?

**Đường wire trên live chat path (xác minh bằng source):**

- `MemoryCognitionCore.__init__` tự lấy embedding index dùng chung và truyền vào
  cả semantic store lẫn living user:
  - `src/memory/memory_cognition.py:219-223` — nếu caller không truyền
    `embedding_index`, nó gọi `from .embedding_index import get_shared_embedding_index`
    rồi `get_shared_embedding_index()`, bọc trong `try/except` nuốt lỗi thành
    `None`.
  - `src/memory/memory_cognition.py:266-274` — truyền `embedding_index=_embedding_index`
    vào `LivingUserMemoryService(...)`.
- `LivingUserMemoryService` chuyển tiếp xuống context compiler:
  - `src/memory/living_user/service.py:89` lưu `self.embedding_index`.
  - `src/memory/living_user/service.py:105-111` tạo `ProfileContextCompiler(..., embedding_index=embedding_index, ...)`.
- Compiler dùng nó cho dense similarity và truyền vào episode search:
  - `src/memory/living_user/context_compiler.py:52` lưu `self.embedding_index`.
  - `context_compiler.py:124-128` gọi `self.episode_store.search(..., embedding_index=self.embedding_index)`.
  - `context_compiler.py:173-187` `_query_vector`/`_dense_similarity` dùng
    `embed_query`/`embed_document`, **bọc try/except trả 0.0/None khi lỗi**.
- Curator cluster cũng dùng embedding:
  - `src/memory/living_user/curator.py:152` lấy `embedding_index or getattr(living_user, "embedding_index", None)`.
  - `curator.py:380-388` `_embed_records` gọi `embed_documents`, try/except trả
    `[]` khi lỗi.

**Ai construct và backend là gì (xác minh bằng source):**

- `src/memory/embedding_index.py:422-443` `get_shared_embedding_index()`:
  - chỉ trả `None` nếu `ERIS_EMBEDDING_ENABLED ∈ {0,false,no,off}` (default `"1"`).
  - nếu không set `ERIS_EMBEDDING_MODEL` và có thư mục MiniLM local thì dùng nó
    làm `cache_dir`; ngược lại construct `EmbeddingIndex()` mặc định.
  - **Lưu ý quan trọng:** hàm này KHÔNG kiểm tra torch/transformers. Nó luôn trả
    một instance (trừ khi env tắt). Chỉ `build_embedding_index()` (dòng 403-419)
    mới import thử torch/transformers rồi trả None nếu thiếu — nhưng *đường live
    đi qua `get_shared_embedding_index`, không qua `build_embedding_index`* (xác
    nhận ở `memory_cognition.py:222`, `event_semantics.py:146`,
    `memory_query_compiler.py:80`). Nên instance embedding gần như luôn tồn tại;
    điểm thất bại thật sự dời sang lúc load model.
- Backend: `EmbeddingIndex._load_model()` (`embedding_index.py:_load_model`) dùng
  `transformers.AutoModel/AutoTokenizer`, device auto cuda/cpu. Model mặc định
  `paraphrase-multilingual-MiniLM-L12-v2` (local dir), family MiniLM → mean pooling.
- **Nuốt lỗi im lặng:** `embedding_index.py:_ensure_loaded()` — nếu
  `_load_model()` ném, nó set `self._load_error`, log `warning(... recall dùng
  lexical only)`, trả `False`. Từ đó `_embed_many` trả `[() for _ in texts]`,
  `embed_query/embed_document` trả `()`. **Không raise ra ngoài** → caller tưởng
  "có embedding" nhưng vector rỗng.

**Trạng thái thật trong checkout này (xác minh bằng filesystem + venv):**

- `.venv` của repo: `torch=False`, `transformers=False` (kiểm bằng
  `importlib.util.find_spec` qua `.venv\Scripts\python.exe`). `numpy=True`.
- `src/paraphrase-multilingual-MiniLM-L12-v2/` **tồn tại nhưng RỖNG**: 0 file,
  không có `config.json`. (Thư mục root `./paraphrase-multilingual-MiniLM-L12-v2`
  không tồn tại; `_LOCAL_MODEL_DIR = parents[1]/... = src/...` nên đúng là cái rỗng này.)
- `embedding_model/` (cache dir mặc định) **không tồn tại**.

→ Hệ quả suy ra từ source + filesystem: với checkout này, `_ensure_loaded()` sẽ
fail (import transformers lỗi, hoặc load từ dir rỗng lỗi). `embedding_index`
là **instance thật nhưng vô dụng** — mọi dense similarity = 0.0, mọi
`embed_query` = `()`. **Memory + curator chạy hoàn toàn bằng lexical fallback.**

> GIỚI HẠN: đây là checkout dev. `docs/knowledge/2026-10-14-...md` mục 4/6 nhắc
> dev và bản chạy từng tách (`Documents/GitHub/eris` vs `Documents/eris`). Nếu
> bản runtime thật chạy từ checkout khác có cài torch + model đầy đủ, embedding
> CÓ thể load được ở đó. Điều này **phải xác minh trên process/endpoint đang
> phục vụ** (xem process thật, `EmbeddingIndex.debug_status()` live) mới kết
> luận được cho production. Trong checkout đang điều tra, bằng chứng nghiêng hẳn
> về "không load được".

### Q2 — Memory có ổn không? (không phải khung rỗng)

**Có cấu trúc thật, không rỗng (xác minh bằng source):**

- Admission trước relevance: `context_compiler.py:71-90` — mỗi profile record
  phải qua `MemoryAdmissionPolicy.decide_profile_record`; record model suy đoán
  không vào prompt chỉ vì path khớp. Sensitive bị loại nếu không `include_sensitive`.
- Scoring đa yếu tố: `context_compiler.py:_score` — trust 0.34 + domain 0.23 +
  lexical 0.18 + dense 0.13 + scope 0.08 + recency 0.04. Khi embedding chết,
  `dense=0.0` → điểm dồn về trust/domain/lexical/recency (vẫn hoạt động).
- Episode recall theo scope: `episode_store.py:search` — lexical 0.50 + phrase
  0.20 + dense 0.20 + importance 0.08 + recency 0.02. Khi `q_vec is None`,
  `dense=0.0`, recall vẫn chạy bằng token overlap + phrase. Query rỗng →
  `recent()`. Giới hạn `max_episodes=4`, `max_items=14`
  (`ProfileContextCompilerConfig`).
- Admission/authority/forget/correct là đường thật, không phải stub:
  `service.py` có `apply_turn_operations` (authority guard trước khi ghi),
  `forget` (tombstone canonical + scrub trace), `correct`, `confirm`, `compile_context`
  ghi `memory_feed_trace.record_retrieval(...)` với admitted/rejected thật.
- Episode build từ hội thoại thật: `service.py:record_conversation_turn` +
  turn buffer (giữ tối đa 48 lượt, checkpoint episode khi ≥28 lượt), consolidate
  → `UserEpisodeStore.add` (merge theo session, cap 240 episode, compact gộp
  episode cũ trùng chủ đề).

**Degrade khi không có embedding (xác minh bằng source):**

- `context_compiler._query_vector` trả `None` khi `embedding_index is None` HOẶC
  `embed_query` không callable HOẶC ném lỗi. Instance rỗng của chúng ta có
  `embed_query` callable nhưng trả `()`; `_dense_similarity` nhận vector rỗng →
  `len(vector) != len(query_vector)` → trả 0.0. Không crash.
- `episode_store.search` tương tự: `q_vec` thành `()` (falsy-ish) hoặc lỗi →
  `dense=0.0`. Recall vẫn bằng lexical+phrase.

→ **Mức "ổn":** cơ chế memory *đúng và đầy đủ về mặt kiến trúc*, và *vẫn chạy*
khi embedding chết, nhưng chất lượng recall bị hạ xuống lexical. Với đặc thù
chat tiếng Việt thiếu dấu/teencode/trộn Anh-Việt (mục 1 tri thức dự án), lexical
overlap dễ trượt (ví dụ "memory" vs "ký ức" không trùng token) → episode/profile
liên quan có thể không được chọn. Đây là suy luận từ công thức scoring, **chưa
đo bằng trace recall live.**

### Q3 — Có dồn cả trăm hội thoại cho Root/Writer không?

**Client Eris CẮT history, không dồn (xác minh bằng source):**

- `src/runtime/prompt_context_builder.py:313-353` `_chat_history_for_llm(limit=...)`
  trả `valid_entries[-limit:]` — chỉ `limit` lượt cuối.
- `prompt_context_builder.py:407-408` `_append_chat_history` cap cứng:
  `if len(self.chat_history) > 64: self.chat_history = self.chat_history[-64:]`.
- Foreground user turn: `src/runtime/ai_orchestrated/orchestrator.py:740-743`
  gọi `history_reader(limit=32)` → truyền `recent_history=history` (≤32) vào
  `kernel.handle_event` (dòng 844-847).
- Autonomous/continuation: cũng `limit=32` (`orchestrator.py:1010`) hoặc `limit=8`.
- Root payload chỉ mang 32 lượt cuối ở dạng projection gọn:
  `src/runtime/conversation/agent.py:708-717` dùng `recent_history[-32:]` và chỉ
  giữ `role/content` + vài metadata delivery.

**Memory context ĐƯỢC inject (không phải chỉ history thô):**

- `src/runtime/conversation/context_assembler.py:264-283` `_typed_memory_context`
  gọi `kernel.build_public_context(user_text, ...)` → đưa vào runtime_context
  key `memory_context` (`context_assembler.py:197-199, 245`).
- `build_public_context` thật sự ghép profile đã nén:
  `src/memory/memory_kernel.py:555-584` gọi living_user context + đánh dấu
  `degraded`, trả `PublicMemoryContext(text, records, degraded)`.
- Root nhận `memory_context` trong `_PUBLIC_CONTEXT_KEYS`
  (`agent.py:796-800`).
- Writer nhận riêng: `src/runtime/conversation/runtime_writer.py:397-398`
  truyền `memory_context` vào `generate_public_reply`, và
  `src/runtime/ai_orchestrated/model_router.py:1785-1786` chèn vào system prompt
  dưới nhãn `"Relevant memory: ..."`. Đồng thời discourse_context được mô tả là
  "index map for the chat_history messages; no duplicated text"
  (`model_router.py:1790-1793`) — tức là có nỗ lực *không* nhân đôi text history.
- Messages cuối Writer: `model_router.py:1856-1860` = `[system] + chat_history(≤32) + [user]`.

**Gateway (mục 9) là layer khác — forward, không tự dồn thêm (xác minh bằng source):**

- `tools/whale2api/internal/prompt` + `internal/util/messages.go` `MessagesPrepare`
  flatten mảng messages thành một prompt text với marker role (`::user::`,
  `::asst::`, `<tool>` ...). Test `internal/util/messages_test.go` /
  `util_edge_test.go` xác nhận giữ nguyên system/user/assistant/tool, merge
  đúng, không tự thêm system instruction. → Gateway giữ "toàn bộ history" đúng
  như mục 9, nhưng "toàn bộ" ở đây = đúng ≤32 lượt client đã gửi, không phải
  gateway đi lục hàng trăm lượt.

**"Phình payload" là vấn đề khác (đối chiếu mục 8 tri thức dự án):**

- Mục 8 ghi: receipt pending→cancelled làm history projection đổi → reconcile
  16 entry → phình payload; `public_turns=16` KHÔNG phải 16 phát ngôn mới. Đây
  là phình do churn metadata/reconcile mỗi lượt, không phải do nhồi cả trăm hội
  thoại. Khớp với cap 64/32 ở trên.

> GIỚI HẠN: tôi xác minh *cơ chế* cắt 32/64 và *điểm inject* memory_context bằng
> source. Tôi **chưa** đọc một trace payload live để đo số token/entry thật gửi
> lên gateway trong một phiên dài. Không tìm thấy file `.agents/tasks/*/*.jsonl`
> dạng raw wire trong phạm vi đọc nhanh; mục 8/10 của tri thức dự án đã dẫn các
> báo cáo audit wire (`2026-10-15-run-agent-loop-tts-audit.md`,
> `2026-10-15-1647-agent-loop-audit.md`) nên con số entry thực tế có thể tra tiếp ở đó.

---

## Kết luận và khuyến nghị (không triển khai)

**Kết luận:**

1. Embedding được nối đúng vào live chat path (Root đọc memory_context,
   Writer đọc "Relevant memory", curator + episode recall nhận embedding_index).
   Nhưng trong checkout dev này nó **không load được** (thiếu torch/transformers,
   model dir rỗng, cache dir thiếu) → degrade im lặng về lexical. Cần kiểm
   process runtime thật mới biết production có khác không.
2. Memory **không rỗng**: admission + recall theo scope + context compiler +
   episode/profile/action store đều thật và vẫn chạy khi embedding chết, chỉ
   giảm chất lượng về lexical. "Ổn ở mức khung + lexical", chưa phải "ổn ở mức
   semantic recall" trong checkout này.
3. **Không** dồn cả trăm hội thoại ở client: cắt 64 (lưu) / 32 (gửi). Memory
   context được nén và inject có chọn lọc. Gateway chỉ forward cái client gửi.

**Khuyến nghị kiểm chứng (ưu tiên trước khi sửa):**

- Chạy `EmbeddingIndex(...).debug_status()` hoặc
  `get_shared_embedding_index().debug_status()` trên **đúng process runtime đang
  phục vụ** để xem `loaded`/`load_error`/`device`/`cache_size`. Đây là bằng
  chứng live duy nhất kết luận được embedding sống hay chết.
- Grep run log cho chuỗi `EmbeddingIndex model load failed` /
  `recall dùng lexical only` — nếu xuất hiện, xác nhận fallback lexical live.
- Đọc memory_feed_trace (`memory_feed_trace.jsonl` trong memory base_dir) để xem
  recall thật admit/reject gì mỗi lượt — kiểm memory "ổn" bằng dữ liệu thật.

**Khuyến nghị sửa (nếu muốn embedding thật sự chạy ở đây):**

- Cài `torch` + `transformers` vào `.venv`, và nạp đủ file model vào
  `src/paraphrase-multilingual-MiniLM-L12-v2/` (hoặc `embedding_model/`), hoặc
  set `ERIS_EMBEDDING_MODEL` tới model tải được. Lưu ý `_fullbuild.py`/
  `repo_detector.py` (mục nêu trong brief) deploy `embedding_model/` cho bản
  đóng gói — cần xác nhận bản runtime thật có bước deploy đó.
- Cân nhắc đổi `_ensure_loaded()` để *không* nuốt lỗi hoàn toàn im lặng ở
  production (ví dụ phát một health signal/metric một lần), tránh tình trạng
  "tưởng có embedding mà toàn vector rỗng" khó phát hiện.
- Nếu giữ lexical fallback làm mặc định chấp nhận được, nên bổ sung chuẩn hoá
  tiếng Việt mạnh hơn cho `normalize_text` (bỏ dấu, map teencode) để lexical
  recall bớt trượt — nhưng cần đo trước khi làm.

---

## Phụ lục: giới hạn phương pháp

- Đã xác minh: wiring embedding/memory, công thức scoring, cap history 32/64,
  điểm inject memory_context, hành vi flatten của gateway — tất cả bằng **đọc
  source**; trạng thái torch/model/cache bằng **kiểm filesystem + venv của
  checkout**.
- Chưa xác minh (cần live): embedding có load trên process runtime thật không;
  recall live chọn đúng episode/profile không; số entry/token payload thật trong
  phiên dài; checkout dev này có phải chính bản đang chạy không.
- Theo AGENTS.md / tri thức dự án: không nâng "đọc source" thành "quan sát live".
  Báo cáo này dừng ở tầng source + filesystem, và nêu rõ chỗ phải chạy live.
