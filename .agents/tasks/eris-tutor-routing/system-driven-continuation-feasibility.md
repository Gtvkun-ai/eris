# Khả thi: Hướng 3 — HỆ THỐNG tự cấp continuation lease (cuốn chiếu kiểu Kiro)

Ngày điều tra: 2026-11-02. Chế độ: **ĐỌC-ONLY** (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev); báo cáo trước
`.agents/tasks/eris-tutor-routing/streaming-cadence-feasibility.md`;
`docs/knowledge/2026-10-14-eris-runtime-lessons.md` (hợp đồng 'text chờ voice' 18/10).
Mỗi khẳng định có file:dòng hoặc symbol. Nơi không đọc được thì ghi 'không tìm thấy'.

**Định nghĩa Hướng 3 (nhắc lại):** ngay cả khi model chọn `after=wait_user`, NẾU mạch
giảng chưa trọn thì HỆ THỐNG tự cấp lease để Root chạy lại (re-evaluate từ ngữ cảnh mới)
và nói nhịp kế. Nhịp do cơ chế đẩy, không do model tự giác; nhưng Root VẪN decide() lại
từ đầu mỗi nhịp nên giữ được "nghĩ lại giữa nhịp".

---

## Tóm tắt câu trả lời (đọc trước)

1. **Hệ thống CÓ THỂ cấp lease độc lập về mặt cơ học — nhưng chỉ ở ĐÚNG MỘT điểm, và
   phải sửa code.** `ContinuationLeaseScheduler.schedule()` (`continuation.py:82-150`) là
   hàm thuần: nó tạo lease theo tham số `after` truyền vào, và **hard-cancel** khi
   `after == WAIT_USER` (`continuation.py:93-95`). Scheduler KHÔNG tự nghe cờ từ move;
   nó chỉ làm theo `after` mà **caller** đưa. Caller duy nhất là
   `kernel.ConversationKernel.settle_delivery()` tại `kernel.py:916-924`, truyền
   `after=turn.move.after`. Vậy Hướng 3 = **sửa một chỗ**: ở `settle_delivery`, "nâng"
   `turn.move.after` từ `WAIT_USER` → `MAY_CONTINUE` khi một điều kiện hệ-thống đúng,
   rồi mới gọi `schedule(...)`. Không cần sửa chính scheduler.

2. **KHÔNG có tín hiệu 'mạch chưa trọn' sẵn trong move/turn mà kernel đọc được.**
   `NextConversationMove` chỉ mang `intent/say/delivery/after/presentation_blocks/
   document_source` (`contracts.py:62-116`). Không có field kiểu `more_to_say`/`continue`/
   `beat_remaining`. Contract **cố ý cấm** thêm field nhịp
   (`contracts.py:1-11`: "Không biểu diễn nhịp nói bằng floor/beat/projection hay quota
   số câu"). `presentation_blocks` là nội dung nhìn, không phải cờ còn-tiếp, và **kernel
   không bao giờ đọc nó** (grep `presentation_blocks` trong `kernel.py`: không tìm thấy).
   → Muốn biết "Root còn ý chưa nói", Hướng 3 **phải tự chế một tín hiệu mới**.

3. **`conversation_trajectory` (V76) có vẻ là tín hiệu sẵn, nhưng KHÔNG dùng được cho
   mục tiêu này và cũng không tới được kernel.** Nó là tín hiệu **chủ đề xuyên NHIỀU
   lượt** (`active/closed/momentum/energy/depth/awaiting_user_answer`,
   `conversation_trajectory.py:106-170`), không phải "trong MỘT nhịp giảng còn ý kế".
   `tutor/auto_path.py:100-101` nói thẳng: depth là "evidence của tính liên tục, không
   phải quota/hard governor để điều khiển lời Root". Quan trọng hơn: trajectory **không
   được inject vào runtime_context của ConversationKernel** (grep trong
   `context_assembler.py`: không tìm thấy; nó chỉ chảy vào Subject/Executive cortex,
   seed worker, tutor auto_path — `subject_ingress.py:63-67,124-126`,
   `executive_cortex.py:764-770`). Kernel cũng không giữ `host` (`bootstrap.py:40-54`
   chỉ truyền writer/delivery `host`, không truyền cho kernel), nên `settle_delivery`
   không thể `ensure_conversation_trajectory_runtime(host)` nếu không thêm wiring mới.

4. **Giữ được 'nghĩ lại giữa nhịp': CÓ.** Khi lease due, `handle_due_continuation`
   (`kernel.py:584-640`) tạo `ConversationEvent.continuation_due` rồi gọi `handle_event`
   → `agent.decide()` **mới hoàn toàn** từ `recent_history`/receipt. Không replay `say`
   cũ (continuation.py docstring:4-6 "chỉ khôi phục quyền re-evaluate, không khôi phục
   câu chữ cũ"). Đây là ưu điểm thật của Hướng 3 so với cắt cơ học một `say`.

5. **Rủi ro CHÍNH của Hướng 3 là runaway, và nó NẶNG hơn Hướng 1.** Breaker self-wake
   (`max_consecutive_self_wakes=24`, `max_chain_seconds=120s`, `continuation.py:50-52,
   98-110`) chặn vòng VÔ HẠN nhưng KHÔNG chặn Eris nói 24 nhịp liền user không muốn —
   vì Hướng 3 chủ động phủ nhận ý định dừng (`wait_user`) của Root. Cần một **điều kiện
   dừng do hệ thống tự định nghĩa** (đếm số lần ép? ngưỡng độ dài?), mà mọi lựa chọn đều
   rơi về **heuristic** vì không có tín hiệu 'mạch chưa trọn' thật (xem §3).

6. **Khuyến nghị: KHÔNG làm Hướng 3; chọn Hướng 1 (prompt).** Vì không có tín hiệu
   'mạch chưa trọn' sẵn, Hướng 3 bắt buộc dựa heuristic (gần như chắc là độ dài `say` +
   đếm lần ép) để quyết khi nào override `wait_user`. Đó đúng là thứ contract cấm
   (`root_prompt_contract.py` dòng cuối: cấm runtime tạo "speech budget, max_sentences,
   desired_shape... semantic scheduler") và là thứ `continuation.py:41-44` tự mô tả nó
   KHÔNG làm ("không cắt câu, không giới hạn số sentence"). Heuristic độ dài ở tầng hệ
   thống **không elegant hơn** bias prompt của Hướng 1, lại thêm rủi ro runaway và phá
   nguyên tắc "model/cá tính quyết nhịp". Nếu vẫn muốn mạnh hơn prompt, phương án đúng
   kiến trúc là **soft-forcing ở tầng Root (agent.py)** — gợi ý model tự chia nhịp +
   `may_continue` rồi để model finalize — chứ không phải hệ thống tự cấp lease sau lưng
   model (xem §6 chi tiết).

---

## Bằng chứng

### Q1. Scheduler có cho hệ thống tự cấp lease không? Call site của `schedule()`?

**`schedule()` là hàm thuần theo `after` của caller; không tự nghe move.**

- `ContinuationLeaseScheduler.schedule(..., after: ConversationAfter, ...)`
  (`continuation.py:82-150`). Logic quyết định:
  - `if after == ConversationAfter.WAIT_USER: self.cancel_session(sid); return None`
    (`continuation.py:93-95`) — wait_user ⇒ hủy lease, dừng chuỗi.
  - Ngược lại tính `delay` (`continue_self`=0.15s, `may_continue`=1.2s,
    `continuation.py:124`), `due_at`, dựng `ContinuationLease(..., mode=after, ...)`
    (`continuation.py:126-141`) rồi `_write(lease)` (`continuation.py:148`).
- `claim_due()` (`continuation.py:227-283`), `peek()` (`continuation.py:205-225`),
  `cancel_session()` (`continuation.py:152-162`): đều là cơ học lease/generation; không
  có nhánh nào tự sinh lease từ nội dung move. `schedule` là **lối vào duy nhất** để tạo
  lease.
- **Call site duy nhất của `schedule()`** (grep `\.schedule\(` trong `src/runtime`):
  `kernel.py:916` trong `ConversationKernel.settle_delivery()`:
  ```
  lease = self.continuation.schedule(
      session_id=turn.session_id, generation=turn.generation,
      move_id=turn.move.move_id, after=turn.move.after,   # <-- kernel.py:921
      parent_chain_started_at=..., parent_self_wakes=...,
  )
  ```
  (`kernel.py:916-924`). `settle_delivery` chỉ chạy khi delivery **thành công**
  (`kernel.py:901-915` nhánh `successful`), tức SAU khi bubble đã commit theo
  `audio_start` — nên override ở đây không đụng hợp đồng text-chờ-voice của bubble vừa
  phát.

→ **Kết luận Q1:** scheduler chỉ làm theo `after` caller đưa. Để hệ thống cấp lease độc
lập, điểm sửa là **`kernel.py:921`**: thay `after=turn.move.after` bằng một giá trị
`effective_after` do kernel tính (nâng `WAIT_USER`→`MAY_CONTINUE` khi điều kiện hệ-thống
đúng). Không cần sửa `continuation.py`.

### Q2. Điểm chèn sạch để 'nâng' wait_user → may_continue?

**Điểm sạch = `kernel.py:916-924`, ngay trước lời gọi `schedule`.** Tại đó kernel đã có
đủ dữ liệu cơ học:
- `turn.move` (move vừa phát, gồm `say`, `after`, `presentation_blocks`).
- `turn.continuation` (`kernel.py:38`) — nhịp này đã là continuation hay chưa.
- `turn.continuation_chain_started_at`, `turn.consecutive_self_wakes`
  (`kernel.py:40-42`) — để tự giới hạn số lần ép.

Một "system override" sẽ có dạng:
```
system_wants_more = self._system_continuation_condition(turn)   # cần ĐỊNH NGHĨA MỚI
effective_after = (
    ConversationAfter.MAY_CONTINUE
    if (turn.move.after == ConversationAfter.WAIT_USER and system_wants_more)
    else turn.move.after
)
lease = self.continuation.schedule(..., after=effective_after, ...)
```
Về mặt cơ học điều này SẠCH và nhỏ (sửa ~1 chỗ). **Vấn đề không nằm ở điểm chèn mà nằm
ở `_system_continuation_condition` — cái này không có tín hiệu thật để dựa vào (Q3).**

Lưu ý guard sẵn giữ nguyên: sau `schedule`, nếu lease != None thì
`phase=CONTINUATION_PENDING` và dispatch `speculative_preparer` (`kernel.py:925-942`);
breaker trong `schedule` vẫn áp. Override chỉ đổi đầu vào `after`, không phá các guard này.

### Q3. Có tín hiệu 'mạch chưa trọn' SẴN không?

**Không có tín hiệu nào đúng ngữ nghĩa "Root còn ý trong NHỊP này" mà kernel đọc được.**

- **Trong contract move:** `NextConversationMove` =
  `intent, say, delivery, after, move_id, literal_dialogue, document_source,
  presentation_blocks, tool_artifact_bundles` (`contracts.py:62-78`). Không field nào
  báo "còn tiếp". `after` là ý ĐỊNH DỪNG của model, chính là thứ Hướng 3 muốn phủ nhận —
  không thể dùng nó làm tín hiệu còn-tiếp. Docstring contract cấm thêm field nhịp
  (`contracts.py:1-11`).
- **`presentation_blocks`:** là structured visual (`agent.py:46-55` schema math/table/
  code/chart/document), tối đa 6 block. Nó KHÔNG đồng biến với "lời nói còn dài" — một
  bài giảng dài có thể 0 block; một câu ngắn có thể kèm 1 bảng. Và **kernel không đọc
  `presentation_blocks`** (grep trong `kernel.py`: không tìm thấy) nên dùng nó phải thêm
  code mới + là proxy sai.
- **`conversation_trajectory` V76:** là tín hiệu chủ đề **xuyên nhiều lượt**, không phải
  trong-một-nhịp:
  - Fields `active/closed/momentum/energy/depth/lifecycle_state/development_mode/
    awaiting_user_answer/public_autonomous_budget` (`conversation_trajectory.py:106-170`).
  - `observe_assistant_commit` đặt `awaiting_user_answer=asks` theo việc câu CÓ "?"/
    hỏi hay không (`conversation_trajectory.py:420-470`), không theo "còn ý giảng".
  - `depth` tăng mỗi user turn mới (`conversation_trajectory.py:330-336`), đo liên tục
    chủ đề qua lượt — `auto_path.py:100-101` ghi rõ không dùng làm governor lời Root.
  - **Đường dây:** trajectory chỉ tới Subject/Executive cortex (`subject_ingress.py:63-67,
    124-126`; `executive_cortex.py:764-770,785-795`), seed worker
    (`random_chat_seed_service.py:910-914,1017-1031`), focus authority
    (`motivational_focus_v99.py:394-446`, `focus_material_authority_v100.py:111-115`),
    tutor auto_path (`auto_path.py:101-104`). **KHÔNG** vào runtime_context của
    ConversationKernel (grep `conversation_trajectory`/`trajectory` trong
    `context_assembler.py`: không tìm thấy), và kernel không giữ `host`
    (`bootstrap.py:40-54`). Để kernel đọc được phải thêm wiring mới xuyên tầng.
  - Dù có nối dây, nó vẫn trả lời sai câu hỏi: "topic còn sống" ≠ "nhịp giảng chưa xong".
    Một bài phân số nhồi trong một bubble vẫn khiến trajectory `active=True momentum cao`
    — nhưng chính nhịp đó ĐÃ nói hết ý, không cần nối.
- **Kernel phase:** `RunPhase` (`contracts.py:40-52`) chỉ có trạng thái vận hành
  (writing/delivering/waiting_user...), không mang "còn ý".

→ **Kết luận Q3:** KHÔNG có tín hiệu 'mạch chưa trọn' sẵn. Hướng 3 buộc phải **chế
heuristic mới**. Heuristic khả dĩ duy nhất mà kernel tự tính được từ dữ liệu tại chỗ là
**độ dài `turn.move.say`** (+ đếm `consecutive_self_wakes` để giới hạn) — đúng loại
"speech budget/max_sentences" mà contract và `continuation.py:41-44` tuyên bố KHÔNG làm.

### Q4. Giữ được 'nghĩ lại giữa nhịp'?

**CÓ, không đổi so với cơ chế hiện tại.**
- `handle_due_continuation` (`kernel.py:584-640`): `claim_due` lease
  (`kernel.py:594-601`); nếu không có speculative prepared thì dựng
  `ConversationEvent.continuation_due` (`kernel.py:612-616`) và gọi `handle_event(...)`
  (`kernel.py:618-623`).
- `handle_event` → `_handle_event_once` → `self.agent.decide(event=..., recent_history=...)`
  (`kernel.py:244-249`). Đây là **một lần decide() mới**: Root đọc history/receipt mới,
  không phát lại `say` đã lưu (lease không mang `say` — `contracts.py:ContinuationLease`
  chỉ có id/generation/due/breaker, docstring:4-6).
- Vậy mỗi nhịp hệ-thống-cấp vẫn là một suy nghĩ mới của Root → vẫn "nghĩ lại giữa nhịp".
  Đây là điểm mạnh thật của Hướng 3 (hơn hẳn phương án chunk một `say` có sẵn). Nhưng nó
  cũng chính là điểm khiến Hướng 3 ≈ "ép Root tự hỏi lại 'còn gì nói không?' sau mỗi
  câu" — mà việc ép đó, nếu không có tín hiệu thật, chỉ là đoán.

### Q5. Rủi ro + điều kiện dừng chuỗi

- **(a) Breaker self-wake có chặn chuỗi hệ-thống-cấp không?** CÓ, một phần.
  `schedule` truyền `parent_self_wakes`/`parent_chain_started_at` từ turn
  (`kernel.py:921-922`); mỗi lần wake `next_self_wakes += 1` và hủy khi vượt 24 hoặc
  120s (`continuation.py:98-110`). Nhưng continuation hệ-thống-cấp truyền lại metadata
  chain nên breaker **đếm xuyên nhiều nhịp** — tốt cho chống vô hạn. **Hạn chế:** 24
  nhịp vẫn là rất nhiều lời user không yêu cầu; breaker là lưới tài nguyên, không phải
  lưới "user không muốn nghe nữa".
- **(b) Runaway (Root nói hoài):** đây là rủi ro MỚI mà Hướng 3 tự tạo. Hiện tại
  `wait_user` là cách Root (và prompt) dừng tinh tế
  (`root_prompt_contract.py`: "Nếu bạn thấy ý đã trọn... hãy tự chọn wait_user/no_reply").
  Hướng 3 phủ nhận tín hiệu dừng đó, nên PHẢI có điều kiện dừng thay thế. Có hai lớp dừng
  khả dĩ, cả hai đều yếu:
  - Root tự trả `no_reply` ở nhịp continuation (prompt đã dạy:
    "Khi continuation_due trở lại... nếu chưa có gì cần nói thêm, chọn no_reply"). Nhưng
    nếu Root đáng tin ở điểm này thì Hướng 1 (để Root tự chọn may_continue) cũng đủ —
    mâu thuẫn với lý do làm Hướng 3.
  - Hệ thống đếm số lần ép (ví dụ chỉ override 1 lần, hoặc tới khi
    `len(say) < ngưỡng`). → heuristic (xem Q3/Q6).
- **(c) Khi nào hệ thống THÔI cấp lease?** Không có nguồn sự thật. Lựa chọn thực tế:
  "ép đúng 1 lần" (an toàn nhất, nhưng chỉ biến 1 bubble dài thành 2 bubble dài — không
  giải quyết bức tường chữ), hoặc "ép đến khi `say` ngắn/`presentation_blocks` rỗng"
  (heuristic độ dài trá hình).
- **(d) Latency cộng dồn:** mỗi nhịp = 1 vòng Root (log trước đo ~10-22s,
  `streaming-cadence-feasibility.md §5`) + 1 synth. Hệ thống ép nhịp → bắt buộc trả giá
  latency kể cả khi model không định nối. Có `speculative_preparer`
  (`kernel.py:925-942`, `orchestrator.py:1172-1179`) giảm nhẹ nhưng không khử.
- **(e) Preempt khi user chen giữa:** đã có. `begin_user_turn`/`_handle_event_once`
  nhánh user_turn đổi generation + `continuation.cancel_session` + discard deliveries
  (`kernel.py:170-192, 730-742`); `preempt_for_user` (`kernel.py:944-958`);
  OpenLoopStore bảo toàn ý dở (`continuation.py:164-203`). Hướng 3 tạo NHIỀU nhịp hơn →
  nhiều điểm có thể bị cắt giữa chừng hơn, nhưng cơ chế preempt hiện có vẫn áp dụng.

→ **Dừng chuỗi:** chỉ có breaker tài nguyên (24/120s) là "sẵn". Mọi điều kiện dừng theo
"đã đủ chưa" đều phải tự chế và đều là heuristic.

### Q6. Elegant/độ lớn — Hướng 3 vs Hướng 1

- **Hướng 1 (prompt, `root_prompt_contract.py`):** độ lớn **S** (sửa chữ ROOT_SYSTEM_CORE:
  câu "say mô tả đầy đủ..." và nâng "nghiêng về may_continue" thành chỉ dẫn nhịp ngắn).
  Giữ nguyên tắc "cá tính quyết nhịp" (prompt tự tuyên bố) và KHÔNG đụng cơ chế. Bias yếu
  (model có thể không tuân — bài học runtime).
- **Hướng 3 (hệ thống cấp lease):** điểm chèn cơ học nhỏ (`kernel.py:921`), NHƯNG:
  - Buộc có `_system_continuation_condition` dựa **heuristic độ dài** (Q3) → vi phạm tinh
    thần `root_prompt_contract.py` (cấm runtime tạo speech budget/max_sentences/semantic
    scheduler) và `continuation.py:41-44` (scheduler không cắt câu/không đếm sentence).
  - Thêm rủi ro **runaway** và cần điều kiện dừng tự chế (Q5b/c).
  - Nếu để tránh heuristic bằng cách "ép đúng 1 lần" thì chỉ biến 1 bubble dài → 2 bubble
    dài, KHÔNG tạo cuốn chiếu thật (bức tường chữ vẫn còn).
  - Về "elegant" theo nghĩa user ("nói một tí rồi chạy dần như Kiro"): Hướng 3 chỉ elegant
    NẾU mỗi nhịp thực sự ngắn — nhưng độ ngắn do model viết `say`, mà điều đó lại quay về
    Hướng 1 (prompt). Hệ thống cấp lease KHÔNG tự làm `say` ngắn đi.

→ **Hướng 3 không elegant hơn Hướng 1 một cách thực chất.** Vì thiếu tín hiệu 'mạch chưa
trọn' sẵn, nó sụp về heuristic độ dài — đúng thứ kiến trúc tuyên bố không làm — và kéo
theo runaway + latency. Giá trị riêng duy nhất của nó ("nghĩ lại giữa nhịp", Q4) thì
Hướng 1 cũng có sẵn khi model chọn `may_continue`, vì cùng đi qua `handle_due_continuation`.

---

## Kết luận & khuyến nghị

1. **Hệ thống cấp lease độc lập được không?** CÓ về cơ học, tại **một điểm duy nhất**:
   `kernel.ConversationKernel.settle_delivery`, đổi `after=turn.move.after`
   (`kernel.py:921`) thành một `effective_after` nâng `WAIT_USER`→`MAY_CONTINUE`. Không
   cần sửa `continuation.py` (schedule đã thuần theo tham số).

2. **Có tín hiệu 'mạch chưa trọn' sẵn không?** KHÔNG. Contract move cấm field nhịp
   (`contracts.py:1-11,62-78`); `presentation_blocks` là proxy sai và kernel không đọc;
   `conversation_trajectory` là tín hiệu chủ đề xuyên-lượt, không tới kernel và trả lời
   sai câu hỏi (`conversation_trajectory.py:106-170`, `auto_path.py:100-101`,
   `context_assembler.py` không có). ⇒ Hướng 3 **bắt buộc dựa heuristic** (gần như chắc
   là độ dài `say` + đếm lần ép).

3. **Điểm sửa chính xác + độ lớn:** `kernel.py:916-924` + một hàm điều kiện mới + (nếu
   dùng trajectory) wiring host→kernel + inject trajectory vào runtime_context. Độ lớn
   **M→L** và chạm vùng contract nhạy cảm, so với Hướng 1 độ lớn **S** chỉ sửa prompt.

4. **Giữ 'nghĩ lại giữa nhịp'?** CÓ (`kernel.py:584-640` → `agent.decide` mới). Nhưng ưu
   điểm này Hướng 1 cũng hưởng qua cùng đường continuation.

5. **Rủi ro + dừng chuỗi:** breaker 24/120s (`continuation.py:50-52,98-110`) chỉ chống vô
   hạn, không chống "nói nhiều hơn user muốn"; Hướng 3 tự tạo rủi ro runaway và cần điều
   kiện dừng heuristic; latency cộng dồn; preempt user đã có sẵn.

6. **Khuyến nghị cuối: chọn Hướng 1 (prompt), KHÔNG làm Hướng 3.** Lý do: Hướng 3 không
   có tín hiệu thật nên sụp về heuristic độ dài — đúng thứ kiến trúc cấm — mà vẫn không
   tự làm `say` ngắn đi (phần quyết định độ elegant vẫn nằm ở model/prompt). Nếu phiên
   live chứng minh prompt không đủ, phương án mạnh hơn **đúng kiến trúc** là
   **soft-forcing ở `agent.py` (quanh nhánh finalize)**: khi `say` dài + `after=wait_user`
   + chưa ép lần nào, chèn một directive vào `tool_results` gợi ý Root chia nhịp và chọn
   `may_continue`, rồi **để chính Root finalize** (fail-soft nếu model vẫn gộp). Cách này
   giữ "model/cá tính quyết nhịp" (không phải hệ thống phủ nhận ý định dừng sau lưng
   model), khác hẳn Hướng 3 là override cơ học ở `settle_delivery`.

**Phải xác minh bằng phiên live** (bài học runtime + §Q5): vấn đề là lựa chọn của model
(`wait_user` + `say` dài), test fixture không tái hiện. Cần log có field `after` thực tế
của move (hiện KHÔNG log — `agent.py` chỉ log loại action `[root-agent] step=... action=`,
không log `after`; có thể thêm một dòng log loại `after` để quan sát, không serialize nội
dung) và nhiều `[public-text] sent ... chars=<nhỏ>` nối nhau qua `continuation_due`.

---

## Phân tầng bằng chứng
- *Cơ chế sẵn tái dùng (mạnh):* continuation lease + `handle_due_continuation` +
  speculative prepare + breaker + preempt (`continuation.py:82-150,98-110,164-203`,
  `kernel.py:584-640,916-942,944-958`, `orchestrator.py:1172-1179,1247-1251`). Giữ
  'nghĩ lại giữa nhịp' và hợp đồng text-chờ-voice.
- *Phải xây mới (yếu hơn):* tín hiệu 'mạch chưa trọn' — KHÔNG tồn tại
  (`contracts.py:1-11,62-78`); nếu làm Hướng 3 thì là heuristic độ dài, mâu thuẫn
  `continuation.py:41-44` và `root_prompt_contract.py` (cấm speech budget/max_sentences/
  semantic scheduler); + wiring trajectory→kernel nếu định dùng trajectory
  (`context_assembler.py` không có, `bootstrap.py:40-54` kernel không giữ host).
- *Đọc source (file:symbol):* `continuation.py` ContinuationLeaseScheduler.schedule
  (82-150), WAIT_USER cancel (93-95), breaker const (50-52) + check (98-110), delay
  (124), self-description "không cắt câu/không giới hạn sentence" (41-44), docstring
  re-evaluate (class docstring 4-6), cancel_session (152-162), claim_due (227-283),
  peek (205-225), open-loop preserve (164-203);
  `kernel.py` KernelTurn (34-53), settle_delivery (896-942) + schedule call (916-924) +
  after=turn.move.after (921), handle_due_continuation (584-640) + handle_event call
  (618-623), _handle_event_once decide (244-249), KernelTurn build continuation flag
  (307-316), preempt_for_user (944-958), begin_user_turn cancel+discard (730-742),
  no presentation_blocks read (grep: none);
  `contracts.py` docstring cấm floor/beat/quota (1-11), NextConversationMove fields
  (62-78), ConversationAfter (34-39), RunPhase (42-52), ContinuationLease (fields, no say);
  `agent.py` NEXT_MOVE_SCHEMA/presentation_blocks schema (37-56), finalize move trực tiếp
  (nhánh kind=="move"), log action loại (không log after);
  `conversation_trajectory.py` ConversationTrajectory fields (106-170), observe_user_turn
  depth (330-336), observe_assistant_commit awaiting_user_answer=asks (420-470), snapshot
  decay (203-221);
  `root_prompt_contract.py` ROOT_SYSTEM_CORE: bias may_continue + "cá tính quyết nhịp,
  không quota" + cấm floor/beat/speech budget/max_sentences/desired_shape/semantic
  scheduler (đoạn cuối);
  `tutor/auto_path.py` depth là evidence không phải governor (100-104);
  `subject_ingress.py` trajectory vào Subject runtime_context (63-67,124-126);
  `executive_cortex.py` trajectory từ frame + courtesy/awaiting gate (764-770,785-795);
  `bootstrap.py` kernel wiring, không truyền host cho kernel (19-60);
  `orchestrator.py` _run_v12_signal build runtime_context (1093-1160), handle_due
  (1180-1186), lease tick driver (1247-1251), speculative prepare (1172-1179).
- *Giới hạn điều tra:* log live `eris_run_20261101_134229.txt` nằm NGOÀI workspace
  (`C:\Users\Gtvkun\Documents\eris\logs\`) nên grep workspace không với tới; dùng lại
  trích dẫn đã xác minh trong `streaming-cadence-feasibility.md` (bubble chars=1259,
  không có continuation nối sau lượt phân số). Không có log field `after` để xác nhận
  trực tiếp Root chọn `wait_user`; suy ra từ việc không có nhịp nối. Chưa chạy live để
  xác nhận; mọi kết luận là đọc source + đối chiếu báo cáo trước.
