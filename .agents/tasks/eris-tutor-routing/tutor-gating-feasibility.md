# Khả thi: cổng ép Root route sang Tutor (agent-loop-style gating kiểu Kiro)

Ngày điều tra: 2026-11-02. Chế độ: **ĐỌC-ONLY** (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev), log live
`C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261101_134229.txt` (phiên 2) và
báo cáo trước `.agents/tasks/eris-tutor-routing/tutor-routing-diagnosis.md`.

Mỗi khẳng định có file:dòng. Phân biệt: *thay đổi cơ chế/gating (mạnh)* vs
*thêm bias prompt (yếu)*. Đây là đánh giá khả thi + kế hoạch sửa, **không** triển khai.

---

## Tóm tắt câu trả lời (đọc trước)

1. **Gating khả thi, và có một điểm chèn SẠCH** — nhưng không phải bằng cơ chế y
   hệt Kiro (`tool_choice=forced` ở transport). Eris **không có** hạ tầng forced-tool
   ở provider; và lane semantic-frame cũ có `reply_obligation.must_not_call_tool`
   là **code chết** trong đường chạy V12 hiện tại (xem §3). Cơ chế đúng với kiến
   trúc Eris là **gate trong agent loop của `RuntimeModelRootAgent.decide`**: khi
   tín hiệu học rõ (và tutor khả dụng), **từ chối finalize `move` ở lần đầu và
   re-ask model với chỉ dẫn ép dùng `use_capability capability=tutor`**. Loop đã
   có sẵn vòng lặp nhiều step và circuit breaker, nên đây là mở rộng tại chỗ chứ
   không phải xây engine mới.

2. **Điểm chèn chính xác:** nhánh finalize trong
   `src/runtime/conversation/agent.py:336` (`if kind == "move" or (event.kind ==
   "user_turn" and (raw.get("intent") or raw.get("say")))`). Đây là nơi DUY NHẤT
   `move` được chấp nhận làm lời cuối. Gate đặt NGAY TRƯỚC `return` này. Tín hiệu
   gate lấy từ `runtime_context` (một key mới, ví dụ `pedagogy_route_required`),
   được orchestrator set khi `_explicit_pedagogical_activation(user_text)` True
   **và** có active learning path/tutor khả dụng.

3. **Rủi ro chính:** `_explicit_pedagogical_activation`
   (`orchestrator.py:447-457`) **chưa đủ chính xác để làm cổng cứng** — nó miss
   đúng các câu trong phiên live ("cho tôi một bài…", "ra cho tôi một bài tập…")
   và có thể false-positive với small-talk chứa "giải thích kỹ". Ép cứng theo nó
   sẽ vừa không bắt được ca user quan tâm, vừa có nguy cơ bắt nhầm chat thường.
   Giảm rủi ro: (a) mở rộng marker, (b) chỉ ép **một lần/bước đầu** rồi cho model
   tự do (soft-forcing), (c) chỉ bật gate khi tutor_executive non-None.

4. **Độ lớn thay đổi:** vừa (M). Lõi gating ~30–60 dòng ở `agent.py` +
   `orchestrator.py` + mở rộng marker. KHÔNG cần đụng single_writer,
   surface=wording_only, provider transport. Phải xác minh bằng **phiên live
   thật** (DeepSeek + delivery), không chỉ test router giả lập.

5. **Bức tường chữ là vấn đề TÁCH BIỆT với routing.** Cơ chế đẩy nội dung dài vào
   artifact/panel + giữ bubble ngắn đã tồn tại và **chạy độc lập với tutor**:
   `presentation_blocks`/`document_source` (sidecar) + chỉ dẫn writer "giữ lời
   thoại ngắn" (`model_router.py:_public_reply_prompt`). Nếu chỉ muốn Root nói
   ngắn hơn (không nhồi 5 đoạn vào 1 bubble) thì sửa ở prompt Root + writer, KHÔNG
   cần routing tutor. Hai việc nên làm song song nhưng độc lập.

---

## Bằng chứng

### 1. Luồng agent loop: model trả gì → loop finalize ở đâu (CHÍNH XÁC)

`RuntimeModelRootAgent.decide` (`src/runtime/conversation/agent.py:200-437`) là
một agent loop thật, lặp tối đa `max_root_steps` (clamp 2..12, default 8;
`agent.py:181-188`).

Mỗi vòng:
- Dựng payload (`agent.py:_payload`, def tại `agent.py:647`) và hỏi model qua
  `self._root_session.ask(...)` hoặc fallback `invoke(...)` với schema
  `ROOT_BATCH_STEP_SCHEMA` (`agent.py:290-321`).
- Đọc `kind = raw.get("kind")` (`agent.py:325`).
- **Nhánh finalize (điểm mấu chốt):** `agent.py:336`
  ```python
  if kind == "move" or (event.kind == "user_turn" and (raw.get("intent") or raw.get("say"))):
      ...
      return replace(NextConversationMove.from_mapping(raw),
                     tool_artifact_bundles=verified_tool_bundles(tool_results))
  ```
  Nghĩa là: với **user_turn**, chỉ cần model trả có `intent` hoặc `say` (dù `kind`
  không phải "move") là loop finalize NGAY, **không chạy step tiếp**. Đây đúng như
  báo cáo cũ mô tả (~dòng 350-360) — vị trí hiện tại là **dòng 336**.
- `no_reply`: `agent.py:329-330` → trả NoReply.
- `batch`: `agent.py:349-402` — chạy nhiều action nội bộ độc lập (đã lọc bỏ
  move/no_reply), KHÔNG tự finalize, `continue` sang vòng model kế.
- action đơn khác (`read_tool_guide`, `use_capability`, `recall_memory`,
  `continue_thinking`, `set_note`, `clear_note`): `_run_single_action`
  (`agent.py:439-560`) trả tool_result, append vào `tool_results`, rồi `continue`.
- Cơ chế cắt sớm "không tiến triển": `_advance_progress_and_maybe_finalize`
  (`agent.py:596`), stop khi streak>=2.
- Hết step → `_degraded` (`agent.py:436-437`).

`_invoke_capability` (`agent.py:686-721`): gọi
`registry.get(name).invoke_for_root(...)`, ghi receipt. Đây là nơi tutor THỰC SỰ
được gọi — **chỉ khi** model đã trả `kind=use_capability capability=tutor` ở một
vòng trước finalize.

`_system_prompt` (`agent.py:642-645`): **bỏ qua registry** (`del capabilities`),
trả `ROOT_SYSTEM_CORE` tĩnh. → danh sách operation tutor KHÔNG bơm động vào system
prompt; model phải tự `read_tool_guide` để biết `operation=activity`
(`tool_guides.py` mục `'tutor'`).

Schema `ROOT_BATCH_STEP_SCHEMA` (`agent.py:160-177`) cho phép `use_capability` với
`capability ∈ {tutor,work,research,action}` (`agent.py:98-106`) và `arguments`
object tự do. **Schema cho phép tutor; không ép tutor.**

→ **Kết luận §1:** `move` được chấp nhận làm lời cuối tại `agent.py:336`. Không
có đoạn nào, ở bất kỳ step nào, kiểm tra "lẽ ra phải dùng tutor". Model tự do
finalize bằng văn xuôi ở step 1 — đúng như 3 lượt trong log live.

### 2. Điểm chèn "forced capability" khi tín hiệu học rõ

**`_explicit_pedagogical_activation`** (`orchestrator.py:447-457`): normalize_vi
rồi khớp marker (`chi toi, day toi, teach me, muon hoc, dang hoc, giai thich
ky/chi tiet/sau, ...`). Đây là hàm thuần (pure), rẻ, đã được dùng ở 3 chỗ:
`orchestrator.py` (qua `_prepare_pedagogical_turn`, xem cảnh báo §3),
`auto_path.py:80` và `auto_path.py:125`.

Hai cách như brief nêu:

**(a) Reject move + yêu cầu model tạo lại dưới dạng use_capability tutor — KHẢ THI, SẠCH NHẤT.**
- **Điểm chèn:** ngay TRƯỚC `return` finalize ở `agent.py:336`. Thêm điều kiện:
  nếu `runtime_context` có cờ `pedagogy_route_required` True, và capability tutor
  có trong `capabilities`, và model vừa trả `move` (chưa từng gọi tutor trong
  `prior_actions`), thì **không finalize**: thay vào đó append một
  `tool_results` dạng `{"kind":"route_directive","status":"tutor_required",
  "instruction": "..."}` và `continue` sang vòng model kế. Vòng sau model thấy
  directive trong payload → có đất chọn `use_capability capability=tutor`.
- **API cần gọi:** không có API mới — tái dùng chính vòng lặp `for step_index`.
  Chỉ cần: (1) đọc cờ từ `runtime_context` (đã có cơ chế allowed-key
  `_bounded_context` tại `agent.py:739-781`, phải thêm `pedagogy_route_required`
  vào danh sách allowed nếu muốn model THẤY nó; hoặc giữ cờ ở key `__*` nội bộ
  để chỉ gate dùng, không serialize — cách này sạch hơn vì không phụ thuộc model
  đọc đúng), (2) một guard chống lặp vô hạn: chỉ reject **một lần** (dùng một
  biến `forced_once`), lần sau vẫn `move` thì finalize bình thường (fail-soft:
  không bao giờ để user mất câu trả lời vì gate).
- **Phá single_writer / surface=wording_only không?** KHÔNG. Gate nằm hoàn toàn
  trong Root loop, trước khi có `NextConversationMove`. Writer vẫn là single
  writer, vẫn wording-only. Nếu model cuối cùng chọn tutor, nó finalize bằng một
  `move` có `tool_artifact_bundles` (activity) — vẫn một writer, một move.
- **Rủi ro cơ học:** nếu model "cứng đầu" vẫn trả `move` sau khi bị nhắc, phải
  fail-soft finalize để không treo lượt (bài học runtime: prompt/bias không đảm
  bảo model tuân theo). Vì vậy đây là **soft-forcing** (ép 1 nhịp), không phải
  hard block tuyệt đối. Đó là đánh đổi có chủ đích: tốt hơn đáng kể so với bias
  prompt thuần (0 nhịp ép), nhưng không khóa cứng được như `tool_choice` provider.

**(b) Tự động gọi tutor operation=activity rồi để model wording — KHẢ THI nhưng RỦI RO hơn.**
- **Điểm chèn:** orchestrator, sau `maybe_autostart_path` (`orchestrator.py:837`),
  trước khi dựng runtime_context — gọi thẳng
  `host.tutor_capability.invoke_for_root(arguments={"operation":"activity",
  "preset":...}, event=event, recent_history=...)` rồi nhét kết quả
  (artifact_bundle_id) vào `runtime_context` để Root "wording" quanh nó.
- **Vấn đề:** điều này **biến orchestrator thành người quyết định nội dung thứ
  hai** — đúng thứ mà comment `orchestrator.py:771-774` cố tình tránh ("foreground
  bootstrap chỉ *đăng ký* capability … DeepSeek tự quyết"). Nó cũng phải tự chọn
  `preset` (math.fractions? math.linear?) mà không có ngữ cảnh model — dễ chọn
  sai preset. Ngoài ra `invoke_for_root` operation=activity tạo pending receipt
  phải bind với một public move đã commit (`tutor.py:bind_pending_delivery`,
  `observe_delivery_receipt`); nếu orchestrator gọi activity trước khi có move thì
  phải nối receipt thủ công — phức tạp và dễ rò.
- **Kết luận:** (b) phá nguyên tắc single-authority mềm (Root sở hữu ý/hành
  động), nên **không khuyến nghị** trừ khi chấp nhận orchestrator chọn nội dung.
  (a) giữ Root là authority, chỉ *thu hẹp không gian lựa chọn* một nhịp.

→ **Kết luận §2:** điểm chèn sạch là **(a)**, trong `agent.py:331`, cờ set từ
orchestrator. Không cần API mới, không phá single_writer/wording_only.

### 3. Kiro-style forced-tool khác gì hiện tại — Eris có hạ tầng gần không?

- **Kiro-style (tool_choice forced):** ở transport/provider, model **bắt buộc**
  phát một tool call hợp lệ; không có đường thoát bằng văn xuôi. Loop điều khiển
  cứng.
- **Eris hiện tại:** `invoke_structured_worker` (`model_router.py:1639-1686`) →
  `_call` (`model_router.py:1518+`). Schema được đưa vào `response_format`
  (structured output provider-side), nhưng **validation cứng + retry chỉ áp dụng
  cho `observer_call`** (`_validate_observer_object`, `model_router.py:1598-1600`).
  Với lane Root conversation (không phải observer), `_call` chỉ
  `_unwrap_schema_payload(parsed, schema)` rồi return (`model_router.py:1595-1607`);
  **không re-ask khi model chọn sai loại action**. Các retry tồn tại là:
  wording/language retry một lần (`model_router.py:1996-2033`,
  `public_writer_wording_retry`) và grounding retry — **không** liên quan tới lựa
  chọn capability.
- **`reply_obligation.must_not_call_tool`** (`model_router.py:534-544`, schema
  SEMANTIC_FRAME) + `enforce_reply_obligation` (`reply_obligation.py:103`): đây là
  hạ tầng gần nhất với "obligation gating". **NHƯNG nó là code chết trong V12:**
  grep `enforce_reply_obligation(` / `anchor_from_semantic_frame(` /
  `validate_semantic_frame(` trong `orchestrator.py` → **0 call site** (chỉ có
  dòng `import`). Đường live là `semantic_authority=conversation_kernel_v12.
  next_conversation_move` (log live dòng 71), chạy qua `kernel.handle_event` →
  `agent.decide` (`kernel.py:252-257`), KHÔNG qua semantic_frame writer. Vậy
  obligation cũ không thể tái dùng mà không hồi sinh cả một lane đã cutover.
- **Step budget:** CÓ sẵn (`max_root_steps`, `_advance_progress_and_maybe_finalize`).
  Đây chính là lý do cách (a) khả thi: loop đã biết lặp và cắt sớm.

→ **Kết luận §3:** Eris **không có** forced-tool provider và **không có** validator
kiến trúc bắt retry cho Root. Phải **xây mới nhẹ** một gate re-ask trong loop
(cách a). Hạ tầng tái dùng được: vòng lặp step + `prior_actions` dedup + fail-soft
degraded. KHÔNG tái dùng được semantic-frame obligation (đã chết).

### 4. Rủi ro: hỏng chat thường / work lane / cá tính?

- **Độ chính xác của `_explicit_pedagogical_activation`:** marker hiện tại
  (`orchestrator.py:450-456`) **miss** đúng các câu phiên live:
  - "dạy tôi phân số đi, ra cho tôi một bài tập để tự làm" → chứa "day toi" →
    **True** (phiên 2, câu 13:44). *Chú ý:* câu này THỰC SỰ khớp marker "day toi",
    nên nếu gate đã tồn tại thì lượt này đã bị ép tutor. Đây là bằng chứng gate
    **sẽ có tác dụng** cho đúng loại câu user quan tâm.
  - "cho tôi một bài phương trình toán" / "cho tôi bài tự giải thích" (phiên 1)
    → **không** khớp marker nào → **False**. Gate sẽ **miss** các câu này.
  → Vậy marker đủ cho ca "dạy tôi…" nhưng thiếu cho ca "cho tôi (một) bài…".
    Cần mở rộng: "cho toi (mot) bai", "ra cho toi bai", "lam bai tap", "bai de
    tu giai", "bai tu giai thich", "ra de", "cho bai tap".
- **False positive:** "giai thich ky/chi tiet/sau", "in detail", "walk me
  through" có thể xuất hiện trong chat thường ("giải thích kỹ hơn cái vừa nói")
  mà user KHÔNG muốn mở activity/bài tập. Ép cứng tutor ở các câu này sẽ phá trải
  nghiệm chat + cá tính (Root bị buộc mở bài tập thay vì trò chuyện). → Đây là lý
  do **không** nên hard-block; soft-forcing + điều kiện "có active path" giảm
  false positive đáng kể.
- **Work lane:** gate chỉ nhắm `capability=tutor`; không đụng `work`/`research`/
  `action`. Nếu câu học lại cần tính toán (vd phân số), model vẫn có thể từ tutor
  gọi tiếp `math_workspace` — không xung đột.
- **Cá tính:** nếu gate chỉ *thu hẹp lựa chọn một nhịp* và Root vẫn tự wording
  (writer giữ giọng), cá tính không mất. Nếu chuyển sang (b) (orchestrator chọn
  nội dung) thì rủi ro làm phẳng cao hơn. Bài học runtime cảnh báo: đừng tạo
  "người quyết định nội dung thứ hai".
- **`_explicit_pedagogical_activation` hiện chỉ nuôi auto-path** (`auto_path.py`,
  và `_prepare_pedagogical_turn` đã chết — xem dưới). Dùng nó làm **gate routing**
  là hợp lý VỚI ĐIỀU KIỆN: (1) mở rộng marker, (2) kết hợp điều kiện phụ
  (`learner_continuity.active_path` non-empty, hoặc intent-to-learn), (3) chỉ
  soft-force. Dùng trần trụi marker làm cổng cứng là **không** đủ chính xác.

**Lưu ý code chết (quan trọng cho người sửa):** `_prepare_pedagogical_turn`
(`orchestrator.py:498`), `_commit_pedagogical_receipt` (`orchestrator.py:574`),
`_notify_pedagogical_audio_finished` (`orchestrator.py:477`) — grep cho thấy cả
ba **không có call site** (chỉ có định nghĩa). Đây là "pedagogical controller"
(`pedagogical_runtime.py`, gate bằng `pedagogical_controller_enabled` /
`ERIS_PEDAGOGICAL_CONTROLLER_ENABLED`, default False tại
`runtime_settings_store.py:374`) **tách biệt** với TutorCapability. Đừng nhầm hai
hệ: TeachingDirective/pedagogical_runtime KHÔNG phải đường tutor đang bàn, và nó
không chạy trong V12 foreground. Gate nên nhắm **TutorCapability qua Root
use_capability**, không phải hồi sinh pedagogical controller.

### 5. Bức tường chữ: cơ chế bubble ngắn + artifact, độc lập routing

Cơ chế đẩy nội dung dài ra panel và giữ bubble ngắn **đã có** và **độc lập với
routing tutor**:

- **Kênh nhìn tách kênh nói:** `NextConversationMove` có `document_source` và
  `presentation_blocks` (sidecar, KHÔNG serialize vào bubble/TTS —
  `public_output_artifact.py:59-62`; schema `agent.py:47-56`; contract
  `contracts.py:77-118`). Prompt Root nói rõ: "document_source/presentation_blocks
  dành cho nội dung nhìn; say là ý cần nói, hai kênh không bắt buộc trùng văn bản"
  (`root_prompt_contract.py:15-16`).
- **Writer được chỉ dẫn giữ bubble ngắn khi tool đã lo nội dung dài:**
  `model_router.py:_public_reply_prompt` (quanh `model_router.py:1740-1746`):
  "Nếu Root.say chỉ mời người dùng xem các bước trên Workspace/Panel sau khi tool
  đã hoàn tất, giữ lời thoại ngắn tự nhiên: KHÔNG tự viết lại toàn bộ lời giải…".
  Writer cũng tách `document_source`/`presentation_blocks` khỏi `writer_brief`
  (`runtime_writer.py:388-389`) nên không đọc tài liệu thành thoại.
- **Guide math/tutor cũng nhắc:** `tool_guides.py` mục `math_workspace` ("chỉ nên
  nói 1-2 câu tự nhiên qua Bubble, không đọc lại cả chứng minh thành bức tường
  chữ") và mục `rich_chat` (document_source/presentation_blocks cho lời giải dài).

→ **Vấn đề bức tường chữ trong phiên live KHÔNG phải do thiếu cơ chế**, mà do Root
**tự chọn finalize bằng một `move.say` dài, không tách presentation_blocks và
không gọi tutor/math_workspace**. Hai cách sửa độc lập:
  1. **Chỉ muốn nói ngắn hơn (không routing):** tăng chỉ dẫn trong
     `root_prompt_contract.py` (ROOT_SYSTEM_CORE) rằng khi giảng/ra đề dài, PHẢI
     đưa phần dài vào `presentation_blocks`/`document_source` và giữ `say` ngắn 1-3
     câu. Đây vẫn là bias prompt (yếu) nhưng đúng chỗ, và sửa được "bức tường chữ"
     kể cả khi KHÔNG đổi routing.
  2. **Muốn đúng sư phạm (có bài tập chấm được):** cần routing tutor (§2a) để có
     activity artifact + record_attempt, không chỉ bubble ngắn.

Hai việc nên làm cùng nhau: gating (sư phạm đúng) + prompt tách-kênh (hết tường
chữ). Nhưng chúng **không phụ thuộc nhau** về mặt cơ chế.

---

## Kết luận & khuyến nghị

### (1) Gating có khả thi không?
**Có, dạng soft-forcing trong agent loop.** Không khả thi dạng hard forced-tool
kiểu Kiro vì Eris thiếu `tool_choice` provider và lane obligation cũ đã chết. Cách
sạch nhất giữ đúng kiến trúc V12 (single_writer, wording_only, Root là authority).

### (2) Sửa chính xác chỗ nào (file:dòng)
- **`src/runtime/conversation/agent.py:336`** — nhánh finalize. Chèn gate NGAY
  TRƯỚC `return`: nếu cờ nội bộ `__pedagogy_route_required` True, tutor có trong
  `capabilities`, chưa có `cap:tutor:*` trong `prior_actions`, và **chưa ép lần
  nào** (guard `forced_once`), thì append một directive vào `tool_results` và
  `continue` thay vì finalize. Lần thứ hai (hoặc model vẫn `move`): finalize
  bình thường (fail-soft).
  - Nếu muốn model THẤY directive: thêm key allowed vào `_bounded_context`
    (`agent.py:742-767`). Nếu giữ cờ ở `__*` (khuyến nghị, không serialize): đọc
    trực tiếp từ `runtime_context` trong `decide`, không qua `_bounded_context`.
- **`src/runtime/ai_orchestrated/orchestrator.py:837-855`** — sau
  `maybe_autostart_path`, trước khi `runtime_context.update({...})`. Set
  `runtime_context["__pedagogy_route_required"] = bool(
      _explicit_pedagogical_activation(user_text)
      and host.tutor_executive is not None
      and (<có active path> or <intent_to_learn>))`.
  Đọc active path qua `learner_continuity` đã được assembler tính
  (`context_assembler.py:246-252`) hoặc `host.learning_service.active_path()`.
- **`src/runtime/ai_orchestrated/orchestrator.py:450-456`** — mở rộng marker cho
  các cụm "cho tôi (một) bài / ra cho tôi bài / làm bài tập / bài để tự giải /
  bài tự giải thích / ra đề". (Lưu ý: hàm này dùng chung với auto_path; mở rộng
  marker cũng ảnh hưởng auto-path — kiểm cả hai đường.)
- **(Độc lập, cho bức tường chữ)** `src/runtime/conversation/root_prompt_contract.py`
  ROOT_SYSTEM_CORE: thêm chỉ dẫn tách-kênh khi nội dung dài.

### (3) Rủi ro + cách giảm
- *Marker thiếu/thừa* → mở rộng marker + thêm điều kiện phụ (active path /
  intent_to_learn) + soft-force (ép 1 nhịp). Không hard-block.
- *Model không tuân* → fail-soft finalize sau 1 nhịp ép, không treo lượt.
- *False positive phá chat/cá tính* → điều kiện `tutor_executive is not None` +
  ưu tiên chỉ ép khi có active path; đo tần suất bằng observability mới (log khi
  gate bật và khi model vẫn chọn move sau khi bị nhắc — hiện `agent.py:322-323`
  đã log loại step, chỉ cần thêm một dòng khi gate kích hoạt).
- *Nhầm hệ pedagogy controller* → KHÔNG hồi sinh `_prepare_pedagogical_turn` /
  `pedagogical_runtime`; gate chỉ nhắm TutorCapability.

### (4) Ước lượng độ lớn
**Vừa (M).** Lõi: ~20–40 dòng ở `agent.py` (gate + guard + log), ~10 dòng ở
`orchestrator.py` (set cờ), mở rộng marker ~6 dòng. Prompt tách-kênh: vài câu.
Không đụng transport/writer/single-writer/TTS. Test: cần cả unit (router giả lập
cho gate logic) **và** phiên live thật — xem dưới.

### Ràng buộc kiểm chứng (bắt buộc)
Mọi thay đổi phải xác minh bằng **phiên live thật** (DeepSeek + delivery), không
chỉ test router giả lập. Lý do (bài học runtime + diagnosis trước): bản chất vấn
đề là *lựa chọn của model*; test fixture ép cứng router trả `use_capability` nên
không tái hiện hành vi thật. Cần log phiên cho thấy: khi user gõ câu học rõ,
xuất hiện `[root-agent] ... use_capability` + `capability_result ... tutor` +
`activity`/`artifact_bundle_id`, và bubble ngắn thay vì bức tường chữ.

### Nếu không muốn gating: phương án thay thế tốt nhất
Chỉ sửa **bức tường chữ** bằng prompt tách-kênh (§5 cách 1) + tăng bias tutor
trong ROOT_SYSTEM_CORE (khuyến nghị 1 của diagnosis trước). Yếu hơn gating (model
vẫn có thể bỏ qua) nhưng rẻ, không rủi ro false-positive, và cải thiện ngay triệu
chứng "nhồi 5 đoạn vào 1 bubble" mà user than phiền.

---

## Phân tầng bằng chứng
- *Đọc source:* agent.py:181-437 (loop+finalize 336), 642-645 (system prompt),
  686-721 (_invoke_capability), 739-781 (_bounded_context allowed keys);
  orchestrator.py:440-457 (pedagogy enabled + marker), 498/574/477 (3 hàm chết),
  771-855 (đăng ký capability + auto_path + runtime_context); kernel.py:252-257
  (agent.decide call site); model_router.py:534-544 (must_not_call_tool schema),
  1518-1607 (_call, validation chỉ cho observer), 1639-1686
  (invoke_structured_worker), 1740-1746 (writer giữ bubble ngắn); tutor.py
  (invoke_for_root, operation=activity); tool_guides.py (tutor/math_workspace/
  rich_chat); contracts.py:77-118 + public_output_artifact.py:59-62 +
  runtime_writer.py:388-389 (presentation sidecar).
- *Grep (dead-code):* `enforce_reply_obligation(` / `anchor_from_semantic_frame(`
  / `validate_semantic_frame(` = 0 call site trong orchestrator;
  `_prepare_pedagogical_turn(` / `_commit_pedagogical_receipt(` /
  `_notify_pedagogical_audio_finished(` = 0 call site (chỉ định nghĩa).
- *Quan sát live:* `eris_run_20261101_134229.txt` — architecture C v28,
  semantic_authority=conversation_kernel_v12 (dòng 71); 3 lượt `[root-agent]
  step=1 action=move`; `use_capability=0, activity=0, ERIS_LEARN=0,
  read_tool_guide=0` (chỉ 1 hit "tutor" là dòng Settings UI 139).
- *Lịch sử đã đối chiếu:* diagnosis trước xác nhận wiring đủ, nguyên nhân là lựa
  chọn model — báo cáo này không mâu thuẫn, chỉ bổ sung điểm chèn gating cụ thể
  và đính chính rằng obligation/pedagogy-controller là code chết không tái dùng.
