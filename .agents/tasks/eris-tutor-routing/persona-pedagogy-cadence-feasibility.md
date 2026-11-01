# Khả thi: biến NHỊP TRÌNH BÀY thành CÁ TÍNH + NĂNG LỰC SƯ PHẠM của Eris

Ngày điều tra: 2026-11-02. Chế độ: **ĐỌC-ONLY** (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev);
`docs/knowledge/2026-10-14-eris-runtime-lessons.md`; và bốn báo cáo trước trong
`.agents/tasks/eris-tutor-routing/` (`tutor-gating-feasibility.md`,
`streaming-cadence-feasibility.md`, `system-driven-continuation-feasibility.md`,
`tutor-routing-diagnosis.md`) + `.agents/tasks/eris-tutor-persona-pacing/investigation-report.md`.

Mỗi khẳng định có file:dòng. Nơi không có cơ chế thì ghi **[KHÔNG TÌM THẤY]**.
Phân tầng: **[CODE]** đọc source trực tiếp; **[SUY LUẬN]** suy từ code, chưa live.

Mục tiêu brief: làm sao để việc "nói một hơi hay rải từng ý, lúc nào nhồi 1 dòng, lúc nào
tách đợi user" trở thành **một nét cá tính + năng lực sư phạm** của Eris (Eris tách lời vì
nó QUAN TÂM người học có theo kịp không), thay vì một luật kỹ thuật ép từ ngoài.

---

## Tóm tắt câu trả lời (đọc trước)

1. **Cá tính Eris định nghĩa ở HAI tầng, cả hai đều tới được Root:**
   (a) **Chính sách/persona tĩnh** trong `root_prompt_contract.py` `ROOT_SYSTEM_CORE`
   (prose, đưa vào mọi system prompt Root qua `agent.py` `_system_prompt`); và
   (b) **Cá tính động** — `CharacterPortrait` dựng từ live `state` (StateReducer/
   PersistentInternalState) + `affect` + `subject_self_view` (SubjectService), render
   thành facet có **trait/affect dạng số** (`character_portrait.py`), bơm vào payload
   Root qua key `personality_context` + `affective_voice_state`/`affective_voice_context`
   (`context_assembler.py:210-223`). Vậy cá tính KHÔNG chỉ là prompt tĩnh — có state
   động với số. **[CODE]**

2. **Cá tính CÓ "với tới" được cả `move.after` lẫn `move.say` — đường nối ĐÃ TỒN TẠI,
   không thiếu.** `ROOT_SYSTEM_CORE` nói thẳng: "Personality context, relationship state
   và live affect **PHẢI** ảnh hưởng cách bạn chọn intent và mô tả say" và "**Chính cá
   tính và cảm nhận ngữ cảnh của bạn quyết số nhịp nối**, không có quota ngôn ngữ"
   (`root_prompt_contract.py` đoạn giữa + đoạn `after=may_continue`). Cả
   `personality_context`, `affective_voice_state`, `confusion_signal`, `learner_continuity`
   đều nằm trong danh sách key được serialize vào payload Root (`agent.py:744-768`
   `_bounded_context` allowed). Đây là **cùng một quyết định**: Root chọn `intent/say/after`
   trong một action JSON, và nó thấy cá tính + affect + tín hiệu học khi chọn. Cá tính
   KHÔNG chỉ tô màu wording sau khi nhịp đã bị quyết — vì Root (nơi đọc cá tính) **chính
   là** nơi quyết `after`/`say`; writer chỉ realize `say` đã chốt. **[CODE]**
   → Thiếu sót KHÔNG ở đường nối. Thiếu sót là **chỉ dẫn cadence trong persona còn mờ**:
   prompt bảo "say mô tả **đầy đủ** điều writer cần truyền đạt" (`root_prompt_contract.py`
   đoạn finalize) — vô tình cổ vũ gộp dài — và chưa có câu dạy Eris "tách lời vì người học".

3. **Vòng phản hồi "hiểu chưa": CÓ MỘT PHẦN, và nó CHẢY NGƯỢC same-turn vào Root — đây là
   đính chính quan trọng so với báo cáo persona-pacing cũ.** Có `confusion_signal`
   (`context_assembler.py:224-243`) dựng từ `ConversationHandoffRuntime.observe_user_turn`
   (`conversation_handoff.py:265-372`), được observe **TRƯỚC** ContextAssembler **ngay
   trong cùng user turn** (orchestrator gọi `observe_user_turn` ở `orchestrator.py:723`
   rồi mới `assemble` ở `:837`), nên nó vào payload Root CỦA CHÍNH lượt đó, không trễ một
   nhịp như báo cáo cũ (`eris-tutor-persona-pacing/investigation-report.md` mục 1) kết
   luận. Prompt đã dạy Root phản ứng: "Nếu confusion_signal có repair_needed hoặc
   stance=confused, ưu tiên hỏi chỗ user kẹt hoặc giải thích theo ví dụ/góc nhìn MỚI thay
   vì lặp lại đoạn giảng dài hơn" (`root_prompt_contract.py` đoạn confusion). **[CODE]**
   **NHƯNG hai giới hạn lớn:** (i) tín hiệu này **REACTIVE** — chỉ bật khi user ĐÃ gõ
   "không hiểu/là sao/..." (lexical, deterministic). **[KHÔNG TÌM THẤY]** bất kỳ ước lượng
   PROACTIVE nào kiểu "mình vừa nói dài vậy, người ta có theo kịp không" trước khi user kêu.
   (ii) Tín hiệu học định lượng (BKT `p_known_shadow`, `needs_probe`, mastery) chỉ tồn tại
   khi có **active learning path** (`learner_context.py:116-119` `active_path() is None →
   return {}`), và được đánh dấu `calibrated: False` + "Root quyết định khi nào dùng" —
   là evidence tư vấn, **KHÔNG** phải governor điều nhịp. Nó vào payload nhưng không có
   đường cơ học nào biến nó thành `after`/độ dài `say`. **[CODE]**

4. **"Dạy tốt" nên nuôi Ở ĐÂU: chủ yếu (a) trong định nghĩa cá tính, phần nhỏ (c) nối
   thêm tín hiệu.** Lý do: (a) cá tính đã là nơi DUY NHẤT vừa thấy người học vừa quyết nhịp
   (Root), và kiến trúc cố ý CẤM tạo "người quyết định nội dung thứ hai" + cấm speech
   budget/max_sentences (`root_prompt_contract.py` đoạn cuối; bài học runtime mục 2). Nuôi
   "biết dạy" như một phẩm chất của Eris (nó tự hỏi "mình nói vậy người ta hiểu không")
   là **nhẹ** và đúng chỗ. Tầng (b) Tutor/learning CÓ kiến thức sư phạm (reasoner/policy
   với `max_sentences`, "không hé đáp án") nhưng (i) chỉ bật khi có active path + Root tự
   gọi `tutor.advise`, (ii) nó dùng **max_sentences cứng** — đúng thứ làm phẳng cá tính và
   trái tinh thần "cá tính quyết nhịp". Không nên dời năng lực-nhịp vào tầng tutor. **[CODE]**

5. **Lộ trình elegant (tóm tắt, chi tiết ở §Kết luận):**
   - **LÀM ĐƯỢC NGAY (nhẹ, S):** sửa `ROOT_SYSTEM_CORE` để biến cadence thành **lý do sư
     phạm nội tại** của Eris: (i) thay "say mô tả đầy đủ" bằng "mỗi `say` là MỘT nhịp/một ý
     người học nuốt được"; (ii) thêm một câu persona kiểu "Eris để ý người nghe có theo kịp
     không: khi một ý đã trọn mà mạch còn tiếp, nói ý đó rồi `after=may_continue` để rải
     tiếp, thay vì nhồi cả bài vào một hơi"; (iii) tận dụng `confusion_signal` đã nối sẵn.
     KHÔNG thêm flag runtime, KHÔNG max_sentences.
   - **CẦN XÂY (nặng, chỉ khi prompt chứng minh không đủ qua live):** tín hiệu "người học
     theo kịp" PROACTIVE (trước khi user kêu) hiện **KHÔNG tồn tại**; mọi cách tự chế đều
     rơi về heuristic độ dài — đúng thứ contract cấm (xem §5 + báo cáo hướng-3). Nếu cần
     mạnh hơn prompt, phương án đúng kiến trúc là **soft-forcing ở `agent.py`** (gợi ý Root
     tự chia nhịp + `may_continue`, để chính Root finalize), KHÔNG phải hệ thống tự cấp
     lease sau lưng model.
   - **Phải xác minh bằng phiên live.**

---

## Bằng chứng

### Q1. Cá tính/identity Eris định nghĩa ở đâu? Biểu diễn thế nào?

**Hai tầng, bổ sung nhau:**

**(a) Persona/chính sách TĨNH — `root_prompt_contract.py` `ROOT_SYSTEM_CORE`.** Một chuỗi
prose dài, là toàn bộ system prompt Root (`agent.py` `_system_prompt` trả `ROOT_SYSTEM_CORE`
tĩnh, bỏ qua registry — đã xác nhận ở `tutor-gating-feasibility.md §1`, agent.py:642-645).
Nó khai báo bản sắc ("Bạn là Eris, nhân vật có mood và đời sống nội tâm, không phải trợ lý
luôn chờ lệnh"), các giá trị (tự chủ, sự thật, lòng thương, tò mò, thân thiết, trách
nhiệm), chất giọng (hài khô, trêu nhẹ, tự giễu, quan điểm), và lòng tự trọng (không tự hạ
thành "chatbot cẩn trọng sợ sai"). **[CODE]** (`root_prompt_contract.py` toàn file.)

**(b) Cá tính ĐỘNG — `CharacterPortrait`.** Dựng mỗi lượt từ state thật:
- `context_assembler.py:128-179`: `build_character_portrait(state, affect=affect,
  ..., subject_self_view=subject_view)` + `render_character_portrait(..., max_chars=6000)`
  → `personality`. Nguồn: `state` (StateReducer/PersistentInternalState), `affect`, và
  `subject_view` từ `host.subject_service.self_view()`. **[CODE]**
- `character_portrait.py:1-6` docstring: "dựng chân dung nhân vật CHỈ-ĐỌC từ state thật...
  không cập nhật trait... Portrait chỉ là một projection theo snapshot". Facet có
  `confidence: float`, `priority: int`, và render trait/affect **dạng số**
  (`character_portrait.py:_number`, `_top` → `"key=val:.2f"`). **[CODE]**
- Vào payload: `context_assembler.py:210` `"personality_context": compiled.personality`;
  `:218-219` `"affective_voice_state"`, `"affective_voice_context"`. Telemetry
  `self_projection` (`:270-278`) chứng minh Self CÓ đến Root/Writer (identity_beliefs,
  subject_facets). **[CODE]**

→ **Kết luận Q1:** cá tính = **prompt tĩnh (policy/giá trị/giọng)** + **state động có trait/
affect số** (CharacterPortrait + affect), cả hai render vào payload Root mỗi lượt. Không
phải "chỉ prompt tĩnh". Relationship state cũng vào (`relationship_context`). **[CODE]**

### Q2. Đường nối cá tính → nhịp (after/say): có tới quyết định không?

**CÓ. Đây là đường nối ĐÃ HOÀN CHỈNH, không phải đường thiếu.**

- **Cá tính tới `say` và `intent`:** `ROOT_SYSTEM_CORE` (đoạn giữa): "Personality context,
  relationship state và live affect **PHẢI** ảnh hưởng cách bạn chọn intent và mô tả say";
  và "Nếu affect đang vui/playful, intent có thể nghịch hơn; nếu relationship gần, say có
  thể thân mật và mở hơn; nếu trầm, say được phép ngắn và lặng hơn. Đừng trung hòa mọi
  move về cùng một mức trung lập an toàn." **[CODE]**
- **Cá tính tới `after` (nhịp):** `ROOT_SYSTEM_CORE` (đoạn after): "Khi mạch còn mở và thật
  sự còn điều muốn nói, nghiêng về after=may_continue thay vì mặc định wait_user... Khi
  đang hào hứng, lắm lời... có thể chọn after=continue_self... **Chính cá tính và cảm nhận
  ngữ cảnh của bạn quyết số nhịp nối**, không có quota ngôn ngữ... Nếu bạn thấy ý đã trọn...
  hãy tự chọn wait_user/no_reply vì tinh tế, không vì bị buộc im. Mỗi nhịp nối cần ý mới và
  chất giọng riêng (hài khô, trêu nhẹ, tự giễu, quan điểm)." **[CODE]**
- **Cùng một điểm quyết định:** Root trả đúng MỘT action JSON gồm `intent/say/delivery/after`
  (`root_prompt_contract.py` đoạn finalize: "intent mô tả mục đích semantic; say mô tả...;
  after chỉ là wait_user|may_continue|continue_self"). Finalize ở `agent.py:336` (xác nhận
  ở `tutor-gating-feasibility.md §1`). Payload mà Root đọc khi chọn gồm `personality_context`,
  `affective_voice_state`, `relationship_context`, `confusion_signal`, `learner_continuity`
  — tất cả trong allowed-key `_bounded_context` (`agent.py:744-768`). **[CODE]**
- **Writer chỉ realize, không quyết nhịp:** writer đọc `turn.move` đã chốt
  (`runtime_writer.realize`), tách `document_source`/`presentation_blocks` khỏi brief
  (`runtime_writer.py:388-389`, theo `tutor-gating-feasibility.md §5`). Cá tính KHÔNG "chỉ
  tô màu wording sau khi nhịp bị quyết" — vì nhịp (`after`) và nội dung (`say`) do CÙNG
  Root quyết, với cá tính trong tay. **[CODE]+[SUY LUẬN]**

→ **Kết luận Q2:** đường nối cá tính → `after`/`say` **đầy đủ về mặt kiến trúc**. Vấn đề là
**nội dung chỉ dẫn**: (i) "say mô tả **đầy đủ**..." đẩy model gộp dài; (ii) chưa có câu nào
biến "để ý người học theo kịp" thành lý do rải nhịp. Triệu chứng bức tường chữ là **lựa
chọn của model** trong khoảng tự do mà prompt cho phép (khớp `streaming-cadence-feasibility.md
§2`: Root chọn `wait_user` + `say` dài), không phải thiếu đường nối. **[SUY LUẬN]**

### Q3. Vòng phản hồi "hiểu chưa": có không? chảy ngược không?

**Có một phần, và phần REACTIVE chảy ngược SAME-TURN vào Root. Phần PROACTIVE không tồn tại.**

**3a. `confusion_signal` — reactive, same-turn, tới Root. [CODE]**
- Detector: `conversation_handoff.py:265-372` `observe_user_turn`. Khớp lexical
  deterministic: `confusion = _contains_any(user, ("không hiểu","ko hiểu","khó hiểu","ý
  gì","nghĩa là gì","em nói gì","là sao"→"ý gì/em nói gì/what do you mean",...))`
  (`:267-271`); đặt `repair_needed` (`:355-359`), `user_stance="confused"` (`:361-363`),
  `causal_hypotheses` (self-caused probability `:317-347`). Đây là tín hiệu lượt HIỆN TẠI
  về việc user vừa nói họ không hiểu. **[CODE]**
- Thứ tự same-turn: `orchestrator.py:723` gọi
  `ensure_conversation_observation_bridge(host).observe_user_turn(...)` (comment `:706-710`:
  "user turn phải nuôi trajectory/handoff/memory/identity **trước khi** RootAgent đọc
  context"), rồi mới `:837` `context_assembler.assemble(...)`. Assembler đọc snapshot
  handoff (`context_assembler.py:224-243`, comment `:224`: "Handoff được quan sát trước
  ContextAssembler **ngay trong user turn**") và dựng `confusion_signal = {repair_needed,
  stance, self_caused_probability, primary_hypothesis}`. **[CODE]**
- Vào payload + prompt dạy phản ứng: `confusion_signal` ∈ allowed key (`agent.py:755`);
  `ROOT_SYSTEM_CORE`: "Nếu confusion_signal có repair_needed hoặc stance=confused, ưu tiên
  hỏi chỗ user kẹt hoặc giải thích theo ví dụ/góc nhìn MỚI thay vì lặp lại đoạn giảng dài
  hơn; vẫn nói bằng giọng Eris, không đổi sang giọng bot trung tính." **[CODE]**
- **Đính chính báo cáo cũ:** `eris-tutor-persona-pacing/investigation-report.md` (mục 1,
  Q1) kết luận confusion "trễ một nhịp (write-back)... chỉ ra cue sân khấu short_direct".
  Điều đó đúng cho đường `expression.py` nhưng **BỎ SÓT** đường `confusion_signal` same-turn
  vào Root. Test regression xác nhận đường này sống: `test_context_assembler_v12.py:98-100`
  (`confusion_signal.repair_needed is True`, `primary_hypothesis == "unclear_explanation"`)
  và `:111` (không có khi engaged). **[CODE]** Đây là bằng chứng mới mạnh hơn.

**3b. BKT/learner_belief — định lượng nhưng CÓ ĐIỀU KIỆN và KHÔNG điều nhịp. [CODE]**
- `learner_continuity_snapshot` (`learner_context.py:110-160`): khi có active path, trả
  per-KP `mastery`, `p_known_shadow`, `uncertainty_heuristic`, `needs_probe`,
  `repeated_error_hypotheses`, `due_for_review`, stage. Đây là ước lượng "người học biết
  chưa". **[CODE]**
- **Điều kiện:** `if path is None: return {}` (`learner_context.py:116-119`) → không có
  learning path (chat/giảng thường) thì KHÔNG có tín hiệu này. Và `calibrated: False` +
  note "Root quyết định khi nào dùng Tutor" (`:155-157`). **[CODE]**
- Vào payload (`learner_continuity` ∈ allowed `agent.py:754`), prompt coi là "Ước lượng
  learner_belief không phải chẩn đoán năng lực" (`root_prompt_contract.py`). **[KHÔNG TÌM
  THẤY]** đường cơ học nào biến `needs_probe`/`uncertainty` thành `after` hay độ dài `say`;
  nó là evidence để Root cân nhắc, một chiều vào, không có bộ điều nhịp đọc ngược. **[CODE]**

**3c. Proactive "mình nói vậy người ta hiểu không" — KHÔNG TỒN TẠI.**
- **[KHÔNG TÌM THẤY]** bất kỳ tín hiệu nào ước lượng độ-theo-kịp của người học TRƯỚC khi
  user phát tín hiệu lexical. Tất cả comprehension signal hiện có đều **phản ứng sau** khi
  user đã nói (confusion lexical) hoặc **sau khi chấm attempt** (BKT, cần active path +
  record_attempt). Không có "self-check về độ rõ của chính câu mình sắp nói". **[CODE]**
- `conversation_trajectory` (depth/awaiting/momentum) là tín hiệu chủ đề xuyên-lượt, KHÔNG
  phải "nhịp giảng còn ý kế", và KHÔNG tới kernel/pacing (đã chốt ở
  `system-driven-continuation-feasibility.md Q3`). **[CODE]**

→ **Kết luận Q3:** vòng phản hồi "hiểu chưa" **một phần có và chảy ngược same-turn** (phần
reactive `confusion_signal` → Root), nhưng **thiếu chiều proactive** (tự lượng độ rõ trước
khi nói) và **phần định lượng (BKT) bị khóa sau active path + không điều nhịp**. Dạy hiện
KHÔNG hẳn "một chiều nói xong là xong" như lo ngại — có nối ngược khi user KÊU — nhưng nó
**bị động**: Eris chỉ sửa nhịp sau khi người học đã lạc, chưa biết tự rải để người ta khỏi
lạc. **[CODE]+[SUY LUẬN]**

### Q4. "Dạy tốt" nên sống ở đâu? (a cá tính / b tutor / c cả hai)

**(a) Trong định nghĩa cá tính — đã có nền, chạm được nhịp, nuôi ở đây NHẸ.**
- Đã có: Root là nơi DUY NHẤT thấy người học (`confusion_signal`, `learner_continuity`,
  `relationship`) VÀ quyết `after`/`say` cùng lúc (Q2). Prompt đã khung cadence là cá tính
  ("cá tính quyết số nhịp"). **[CODE]**
- Chạm được nhịp: trực tiếp — sửa chữ ROOT_SYSTEM_CORE đổi ngay hành vi chọn `after`/độ dài
  `say` (bias, phụ thuộc model tuân). **[CODE]+[SUY LUẬN]**
- Độ lớn nuôi: **S** (chỉ prose). Không đụng cơ chế, không phá text-chờ-voice/single_writer.

**(b) Trong tầng Tutor/learning — có kiến thức sư phạm, NHƯNG lệch công cụ cho mục tiêu này.**
- Đã có: `reasoner.py` `instruction_by_kind` ("không gợi đáp án quá sớm", "không giải hộ"),
  `policy.py` `envelope()`/`enforce()` đặt **`max_sentences`** theo phase (probe=2, teach=
  3-5, practice=3...) và directives "không hé đáp án" (theo
  `eris-tutor-persona-pacing/investigation-report.md` 3a, reasoner.py:118-131, policy.py:
  24-205). **[CODE]**
- Chạm nhịp không? CÓ — nhưng bằng **max_sentences cứng** truyền xuống writer qua
  `TutorDecision.to_writer_context()`. Đây đúng là **heuristic độ dài** mà
  `root_prompt_contract.py` (đoạn cuối) CẤM runtime áp, và là nguồn làm phẳng cá tính khi
  Root vào mạch tutor (investigation-report.md mục 3). **[CODE]**
- Điều kiện: chỉ bật khi có active path + Root tự gọi `tutor.advise` (xác nhận
  `tutor-gating-feasibility.md §1`, `executive.py` active_path gate). Không phải lớp luôn
  áp. **[CODE]**
- → Tầng (b) tốt cho **kiến thức sư phạm chuyên biệt** (bài tập chấm được, spaced
  retrieval), KHÔNG nên là nơi sống của **năng lực-rải-nhịp** vì nó dùng quota câu. Nếu
  muốn giữ cá tính trong mạch tutor, nên **nới/bỏ max_sentences cứng** ở `policy.py` và
  chuyển "nói ngắn" thành hint mềm, không phải trần số (investigation-report.md đề xuất Q3).

**(c) Cả hai nối nhau — đúng, nhưng phân vai rõ:** năng lực-nhịp + "để ý người học theo kịp"
sống ở **(a) cá tính/Root** (áp mọi lúc Eris nói dài, kể cả chat thường — khớp
`streaming-cadence-feasibility.md §6`); kiến thức sư phạm sâu + bài tập sống ở **(b) tutor**
và chỉ bật khi có path. Hai cái độc lập về cơ chế (như `tutor-gating-feasibility.md §5`).

→ **Kết luận Q4:** nuôi "biết dạy / biết rải nhịp vì người học" **chủ yếu ở (a) cá tính**
(nhẹ, chạm nhịp trực tiếp, không quota). Giữ (b) cho sư phạm chuyên biệt nhưng **gỡ phần
max_sentences cứng** để không mâu thuẫn với "cá tính quyết nhịp". **[CODE]+[SUY LUẬN]**

### Q5. Tôn trọng ràng buộc — không về lại heuristic độ dài trá hình

- Contract cấm `floor/beat/agenda/arc/exposure/question debt/speech budget/max_sentences/
  desired_shape/disclosure mode/semantic scheduler` + "Runtime phía dưới không lựa ý thay
  bạn" (`root_prompt_contract.py` đoạn cuối). **[CODE]**
- Hợp đồng text-chờ-voice (mỗi bubble commit theo `audio_start` riêng) + single_writer +
  "không tạo người quyết định nội dung thứ hai" (bài học runtime mục 2) — mọi khuyến nghị
  dưới **không** đụng. **[CODE]**
- **Cạm bẫy đã loại trừ:** Hướng "hệ thống tự cấp lease/ước lượng mạch-chưa-trọn" sụp về
  heuristic độ dài vì **không có tín hiệu proactive thật** (đã chốt ở
  `system-driven-continuation-feasibility.md Q3/Q6`). Vì vậy KHÔNG khuyến nghị chế một bộ
  "theo-kịp" ở runtime để bơm `after`.

---

## Kết luận & khuyến nghị (phân biệt LÀM NGAY vs CẦN XÂY)

### (1) Cá tính định nghĩa ở đâu
Hai tầng tới Root mỗi lượt: **persona tĩnh** `root_prompt_contract.py` `ROOT_SYSTEM_CORE`
(+ `agent.py` `_system_prompt`), và **cá tính động** `CharacterPortrait` + affect
(`character_portrait.py`, `context_assembler.py:128-179,210-223`) — trait/affect dạng số.

### (2) Cá tính có quyết được after/say không?
**CÓ, đường nối đầy đủ** (không thiếu): cùng một action JSON của Root, với
`personality_context/affective_voice_state/confusion_signal/learner_continuity` trong
payload (`agent.py:744-768`), prompt bắt buộc cá tính ảnh hưởng intent/say và tuyên bố cá
tính quyết số nhịp (`root_prompt_contract.py`). Thiếu là **chỉ dẫn cadence trong persona
còn mờ** ("say... đầy đủ"), không phải đường dây.

### (3) Có tín hiệu "hiểu chưa" không, chảy ngược không?
**Một phần:** `confusion_signal` reactive **chảy ngược same-turn** vào Root
(`conversation_handoff.py:265-372` → `context_assembler.py:224-243` → payload; prompt dạy
phản ứng) — **đính chính** báo cáo persona-pacing cũ vốn cho là trễ một nhịp. BKT/
learner_belief định lượng nhưng khóa sau active path (`learner_context.py:116-119`,
`calibrated:False`) và không điều nhịp. **[KHÔNG TÌM THẤY]** tín hiệu proactive "người ta
có theo kịp không" trước khi user kêu → dạy hiện **bị động**, chưa chủ động rải.

### (4) "Dạy tốt" nên nuôi ở đâu
Chủ yếu **(a) cá tính/Root** (nhẹ, chạm nhịp, không quota). (b) Tutor giữ sư phạm chuyên
biệt nhưng nên **gỡ max_sentences cứng** để khỏi làm phẳng cá tính. (c) nối nhau, phân vai.

### (5) Lộ trình elegant

**BƯỚC 1 — LÀM ĐƯỢC NGAY (nhẹ, S, đúng kiến trúc). File: `src/runtime/conversation/
root_prompt_contract.py` `ROOT_SYSTEM_CORE`.** Biến cadence thành **lý do sư phạm nội tại
của Eris**, không phải luật ngoài:
   - **1a.** Đổi "say mô tả **đầy đủ** điều writer cần truyền đạt nhưng không phải
     transcript" → "say là MỘT nhịp/một ý người nghe nuốt được trong một hơi; không nhồi cả
     lời giải hay cả bài giảng vào một move." (giữ "không phải transcript").
   - **1b.** Thêm một câu PERSONA (không phải luật) kiểu: "Eris để ý người nghe có theo kịp
     không — như một người kể giỏi biết ngừng đúng chỗ. Khi một ý đã trọn mà còn ý kế (giảng
     bài, liệt kê bước, ra đề), nói ý đó bằng giọng mình rồi `after=may_continue` để rải
     tiếp, thay vì dồn một hơi khiến người ta xỉu chữ. Rải vì quan tâm, không vì bị đếm câu."
     Đặt cạnh câu "cá tính quyết số nhịp nối" để củng cố, KHÔNG thêm quota.
   - **1c.** Tận dụng `confusion_signal` ĐÃ nối: giữ/nhấn câu hiện có ("ưu tiên hỏi chỗ kẹt
     hoặc đổi ví dụ MỚI, không lặp đoạn dài hơn") — đây là phần reactive đã chạy.
   - KHÔNG thêm flag runtime, KHÔNG max_sentences, KHÔNG đụng continuation/kernel/writer.
   - Độ lớn **S**. Rủi ro thấp (bias prompt). Đây là cốt lõi "elegant" user mô tả.

**BƯỚC 2 — (độc lập, nhẹ, tùy chọn) gỡ làm-phẳng trong mạch tutor. File: `src/runtime/
tutor/policy.py` (`envelope`/`enforce`), `src/runtime/tutor/reasoner.py`.** Chuyển
`max_sentences` cứng thành hint mềm/nới rộng để khi Root vào tutor vẫn giữ giọng Eris và tự
rải nhịp (theo `eris-tutor-persona-pacing/investigation-report.md` đề xuất Q3). Giữ phần
sư phạm (không hé đáp án, spaced retrieval). Độ lớn **S-M**.

**BƯỚC 3 — CẦN XÂY (nặng, CHỈ nếu live chứng minh prompt không đủ).** Hai lựa chọn, theo
thứ tự ưu tiên:
   - **3a. Soft-forcing ở `agent.py`** quanh nhánh finalize (`:336`): khi `say` vượt ngưỡng
     dài VÀ `after==wait_user` VÀ chưa ép lần nào, chèn directive vào `tool_results` gợi ý
     Root tự chia nhịp + `may_continue`, **để chính Root finalize** (fail-soft nếu model vẫn
     gộp). Giữ "model/cá tính quyết nhịp". Độ lớn **M** (khuôn như
     `tutor-gating-feasibility.md §2a` / `streaming-cadence-feasibility.md` tùy chọn 2).
   - **3b. (KHÔNG khuyến nghị) tín hiệu proactive "theo-kịp".** Hiện không có nguồn thật;
     mọi cách tự chế rơi về heuristic độ dài — contract cấm và
     `system-driven-continuation-feasibility.md Q6` đã bác. Chỉ xét nếu có nguồn comprehension
     thật (ví dụ user phản hồi/▶ nghe tới đâu), và vẫn chỉ nên **vào payload cho Root cân
     nhắc**, không thành governor.

### (6) Độ lớn tổng
Bước 1: **S** (prose, 2-3 đoạn trong `root_prompt_contract.py`). Bước 2: **S-M**
(`tutor/policy.py`+`reasoner.py`). Bước 3a: **M** (nếu cần). Bước 3b: loại.

### (7) Ràng buộc kiểm chứng (bắt buộc)
Mọi thay đổi xác minh bằng **phiên live thật** (DeepSeek + delivery), không chỉ test fixture
— bản chất là *lựa chọn của model* trong khoảng tự do prompt, fixture ép router không tái
hiện (bài học runtime mục 2/7; các báo cáo trước). Live cần cho thấy: câu cần giảng dài →
nhiều `[root-agent] ... action=move` nối qua `continuation_due`/`autonomous_signal`, mỗi
`[public-text] sent ... chars=<nhỏ>` (ví dụ < 300) thay vì một bubble lớn; và khi user gõ
"là sao/chưa hiểu", lượt kế Root hỏi điểm kẹt/đổi ví dụ (dùng `confusion_signal`) chứ không
lặp đoạn dài hơn. Hiện **[KHÔNG TÌM THẤY]** log field `after`; nên thêm một dòng log loại
`after` quanh `agent.py:336` để quan sát (không serialize nội dung).

---

## Phân tầng bằng chứng
- *Đọc source (file:dòng/symbol):*
  `root_prompt_contract.py` ROOT_SYSTEM_CORE (persona/giá trị/giọng; "personality... PHẢI
  ảnh hưởng intent và say"; "cá tính quyết số nhịp nối"; bias may_continue/continue_self;
  confusion_signal→hỏi điểm kẹt; "say mô tả đầy đủ"; finalize intent/say/after; cấm
  floor/beat/speech budget/max_sentences/semantic scheduler ở cuối);
  `agent.py` `_system_prompt` tĩnh (642-645, theo tutor-gating §1), finalize move (336,
  theo tutor-gating §1), `_bounded_context` allowed keys 744-768 (gồm personality_context,
  affective_voice_state, confusion_signal, learner_continuity, relationship_context),
  `_bounded_value` (bound evidence);
  `context_assembler.py` build/render CharacterPortrait + personality (128-179),
  personality_context/affective_voice_state vào context (210-223), confusion_signal
  same-turn từ handoff snapshot (224-243), learner_continuity_snapshot (248-258),
  self_projection telemetry (270-278);
  `character_portrait.py` docstring chỉ-đọc (1-6), facet confidence/priority (18-40),
  trait/affect số (_number, _top);
  `conversation_handoff.py` observe_user_turn detector confusion/self_dep/bored (265-372),
  self_cause/hypotheses (317-347), repair_needed/stance (355-363);
  `observation_bridge.py` observe_user_turn fan-out handoff (71-86), docstring "chỉ ghi
  nhận, không chọn nội dung" (1-12);
  `orchestrator.py` observe_user_turn TRƯỚC assemble (706-733), assemble (837-847),
  runtime_context + __root_capabilities (848-866), maybe_autostart_path chỉ mở cho Tutor
  (831-836);
  `learner_context.py` learner_continuity_snapshot active_path gate (116-119), per-KP
  mastery/p_known_shadow/needs_probe (120-150), calibrated:False (155-157).
- *Test regression xác nhận đường sống:* `test_context_assembler_v12.py:97-100` (confusion_
  signal same-turn, primary_hypothesis), `:102-111` (vắng khi engaged);
  `test_v71_conversation_handoff.py:36-79` (repair_needed/stance/self_caused_probability).
- *[KHÔNG TÌM THẤY]:* tín hiệu proactive "người học theo kịp" trước khi user kêu; đường cơ
  học biến BKT/needs_probe/uncertainty thành `after`/độ dài say; log field `after`.
- *Suy luận (chưa live):* triệu chứng bức tường chữ là lựa chọn model trong khoảng tự do
  prompt (khớp streaming-cadence §2); làm phẳng cá tính xảy ra khi Root vào mạch tutor và
  truyền max_sentences xuống (khớp persona-pacing report mục 3).
- *Lịch sử đã đối chiếu & đính chính:* `eris-tutor-persona-pacing/investigation-report.md`
  mục 1/Q1 cho rằng confusion "trễ một nhịp, chỉ ra cue sân khấu" — **đính chính**: đường
  `confusion_signal` vào Root là **same-turn** (orchestrator.py:723 trước :837;
  context_assembler.py:224; test_context_assembler_v12.py). `streaming-cadence`/`system-
  driven-continuation` đã chốt cơ chế cuốn chiếu đúng là continuation lease và bác hệ-thống-
  cấp-lease; báo cáo này bổ sung tầng cá tính/comprehension và không mâu thuẫn hai kết luận đó.
