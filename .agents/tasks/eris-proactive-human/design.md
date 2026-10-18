# Thiết kế: Eris chủ động hơn, con người hơn

Mục tiêu sản phẩm (user chốt): một hướng thống nhất khiến Eris (a) tự mở một
mạch dạy-có-kế-hoạch + mô hình hoá người học khi nhận ra user đang học, (b) giữ
nhịp hội thoại chủ động ở mức hợp lý thay vì luôn chờ user, (c) phản ứng tức thì
và "con người" khi user bối rối ("chưa hiểu / là sao") — hỏi chỗ kẹt / đổi cách
giải thích thay vì giảng lại dài hơn. Tất cả KHÔNG được làm phẳng cá tính (hài
khô, trêu nhẹ, tự giễu, quan điểm riêng — docs mục 1).

Phạm vi: thay đổi nhỏ, KHÔNG refactor lớn, KHÔNG viết lại logic adapt/BKT, KHÔNG
đụng scheduler trừ khi có lý do cụ thể (không có).

Stack khoá sau khi duyệt: Python runtime hiện có (`src/runtime/**`), learning
kernel deterministic (`learning_core/*`), tutor cognition (`tutor/*`),
conversation V12 (`conversation/*`), `ai_orchestrated/orchestrator.py`. Không
thêm dependency mới, không thêm process/lane mới.

---

## PHẦN 0 — Chẩn đoán đã kiểm chứng lại trên code HIỆN TẠI (worktree)

Mọi dòng dưới đây đã đọc trực tiếp trong
`c:/Users/Gtvkun/Documents/GitHub/eris/.worktrees/proactive-human/src/runtime`.
Ký hiệu [XÁC NHẬN] = đúng như report cũ; [ĐÍNH CHÍNH] = khác report, đã điều
chỉnh thiết kế theo code thật.

1. **[XÁC NHẬN] `register_path`/`activate_path` không có caller production.**
   `learning_core/service.py:117` `register_path`, `:122` `activate_path`. Grep
   `register_path|activate_path` trong `src/**` chỉ trả về hai test
   (`test_long_term_learner_v2.py:37/41`, `test_tutor_executive_v1.py:38/39`) và
   chính service. KP khởi tạo `self._active_path_id = ""` (`service.py:107`).
   → Production không bao giờ có path active.

   **[ĐÍNH CHÍNH nhỏ]** Report nói còn một CLI `src/tools/learner_simulation.py`
   gọi hai hàm này. Trong worktree HIỆN TẠI grep `register_path|activate_path`
   dưới `src/tools/**` trả về **0 kết quả** — CLI đó không còn là caller. Không
   ảnh hưởng kết luận (vẫn không có caller production), nhưng ghi lại để không
   dựa vào một call-site đã biến mất.

2. **[XÁC NHẬN] `tutor/executive.py::plan_next_move` thoát sớm khi không có path.**
   `executive.py:89-91`: `path = self.learning.active_path(); if path is None:
   return None`; `next_tutor_step` cũng trả None nếu không path (`service.py:146`,
   `:150-151`). `observe_response` cũng `if path is None: return None`
   (`executive.py:155-157`). → Toàn bộ tutor cognition im khi chưa có path.

3. **[XÁC NHẬN] `_prepare_pedagogical_turn` (System 2) là dead code + mặc định tắt.**
   `orchestrator.py:498` chỉ có *định nghĩa*; grep `_prepare_pedagogical_turn`
   trong `src/**` không có call-site nào khác. Gate `_pedagogy_enabled` đọc
   `pedagogy.enabled` default False. → System 2 không chạy.

4. **[XÁC NHẬN] continuation lease theo `after`.** `conversation/continuation.py`
   `schedule()`: `if after == WAIT_USER: self.cancel_session(sid); return None`
   (dòng ~85-87); chỉ `CONTINUE_SELF`/`MAY_CONTINUE` arm lease (delay 0.15s /
   1.2s). Đã có breaker tài nguyên sẵn: `max_consecutive_self_wakes=24`,
   `max_chain_seconds=120.0` (constructor). → Cơ chế giữ nhịp CÓ sẵn; vấn đề là
   Root luôn chọn `wait_user`.

5. **[XÁC NHẬN] system prompt bảo Root "im lặng hợp lệ" + cấm `max_sentences`.**
   `conversation/agent.py::_system_prompt`: "...với autonomous/continuation, im
   lặng là lựa chọn hợp lệ." và câu cuối "Không tạo floor, beat, agenda, arc,
   exposure, question debt, speech budget, max_sentences, desired_shape...".

6. **[ĐÍNH CHÍNH QUAN TRỌNG] confusion KHÔNG phải "chỉ ảnh hưởng lượt sau".**
   Report cũ nói `conversation_handoff.observe_user_turn` chạy write-back SAU
   lượt. Đọc lại luồng V12 thực tế trong `orchestrator.py::_run_v12`:
   - dòng ~725-740: `ensure_conversation_observation_bridge(host)
     .observe_user_turn(...)` chạy **đầu lượt**, trước khi dựng context.
   - bridge gọi `conversation_handoff.observe_user_turn` (observation_bridge.py:72)
     → state handoff (`repair_needed`, `user_stance="confused"`) được cập nhật
     NGAY trong lượt hiện tại.
   - SAU đó `orchestrator.py:~825` gọi
     `context_assembler.assemble(...)` → rồi `kernel.handle_event` (Root quyết).

   Nghĩa là tín hiệu confusion của CHÍNH lượt này ĐÃ có sẵn trước khi Root suy
   nghĩ. Vấn đề thật: **`context_assembler.assemble` KHÔNG đọc handoff
   confusion vào payload Root.** Nó chỉ bơm `discourse_context` (continuity/
   ledger) và `conversation_status.latest_observation` — mà `latest_observation`
   lấy từ post_observer của lượt TRƯỚC (StateReducer), nên đó mới là đường "trễ
   một nhịp". Đồng thời `expression.py` chỉ dùng `repair_needed` để chọn preset
   sân khấu `short_direct` (cue frontend, không ép nội dung).

   → Hệ quả thiết kế: KHÔNG cần đổi thời điểm observe. Chỉ cần cho
   `context_assembler` đọc handoff state hiện tại và đưa một tín hiệu confusion
   *same-turn* vào `runtime_context` để Root thấy ngay. Đây là thay đổi nhỏ
   hơn và đúng hơn đề xuất cũ.

7. **[XÁC NHẬN] `learner_continuity_snapshot` trả `{}` khi không path.**
   `tutor/learner_context.py` trong `learner_continuity_snapshot`: `path =
   learning.active_path(); if path is None: return {}` (~dòng 110-112).
   `context_assembler.py:221-227` bơm `learner_continuity` vào context Root. →
   Ở production Root luôn nhận `learner_continuity = {}`.

8. **[XÁC NHẬN + làm rõ] đường evidence học ĐÃ nối đủ, chỉ thiếu path.**
   - `TutorCapability.observe_delivery_receipt` (capabilities/tutor.py:142) gọi
     `executive.commit_delivery(...)` và set `_waiting_for_response =
     receipt.successful and _pending_expects`.
   - Receipt đến từ `public_output_runtime.py:153-160`: nó lặp
     `meta["capabilities"]` rồi gọi `observe_delivery_receipt` trên
     `{name}_capability`.
   - `meta["capabilities"]` được nạp ở `conversation/delivery_adapter.py:291`
     từ `rendered.metadata["root_capabilities_used"]`.
   - `root_capabilities_used` được `runtime_writer.py:490` lấy từ
     `registry.invocations_for(event_id)` — tức chính các capability Root đã gọi
     lượt đó (ghi qua `agent.py::_invoke_capability → record_invocation`).
   → Khi Root gọi `tutor.advise` và move được delivered thành công, receipt tự
   chảy về tutor, `_waiting_for_response=True`; lượt kế `tutor.advise` mặc định
   `response_to_previous=True` → `observe_response` → chấm → commit evidence →
   BKT/mastery cập nhật. **Toàn bộ vòng evidence đã hoạt động; mắt xích đứt duy
   nhất là không có path để `plan_next_move` chạy.**

**Kết luận Phase 0:** "bộ não học" (~80%) + vòng evidence + đường phơi bày cho
Root đều đã có. Thiếu đúng ba công tắc: (a) tạo/activate path từ hội thoại; (b)
chính sách Root chọn `may_continue`; (c) đưa confusion same-turn vào payload
Root. Cộng một ràng buộc: nới lớp tutor để không gọt cá tính.

---

## CAPABILITY (a) — Tự mở mạch dạy-có-kế-hoạch + learner model

### Quyết định kiến trúc
Dùng **Hệ 1 (LearningService + TutorExecutive) làm xương sống** vì learner model
(BKT, hypothesis, adaptive_policy, review) và vòng evidence đã nằm ở đó và đã
nối tới Root. Chỉ **mượn `TeachingPlanBuilder` của Hệ 2** để model đề xuất
knowledge points, rồi map sang `learning_core.contracts`. KHÔNG bật System 2
(`pedagogy.enabled` giữ False), KHÔNG nối call-site cho `_prepare_pedagogical_turn`.
Lý do: Hệ 2 có learner model mỏng hơn (comprehension/concept episode), còn mục
tiêu user là "mô hình hoá người dùng" sâu — đúng thế mạnh Hệ 1.

### Thành phần mới: path builder từ hội thoại
Thêm một hàm thuần (không I/O ngoài LearningService) nối "ý định học" → path:

- File mới: `src/runtime/tutor/auto_path.py`
  - `propose_learning_path(router, *, topic_text, recent_history) ->
    LearningPath | None`:
    1. Gọi `TeachingPlanBuilder(router).build({"explicit_plan_request": True,
       "current_turn": topic_text, "recent_public_history": [...]})` →
       `TeachingPlan | None` (đã có sẵn: `pedagogical_plan_builder.py:77`,
       `model_router.plan_teaching_episode` tại `model_router.py:1645`).
    2. Map `TeachingPlan.concepts[i]` → `KnowledgePoint(kp_id=concept.concept_id,
       title=concept.objective[:240], kp_type="concept",
       description=concept.description, prerequisites=concept.prerequisite_ids)`.
    3. Dựng `LearningPath(path_id=_stable("autopath", global_goal), title=...,
       goal=global_goal, knowledge_points=(...), source="eris_auto")` —
       `source="eris_auto"` đã được contract cho phép (`contracts.py` LearningPath).
    4. Số KP bám ràng buộc `TeachingPlan`: builder đã ép **3–8 concept**
       (`pedagogical_contracts.py:200-203` raise nếu <3 hoặc >8). Vậy path tự
       tạo có 3–8 KP. Fail-closed: builder trả None (model lỗi/timeout) →
       `propose_learning_path` trả None, KHÔNG tạo path. (Không cần tự cắt về
       1 KP; `LearningPath` chỉ cần ≥1, builder đã bảo đảm ≥3.)
  - `maybe_autostart_path(host, *, user_text, recent_history, now) -> bool`:
    kiểm ngưỡng kích hoạt (xem quyết định i), nếu đạt thì
    `propose_learning_path(...)` → `learning.register_path(path)` +
    `learning.activate_path(path.path_id)`. Idempotent: nếu `active_path()` đã có
    thì trả False ngay (không chồng path).

### Điểm nối trong orchestrator
- `src/runtime/ai_orchestrated/orchestrator.py::_run_v12`: **trước** khi gọi
  `context_assembler.assemble` (để `learner_continuity` kịp không rỗng ngay lượt
  mở lớp), thêm một nhánh gọi `tutor.auto_path.maybe_autostart_path(host,
  user_text=..., recent_history=history, now=cycle_start)` trong `try/except`
  boundary (dùng `_orchestrator_boundary_note` như các block khác). Chỉ chạy khi
  `getattr(host, "learning_service", None)` và `getattr(host, "ai_model_router",
  None)` tồn tại. Không làm sập lượt chat nếu builder lỗi.
- KHÔNG tự gọi `tutor.advise` ở đây — vẫn để **Root** quyết gọi tool. Khi path
  đã active, `learner_continuity` có `active_path_id`, và system prompt (sửa ở
  mục dưới) hướng Root cân nhắc gọi `tutor.advise` khi user còn trong chủ đề đó.

### Evidence/dữ liệu cho learner model (không viết lại adapt)
Không đổi `adaptive_policy.py`, `belief_model.py`, `executive.observe_response`.
Vòng đã nối (Phase 0 mục 8). Việc duy nhất phải đảm bảo: khi Root gọi
`tutor.advise` lần đầu sau khi path active, nó **không** gắn
`response_to_previous=True` sai (chưa có move nào phát). Code hiện tại đã an
toàn: `TutorCapability.advise` lấy `response_to_previous = self._waiting_for_
response` (mặc định False cho tới khi có receipt thành công của một move
`requires_user_response`). Không cần sửa.

### Edge cases (a)
- Builder trả None / 0 concept → không tạo path, lượt chat tiếp tục bình thường.
- `plan_teaching_episode` timeout/ném lỗi → `TeachingPlanBuilder.build` đã
  `except: return None`; `maybe_autostart_path` trả False.
- Path trùng (đã active) → bỏ qua, không tạo mới.
- User đổi chủ đề giữa chừng → KHÔNG tự tạo path thứ hai; chuyển/đóng path thuộc
  quyết định sau (giữ ngoài phạm vi lần này để scoped).

---

## CAPABILITY (b) — Nhịp nối chủ động, nấu sẵn song song, cá tính làm chủ

Quyết định sản phẩm (user chốt): Eris là một nhân vật CÓ MOOD. Khi đang mood
lắm lời thì nó cứ nói, không cần tỏ ra lịch sự, kể cả chen ngang lời user. KHÔNG
dùng thang điểm "quan trọng" cứng do runtime chấm — chính **cá tính Eris** (qua
lựa chọn của Root) quyết nói tiếp hay dừng, nói thường hay chen. Runtime chỉ lo
hai việc: (1) làm nhịp nối tới NHANH (không trễ 6-9s), (2) chặn tai nạn runaway.

### Hai phần tách bạch: "quyết nói gì" (cá tính) vs "làm cho nhanh" (cơ chế)

**Phần cá tính — prompt, Root tự quyết (không có governor):**
Thêm vào `conversation/agent.py::_system_prompt`, cạnh câu "im lặng là lựa chọn
hợp lệ", đại ý:

> "Bạn là một nhân vật có mood và đời sống nội tâm, KHÔNG phải trợ lý chờ lệnh.
> Khi mạch còn mở và bạn còn điều muốn nói, mặc định chọn after=may_continue để
> tự nói thêm thay vì wait_user. Khi đang mood lắm lời, hào hứng, hay có một ý
> bạn THẬT SỰ muốn nói ra, bạn được phép chọn after=continue_self để nói tiếp
> gần như ngay — kể cả chen vào khi user chưa kịp đáp. Bạn KHÔNG bắt buộc phải
> tỏ ra lịch sự hay luôn nhường lời; một người thú vị đang say chuyện thì nói
> nốt ý của mình. Nối bao nhiêu nhịp, chen hay không, là do mood và cá tính bạn
> quyết ở từng lúc — không có hạn mức máy móc.
>
> Chọn wait_user/no_reply khi CHÍNH BẠN thấy đã nói hết, chỉ còn lặp ý cũ, hoặc
> user rõ ràng muốn dừng ('thôi', 'đủ rồi') — vì bạn tinh tế, không vì bạn bị
> bắt phải nhường. Mỗi nhịp nối mang giọng của bạn (hài khô, trêu nhẹ, quan
> điểm riêng), không phải câu đưa đẩy trung tính."

Giữ nguyên câu cấm tạo `max_sentences`/`desired_shape`. Ba mức `after` ánh xạ
tự nhiên vào cường độ mood: `wait_user` (nhường) / `may_continue` (nói tiếp sau
một nhịp chờ) / `continue_self` (nói gần như ngay, dùng khi muốn chen). KHÔNG
thêm trường "điểm quan trọng" — mức `after` CHÍNH LÀ cách Eris biểu đạt mức muốn
nói, do cá tính chọn.

**Phần cơ chế — speculative continuation để nhịp nối tới tức thì:**
Vấn đề hiện tại: kể cả khi Root chọn `may_continue`, câu nối chỉ được *sinh sau*
khi lease `continuation_due` kêu (1.2s) → cộng thêm 6-9s sinh câu → nhịp nối đến
quá trễ, gãy mạch. User muốn: nấu sẵn câu nối SONG SONG ngay khi câu trước vừa
commit, chờ user một nhịp, user im thì bắn luôn câu đã nấu.

Thiết kế speculative (ý user, map vào lease sẵn có):
1. Ngay khi một public move commit với `after ∈ {may_continue, continue_self}`,
   khởi một **tác vụ nền sinh trước** nhịp nối kế (speculative continuation):
   gọi đúng đường Root→writer dùng cho `continuation_due`, nhưng chạy *đồng thời*
   với cửa sổ chờ user, thay vì sau nó. Kết quả (candidate đã localize/prepare)
   giữ trong một ô đệm gắn `event_id`/`generation` của lease.
2. **User là cancel scope tuyệt đối.** Nếu user gửi message trong cửa sổ chờ →
   huỷ tác vụ speculative + bỏ candidate đệm (dùng chính `user_turn(scope)` +
   `_preempt_background_for_chat` đã có). User luôn thắng — trừ nhánh "chen" ở
   dưới, do cá tính Root chủ động chọn từ trước.
3. **Khi lease đến hạn (user im):** nếu candidate đệm còn hợp lệ (cùng
   generation, chưa bị preempt) → phát NGAY, bỏ qua độ trễ sinh câu. Nếu không
   còn (đã preempt / generation đổi) → rơi về đường sinh bình thường như hiện
   tại (không hồi quy).
4. **Chen lời (continue_self):** khi Root chọn `continue_self`, cửa sổ chờ rút
   gần như bằng 0 (lease delay 0.15s đã có) — candidate nấu sẵn phát gần như tức
   thì, tạo hiệu ứng "chen". Đây là hành vi do cá tính Root chủ động chọn, không
   phải runtime tự cắt lời user.

Điểm neo code: `continuation.py` lease (delay 0.15/1.2s, breaker sẵn);
`kernel.py::handle_due_continuation`; `orchestrator.py::run_iteration` /
`_run_v12_signal("autonomous_signal")` — nơi hiện sinh nhịp nối SAU lease, cần
tách phần sinh ra chạy song song và đệm candidate. Writer/delivery/preempt
dùng lại nguyên, chỉ đổi *thời điểm* sinh (song song thay vì tuần tự).

### Vì sao an toàn (tôn trọng docs mục 8/10) — rào là chống TAI NẠN, không phải chống cá tính
- Breaker `continuation.py` giữ nguyên: tối đa `max_consecutive_self_wakes=24` /
  `max_chain_seconds=120`/chain. Đây KHÔNG phải để bắt Eris lịch sự — chỉ để một
  bug vòng lặp không biến thành Eris nói hàng trăm câu. Mood thoáng tới đâu cũng
  không nên để runaway kỹ thuật. User đã đồng ý giữ rào này.
- Speculative candidate luôn gắn `generation`/`event_id`; chỉ phát khi khớp →
  không phát nhầm câu "nguội" sau khi context đã đổi.
- `wait_user` vẫn huỷ lease + bỏ speculative. User message vẫn là cancel scope
  cho mọi nhánh trừ `continue_self` đang bay (chen) — và ngay cả chen cũng chỉ
  một candidate đã nấu, không phải vòng sinh mới đè user.
- Chỉ phần prompt là thay đổi hành vi; phần speculative là tối ưu *thời điểm*,
  không tạo "người phát lời thứ hai" (vẫn một Root, một writer, một delivery).

### Giới hạn phải đo live (không nâng source→live)
- Cảm giác "chen lời" đúng hay khó chịu CHỈ biết khi nghe thật. Thiết kế nghiêng
  về chủ động/thoáng theo ý user; nếu live thấy chen quá đà gây phản cảm, tuyến
  điều chỉnh là siết prompt hoặc hạ hằng breaker — KHÔNG đổi kiến trúc.
- Chi phí: speculative sinh thêm một candidate mỗi nhịp nối, đôi khi bị vứt khi
  user nói. Đây là đánh đổi tải-LLM lấy độ trễ, user chấp nhận. Cần đo tải thật
  so với nhịp nối tiết kiệm được; nếu nặng, có thể chỉ speculative khi
  `continue_self` (mood cao) chứ không cho mọi `may_continue`.

### Edge cases (b)
- User đóng chủ đề ("thôi", "đủ rồi") → cá tính Root được hướng chọn không tự
  nối (handoff `topic_closed=True` để Root tham chiếu). Đây là lựa chọn tinh tế
  của nhân vật, không phải luật cứng.
- Message mới đến khi lease pending (nhánh may_continue) → preempt hiện tại huỷ
  lease + speculative candidate; user thắng.
- Message mới đến khi `continue_self` candidate đang phát (chen) → vẫn để
  candidate đã nấu phát nốt (một nhịp ngắn), rồi lượt user được xử ngay sau.
  Đây là "chen" có chủ đích của cá tính, không phải runtime cố tình đè user.
- Speculative candidate nguội (generation đổi giữa chừng) → không phát, rơi về
  sinh thường. Không hồi quy so với hiện tại.
- Root nối quá đà (lảm nhảm/chen liên tục) → tuyến phòng thủ cứng DUY NHẤT là
  breaker `max_consecutive_self_wakes`/`max_chain_seconds`. Không thêm luật
  "phải lịch sự". Nếu live thấy phản cảm, siết prompt hoặc hạ hằng breaker.
  Chủ đích thiết kế NGHIÊNG VỀ chủ động/thoáng (user chốt); thà đo rồi chỉnh
  xuống còn hơn mặc định thụ động.

---

## CAPABILITY (c) — Phản ứng tức thì khi user bối rối

### Quyết định kiến trúc
Đưa tín hiệu confusion của CHÍNH lượt này (từ `conversation_handoff` state đã
cập nhật đầu lượt, Phase 0 mục 6) vào `runtime_context` để Root thấy ngay, thay
vì đợi `latest_observation` lượt sau. KHÔNG dùng `max_sentences` cứng (giữ cá
tính). Nếu có tutor path active, để `adaptive_policy` lo repair (đã có:
`adaptive_repair_repeated_error`).

### Điểm nối
- `src/runtime/conversation/context_assembler.py::assemble`: thêm một nhánh đọc
  `conversation_handoff` runtime hiện tại (không gọi observe lại — chỉ đọc state)
  và bơm một khối nhỏ `confusion_signal` vào `context`:
  - Nguồn: `ensure_conversation_handoff_runtime(host)` đã tồn tại trên host sau
    bridge; lấy `state` qua `to_dict()` (ConversationHandoff đã có `to_dict`).
  - Trích: `{ "repair_needed": bool, "stance": user_stance,
    "self_caused_probability": self_caused_reaction_probability,
    "primary_hypothesis": causal_hypotheses[0].kind nếu có }`.
  - Chỉ đưa khi `repair_needed` True hoặc `stance == "confused"`; ngược lại để
    key vắng để không nhiễu prompt bình thường.
  - Thêm `"confusion_signal"` vào danh sách field Root được đọc ở
    `agent.py:~797` (`learner_continuity`, `discourse_context`, ...).
- `src/runtime/conversation/agent.py::_system_prompt`: thêm chỉ dẫn:

  > "Nếu confusion_signal báo repair_needed/stance=confused, phản ứng như một
  > người đang dạy giỏi: ưu tiên HỎI user kẹt ở bước/chỗ nào, hoặc ĐỔI cách giải
  > thích (ví dụ khác, góc nhìn khác), thay vì giảng lại dài hơn. Vẫn giữ giọng
  > của bạn; không biến thành câu trung tính."

  Đây là hint mềm — Root vẫn sở hữu `say`, không có governor cắt câu.

### Vì sao không phá "latest_observation" cũ
`conversation_status.latest_observation` (trễ một nhịp) được giữ nguyên cho các
tín hiệu khác. `confusion_signal` là kênh same-turn bổ sung, đọc từ handoff state
đã refresh đầu lượt. Không trùng lặp vai trò.

### Edge cases (c)
- Không có host handoff runtime (adapter legacy) → nhánh `try/except` bỏ qua,
  key vắng.
- User nói "chưa hiểu" nhưng là trêu/đùa → vẫn chỉ là hint; Root được phép đọc
  ngữ cảnh affect/relationship và chọn không "vào chế độ dạy".
- Có path active → ngoài hint, Root gọi `tutor.advise(response_to_previous=...)`;
  `adaptive_policy` tự chọn repair theo evidence. Không thêm code adapt.

---

## PERSONALITY — giữ cá tính kể cả trong chế độ dạy (bắt buộc, docs mục 1)

Kiến trúc hiện tại: tutor trả advice **data-only** cho Root (tool_result), KHÔNG
tự inject vào writer và KHÔNG tự phát public (`capabilities/tutor.py`,
`to_writer_context` chỉ được tutor.py đọc để tính `expects`, không đẩy xuống
writer). Vậy flattening chỉ xảy ra NẾU Root sao chép `instruction_vi` +
`max_sentences` vào `say`. Hai thay đổi nhỏ để giọng luôn sống:

1. **Nới envelope teach/explain** (`tutor/policy.py::envelope`): tăng
   `teach_budget` tối thiểu khi phase teach để câu không bị bóp còn 3-4 câu khô.
   Đổi `teach_budget = 5 if slow else (3 if fast else 4)` → tối thiểu 4, và với
   nhánh `explain`/`analogy`/`worked_example` cho phép tối đa 6. KHÔNG bỏ
   `max_sentences` (vẫn cần guardrail chống lecture 10 đoạn) — chỉ nới đủ để chèn
   một câu trêu/ví von. `probe/assess/review` giữ nhỏ (đó là lúc cần user trả
   lời, ngắn là đúng).

2. **Cho giọng đi kèm nội dung sư phạm** trong chỉ dẫn writer:
   - `tutor/reasoner.py::choose_move` (`instruction_by_kind`) và
     `tutor/model_reasoner.py` (prompt dòng ~186-189): thêm một câu chung vào
     `instruction_vi` kiểu "giữ giọng tự nhiên của Eris (hài khô/trêu nhẹ/quan
     điểm) khi truyền nội dung; không gọt thành câu trung tính" — vẫn giữ các
     ràng buộc sư phạm ("không hé đáp án", "không giải hộ").
   - `tutor/policy.py::enforce`: giữ nguyên hành vi ép `kind`/`requires_response`
     /`max_sentences=min(...)`. KHÔNG thêm directive làm phẳng. (Hiện `enforce`
     không ghi đè `instruction_vi` trong bản worktree này — đã kiểm; nên chỉ cần
     sửa reasoner/model_reasoner.)

3. **System prompt Root** (mục c ở trên đã có) nhấn: dù dùng tutor advice, giọng
   vẫn là của Root; advice là gợi ý sư phạm, không phải khuôn câu.

Kết quả: ngay cả khi Root vào mạch tutor, nội dung sư phạm (probe/repair/không
hé đáp án) được giữ, nhưng độ dài không bị bóp nghẹt và chỉ dẫn không ép giọng
trung tính.

---

## BA QUYẾT ĐỊNH BẮT BUỘC

### (i) Triệu chứng nào kích hoạt auto-tạo path — ngưỡng TỰ DO, cá tính dẫn dắt
Quyết định sản phẩm (user chốt): Eris là AI vui vẻ, chủ động — KHÔNG nên đợi
một câu lệnh tường minh mới chịu vào mạch dạy. Ngưỡng nên **tự do hơn**, miễn là
việc mở mạch dạy đến từ *cá tính và sự quan tâm thật của Eris*, không phải một
bộ đếm máy móc. Đồng thời vẫn tránh biến MỌI câu hỏi vặt thành một "learning
path" rác trong SQLite.

Kích hoạt khi chưa có path active VÀ bất kỳ điều kiện nào dưới đây:
- **A. Marker học tường minh:** tái dùng `_explicit_pedagogical_activation`
  (`orchestrator.py:447` — "dạy tôi", "teach me", "i want to learn", "giải thích
  sâu"...).
- **B. Bối rối trên một chủ đề có chiều sâu:** `conversation_handoff` báo
  `repair_needed/stance=confused` ở lượt hiện tại trên một chủ đề đáng học (không
  phải câu đùa/một từ). KHÔNG còn bắt buộc "lặp lại ≥2 lần" như bản bảo thủ cũ —
  một tín hiệu "chưa hiểu" thật trên chủ đề thực chất là đủ để Eris chủ động mở
  mạch dạy, giống một người bạn thấy mình loay hoay thì xắn tay giúp.
- **C. Chủ đề học kéo dài nhiều lượt:** user hỏi liên tiếp quanh cùng một chủ đề
  mang tính học/kỹ thuật (dùng `conversation_trajectory` depth/topic đã có) —
  Eris nhận ra "đây không phải small talk, user đang thật sự muốn hiểu" và chủ
  động dựng kế hoạch.

Bộ lọc giữ cho ngưỡng tự do mà không rác (thay cho "bảo thủ bằng cách chờ"):
1. **Model builder là trọng tài chất lượng.** `TeachingPlanBuilder.build` chỉ
   trả plan khi chủ đề đủ chất để sinh 3–8 knowledge point; chủ đề vặt/không dạy
   được → builder trả None → KHÔNG tạo path. Đây là cổng lọc tự nhiên: không cần
   luật cứng "mấy lần mới mở", để chính khả năng dựng được giáo trình quyết định.
2. **Idempotent + nguồn đánh dấu:** đã có path active thì không tạo thêm;
   `source="eris_auto"` để lọc/expire sau nếu cần.
3. **Cá tính có quyền phủ quyết:** việc mở path chỉ *trao cho Root khả năng* dạy
   có kế hoạch (learner_continuity không rỗng + gợi ý gọi `tutor.advise`). Root
   vẫn giữ giọng và vẫn được chọn trêu/nói chuyện thường thay vì "lên lớp" nếu
   ngữ cảnh affect cho thấy user đang đùa. Ngưỡng tự do mở *cánh cửa*, cá tính
   quyết có bước qua hay không.

Lý do đổi hướng: bản trước nghiêng "bảo thủ = chờ marker/chờ lặp", làm Eris thụ
động — trái mục tiêu. Bản này nghiêng "chủ động = dễ mở, nhưng lọc bằng chất
lượng giáo trình + cá tính", đúng tinh thần AI vui vẻ chủ động. Rủi ro dương-giả
được hấp thụ bởi builder (không dựng được plan thì không có path) chứ không bởi
một ngưỡng đếm cứng.

### (ii) Path session-tạm hay bền qua phiên?
**Bền qua phiên** (durable), vì:
- Learner model (mastery/BKT/review spaced-repetition) chỉ có ý nghĩa nếu tích
  luỹ qua thời gian — đúng yêu cầu "mô hình hoá người dùng". Review D/S/R vô
  nghĩa nếu reset mỗi phiên.
- Hạ tầng đã bền sẵn: `register_path`/`activate_path` ghi SQLite
  (`learning.sqlite3`) + con trỏ meta `learning_runtime_v1`
  (`service.py` restore/persist). Không thêm gì để bền.
- `source="eris_auto"` đánh dấu nguồn để về sau có thể lọc/expire path tự tạo
  nếu cần — nhưng việc expire KHÔNG thuộc phạm vi lần này.

Rủi ro & chặn: để tránh tích luỹ path rác, `maybe_autostart_path` idempotent
(không tạo khi đã có active path) và chỉ tạo khi marker tường minh (ngưỡng i).
Việc đóng/đổi path khi user rời chủ đề là hạng mục backlog, KHÔNG làm lần này.

### (iii) Biên an toàn cho nhịp nối — chống TAI NẠN, không chống cá tính
Quyết định sản phẩm (user chốt): KHÔNG giới hạn "một nhịp" cứng, KHÔNG thang
điểm quan trọng, KHÔNG luật "phải lịch sự/phải nhường". Số nhịp nối và việc chen
lời do **cá tính Eris** quyết ở từng lúc (qua lựa chọn `after`). Runtime chỉ giữ
MỘT rào, và rào đó là để chống lỗi kỹ thuật runaway, không phải để gò tính cách:

- **Rào cứng duy nhất:** breaker tài nguyên sẵn có `max_consecutive_self_wakes=24`,
  `max_chain_seconds=120`/chain (`continuation.py`). Không hạ các hằng này trong
  phạm vi lần này. Lý do giữ: một bug vòng tự gọi (Root kẹt chọn continue mãi)
  không được phép biến thành Eris nói hàng trăm câu / treo tài nguyên. Đây là
  lưới an toàn cho tai nạn, tương thích với "mood thoáng" — nó chỉ chặn trường
  hợp hỏng, không chặn nhân vật đang say chuyện nói mươi câu liền.
- **Mọi "stop" khác là của cá tính, không phải luật:** prompt mô tả nhân vật
  tinh tế biết khi nào đủ, nhưng KHÔNG ép. Nếu Eris chọn nói tiếp, runtime cho
  phép tới khi chạm breaker.
- **Chen lời:** là hành vi hợp lệ do Root chọn `continue_self`; candidate đã nấu
  sẵn (speculative) nên phát gần như tức thì. Không có cơ chế runtime tự ý cắt
  lời user — "chen" luôn bắt nguồn từ lựa chọn của cá tính Eris ở lượt trước.
- **Điều chỉnh sau khi đo live:** nếu nghe thấy chủ động/chen quá đà gây phản
  cảm, tuyến chỉnh là (1) siết câu chữ prompt, hoặc (2) hạ `max_consecutive_
  self_wakes`. KHÔNG đổi kiến trúc, KHÔNG thêm governor cứng. Hướng mặc định là
  thoáng; chỉnh xuống dễ hơn là nới một hệ thống thụ động lên.

---

## DANH SÁCH FILE

### Sửa (change)
- `src/runtime/tutor/auto_path.py` — **MỚI**: `propose_learning_path`,
  `maybe_autostart_path` (builder hội thoại → LearningPath, register+activate).
- `src/runtime/ai_orchestrated/orchestrator.py` — trong `_run_v12`: gọi
  `maybe_autostart_path` trước `context_assembler.assemble` (try/except
  boundary). KHÔNG đụng `_prepare_pedagogical_turn`, KHÔNG bật pedagogy.
- `src/runtime/conversation/context_assembler.py` — trong `assemble`: đọc
  `conversation_handoff` state hiện tại, bơm `confusion_signal` (chỉ khi
  repair/confused).
- `src/runtime/conversation/agent.py` — `_system_prompt`: (b) đoạn cá tính chọn
  `may_continue`/`continue_self` (mood làm chủ, cho phép chen); (c) đoạn phản ứng
  confusion; thêm `"confusion_signal"` vào danh sách field Root đọc (~dòng 797).
- `src/runtime/conversation/continuation.py` — hỗ trợ đệm speculative candidate
  gắn `generation`/`event_id` trên lease (KHÔNG hạ breaker). Thêm chỗ chứa
  candidate nấu sẵn + điều kiện khớp generation khi lease đến hạn.
- `src/runtime/conversation/kernel.py::handle_due_continuation` — khi lease đến
  hạn: nếu có candidate speculative hợp lệ thì phát ngay, ngược lại sinh thường.
- `src/runtime/ai_orchestrated/orchestrator.py` — ngoài nhánh auto-path: sau khi
  public move commit với `after ∈ {may_continue, continue_self}`, khởi tác vụ
  nền sinh trước nhịp nối (speculative), chạy song song cửa sổ chờ user; huỷ khi
  user message (dùng `user_turn(scope)`/`_preempt_background_for_chat` sẵn có).
- `src/runtime/tutor/policy.py` — `envelope`: nới `teach_budget`/`max_sentences`
  nhánh teach/explain để không bóp giọng. Không đổi `enforce`.
- `src/runtime/tutor/reasoner.py` — `choose_move`: thêm câu giữ giọng vào
  `instruction_vi` (vẫn giữ ràng buộc sư phạm).
- `src/runtime/tutor/model_reasoner.py` — prompt (~dòng 186-189): thêm chỉ dẫn
  giữ giọng kèm nội dung sư phạm.

### Chỉ đọc (read-only, để hiểu/khớp pattern — KHÔNG sửa)
- `src/runtime/learning_core/service.py`, `contracts.py`, `store.py`,
  `belief_model.py` (API path/evidence/BKT — tái dùng, không sửa).
- `src/runtime/tutor/executive.py`, `adaptive_policy.py`, `learner_context.py`,
  `contracts.py` (vòng cognition/adapt — không sửa logic).
- `src/runtime/capabilities/tutor.py` (vòng advice/receipt — đã đủ, không sửa).
- `src/runtime/conversation/observation_bridge.py`,
  `src/runtime/conversation_handoff.py` (đã cập nhật state đầu lượt — không sửa).
- `src/runtime/conversation/runtime_writer.py`,
  `src/runtime/conversation/delivery_adapter.py`,
  `src/runtime/public_output_runtime.py` (đường receipt — không sửa).
- `src/runtime/pedagogical_plan_builder.py`,
  `src/runtime/ai_orchestrated/model_router.py::plan_teaching_episode`
  (builder mượn — gọi, không sửa).

---

## TESTABILITY

- **Unit (mới):**
  - `auto_path.propose_learning_path`: fake router trả một TeachingPlan cố định
    → assert map đúng số KP, `source="eris_auto"`, goal khớp; builder trả None →
    hàm trả None (không raise).
  - `auto_path.maybe_autostart_path`: idempotent khi đã có active path; marker
    tường minh → path active sau khi gọi; câu thường → không tạo path.
  - `context_assembler`: với handoff state `repair_needed=True` →
    `context["confusion_signal"]` xuất hiện; stance engaged → key vắng.
  - `policy.envelope`: teach budget ≥ 4; explain cho phép tới 6; probe/assess
    vẫn nhỏ.
  - **Speculative continuation (cơ chế, test được một phần):**
    - Candidate nấu sẵn khớp `generation` → phát ngay khi lease đến hạn; giả lập
      lease due với candidate đệm hợp lệ → assert dùng candidate (không gọi lại
      đường sinh). Candidate `generation` lệch → assert rơi về sinh thường.
    - User message trong cửa sổ chờ (nhánh may_continue) → assert tác vụ
      speculative bị huỷ + candidate bỏ (dùng fake broker/cancel scope).
    - Breaker: chuỗi self-wake chạm `max_consecutive_self_wakes` → lease dừng
      arm (assert không vượt hằng). Dùng pattern test continuation sẵn có.
- **Integration:**
  - Luồng `_run_v12` với marker "dạy tôi X": path auto active →
    `learner_continuity` không rỗng ở payload Root. (Dùng harness giả router như
    `test_tutor_executive_v1.py`.)
  - Vòng evidence: giả lập Root gọi `tutor.advise` → move delivered (receipt
    successful) → lượt sau `tutor.advise` chấm response → mastery/belief đổi.
    Tái dùng pattern `test_long_term_learner_v2.py`.
- **Khó test bằng unit — phải đo LIVE (ghi nhận):**
  - *Hành vi* chọn `may_continue`/`continue_self` của Root và hint confusion là
    *prompt-driven* — unit test chỉ xác nhận được field/chỉ dẫn CÓ MẶT trong
    payload/prompt, không xác nhận được Root THỰC SỰ chọn đúng mood.
  - *Cảm giác* nhịp nối tự nhiên hay gượng, chen lời duyên hay phản cảm, tốc độ
    nhịp nối có đủ "tức thì" — chỉ biết khi nghe live. Đây là phần rủi ro cao
    nhất của thiết kế (docs mục 2/7: không nâng source→live).
  - *Chi phí tải LLM* của speculative (sinh candidate đôi khi bị vứt) — cần đo
    thực tế; nếu nặng, thu hẹp speculative về chỉ nhánh `continue_self`.

---

## RỦI RO & GIỚI HẠN (theo AGENTS.md / docs)

- Mọi kết luận Phase 0 ở tầng **đọc source worktree hiện tại**; chưa chạy live.
  Trước khi coi là "đã sửa", phải chạy live đo: path có auto-mở đúng ngưỡng;
  Root có chọn `may_continue` hợp lý; giọng còn cá tính; confusion được phản ứng
  tức thì. "Module có code" ≠ "tính năng chạy production".
- Thay đổi (b) có HAI phần: phần *prompt* (cá tính chọn nói tiếp/chen — phụ
  thuộc model tuân theo, phải đo live) và phần *code speculative* (nấu sẵn nhịp
  nối song song — là phần kỹ thuật nặng nhất lần này, chạm continuation/kernel/
  orchestrator). Phần (c) phần lớn là prompt + một chỗ đọc state. Rủi ro tập
  trung ở speculative (đúng/nhanh/không phát nhầm câu nguội) và ở cảm giác live
  của chen lời.
- Speculative là NGOẠI LỆ so với nguyên tắc "không đụng scheduler": nó KHÔNG hạ
  breaker, KHÔNG đổi lifecycle lease, chỉ đổi *thời điểm* sinh nhịp nối (song
  song thay vì sau lease) + thêm ô đệm candidate gắn generation. Vẫn một Root /
  một writer / một delivery. Nếu phần này rủi ro quá cho một lần, có thể tách:
  giao phần prompt (b) + (a) + (c) trước, speculative làm phase sau — nhưng user
  muốn giết độ trễ nên thiết kế gộp luôn.
- Không hạ guardrail nào của continuation/preempt; không bật System 2; không
  viết lại adapt/BKT — giữ phạm vi như user chốt (chủ động hơn, người hơn; không
  đại phẫu kiến trúc).
- Đính chính Phase 0 mục 6 (confusion same-turn) và mục 1 (CLI simulation không
  còn gọi path API) thay thế các mô tả tương ứng trong hai report cũ; phần còn
  lại của report được xác nhận đúng với code hiện tại.
