# Báo cáo điều tra: verbosity khi "chưa hiểu", pacing agent loop, và lớp tutor persona

Phiên tham chiếu: `eris-run-20261017-221337`. Điều tra READ-ONLY, không sửa code.
Workspace: `c:/Users/Gtvkun/Documents/GitHub/eris`.

Quy ước bằng chứng trong báo cáo:
- **[CODE]** = đọc trực tiếp từ source hiện tại, có file + hàm + dòng.
- **[SUY LUẬN]** = suy ra từ code, chưa có trace/live xác nhận.
- **[KHÔNG TÌM THẤY]** = đã tìm nhưng không có cơ chế tương ứng trong code.

Đã đọc trước `docs/knowledge/2026-10-14-eris-runtime-lessons.md`: trục
Root → Writer → Localizer là nối tiếp (mục 3); background lane chạy xong không
chứng minh nội dung đúng (mục 2); không nâng một tầng bằng chứng (source) thành
tầng cao hơn (live). Báo cáo này ở tầng "đọc source", chưa chạy live.

---

## Tóm tắt trả lời (đọc trước phần bằng chứng)

**1. Verbosity / "chưa hiểu":**
**[KHÔNG TÌM THẤY]** bất kỳ bộ giới hạn độ dài nào trong đường public chính
(Root → writer). System prompt của Root còn CẤM tạo `max_sentences`, `speech budget`,
`desired_shape` (`agent.py`, cuối `_system_prompt`, ~dòng 731). Writer cũng không
có giới hạn số câu (`runtime_writer.py`, `realize`/`_realize_v03`).

Có một bộ phát hiện confusion riêng — `conversation_handoff.py::observe_user_turn`
(dòng ~265–360) — nhận "không hiểu/khó hiểu/là sao" và đặt `repair_needed=True`,
`stance="confused"`. Nhưng:
- Nó chạy ở **write-back bridge SAU lượt** (`observation_bridge.py`, dòng 71–86),
  nuôi StateReducer/`latest_observation` cho **lượt kế tiếp**, không phải chỉ thị
  tức thì cho chính lượt "chưa hiểu".
- Tín hiệu `repair_needed` chỉ sinh ra một **preset sân khấu** `sentence_bias="short_direct"`
  trong `expression.py` (dòng 70) — đây là cue cho frontend/Live2D nhịp/pose,
  KHÔNG phải ràng buộc độ dài nội dung lên Root/writer. **[CODE]**

Kết luận: **không có cơ chế nào ép rút gọn hoặc "hỏi điểm kẹt"** khi user nói
"chưa hiểu" trong đường chat chính; cũng **không có** cơ chế ép "giải thích lại
dài hơn" ở tầng runtime. Độ dài hoàn toàn do model Root/writer tự quyết. **[SUY LUẬN]**
về nguyên nhân đoạn 58 giây: nhiều khả năng là lựa chọn tự do của model, không
phải do một length-governor nào đó.

**2. Agent loop pacing:**
- Trục Root → writer là nối tiếp (đồng bộ trong một lượt). **[CODE]**
- `observer`/post_observer là **lane nền, optional, preemptible**, và cố ý
  **chờ user idle** trước khi chạy (`observer.py` dòng ~193–194
  `wait_for_user_idle`, lane `post_observer` optional ở `model_router.py` dòng ~1383). **[CODE]**
- Lý do các lane nền chạy "sau writer và sau khi user gửi lượt mới": chúng được
  submit từ `observe_assistant_commit` (sau commit) và tự nhường user
  (`post_observer_user_turn_deadline`). **[CODE]**
- Cơ chế quyết định Root tự chèn nhịp nối hay chờ user nằm ở trường `after` của
  move (`wait_user|may_continue|continue_self`) + `ContinuationLeaseScheduler`
  (`continuation.py::schedule`). **`after=wait_user` → HỦY lease → không có
  continuation tự chạy** (dòng 81–84). Chỉ `may_continue`/`continue_self` mới arm
  một lease để timer đánh thức Root lại (dòng 105–120). **[CODE]**
- Vì vậy khi trong log "mọi autonomous_signal → no_reply/`after=wait_user`": đó là
  **Root tự chọn** `wait_user`/`no_reply`; system prompt hướng Root rằng với
  autonomous/continuation "im lặng là lựa chọn hợp lệ" (`agent.py`, system prompt). **[CODE]**
  Runtime KHÔNG ép Root phải chờ — Root có đủ công cụ để tự chèn nhịp (chọn
  `may_continue`), nhưng model đang không chọn. **[SUY LUẬN]**

**3. Tutor persona:**
- CÓ các chỉ thị kiểu "không gợi đáp án quá sớm / không giải hộ / không hé đáp án /
  giải thích lại" — chúng nằm trong `reasoner.py::choose_move` (instruction_by_kind,
  dòng ~118–131) và `policy.py::enforce` (directives, dòng ~160–205), gắn vào
  `TeachingMove.instruction_vi` + `max_sentences`. **[CODE]**
- NHƯNG lớp này **KHÔNG luôn bật**. Nó chỉ chạy khi:
  (a) Root **tự quyết** gọi tool `tutor.advise` (`orchestrator.py` dòng ~807–815),
  và (b) có **learning path đang active** — nếu `active_path() is None` thì
  `plan_next_move` trả None ngay (`executive.py` dòng ~95–99). **[CODE]**
- Kết quả tutor trả về Root dưới dạng **tool_result data-only** (`tutor.py::invoke_for_root`,
  `_tutor_advice` bọc thành `{"status":"completed","data":...}`), KHÔNG tự inject vào
  prompt writer và KHÔNG tự phát public. Root mới là người quyết có dùng hay không. **[CODE]**
- Có một lớp persona THỨ HAI, khác tutor: `adaptive_companion.py` chọn stance
  `peer/companion/teach_guided`. Nó cũng chỉ bật ở ngữ cảnh kỹ thuật/học, và
  câu "tôi chưa hiểu/từ đầu/cơ bản" lại là điều kiện CHẶN chuyển sang peer
  (dòng 521). **[CODE]**

Vậy: tutor policy **KHÔNG phải lớp luôn áp dụng**, và về mặt kiến trúc **không ghi
đè trực tiếp giọng nhân vật** — nó chỉ đưa gợi ý cho Root. Nhưng **nếu** Root đã
vào chế độ tutor (log cho thấy goal "không đưa đáp án mới", "giải thích lại...
bằng ngôn ngữ đơn giản"), thì `instruction_vi` Socratic + `max_sentences` nhỏ sẽ
đẩy giọng về kiểu gia sư, làm phẳng "hài khô/trêu nhẹ" ở lượt đó. **[SUY LUẬN]**
Đây là làm phẳng *có điều kiện qua lựa chọn của Root*, không phải *bắt buộc toàn hệ thống*.

---

## Bằng chứng chi tiết

### Câu hỏi 1 — Pipeline độ dài & phản ứng confusion

**1a. Root không có bộ điều tiết độ dài; còn cấm tạo nó.**
`src/runtime/conversation/agent.py`, `RuntimeModelRootAgent._system_prompt` (câu cuối,
quanh dòng 731):
> "Không tạo floor, beat, agenda, arc, exposure, question debt, speech budget,
> max_sentences, desired_shape, disclosure mode hoặc semantic scheduler."

Finalize move đi thẳng: `decide()` trả `NextConversationMove.from_mapping(raw)` ngay
khi `kind == "move"` (agent.py, nhánh finalize ~dòng 300), không có bước đo/cắt độ dài.
`NextConversationMove` (`contracts.py` dòng ~63–78) chỉ có `intent/say/delivery/after` —
không có trường độ dài. **[CODE]**

**1b. Writer không giới hạn số câu.**
`src/runtime/conversation/runtime_writer.py::RuntimeConversationWriter.realize`
dựng `generate_kwargs` với `reasoning_effort="low"`, `thinking_mode="disabled"` cho
tốc độ, nhưng **không** có `max_sentences`/budget. `root_context` còn dặn writer:
"do not add a new topic, steering question, teaching step or continuation" (dòng ~ trong
`realize`, khối `root_context`). `_realize_v03` chỉ kiểm display rỗng
(`v03_missing_public_surface`) và mismatch ngôn ngữ, không kiểm độ dài. **[CODE]**

**1c. Bộ phát hiện "chưa hiểu" có tồn tại — nhưng ở write-back lượt-sau và chỉ ra cue sân khấu.**
- `src/runtime/conversation_handoff.py::observe_user_turn` (dòng ~265–372):
  `confusion = _contains_any(user, ("không hiểu","khó hiểu","ý gì","là sao"... ))`;
  đặt `repair_needed`, `stance="confused"`, và hypothesis
  `"reaction_to_previous_eris_clarity"` ("độ rõ của câu ERIS vừa nói"). **[CODE]**
- Đường gọi nó là WRITE-BACK SAU lượt, không phải input tức thì:
  `src/runtime/conversation/observation_bridge.py::observe_user_turn` (dòng 71–86)
  gọi `ensure_conversation_handoff_runtime(...).observe_user_turn(...)`; module docstring
  nói rõ bridge "chỉ ghi nhận những gì đã xảy ra... không chọn nội dung". **[CODE]**
- Tín hiệu `repair_needed` được tiêu thụ thành **preset sân khấu**:
  `src/runtime/ai_orchestrated/expression.py` dòng 70:
  `add(0.96, "repair", "repair_needed", "short_direct", -0.35)` — đây là
  `sentence_bias`/preset cho frontend (module docstring: "chỉ chọn preset sân khấu
  cơ học... Main model vẫn sở hữu câu chữ; frontend chỉ nhận nhịp/pose/cue"). **[CODE]**
- `executive_cortex.py` dòng 1165 còn dặn: nếu handoff báo `repair_needed` thì coi là
  "uncertain evidence; do not materialize or prefer a speech action here" — tức
  KHÔNG tự biến thành hành động nói. **[CODE]**

**Hệ quả [SUY LUẬN]:** Khi user gõ "chưa hiểu / là sao":
1. Root nhận `latest_observation` (từ post_observer của lượt trước), có thể có
   `repair_needed`, nhưng đây là tín hiệu *trễ một nhịp*, và chỉ nói "cần nhận và
   sửa thẳng" (`contracts.py` dòng ~581–582) — KHÔNG ép ngắn gọn, KHÔNG ép "hỏi điểm kẹt".
2. Không có component nào chuyển "chưa hiểu" thành lệnh writer "rút gọn + hỏi user
   kẹt ở đâu". Việc trả lời 58 giây là model tự chọn độ dài. **[KHÔNG TÌM THẤY]** bộ ép rút gọn.

> Lưu ý phân biệt: `banter_arbiter.py` (dòng 45–63) và `outcome_observer.py`
> (`CONFUSION_PATTERNS`, dòng 162–166) cũng có khái niệm confusion, nhưng chúng phục vụ
> repair/feedback học, không phải bộ điều tiết độ dài. **[CODE]**

### Câu hỏi 2 — Pacing: đồng bộ vs nền, và ai quyết wait_user

**2a. Root → writer: nối tiếp trong một lượt.** `RuntimeConversationWriter.realize` được
gọi sau khi Root finalize move; writer đọc `turn.move` (`runtime_writer.py`, đầu `realize`). **[CODE]**

**2b. post_observer là nền, optional, và cố ý chờ user idle.**
`src/runtime/ai_orchestrated/observer.py`:
- dòng ~149 `cancel_scope=f"background:post_observer:{turn_id}"`;
- dòng ~193–194: `if not GLOBAL_INFERENCE_BROKER.wait_for_user_idle(idle_budget): raise InferenceRejected("post_observer_user_turn_deadline")` — **chủ động nhường user**;
- `inference_context("post_observer", ..., optional=True, ...)` (dòng ~207–209).
`src/runtime/ai_orchestrated/model_router.py` dòng ~1366, ~1378, ~1383: lane
`"observer"/"observation"/reflection/deep/subconscious_4b` → `post_observer`, nằm trong
tập `optional = {"post_observer", "autonomous", "tutor_background", ...}`. **[CODE]**

Submit post_observer xảy ra ở `observation_bridge.py::observe_assistant_commit`
(khối `ai_post_turn_observer.submit`, dòng ~ cuối hàm) — tức SAU khi public commit.
Nên quan sát "lane nền chạy sau writer, sau lượt user mới" là đúng kiến trúc:
chúng cập nhật StateReducer cho *lượt sau*. **[CODE]**

> Chưa đọc call site cụ thể của curator/seed/inner trong phiên này; tài liệu mục 6
> ghi các lane này "chưa audit". Theo `model_router.py`, `tutor_background` và
> `autonomous` cùng nằm nhóm optional/preemptible. **[SUY LUẬN]** các lane nền khác
> cũng không chặn foreground, nhưng cần trace từng lane để chắc. **[KHÔNG TÌM THẤY]**
> bằng chứng chúng chạy đồng bộ chặn lượt.

**2c. Ai quyết Root chờ user hay tự chèn nhịp — trường `after` + lease.**
`src/runtime/conversation/continuation.py::ContinuationLeaseScheduler.schedule`:
- dòng 81–84: `if after == WAIT_USER: self.cancel_session(sid); return None` —
  **không arm lease, không có timer đánh thức** → Root sẽ không tự chạy tiếp.
- dòng 105–120: chỉ `CONTINUE_SELF` (delay 0.15s) hoặc `MAY_CONTINUE` (delay 1.2s) mới
  tạo lease `due_at`, để `run_iteration`/`handle_due_continuation` đánh thức Root. **[CODE]**

`src/runtime/conversation/kernel.py::handle_due_continuation` (dòng ~467–513): khi lease
đến hạn, claim lease rồi gọi lại `handle_event` với event `continuation_due` — tức
Root ĐƯỢC re-evaluate với context mới nhất, **không** replay câu cũ. **[CODE]**

`src/runtime/ai_orchestrated/orchestrator.py::run_iteration` (dòng ~1186–1207): nếu có
lease đến hạn thì `_run_v12_signal("autonomous_signal")`; `_run_v12_signal` gọi
`kernel.handle_due_continuation` cho autonomous (dòng ~1130–1140). **[CODE]**

**Vì sao log toàn `no_reply`/`after=wait_user` [SUY LUẬN]:**
System prompt dặn Root "với autonomous/continuation, im lặng là lựa chọn hợp lệ" và
"Nếu event autonomous/opening/continuation... không đáng nói, chọn no_reply"
(`agent.py` system prompt). Mỗi lần Root chọn `wait_user`, `schedule()` hủy lease →
không có nhịp nền tự chạy → phải đợi user. Đây là **hành vi do Root quyết, không phải
runtime ép**. Kiến trúc đã cho sẵn `may_continue`/`continue_self` để Root giữ nhịp nối;
Root hiện không dùng. Tài liệu mục 10 cũng từng ghi "Ba timer đầu chọn chờ, rồi Root
tự đổi sang nói tiếp" — tức khả năng tự chèn nhịp CÓ, phụ thuộc Root chọn. **[CODE]+[SUY LUẬN]**

### Câu hỏi 3 — Tutor persona: inject ở đâu, điều kiện bật, tương tác cá tính

**3a. Nội dung chỉ thị "đừng giải hộ / không hé đáp án / giải thích lại" nằm ở đâu.**
- `src/runtime/tutor/reasoner.py::ConservativeTutorReasoner.choose_move`, dict
  `instruction_by_kind` (dòng ~118–131):
  - `socratic_question`: "...user tự nối nguyên nhân và hệ quả; không gợi đáp án quá sớm."
  - `guided_practice`: "...không giải hộ toàn bộ."
  - `probe_question`: "...chưa giải thích đáp án trước."
  Các câu này gán vào `TeachingMove.instruction_vi`. **[CODE]**
- `src/runtime/tutor/policy.py::TutorGuardrailPolicy.enforce`, dict `directives`
  (dòng ~160–205): ví dụ `adaptive_transfer_probe`: "...Không giải mẫu, không hé đáp án
  và không gợi ý trước khi người học trả lời."; `spaced_retrieval_before_reteaching`:
  "...không chép đáp án hay giải mẫu trước." Ghi đè `instruction_vi`, đặt
  `max_sentences=min(move.max_sentences, envelope.max_sentences)`. **[CODE]**
- `envelope()` (policy.py dòng ~24–150) đặt `max_sentences` nhỏ theo phase:
  probe=2, teach=teach_budget (3–5), practice=3, assess/review/advance=2, wait=1. **[CODE]**
- `instruction_vi` được xuất cho writer qua `TutorDecision.to_writer_context()`
  (`contracts.py` dòng ~540–549): `move` = `move.to_writer_dict()`, và
  `delivery_constraints` = `{ max_sentences, requires_user_response }`. **[CODE]**

Đây chính là lớp khớp với goal trong public trace ("không đưa đáp án mới",
"giải thích lại... bằng ngôn ngữ đơn giản"): giọng gia sư + ép câu ngắn + cấm hé đáp án.
**[SUY LUẬN]** (trace không đọc trực tiếp ở điều tra này; khớp về mặt ngữ nghĩa với code).

**3b. Lớp này KHÔNG luôn bật — điều kiện kích hoạt.**
1. Phải có learning path active: `executive.py::plan_next_move` dòng ~92–99:
   `path = self.learning.active_path(); if path is None: return None`;
   `step = self.learning.next_tutor_step(...); if step is None: return None`. **[CODE]**
2. Root phải tự gọi tool `tutor.advise`: đăng ký ở
   `orchestrator.py` dòng ~807–815 (`DomainTool(id="tutor.advise", group="learning",
   risk="low", ... available=lambda: tutor_capability.executive is not None)`),
   và system prompt Root dặn "tutor.advise chỉ dùng khi cần dạy hoặc đánh giá người học"
   và "Small talk, joke... phải tự xử lý trực tiếp, không gọi tutor/work/research cho có"
   (`agent.py` system prompt). **[CODE]**
   `TutorCapability` docstring (dòng 7–10): "KHÔNG được gọi ở mọi user turn". **[CODE]**

Vậy phân biệt rõ: **policy tutor chỉ áp dụng khi (a) có learning path active VÀ
(b) Root chủ động gọi tutor.advise** — KHÔNG phải lớp luôn áp lên mọi câu. **[CODE]**

**3c. Tutor không trực tiếp inject vào prompt writer / không tự phát public.**
- `tutor.py::invoke_for_root` trả `advice.to_dict()` (data-only). `TutorCapability`
  docstring: "chỉ trả advice/evidence cho RootAgent. Nó không có API phát public text." **[CODE]**
- `orchestrator.py::_tutor_advice` (dòng ~788–790) bọc thành
  `{"status":"completed","data": ...}` — đây là **tool_result** quay về vòng Root
  (`agent.py::_run_single_action`, nhánh `tool_call`), KHÔNG đi thẳng vào
  `RuntimeConversationWriter.realize` (writer chỉ đọc `turn.move` do Root chốt). **[CODE]**
- System prompt Root xử lý `learner_belief/learner_state` như "ước lượng THỬ NGHIỆM,
  chưa calibrated; không tuyên bố p_known là sự thật"; "người học có quyền đổi chủ đề,
  không ép học liên tục" (`agent.py` system prompt). **[CODE]**

**Hệ quả tương tác với cá tính [SUY LUẬN]:**
- Về kiến trúc, tutor KHÔNG ghi đè giọng — nó đưa `instruction_vi` cho Root cân nhắc;
  Root vẫn giữ quyền viết `say` với cá tính (personality_context bắt buộc ảnh hưởng
  intent/say theo system prompt). Nên "làm phẳng" không phải bắt buộc toàn hệ thống.
- NHƯNG một khi Root đã quyết vào mạch tutor và truyền `instruction_vi`
  ("không hé đáp án", "giải thích lại") + `delivery_constraints.max_sentences` xuống
  writer (qua `discourse_context`/move), thì writer được dẫn mạnh về giọng gia sư,
  câu ngắn, bỏ đáp án — dễ nuốt "hài khô/trêu nhẹ" ở lượt đó. Mức làm phẳng tỉ lệ với
  mức Root tin vào advice và lặp lại nó.

**3d. Lớp persona thứ hai cần biết: AdaptiveCompanion stance (độc lập tutor).**
`src/runtime/adaptive_companion.py::_directive`/`observe_user_turn` (dòng ~480–560)
chọn `stance ∈ {companion, peer, teach_guided}` + `teaching_permission` +
`explanation_depth`. Đáng chú ý dòng 521: khi evidence kỹ thuật mạnh Eris nên tranh
luận như peer, NHƯNG điều kiện bị chặn nếu user nói "tôi chưa hiểu/từ đầu/cơ bản" →
rơi về hướng dạy lại. Đây là một đường khác có thể cũng đẩy giọng về "dạy" khi gặp
tín hiệu bối rối. Cần kiểm call site có đang được nối vào chat path V12 không trước
khi kết luận ảnh hưởng. **[CODE]+[KHÔNG TÌM THẤY]** (chưa xác nhận wiring live).

---

## Kết luận

1. **Verbosity:** Không có length-governor trong đường public chính; Root còn bị cấm
   tạo một cái. Bộ phát hiện "chưa hiểu" có thật nhưng (i) trễ một nhịp (write-back),
   (ii) chỉ ra cue sân khấu `short_direct`, không ép nội dung. Đoạn 58s là lựa chọn
   độ dài của model, không phải do policy nào ép dài. Cũng không có cơ chế ép "hỏi điểm
   kẹt".

2. **Pacing:** Root→writer đồng bộ; observer/post_observer (và nhóm `tutor_background`,
   `autonomous`) là nền/optional và chủ động nhường user. Việc Root luôn chờ user là do
   Root tự chọn `after=wait_user`/`no_reply`; `schedule()` hủy lease khi `wait_user` nên
   không có nhịp nền tự chạy. Kiến trúc CÓ sẵn `may_continue`/`continue_self` để Root giữ
   nhịp nối — vấn đề là chính sách lựa chọn của Root, không phải thiếu cơ chế.

3. **Tutor persona:** Các chỉ thị "không hé đáp án / không giải hộ / giải thích lại" +
   `max_sentences` là có thật (reasoner.py, policy.py) và khớp với trace. Nhưng đây là
   lớp **CÓ ĐIỀU KIỆN** (cần learning path active + Root tự gọi `tutor.advise`), trả
   data-only cho Root, không tự phát public và không trực tiếp ghi đè writer. Làm phẳng
   cá tính xảy ra *khi và chỉ khi* Root đã vào mạch tutor và truyền các ràng buộc này
   xuống — không phải mặc định toàn hệ thống.

---

## Đề xuất hướng chỉnh (KHÔNG thực thi)

**Verbosity / confusion (Q1):**
- Thêm nhánh *tức thì* trong đường user_turn để khi detect confusion ("chưa hiểu/là sao")
  thì đưa một hint vào runtime_context cho Root ở CHÍNH lượt đó (không đợi write-back).
  Nơi tự nhiên: `conversation_handoff.observe_user_turn` đã có `confusion`/`stance`;
  cần đường đọc nó vào payload Root (qua `context_assembler.assemble` / `discourse_context`),
  thay vì chỉ nuôi `latest_observation` lượt sau. **File/hàm:** `conversation_handoff.py::observe_user_turn`,
  `conversation/context_assembler.py::assemble`/`_discourse_context`, `conversation/agent.py::_payload`.
- Nếu muốn ép rút gọn + hỏi điểm kẹt khi confusion: thêm hint *mềm* trong
  `runtime_writer.realize` `root_context` (ví dụ "nếu user báo chưa hiểu, ưu tiên một câu
  ngắn hỏi họ kẹt ở bước nào trước khi giải thích lại") — nhưng để Root/writer giữ cá tính,
  nên là hint, không phải max_sentences cứng. **File/hàm:** `conversation/runtime_writer.py::realize`.
  Cân nhắc docs mục 1 (không tự gọt về câu trung tính).

**Pacing (Q2):**
- Không cần sửa scheduler; cần điều chỉnh *chính sách chọn `after`* của Root. Có thể làm
  rõ trong system prompt khi nào nên `may_continue` để giữ nhịp (ví dụ: vừa đưa một ý mở,
  user chưa phản hồi, mạch còn tự nhiên để nói tiếp một nhịp ngắn). **File/hàm:**
  `conversation/agent.py::_system_prompt`.
- Nếu muốn lane nền chạy sớm hơn để giữ nhịp, xem lại `observer.py::wait_for_user_idle`
  budget và `model_router` lane optional — nhưng phải cân với rủi ro preempt câu đang phát
  (docs mục 8/10: hủy delivery khi message mới). **File/hàm:** `ai_orchestrated/observer.py`,
  `ai_orchestrated/model_router.py` (phân lane).

**Tutor persona (Q3):**
- Nếu muốn giữ cá tính ngay cả trong mạch tutor: nới `max_sentences` cho phase teach/explain
  trong `policy.py::envelope`, và sửa `instruction_by_kind`/`directives` để cho phép giọng
  "hài khô/trêu nhẹ" đi kèm nội dung sư phạm (đổi "chỉ dẫn ngắn cho writer" sao cho không
  triệt tiêu giọng). **File/hàm:** `tutor/policy.py::envelope`+`enforce`, `tutor/reasoner.py::choose_move`.
- Siết điều kiện Root gọi tutor cho câu như "là sao/chưa hiểu" thuộc small talk/kỹ thuật
  nhẹ: làm rõ trong system prompt rằng "chưa hiểu" một bài logic ngắn nên trả lời trực tiếp
  (companion), không mặc định mở lớp tutor. **File/hàm:** `conversation/agent.py::_system_prompt`,
  đối chiếu `adaptive_companion.py` dòng 521.
- Kiểm wiring `adaptive_companion` vào chat path V12 trước khi chỉnh — nếu nó đang đẩy
  `teach_guided` khi gặp "chưa hiểu", đó là nguồn làm phẳng thứ hai độc lập tutor.
  **File/hàm:** `adaptive_companion.py` (call site), cần grep thêm điểm nối vào Root payload.

**Cảnh báo kiểm chứng:** mọi đề xuất trên mới ở tầng đọc source. Trước khi sửa cần (a) đọc
trace phiên `eris-run-20261017-221337` để xác nhận lượt 58s có thực sự đi qua tutor hay chỉ
là Root tự dài; (b) chạy live để đo, theo đúng nguyên tắc docs mục 2/7 (không nâng source →
live). Đặc biệt với Q3: xác nhận trong trace `tutor.advise` CÓ được Root gọi ở lượt đó không —
nếu KHÔNG, thì verbosity/giọng gia sư đến từ Root tự chọn, không phải lớp tutor.
