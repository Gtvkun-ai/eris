# Báo cáo READ-ONLY: Luồng memory/embedding từ câu user vào Root + Writer

Ngày: 2026-10-16. Phạm vi: đọc source trong checkout
`c:\Users\Gtvkun\Documents\GitHub\eris`. **Không chạy live, không đo ms thật,
không sửa code.** Mọi kết luận ghi rõ: xác minh bằng đọc source, hay cần chạy
live mới biết. Báo cáo này KHÔNG lặp lại điều tra wiring 32/64 và trạng thái
torch/model — xem `embedding-memory-report.md` cho phần đó. Tập trung vào
**LUỒNG + SYNC/ASYNC + BATCH/từng-cái + ước lượng latency**.

---

## Tóm tắt trả lời (đọc trước)

**A. Recall là SYNC, nằm thẳng trên critical path của Root.** Bước
`build_public_context` (recall cho prompt) được gọi **đồng bộ** bên trong
`ContextAssembler.assemble(...)`, và `assemble(...)` được gọi **trước**
`kernel.handle_event(...)` trong cùng một hàm orchestrator không-async. Không
có thread, không có `await`, không có timeout/budget bao quanh recall. Nghĩa là:
nếu embedding load được và chạy, thời gian embed **cộng thẳng** vào độ trễ tới
lúc Root ra move. Đây là đường **ĐỌC** memory. Đường **GHI** memory
(`observe_turn`, digest, dream) thì ngược lại — chạy trên **daemon thread qua
queue**, không chặn chat.

**B. Embed theo TỪNG CÁI trong vòng lặp, KHÔNG batch — nhưng có cache vector
theo text.** Trong đường recall, `embed_query` gọi **một lần** cho query, rồi
`embed_document` gọi **lặp từng document một** trong vòng for (một lần cho mỗi
profile record được chấm điểm, một lần cho mỗi episode candidate). Hàm batch
`embed_documents` **tồn tại nhưng KHÔNG được gọi** trên đường recall này. Mỗi
`embed_document` cache-miss = một forward pass GPU batch_size=1 (overhead launch
kernel cộng dồn). Có `_vector_cache` keyed theo `(model|family|pooling|maxlen|
role|instruction)+text`, nên document lặp lại giữa các lượt được tái dùng rẻ;
nhưng document **mới/chưa gặp** trong lượt vẫn phải encode riêng từng cái.

**C. Khối lượng embed mỗi lượt bị chặn bởi số candidate, không phải budget
token.** `max_items=14` (profile), `max_episodes=4` (episode), nhưng số lần
`embed_document` thực tế = **số profile record qua admission** (chấm điểm
TRƯỚC khi cắt top-14) + **số episode trong scope** (chấm điểm TRƯỚC khi cắt
top-4). Token budget 900/6000 chỉ cắt *output* đưa vào prompt, **không** giảm
số document phải embed. Nếu user model còn nhỏ, đây là vài–vài chục embed/lượt.

**Một câu cho user:** phần ĐỌC ký ức (recall) chạy đồng bộ ngay trên đường tới
lúc Root quyết định, và nó embed từng đoạn một chứ không gộp batch, nên NẾU
embedding thật sự load (ở checkout này thì không — xem báo cáo trước) thì mỗi
lượt Root sẽ bị cộng thêm thời gian = số đoạn phải embed × chi phí một forward
pass; phần GHI ký ức thì đã tách ra chạy nền nên không làm chậm câu trả lời.

---

## Sơ đồ luồng từng bước (1 → 6) kèm file:dòng

```
[1] USER TURN vào orchestrator
    orchestrator.py: chụp history (limit=32) TRƯỚC khi append câu hiện tại
          │   history = tuple(host._chat_history_for_llm(limit=32))   # :738-743
          │   append_history("user", user_text)                       # :745-747 (sau khi chụp)
          │   event = ConversationEvent(kind="user_turn", text=user_text)  # :749-754
          ▼
[2] CONTEXT ASSEMBLER (ĐỒNG BỘ, trước Root)
    orchestrator.py:820-828  runtime_context = ensure_conversation_context_assembler(host)
                                                 .assemble(user_text=..., recent_history=history, event=event)
    context_assembler.py:58  def assemble(self, *, ...)   ← hàm THƯỜNG, không async
    context_assembler.py:77  memory, memory_records, memory_degraded = self._typed_memory_context(user_text)
    context_assembler.py:197 context["memory_context"] = compiled.memory  ← đặt vào runtime_context key "memory_context"
          ▼
[3] MEMORY KERNEL RECALL (vẫn trong cùng call stack đồng bộ của [2])
    context_assembler.py:264-283  _typed_memory_context():
          packet = kernel.build_public_context(user_text, session_id=..., user_context_token_budget=6000, max_lines=64)  # :276-277
          (user_text CHÍNH LÀ query recall — truyền thẳng vào build_public_context)
    memory_kernel.py:555-584  build_public_context():
          packet = self.core.recall(query)                    # :564  (semantic core)
          profile = living_user.compile_context(query, session_id=..., token_budget=...)  # :572-575
          return PublicMemoryContext(text=combined, records=records, degraded=...)         # :584
    service.py:434-452  compile_context() → self.compiler.compile(query, scope=..., token_budget=...)  (ĐỒNG BỘ)
    context_compiler.py:57  compile():
          q_vec = self._query_vector(query)                   # :85   → embed_query MỘT LẦN
          for record in records:                              # :86-90 vòng lặp profile
              score,_ = self._score(..., q_vec=q_vec)          #        → _dense_similarity → embed_document TỪNG CÁI (:184)
          episodes = self.episode_store.search(query, embedding_index=self.embedding_index)  # :124-128
    episode_store.py:57-98  search():
          q_vec = embedding_index.embed_query(query)          # :75    MỘT LẦN
          for episode in items:                               # :80
              d_vec = embedding_index.embed_document(text)    # :88    TỪNG CÁI trong vòng lặp
              dense = _cosine(q_vec, d_vec)                   # :89
          ▼
[4] memory_context → ROOT
    agent.py:796-800  memory_context nằm trong allow-list _bounded_context (serialize vào Root payload)
    agent.py:700-719  recent_public_history = recent_history[-32:]  (history ĐI RIÊNG, projection gọn role/content)
          → Root nhận memory_context như một field context RIÊNG, KHÁC với recent_public_history.
          ▼
[5] memory_context → WRITER
    runtime_writer.py:397-398  "memory_context": str(runtime_context.get("memory_context",""))  → generate_public_reply
    model_router.py:1785-1786  context_parts.append(f"Relevant memory: {memory_context}")  (chèn vào SYSTEM prompt)
    model_router.py:1790-1793  discourse_context = "index map for chat_history; no duplicated text"
    model_router.py:1856-1860  messages = [system(+Relevant memory)] + chat_history(≤32) + [user]
          → Writer nhận memory_context qua ĐƯỜNG RIÊNG (trong system), không trộn vào history.
          ▼
[6] ROOT QUYẾT ĐỊNH
    orchestrator.py:844-847  result = kernel.handle_event(event, recent_history=history, runtime_context=runtime_context)
          (handle_event là hàm ĐỒNG BỘ — kernel.py:125; chạy SAU khi [2][3] đã hoàn tất)
```

Ghi chú: Root sở hữu quyết định move; Writer chỉ diễn đạt. Cả hai đều nhận
*cùng* một chuỗi `memory_context` đã nén, nhưng qua hai điểm inject khác nhau
(Root: field context; Writer: dòng "Relevant memory" trong system). Khớp với
nguyên tắc "Root quyết, Writer diễn đạt" trong tri thức dự án.

---

## Ẩn số A — SYNC hay ASYNC (trọng tâm)

**Kết luận: đường ĐỌC (recall cho prompt) là SYNC, nằm thẳng trên critical path
của Root. Đường GHI là ASYNC (background thread).** Xác minh bằng source:

### Bằng chứng recall là SYNC

1. `orchestrator.py:820-828` — `runtime_context = ...assemble(...)` được gọi
   **trước** `kernel.handle_event(...)` ở `orchestrator.py:844-847`, trong cùng
   một hàm. Không có `await`, không tạo task, không spawn thread giữa hai lời gọi.
2. `context_assembler.py:58` — `def assemble(self, *, ...)` là **hàm đồng bộ**
   (không `async def`). Tại `:77` nó gọi `self._typed_memory_context(user_text)`
   **ngay trong thân hàm**, lấy kết quả rồi mới dựng `compiled`/`context`.
3. `context_assembler.py:264-283` — `_typed_memory_context` gọi
   `kernel.build_public_context(...)` đồng bộ, `return` trực tiếp packet.
4. `memory_kernel.py:555-584` — `build_public_context` là hàm đồng bộ; gọi
   `self.core.recall(query)` (`:564`) và `living_user.compile_context(...)`
   (`:572`) tuần tự rồi mới return.
5. `service.py:434-452` — `compile_context` đồng bộ → `self.compiler.compile(...)`.
6. `context_compiler.py` `compile()` và `episode_store.py` `search()` đều là hàm
   đồng bộ chạy vòng lặp embed tại chỗ (xem Ẩn số B).
7. `kernel.py:125` — `handle_event` cũng là hàm **đồng bộ**; grep xác nhận
   không có `async def`/`await` trong `kernel.py`.

→ Toàn bộ chuỗi `assemble → _typed_memory_context → build_public_context →
compile_context → compile/search → embed_query/embed_document` nằm trong **một
call stack đồng bộ duy nhất**, hoàn tất **trước** khi `handle_event` chạy Root.
Thời gian recall (kể cả embed) **cộng thẳng** vào thời gian tới lúc Root ra move.

### Bằng chứng đường GHI là ASYNC (tương phản)

- `background_living_user_observer.py:3-9` (docstring) — lane nền chuyên dụng;
  user turn được **queue** và xử lý bởi `LivingUserMemoryService.observe_turn`
  trên **daemon worker**, để "profile extraction, curator inference, JSON
  persistence, và trace writes **không bao giờ chặn** chat writer".
- `background_living_user_observer.py:89-100` — `queue.Queue(maxsize=64)` +
  `threading.Thread(..., name="ERIS-LivingUserCurator", daemon=True)`.
- `background_living_user_observer.py:171-175` — worker `_process` mới gọi
  `self.living_user.observe_turn(...)`.
- `state_commit_service.py:98-102` và `turn_memory_pipeline.py:248` — write được
  đẩy qua `enqueue_user_turn` (không gọi `observe_turn` đồng bộ trên chat path).
- `background_memory_digest_kernel.py:270` — digest cũng có `enqueue_user_turn`
  riêng (nền).

→ Phân biệt rõ: **ĐỌC = sync, chặn Root**; **GHI = async, không chặn**. Điều này
phủ nhận giả định "mọi thứ memory đều nền". Chỉ phần ghi là nền; phần đọc thì
không.

### Câu hỏi phụ — có deadline/budget bao recall không?

**Không tìm thấy timeout/deadline bao quanh recall trong đường đọc.** Grep
`timeout|deadline|budget|asyncio|run_in_executor` trong `service.py` chỉ ra
`context_token_budget` (cắt *token output*, không phải thời gian) và một
`RLock` cho turn buffer; không có cơ chế huỷ recall theo thời gian. `kernel.py`
không có `async`/`await`. → Nếu recall chậm, **Root bị chặn chờ**, không có
đường "bỏ qua recall để Root chạy trước". Recall chỉ "degrade" theo *chất lượng*
(embedding chết → lexical, `context_compiler.py:173-187`, `_query_vector` trả
`None`), **không** degrade theo *thời gian*. (Giới hạn: tôi đọc trong các file
trên; nếu có wrapper timeout ở tầng gọi `assemble` cao hơn mà tôi chưa thấy thì
cần kiểm tiếp — nhưng trong `orchestrator.py` quanh :820-847 không có.)

---

## Ẩn số B — BATCH hay TỪNG CÁI, có cache không (trọng tâm)

**Kết luận: TỪNG CÁI trong vòng lặp (không batch), NHƯNG có cache vector theo
text.** Xác minh bằng source:

### Query: một lần

- `episode_store.py:73-75` — `q_vec = embedding_index.embed_query(query)` gọi
  **một lần** cho cả search episode.
- `context_compiler.py:85` — `q_vec = self._query_vector(query)` →
  `context_compiler.py:173-182` gọi `embed_query` **một lần** cho profile.
  (Hai đường profile và episode **mỗi đường gọi embed_query riêng** → query bị
  embed **2 lần**/lượt, nhưng lần thứ 2 là cache-hit nếu text query trùng.)

### Document: lặp từng cái, KHÔNG batch

- **Profile:** `context_compiler.py:86-90` vòng `for record in records:` gọi
  `self._score(...)` → `context_compiler.py:170` `_dense_similarity(q_vec,
  f"{record.path}: {record.value}")` → `context_compiler.py:184`
  `embed = embed_document`; `vector = embed(document)` — **một call
  embed_document cho MỖI record** trong vòng lặp.
- **Episode:** `episode_store.py:80-92` vòng `for episode in items:` gọi
  `embedding_index.embed_document(text)` (`:88`) — **một call cho MỖI episode**.
- Hàm batch `embed_documents` (`embedding_index.py:197-198`) **tồn tại** và được
  dùng ở nơi khác (curator `_embed_records`, xem báo cáo trước) **nhưng KHÔNG
  được gọi trong đường recall** profile/episode này.

→ Hệ quả: nếu embedding load được, mỗi document chưa cache sẽ là **một forward
pass riêng với batch_size=1**. `_encode` (`embedding_index.py:289-315`) có vòng
batch nội bộ (`ERIS_EMBEDDING_BATCH_SIZE=16`), nhưng vì caller truyền **một
text mỗi lần**, batch luôn = 1 → không tận dụng được batching GPU, overhead
launch kernel + tokenize cộng dồn theo số document.

### Có cache vector — theo text, cross-turn

- `embedding_index.py:347-363` `_encode_with_cache`: tính `keys` = `_cache_key`
  cho từng text, chỉ encode `uncached_indices`, lưu vào `self._vector_cache`.
- `embedding_index.py:365-370` `_cache_key`: namespace =
  `model_name|model_family|pooling|max_seq_length|role|query_instruction` + `"\n"`
  + text, rồi md5 (`_short_hash`). → Cache key **phụ thuộc cả nội dung text lẫn
  cấu hình model/role**. Đổi model/pooling/instruction ⇒ cache cũ không bị tái
  dùng nhầm (an toàn), nhưng cũng nghĩa là mọi document phải encode lại khi đổi
  cấu hình.
- `_vector_cache` là `dict` trên **instance dùng chung toàn tiến trình**
  (`get_shared_embedding_index`, instance `_SHARED_INDEX`). Vậy **document lặp
  lại giữa các lượt** (profile record ổn định, episode cũ) chỉ encode **lần đầu**;
  các lượt sau là cache-hit rẻ. **Document mới** mỗi lượt (ví dụ episode vừa
  thêm) vẫn tốn một encode.
- Lưu ý: `embed_document` → `_embed_many([text]) → _encode_with_cache([text])`
  (`embedding_index.py:190-192, 275-287`). Nên dù gọi từng cái, **vẫn qua cache**.
  Chi phí thật = **số document DISTINCT chưa-cache** mỗi lượt, không phải tổng số
  lần gọi.

### Bao nhiêu document mỗi lượt?

- Số `embed_document` **gọi** = (số profile record qua admission, chấm điểm
  trước cắt top-14) + (số episode trong scope, chấm điểm trước cắt top-4). Cận
  `max_items=14`/`max_episodes=4` áp **SAU** khi đã chấm điểm → **không** giảm số
  embed. `context_token_budget` (900 living-user / 6000 public) cắt *output*, cũng
  không giảm số embed.
- Số **encode thật** (cache-miss) = số document distinct **mới** trong lượt đó.
  Với user model nhỏ/mới, gần như tất cả là miss ở lượt đầu; về sau chủ yếu là
  episode mới + query mới.

---

## Ước lượng latency mỗi lượt (từ đặc tính code, CHƯA đo live)

Đây là **ước lượng suy từ cấu trúc code**, không phải số đo. GPU 4GB (ví dụ
user nêu) chạy MiniLM-L12 (paraphrase-multilingual, ~118M param) trên CPU/GPU:

- **Chi phí một forward pass batch_size=1** cho một câu ngắn trên GPU rời: cỡ
  **vài–chục ms** (MiniLM nhỏ), nhưng vì gọi **từng cái** nên cộng thêm overhead
  tokenize + launch kernel + `.cpu()` copy mỗi call. Trên CPU (nếu `_cuda_available`
  = False) có thể **hàng chục–trăm ms mỗi câu**.
- **Lần đầu phiên (loại trừ theo yêu cầu):** load model
  (`embedding_index.py:_load_model`, log "Model loaded in %.1fs") — một lần, có
  thể vài giây; **không tính** theo đề bài.
- **Mỗi lượt ấm (cache phần lớn hit):** query 1 encode (hoặc 0 nếu trùng) +
  vài document mới. Nếu N_miss ≈ 1–6 document mới → **cỡ chục–vài trăm ms**
  cộng vào critical path trước Root (ước lượng; nghiêng về GPU rẻ hơn, CPU đắt hơn).
- **Lượt "lạnh cache" (user model lớn, nhiều record/episode distinct chưa gặp):**
  N_miss có thể vài chục → vì **không batch**, chi phí ≈ N_miss × (một forward
  pass batch_size=1). Đây là kịch bản tệ nhất và là lý do "không batch" đáng lo:
  gộp batch sẽ rẻ hơn nhiều cho cùng N_miss.

**Quan trọng cho checkout này:** theo `embedding-memory-report.md`, checkout dev
này **thiếu torch/transformers + model dir rỗng** → `_ensure_loaded()` fail,
`embed_query/embed_document` trả `()` **ngay lập tức** (không có forward pass).
Vậy **ở checkout này latency embedding thực tế ≈ 0** (chỉ còn lexical, rẻ).
Phần ước lượng chục–trăm ms ở trên chỉ áp dụng **nếu/khi** embedding thật sự
load được trên process runtime thật. **Cần chạy live + `debug_status()` mới
biết môi trường phục vụ có load embedding hay không.**

---

## Kết luận gọn

1. **Luồng:** user_text → (sync) `assemble` → `_typed_memory_context` →
   `build_public_context` → `compile_context` → `compile`/`episode_store.search`
   → embed → `memory_context` → inject vào **Root (field context)** và
   **Writer (dòng "Relevant memory" trong system)** → rồi `handle_event` chạy Root.
2. **Recall = SYNC trên critical path của Root** (orchestrator.py:820-828 trước
   :844-847; cả chuỗi không async, không timeout). **Write = async** (daemon
   thread qua queue, `background_living_user_observer.py`).
3. **Embed = từng cái trong vòng lặp, không batch** (`context_compiler.py:184`,
   `episode_store.py:88`); **có cache vector theo text** cross-turn
   (`embedding_index.py:347-370`). Số embed/lượt = số profile record qua
   admission + số episode trong scope; cận 14/4 và token budget 900/6000
   **không** giảm số embed, chỉ cắt output.
4. **Ước lượng latency:** nếu embedding load, mỗi lượt ấm cộng ~chục–vài trăm ms
   (tỉ lệ số document mới chưa cache); lượt lạnh-cache tệ hơn vì không batch. Ở
   **checkout dev này embedding không load** nên chi phí ≈ 0 (lexical). **Chưa
   đo ms thật.**

---

## Khuyến nghị (KHÔNG triển khai — chỉ nêu)

- **Batch hoá recall:** thu thập tất cả document candidate (profile + episode)
  rồi gọi `embed_documents` **một lần** thay vì `embed_document` trong vòng lặp
  (`context_compiler.py:86-90`, `episode_store.py:80-92`). Cùng N_miss, một
  forward pass batch sẽ rẻ hơn nhiều N pass batch_size=1. Đây là cải thiện lớn
  nhất cho latency NẾU embedding bật.
- **Đưa recall ra khỏi critical path (tuỳ chọn):** vì recall là sync và chặn
  Root, cân nhắc (a) thêm timeout/budget để degrade sang lexical khi embed chậm,
  hoặc (b) pre-warm vector ở background (`ensure_vectors`,
  `embedding_index.py:144-163`) sau mỗi lượt để lượt sau chủ yếu cache-hit.
- **Đo trước khi sửa:** chạy live + `get_shared_embedding_index().debug_status()`
  (`loaded`, `load_error`, `device`, `cache_size`) và đo riêng thời gian
  `build_public_context` vs thời gian Root, theo đúng nguyên tắc tri thức dự án
  "đo từng stage, không suy từ thời gian tổng". Không tối ưu batch nếu embedding
  không hề load ở môi trường phục vụ.

---

## Giới hạn phương pháp

- Xác minh bằng **đọc source**: tính sync của `assemble`/`handle_event`/
  `build_public_context`/`compile_context`; vị trí gọi (assemble trước
  handle_event); vòng lặp embed từng-cái; cơ chế cache; tính async của write
  path; vắng mặt timeout/deadline quanh recall.
- **Chưa xác minh (cần live):** ms thật mỗi stage; embedding có load trên
  process runtime thật không (checkout dev này không load — xem báo cáo trước);
  số document distinct thực tế mỗi lượt trên user model thật; có wrapper timeout
  nào ở tầng cao hơn `orchestrator.py` quanh :820-847 mà tôi chưa đọc không.
- Theo AGENTS.md/tri thức dự án: không nâng "đọc source" thành "quan sát live".
  Báo cáo dừng ở tầng source và nêu rõ chỗ phải chạy live.
