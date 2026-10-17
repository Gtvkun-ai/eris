# Design review: tách "true state" khỏi "derived prompt" cho Root conversation session

Ngày review: 2026-10-16. Reviewer: design-review subagent (đọc fresh, không mang
context của tác giả). Tài liệu được review: `.agents/tasks/eris-root-session-redesign/design.md`
(bản revise lần 2, đã xử lý 12 finding của vòng trước, có §11 ghi lại).

Phương pháp: đọc toàn bộ design, đối chiếu với bốn nguồn bằng chứng bắt buộc
(lessons Mục 1/8/9, token-growth-report, degrade-and-mute-report, AGENTS.md),
và **spot-check source** tại các điểm design trích dẫn trực tiếp để xác nhận
file+line là thật, không chỉ tin lời design.

**Verdict: APPROVED** (0 HIGH, 0 MEDIUM; chỉ các finding NIT).

Lý do ngắn: design giữ đúng mọi ràng buộc brief kiểm cụ thể — true state tách
khỏi derived prompt (projector re-render, reconcile-resend bất khả thi về cấu
trúc), STATE shape cụ thể (TurnRecord với turn_id ổn định + status), projector
pure/idempotent/bounded với K có căn cứ, full-Self-no-top-k sau cache boundary
với Option A (bác bỏ có lý do) + Option B, premise messages.go dev≠portable +
chưa biết cây build + chưa xác minh prefix cache upstream, mọi guard an toàn
giữ nguyên, scope đúng, có verification plan + risks. Các điểm còn lại là NIT:
chúng không làm sai thiết kế mà chỉ cần implementer biết để không hiểu nhầm một
câu mô tả hoặc một con số.

---

## Verified assumptions (đã đọc source, khớp design)

Mỗi dòng dưới đây là một claim design gắn **[đọc source]**, tôi đã mở file xác
nhận là đúng:

1. **Gateway merge same-role + join phẳng (dev tree).**
   `tools/whale2api/internal/prompt/messages.go` — `MessagesPrepareWithThinking`
   gộp message cùng role liền nhau (`merged[len-1].Text += "\n\n" + msg.Text`,
   ~dòng 41-44) rồi `strings.Join(parts, "")` (~dòng 72). Dev tree **không** có
   `outputIntegrityGuardPrompt`. Khớp design §0.1, §3.2 (lưu ý wire ≤ bound),
   §3.4 (role carry = system để tránh merge).

2. **Gateway tạo session + auto-delete mỗi request.**
   `nonstream.go` `startCompletionAttempt` gọi `ds.CreateSession(...)` fresh mỗi
   lần (~dòng 82), build `stdReq.CompletionPayload(sessionID)`;
   `handler_chat.go` `ChatCompletions` có `defer func(){ h.autoDeleteRemoteSession(...) }`
   (~dòng 34-39). Khớp design §0.2, §4.1.

3. **Cơ chế `parent_message_id` cho follow-up trong cùng session (bằng chứng B1).**
   `shared/empty_retry.go` `ClonePayloadForAssistantRetry` set
   `clone["parent_message_id"] = parentMessageID` với chú thích "submitted as a
   follow-up turn in the same DeepSeek session" (~dòng 34-47). Khớp design §4.2
   B1 — cơ chế nối tiếp đã tồn tại, chỉ đang dùng cho retry. (Xem NIT-2 về sắc
   thái design chưa nói hết.)

4. **`self._messages` append-only, 2 msg/lượt, chỉ reset khi lỗi hoặc `not _fits`.**
   `root_session.py` — init `self._messages = []`; `_prime` set
   `self._messages = messages + [assistant ack]`; trong `ask`,
   `messages = self._messages + [user step]` rồi `self._messages = messages +
   [assistant]`; nhánh `not self._fits(...)` gọi lại `_prime`. Khớp design §1.1.

5. **`_changed(previous, current)` chỉ trả field mới/đổi, tombstone
   `__erased_from_self`/`__value_now_null`; baseline cũ = `self._self` cập nhật
   mỗi lượt.** Khớp design §1.2, §2.3 (finding #1).

6. **Overlap suffix/prefix trên `raw_content`; `overlap==0` + previous →
   `recent_public_history_reconcile = history` (nguyên cửa sổ).** `ask` so
   `item.get("raw_content", item.get("content"))`, vòng `for length in range(...)`,
   nhánh else gán `history_key = "recent_public_history_reconcile"`,
   `new_history = history`. Khớp design §1.2.

7. **`recent_public_delivery_updates` chỉ gửi status đổi so với
   `self._last_delivery_status`.** Khớp design §1.2, §3.3 (lý do bỏ kênh thứ hai).

8. **`_fits` nới cap localhost DeepSeek lên `max(cap, ERIS_ROOT_SESSION_PROMPT_CAP_TOKENS=90000)`.**
   Khớp design §1.1, §1.4.

9. **`_chat_history_for_llm` chèn `context_note` vào `content`, giữ `raw_content`
   gốc; nhãn pending/cancelled/failed đúng chuỗi.**
   `prompt_context_builder.py` — khối `status in {"pending","cancelled","failed"}`
   gán `content = f"{context_note} {content}"`, `entry["raw_content"] =
   str(item.get("content",""))`. Ba nhãn đúng y chuỗi design §3.3 trích. Khớp.

10. **`compress_system_message` xóa hẳn block "PrivateMind speech bias", "Nhật
    ký nội tâm hiện tại"/"recently_resolved"/"Đã nguôi gần đây"; thay persona
    `"Bạn là ERIS"/"Bạn là Eris"` (>250 ký tự) bằng đoạn generic.**
    `token_budget.py` khớp từng điều kiện. Khớp design §1.4, §7.

11. **`_system_block_priority`: hard markers (turnframe/responsecontract/
    `[grounding]`/`[dynamic_policy]`/latest visible)=100; medium
    (state_style/capability/voice policy)=60; optional (private mind/
    thought_stream/nhật ký nội tâm/inner diary/recently_resolved/content seed/
    ambient)=10.** Khớp chính xác design §1.4.

12. **`enforce_prompt_cap` thứ tự: bảo vệ system + 5 lượt gần nhất → bỏ history
    cũ → `compress_system_message` → `_truncate_to_cap`.** Khớp design §1.4.

13. **Router pass-through không cắt cửa sổ.** `model_router.py`
    `invoke_structured_worker` → `create_chat_completion(messages=[dict(m) for m
    in conversation_messages] if conversation_messages is not None else [system,
    user])`. Không có bước cắt window. Khớp design §1.3, §1.5.

14. **Fallback one-shot khi `ask` trả None.** `agent.py` — `if raw is None:
    raw = invoke(... schema=ROOT_BATCH_STEP_SCHEMA, name="eris_root_conversation_step_v12")`.
    Khớp design §3.5-overflow nhánh (a), §5.

15. **`_prime` trả False (→ None lên caller) khi `not self._fits` nguyên khối
    Self.** `_prime` có `if not self._fits(client, messages): return False`.
    Khớp design §3.5-overflow nhánh (a).

16. **Số dòng appendix nằm trong khoảng ±1 như design tuyên bố.** Các block
    (`_changed`, `_shrink_system_by_blocks`, `_truncate_to_cap`,
    `compress_system_message`, `enforce_prompt_cap`, `root_session_prompt_cap`)
    xuất hiện đúng thứ tự và gần đúng số dòng design nêu. Design §11 đã tự
    re-verify; spot-check của tôi không thấy drift đủ lớn để chặn.

---

## Unverified / Wrong assumptions (design chưa chốt hoặc mô tả chưa chính xác)

### Design TỰ gắn [chưa xác minh] (đã xử lý đúng — không phải lỗi design)

Các điểm này design chủ động đánh dấu chưa xác minh và chuyển thành premise
step-zero hoặc rủi ro, đúng tinh thần AGENTS.md:

- **Binary gateway build từ cây dev hay portable** (§0.1) — design bắt xác định
  trước khi code phần gateway. Tôi **không** thể xác minh (binary nằm ngoài
  workspace, trong container Compose). Xử lý đúng.
- **DeepSeek Web có hỗ trợ prefix caching giảm giá hay không** (§0.2, §4.1) —
  design kết luận "coi là không" và đặt Option B làm đường chính. Xử lý đúng.
- **Session Web sống bao nhiêu lượt; SessionGuard V3 hủy chuỗi khi reply lỗi**
  (§4.2 B1, §8) — design để B1 ở giai đoạn 2, lợi ích chính (§3) không phụ thuộc.
  Xử lý đúng.
- **Nguyên nhân chính xác phá overlap trên HEAD `c3805cc6`** (§1.2) — design nêu
  hai ứng viên (window trượt / đổi tập statuses), đánh dấu [chưa xác minh đầy đủ],
  và lập luận state mới xóa reconcile bất kể nguyên nhân. Xử lý đúng.

Tôi **xác nhận** một quan sát source củng cố lập luận §1.2: `ask` thật sự so
overlap trên `raw_content`, và `_chat_history_for_llm` giữ `raw_content` nguyên
khi receipt flip. Vậy giả thuyết "flip làm đổi content phá overlap" **không**
đúng ở tầng `raw_content` — đúng như design nói nguyên nhân cũ cần re-verify.
Điều này không hạ cấp design; nó khẳng định việc design không phụ thuộc chốt
nguyên nhân cũ là lựa chọn đúng.

### Mô tả chưa chính xác trong design (→ các NIT bên dưới)

- **Finding #11 / §2.1 phụ lục nói builder "tái sinh id mỗi build".** Đọc
  `_chat_history_for_llm` thực tế: `if not item.get("history_id"): item["history_id"]
  = f"history:{uuid4}"` — chỉ sinh **khi thiếu**, và gán **vào chính item của
  `self.chat_history`** (mutate list bền), nên trong một process id **ổn định**
  qua các lần build. Vậy rủi ro "mỗi build ra id mới" mà finding #11 ngụ ý
  **không tồn tại trong một process**. Rủi ro thật chỉ là **qua reload process**
  (chat_history dựng lại không kèm id). Fix của design (state giữ id) vẫn đúng và
  vẫn đáng làm cho case cross-process — nên đây là NIT về cách diễn đạt, không
  phải lỗi thiết kế. Xem NIT-1.

---

## Findings

### NIT-1 — §2.1 / finding #11 / phụ lục: mô tả "builder tái sinh id mỗi build" không khớp code hiện tại

**Vấn đề.** Design (§2.1, finding #11, và phụ lục dòng
"prompt_context_builder.py:329-331 history_id tái sinh nếu thiếu") trình bày việc
builder "tái sinh id mỗi build" như rủi ro mà fix nhắm tới. Code thực tế chỉ sinh
id **khi thiếu** và persist vào item của `self.chat_history`, nên id ổn định
trong một process. Rủi ro thật chỉ xảy ra khi `chat_history` được dựng lại ở
**process mới** mà không mang theo id cũ. Diễn đạt hiện tại có thể khiến
implementer tin builder đang hỏng và "sửa" nhầm chỗ.

**Fix cụ thể.** Sửa một câu ở §2.1 và finding #11 thành đúng ngữ nghĩa code:
> `_chat_history_for_llm` sinh `history_id` **chỉ khi thiếu** và mutate vào
> `self.chat_history` (id ổn định trong một process). Rủi ro cần guard là id
> **không bền qua reload process** khi history dựng lại không kèm id. Vì vậy
> state sở hữu `turn_id`: nhận `history_id` sẵn có nếu đủ, tự sinh một lần nếu
> thiếu, và **không** phụ thuộc builder để giữ ổn định qua process.

Giữ nguyên fix và `test_turn_id_stable_on_reload` (§6.2) — test này đúng, chỉ cần
mô tả động cơ cho khớp code.

### NIT-2 — §0.2 / §4.1 phát biểu tuyệt đối "Web KHÔNG giữ context giữa các request", nhưng bằng chứng B1 (§4.2) cho thấy follow-up cùng session là khả thi

**Vấn đề.** §0.2 nói "upstream Web KHÔNG giữ context giữa các request". Nhưng
chính design §4.2 trích `ClonePayloadForAssistantRetry` set `parent_message_id`
để "submit lượt nối tiếp trong CÙNG session DeepSeek" — tức transport Web **có**
cơ chế context server-side sống qua một follow-up, chỉ là gateway hiện **chủ
động auto-delete** sau mỗi request Eris. Hai câu đọc liền nhau có vẻ mâu thuẫn.
Thực chất không mâu thuẫn (auto-delete là lựa chọn của gateway, không phải giới
hạn upstream), nhưng câu §0.2 ở dạng tuyệt đối dễ bị hiểu là "upstream không thể
giữ context" → có thể khiến implementer loại B1 sớm.

**Fix cụ thể.** Đổi câu tiêu đề §0.2 cho chính xác:
> Upstream DeepSeek Web **có** session server-side (follow-up qua
> `parent_message_id`), nhưng gateway hiện **auto-delete session sau mỗi
> request** (`handler_chat.go:34-39`), nên **ở transport hiện tại** không có
> context sống qua các request Eri. Prefix cache dựa vào session bền do đó chưa
> khả dụng **cho tới khi** B1 tắt auto-delete và tái dùng session.

Điều này làm §0.2 và §4.2 nhất quán và giữ cửa cho B1 đúng như §4.3 giai đoạn 2.

### NIT-3 — §6.1 ngưỡng token tuyệt đối (35k–45k) chưa chốt, phụ thuộc đo Self thật

**Vấn đề.** §6.1 đặt PASS/FAIL một phần theo con số tuyệt đối "~35k-45k
token/lượt", đồng thời tự nói "chốt lại ngưỡng tuyệt đối sau khi đo Self thật".
Hai ngưỡng tương đối (lượt 20 ≤ lượt 5 +10%; không nhảy >15% tại cancelled; phẳng
±5% sau warm-up) là **đủ** để chứng minh mục tiêu (chặn phình tuyến tính + xóa
nhảy-bậc-reconcile) **độc lập** với con số tuyệt đối. Để con số tuyệt đối trong
tiêu chí pass có thể gây fail giả nếu Self thực tế lệch ước lượng chars/3.

**Fix cụ thể.** Giữ ba ngưỡng tương đối làm tiêu chí PASS/FAIL **chính thức**;
hạ "35k-45k" xuống thành *kỳ vọng tham khảo để sanity-check*, không phải điều
kiện fail. Thêm một dòng: "Nếu đường token phẳng (±5% sau warm-up) nhưng mức
tuyệt đối lệch ước lượng, cập nhật kỳ vọng theo Self đo được, **không** đánh fail
chỉ vì sai mức tuyệt đối."

### NIT-4 — §3.4 identity-carry mặc định "chỉ đếm số lượt" có thể dưới mức brief/degrade-report cảnh báo mất mạch

**Vấn đề.** §3.4 chốt mặc định tối giản: carry **chỉ một số nguyên đếm số lượt
bị loại**, nâng mức chỉ khi đo thấy mất mạch. degrade-report §7 và lessons Mục 2
cảnh báo đừng để window quá ngắn gây mất mạch; token-growth khuyến nghị 1 nói
dùng "identity ổn định cho lượt cũ". Một con số đếm thuần có thể không đủ "identity
ổn định" theo tinh thần đó. Đây là lựa chọn thiết kế hợp lệ (bounded, pure,
có đường nâng cấp theo số đo), nên **không chặn**, nhưng cần nói rõ tiêu chí
quyết định nâng mức để implementer không phải tự đoán.

**Fix cụ thể.** Thêm một câu tiêu chí ở §3.4: "Nếu §6.1/§6.3 (hoặc đánh giá chất
lượng live) cho thấy Root mất tham chiếu tới chủ đề/giao kèo đã rời window, nâng
carry lên **dòng đầu rất ngắn của ≤3 turn gần ranh giới** (vẫn phái sinh thuần,
không gọi LLM). Ngưỡng kích hoạt nâng mức: Root nhắc lại/hỏi lại thông tin đã có
trong lượt vừa rời window." Giữ default đếm-số-nguyên cho giai đoạn 1.

---

## Đối chiếu với checklist brief (mọi mục PASS)

- **True state ≠ derived prompt; reconcile-resend bất khả thi (không phải vá):**
  PASS. §2 bỏ `self._messages`; §3 projector re-render từ `turns`; §3.6 + §5 bỏ
  hẳn `recent_public_history_delta/reconcile`. Không còn nhánh reconcile để gãy.
- **STATE shape cụ thể (turn records + stable id + delivery status) thay
  `self._messages`:** PASS. `RootSessionState{self_ref, turns[TurnRecord], ...}`,
  `TurnRecord{turn_id, role, content, delivery_id, status, kind}`, §2.1 chốt
  turn_id ổn định qua status-flip và reload.
- **Projector pure-function, window K có căn cứ, idempotent, size-bounded:**
  PASS. §3.1 chữ ký + hợp đồng pure; §3.2 K=12 (24 turn thô) có căn cứ từ
  `recent_public_history[-32:]` + `limit=16` + audit `public_turns=16`, env-tunable;
  §3.6 + test §6.2 idempotent & bounded trên list tầng Eris (wire ≤ bound, finding #5).
- **Full Self no top-k lần đầu + cache boundary + Option A AND Option B + nêu
  rõ messages.go đổi gì:** PASS. §2.2 `content_json` nguyên văn `_read_self`;
  §4.1 Option A bác bỏ **có lý do** (transport Web); §4.2 Option B (B1 session
  bền + B2 prefix store), nêu rõ handler_chat.go + messages.go + CompletionPayload
  `parent_message_id` cần đổi.
- **Premise messages.go dev≠portable + xác định cây build + prefix cache
  upstream + alternative:** PASS. §0.1 (dev≠portable, SHA khác, phải xác định
  binary trước khi code), §0.2 (đã đọc source create+auto-delete; alternative =
  platform API nếu chuyển).
- **Giữ mọi guard an toàn (grounding/action-claim/secret-redaction/language/
  single-speaker, TurnFrame/ResponseContract/[grounding]/[dynamic_policy]):**
  PASS. §7 — guard nằm ngoài `RootConversationSession`; projector không chạm;
  hard markers=100 giữ nguyên; compress làm lưới cuối không xóa.
- **Scope đúng + 'mất tiếng do preempt' out of scope:** PASS. §9 xác nhận
  preempt/backchannel out of scope (degrade-report §3.5).
- **File+line cho mọi claim + tách [đọc source] / [giả định thiết kế]:** PASS.
  Mọi dòng gắn nhãn; phụ lục liệt kê file+line; §0 phân biệt [đọc source] vs
  [chưa xác minh]. (NIT-1 là một chỗ mô tả chưa khớp, không phải thiếu nhãn.)
- **Verification plan (token before/after, idempotency/bound, reconcile gone) +
  risks/tradeoffs short-window:** PASS. §6.1-6.4 đầy đủ; §8 risks có mục window
  ngắn mất context + B1 chưa xác minh + token Self upstream vẫn re-count.

---

## Kết luận

Design đã ở trạng thái implementable. Bốn finding đều là NIT (mô tả/ngưỡng/mặc
định), không có HIGH/MEDIUM. Theo quy tắc đếm cơ học: 0 HIGH + 0 MEDIUM →
**APPROVED**. Khuyến nghị tác giả sửa bốn NIT khi tiện (nhất là NIT-1 và NIT-2
vì chúng chạm vào tính chính xác của mô tả code/transport mà implementer sẽ dựa
vào), nhưng không chặn chuyển sang code.
