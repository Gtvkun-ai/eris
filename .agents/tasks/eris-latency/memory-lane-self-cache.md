# Memory lane nền + cache Self — điểm sửa cho hai quick win latency

Điều tra READ-ONLY ngày hôm nay. Chỉ đọc source trong checkout
`c:\Users\Gtvkun\Documents\GitHub\eris` (nhánh **`main`**, không phải `dev` như brief
giả định — cần lưu ý khi áp patch). Không sửa/build/chạy app. Mọi khẳng định kèm
`file:dòng`; chỗ không chứng minh được bằng đọc tĩnh thì ghi rõ "[CHƯA CHẮC]".

---

## Tóm tắt (đọc trước)

**Câu 1 — Memory build chẹn ở đâu:** `build_public_context` chạy **đồng bộ, inline,
không có timeout nào** trong đường user→Root. Call site:
`src/runtime/ai_orchestrated/orchestrator.py:831` gọi
`ConversationContextAssembler.assemble(...)`, và trong `assemble`,
`src/runtime/conversation/context_assembler.py:80` gọi `_typed_memory_context` →
`MemoryKernel.build_public_context` (`src/memory/memory_kernel.py:555`). Đồng hồ
`memory_context_ms` (`context_assembler.py:311-313`) bọc đúng dòng 80 đó. Đây chính
là 42s của lượt outlier.

**Câu 2 — Tách lane nền có khả thi + chèn sạch ở đâu:** KHẢ THI và có điểm chèn sạch.
Root **đã có sẵn** một tool recall-theo-yêu-cầu riêng (`memory_recall_tools_for_host`,
`orchestrator.py:849`, định nghĩa ở `src/runtime/conversation/context.py:64`) trả
`{status, text, degraded, source_count}` và tôn trọng provenance. Nghĩa là Root
không bắt buộc phải nhận memory qua eager-build; có đường để Root chủ động gọi.
`build_public_context` cũng đã trả cờ `degraded` (`memory_kernel.py:587`) và được
dùng để đánh dấu `evidence_degraded` (`context_assembler.py:257`). Điểm chèn lane nền
sạch nhất = tại `context_assembler.py:79-81`: dựng memory ở worker nền + dùng snapshot
gần nhất cho lượt hiện tại, giữ nguyên `records`/`degraded` khi commit snapshot nên
**không phá receipt/provenance/admission**.

**Câu 3 — Timeout cứng:** LÀM ĐƯỢC, và là quick win ít rủi ro nhất. Chèn `wait_for`
(hoặc thread + join có deadline) quanh đúng dòng `context_assembler.py:80`, quá hạn
~1–2s thì trả snapshot gần nhất hoặc chuỗi rỗng + `degraded=True`. **Không** đụng
regression "curator required/concurrency=1" vì regression đó bảo vệ *maintenance nền*
(`memory_maintenance.py`), KHÔNG phải read-path `build_public_context`. Timeout ở đây
chỉ bỏ qua phần đọc chậm của một lượt, không biến curator thành optional rồi bỏ việc.

**Câu 4 — Self không cache:** Self dựng lại mỗi lượt vì CharacterPortrait được build
mới mỗi lượt từ state/affect tươi (`context_assembler.py:175-217`), và phần nặng nhất
nhồi vào payload chính là memory context (`self.memory_state` 72k, `memory.living_user`
52k theo latency-breakdown) — tức cùng chuỗi do `build_public_context` sinh, **không
có lớp cache per-phiên** cho nó. Fingerprint đổi mỗi lượt vì portrait trộn affect động
+ memory text động. Phần TĨNH có thể cache: `living_user.profile` (34k) ít đổi giữa các
lượt (profile store có cap + decay chậm). Cache phần tĩnh khả thi nhưng rủi ro vừa vì
phải giữ đúng projection; ít hấp dẫn hơn #1/#3.

**Câu 5 — Token tăng tiến theo time:** **KHÔNG tăng vô hạn.** Profile store có cap
cứng `max_records=320`, `_trim()` giữ top 320 (`src/memory/living_user/store.py:36,
732-745`), decay theo ngày + `forget_after_days=120` + `drop_below_confidence=0.08`
(`store.py:43-44, 394-410`). Turn buffer cap 48 (`service.py:169`). Payload nặng là do
**số record chạm trần (tới 320) và budget render rộng**, KHÔNG phải rò rỉ theo thời
gian. Lo lắng "dồn token tăng tiến theo time" của user chỉ đúng tới một trần, không
phải tăng mãi.

**Ưu tiên quick win ít rủi ro nhất:** **#3 timeout cứng tại `context_assembler.py:80`**
(rẻ, một điểm, fail-soft, không đụng vùng nhạy cảm), rồi mở rộng thành **#2 lane nền +
snapshot** nếu muốn bỏ hẳn cú 42s mà vẫn giữ memory tươi. Self-cache (#4) để sau.

---

## Bằng chứng theo câu hỏi

### Câu 1 — Memory build nằm đâu trên critical path

1. **Call site đồng bộ trong user turn:**
   `src/runtime/ai_orchestrated/orchestrator.py:831-839` —
   `runtime_context = ensure_conversation_context_assembler(host).assemble(user_text=..., channel="chat", event=event, ...)`.
   Không `await`/thread; kết quả dùng ngay để dựng prompt cho Root ở các dòng sau
   (`orchestrator.py:841-861`). → `assemble` nằm thẳng trên đường user→Root.

2. **Trong `assemble`, memory build là bước chặn:**
   `src/runtime/conversation/context_assembler.py:79-81`:
   ```
   memory_started = time.perf_counter()
   memory, memory_records, memory_degraded = self._typed_memory_context(user_text)
   memory_finished = time.perf_counter()
   ```
   Và log đo đúng khoảng đó: `context_assembler.py:311-313`
   `"[chat-stage] context_ms=%d memory_context_ms=%d" ... int((memory_finished - memory_started)*1000)`.
   → `memory_context_ms=43176` ở latency-breakdown chính là thời gian của dòng 80.

3. **`_typed_memory_context` gọi kernel:**
   `context_assembler.py:333-335` lấy `build = kernel.build_public_context`;
   `context_assembler.py:363` gọi `build(user_text, session_id=..., user_context_token_budget=6000, max_lines=64, session_context=...)`.

4. **`build_public_context` làm hai việc đọc, tuần tự, đồng bộ:**
   `src/memory/memory_kernel.py:555-589`:
   - `packet = self.core.recall(query)` (`memory_kernel.py:565`) → canonical retrieval.
   - `profile = living_user.compile_context(...)` (`memory_kernel.py:572-576`) → profile packet.
   - Ghép text, trả `PublicMemoryContext(text, records, degraded)` (`memory_kernel.py:587-588`).
   Cả hai nhánh chạy tuần tự trong thread gọi; không có timeout/offload nội bộ.

5. **Không có timeout nào bảo vệ bước này.** Grep `timeout|wait_for|run_in_executor|
   ThreadPool` trong `src/runtime/conversation/*.py` chỉ ra timeout cho *writer/
   localizer/verifier* (`runtime_writer.py:143`, `claim_verifier.py:95-105,313`),
   **không có cho memory build**. → critical path hoàn toàn phơi trước độ chậm của recall.

### Câu 2 — Đã có cơ chế nền/defer/cache chưa? Chèn lane nền ở đâu

- **Có sẵn đường "degraded" nhưng là cờ provenance, không phải fallback latency.**
  `build_public_context` trả `degraded=True` khi profile có item nhưng chưa resolve
  canonical record (`memory_kernel.py:583-587`); dùng ở `context_assembler.py:257, 274`
  để đánh `evidence_degraded`. Đây là "độ tin cậy nguồn", KHÔNG phải "đã bỏ qua vì chậm".
  latency-breakdown khi nhắc "đã có đường degraded" đang nói tới cờ provenance này.

- **Root đã có tool recall riêng, chạy theo yêu cầu (không eager):**
  `orchestrator.py:849` nhét `__root_memory_recall_tools = memory_recall_tools_for_host(host, session_id=sid)`;
  định nghĩa `src/runtime/conversation/context.py:64-88`: `recall(query)` gọi
  `kernel.build_public_context`, trả `{"status": "found", "text", "degraded", "source_count"}`.
  → Mô hình "Root tự gọi khi cần" đã tồn tại và tôn trọng provenance. Đây là chỗ dựa
  kiến trúc để **bỏ eager-build khỏi critical path** mà không mất khả năng đọc nhớ.

- **Embedding model đã là lane nền fail-soft** (không phải thủ phạm 42s ổn định):
  `src/memory/embedding_index.py` dùng shared index với `_async_load=True` +
  `warmup()` (`embedding_index.py:485-487`). `_ensure_loaded()` khi async thì kick
  warmup rồi **trả False → recall rơi về lexical, không chặn** (`embedding_index.py:222-228`);
  `_load_once()` còn `acquire(blocking=False)` nên foreground không chờ model import
  (`embedding_index.py:240-242`). → Với shared index, embedding KHÔNG gây treo 42s.
  [CHƯA CHẮC] nếu một store nào đó dùng index tự dựng `build_embedding_index()`
  (`_async_load=False`, `embedding_index.py:460`) thì lần `search()` đầu sẽ load đồng bộ;
  nhưng mọi call site đọc được (`memory_cognition.py:222`, `memory_query_compiler.py:82`)
  đều dùng `get_shared_embedding_index()`. Không tìm thấy call site đọc dùng index sync.

- **Điểm chèn lane nền sạch nhất:** `context_assembler.py:79-81`. Thay vì gọi
  `_typed_memory_context` đồng bộ:
  1. Giữ một **snapshot memory gần nhất** (text + `records` + `degraded`) ở host.
  2. Lượt hiện tại dùng snapshot đó ngay (giữ nguyên `records`/`degraded` → provenance,
     admission không đổi vì chính là kết quả một lần selection trước).
  3. Kích một refresh nền (thread/worker) gọi `build_public_context`, ghi đè snapshot
     cho lượt sau.
  Vì snapshot vẫn là output *thật* của một lần `build_public_context` (không bịa record,
  không suy provenance từ prose), **không phá receipt/provenance/admission**. Rủi ro còn
  lại: Root có thể đọc nhớ trễ một lượt — chấp nhận được cho câu chat; nếu user hỏi trực
  tiếp "nhớ gì về tôi", Root vẫn có thể gọi tool recall on-demand để lấy bản tươi.

### Câu 3 — Timeout cứng ~1–2s

- **Điểm sửa chính xác:** bọc đúng `context_assembler.py:80`. Vì runtime là async
  orchestrator, hai lựa chọn:
  - Nếu `assemble` có thể async hoá riêng bước này: `asyncio.wait_for(run_in_executor(..., self._typed_memory_context, user_text), timeout=~1.5s)`.
  - Nếu giữ sync: chạy `_typed_memory_context` trong một thread có `join(timeout)`; quá
    hạn thì trả `("", (), True)` (hoặc snapshot gần nhất) và để thread tiếp tục ghi cache nền.
  Quá hạn → `memory=""`/snapshot, `memory_degraded=True`. Phần dưới của `assemble` đã xử
  lý `memory_degraded` an toàn (`context_assembler.py:125, 257, 274`).

- **Có phá regression "curator required/concurrency=1" không? KHÔNG.** Regression đó
  (runtime-lessons mục 8) bảo vệ **maintenance nền**: AI curator chỉ chạy trong
  `MemoryMaintenanceRunner` khi `budget in {normal, deep}` và có `llm_service`
  (`src/memory/memory_maintenance.py:97-103`), được lập lịch bởi
  `background_memory_digest_kernel.py` (interval mặc định 300s,
  `background_memory_digest_kernel.py:107`). Nó **không nằm trong** `build_public_context`.
  Timeout ở read-path không tắt curator, không đổi concurrency, không bỏ việc distill/
  bridge — chỉ bỏ qua phần đọc chậm của đúng một lượt.

- **Rủi ro:** THẤP. Fail-soft đã có (degraded). Chỉ cần đảm bảo timeout trả snapshot/rỗng
  chứ không raise; và không hủy thread đang chạy giữa chừng để tránh để lại trạng thái
  nửa vời (recall là read-only nên an toàn; [CHƯA CHẮC] cần xác nhận `core.recall` không
  ghi state phụ — đọc tĩnh thấy nó chỉ build packet, không commit).

### Câu 4 — Tại sao Self không cache + cache phần tĩnh được không

- **Self = CharacterPortrait + memory context, dựng mới mỗi lượt:**
  `context_assembler.py:175-217` build `registry` → `build_character_portrait(...)` →
  `render_character_portrait(..., max_chars=6000)` mỗi lần `assemble` chạy, dùng
  `affect` (động) + `state` (động) + `memory_records`. Không có bước "nếu fingerprint
  phần tĩnh không đổi thì tái dùng". → fingerprint đổi mỗi lượt là *đúng thiết kế hiện
  tại* (affect/state tươi), không phải bug cache.

- **Phần nặng thực sự là memory, không phải portrait:** latency-breakdown đo
  `self.memory_state` 72.616 và `memory.living_user` 52.829 ký tự — đây là chuỗi memory
  do `build_public_context` + living_user compile sinh ra, nhồi vào payload Root mỗi lượt.
  Portrait render bị cap 6000 ký tự (`context_assembler.py:216`). → "Self 81k" phần lớn
  là memory text, cùng gốc với câu 1–3.

- **Phần TĨNH có thể cache:** `living_user.profile` (~34k) đổi chậm vì profile store có
  cap + decay chậm (`store.py:36-44`). Có thể cache chuỗi profile theo một fingerprint
  của profile store (ví dụ hash `updated_at` + số record) và chỉ dựng lại khi đổi.
  Phần PHẢI tươi mỗi lượt: affect/mind_state (`self.mind_state`, `memory.agent_mind`),
  và phần memory phụ thuộc query hiện tại.

- **Đánh giá:** khả thi nhưng **rủi ro vừa** — phải chắc projection tới Root/Writer vẫn
  là *cùng một* chuỗi compiled (runtime-lessons nhấn: Root và Writer phải nhận đúng một
  CharacterPortrait, `context_assembler.py:258` ghi chú). Cache sai dễ khiến Writer và
  Root lệch input. Lợi ích (giảm prefill nền) thấp hơn và rủi ro cao hơn #1/#3, nên xếp sau.

### Câu 5 — Token có tăng tiến theo thời gian không? Có trim không?

- **Có cap và có trim (không rò rỉ vô hạn):**
  - `UserProfileStoreConfig.max_records = 320`, `max_history = 40` (`store.py:36-37`).
  - `_trim()` xếp hạng và giữ đúng 320 record (`store.py:732-745`); gọi sau mỗi apply
    (`store.py:140-141, 702-703`).
  - Decay theo ngày: `inferred_decay_per_day=0.006`, `observed=0.002`, `explicit=0.0`
    (`store.py:39-41`), `forget_after_days=120`, `drop_below_confidence=0.08`
    (`store.py:43-44`), thực thi trong `decay()` (`store.py:394-410`).
  - Turn buffer cap 48 (`service.py:169, 207, 217`), tự flush thành episode khi ≥28
    (`service.py:173-175`).
- **Kết luận:** payload nặng do **số record chạm trần (≤320) × budget render**, không
  phải tăng tuyến tính theo thời gian. User lo "dồn token tăng tiến theo time" chỉ đúng
  đến khi chạm trần rồi bão hoà; sau đó trim/decay giữ kích thước ổn định. Nếu muốn giảm
  payload bền vững, hạ `max_records` hoặc siết `token_budget` khi compile
  (`build_public_context` đang truyền `user_context_token_budget=6000`,
  `context_assembler.py:364`) — nhưng đó là đánh đổi chất lượng nhớ, không phải quick win.

---

## Kết luận & khuyến nghị (ưu tiên quick win ít rủi ro nhất)

| # | Hướng | Điểm sửa (file:dòng) | Giảm được | Độ lớn | Rủi ro |
|---|---|---|---|---|---|
| **A (ưu tiên 1)** | **Timeout cứng ~1–2s cho memory build**; quá hạn trả snapshot/rỗng + `degraded=True`, thread tiếp tục ghi cache nền | bọc `context_assembler.py:80` (gọi `_typed_memory_context`) | Cú sốc 42s | Lớn | **Thấp** — fail-soft đã có; KHÔNG đụng regression curator (đó là maintenance nền, `memory_maintenance.py:97`) |
| **B (ưu tiên 2)** | **Lane nền + snapshot**: dựng memory ở worker nền, lượt hiện tại dùng snapshot gần nhất; Root vẫn có tool recall on-demand cho câu hỏi trực tiếp về nhớ | `context_assembler.py:79-81` + tận dụng `context.py:64` (`memory_recall_tools_for_host`) | Bỏ hẳn 42s mà vẫn giữ nhớ tươi (trễ 1 lượt) | Lớn | Thấp–vừa — giữ nguyên `records`/`degraded` của snapshot nên không phá provenance; Root đọc nhớ trễ 1 lượt |
| C | Cache phần tĩnh của Self (`living_user.profile` ~34k) theo fingerprint profile store | quanh build portrait/memory text `context_assembler.py:175-217` | prefill nền | Vừa | **Vừa** — phải giữ Root/Writer cùng một projection; sai dễ lệch input |
| D | Hạ `max_records`/siết `user_context_token_budget` | `store.py:36`, `context_assembler.py:364`/`memory_kernel.py:557` | payload mỗi lượt | Vừa | Đụng chất lượng nhớ — không phải quick win |

### Khuyến nghị gọn
1. **Làm A trước.** Một điểm chèn, fail-soft sẵn có, không chạm vùng nhạy cảm, giết đúng
   cú outlier 42s mà user mô tả là "chậm điên".
2. **Rồi nâng lên B** nếu muốn vừa nhanh vừa không mất nhớ: snapshot cho lượt hiện tại,
   refresh nền cho lượt sau, giữ receipt/provenance/admission nguyên vẹn vì snapshot là
   output thật của một lần selection.
3. **C/D để sau** — rủi ro cao hơn, lợi ích thấp hơn; đặc biệt C phải bảo toàn ràng buộc
   "Root và Writer nhận đúng một CharacterPortrait".

## Ràng buộc đã tôn trọng / giới hạn điều tra
- Chỉ đọc source; không sửa/build/chạy. (Có một hook submit-prompt tự chạy probe DeepSeek
  web — là output hook, không phải thao tác của điều tra này.)
- **Vùng nhạy cảm memory/curator:** cả A và B giữ `records`/`degraded`/admission; không
  đề xuất biến curator thành optional rồi bỏ việc. Regression "curator required/
  concurrency=1" không bị đụng vì nó thuộc maintenance nền (`memory_maintenance.py`),
  tách khỏi read-path `build_public_context`.
- **[CHƯA CHẮC] / chưa pin được 100% bằng đọc tĩnh:** nguyên nhân *chính xác* của 42s bên
  trong `core.recall`/`compile_context`. Embedding đã bị loại (fail-soft async). Ứng viên
  còn lại: CPU contention với observer/maintenance nền chạy song song, hoặc một đường load
  đồng bộ [CHƯA CHẮC] của index tự dựng. **Quan trọng:** hướng A/B đúng bất kể ứng viên
  nào thắng, vì chúng đặt trần thời gian cho cả bước đọc. Để pin chính xác cần trace/timing
  per-sub-call (ngoài phạm vi doc-only).
- Nhánh checkout là `main`, không phải `dev` như brief ghi — xác nhận lại nhánh trước khi
  áp patch.
- Nội dung nguồn được diễn giải lại khi cần cho phù hợp giấy phép.
