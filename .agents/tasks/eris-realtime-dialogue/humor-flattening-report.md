# Báo cáo: vì sao Eris trả lời nhạt khi user nói humor

Read-only investigation. Mọi claim kèm `file:line`. Phân lớp bằng chứng:
**[REQUIREMENT]** (yêu cầu sản phẩm), **[DESIGN]** (ý định thiết kế trong code/doc),
**[HISTORICAL-CORRECTED]** (trạng thái lịch sử đã đính chính trong knowledge doc),
**[CODE-PROVEN]** (đọc trực tiếp source), **[HYPOTHESIS-LIVE]** (cần trace live xác nhận).

---

## 0. Tóm tắt câu trả lời (đọc trước)

Khiếu nại đã tinh chỉnh của user: KHÔNG phải độ dài/cắt câu, mà là **chất lượng/cá tính** —
khi user gửi câu đùa/deadpan, Eris đáp lại **nhạt, không bắt được joke**. Đây là
**flattening của hài khô**.

**Nguyên nhân gốc nhiều khả năng nhất, đã chứng minh từ code:**

1. **[CODE-PROVEN] Humor của user KHÔNG được phân loại trên đường chat trực tiếp.**
   Có một classifier đo `playfulness` của câu user (`AffectSemanticClassifier`,
   `src/cortex/affect_semantics.py:208` + nhóm phrase `playfulness` tại `:703-711`),
   nhưng nó **chỉ được gọi qua `RelationshipDynamics.infer_event`**
   (`src/cortex/relationship_dynamics.py:647-651`), và `infer_event` **không có caller
   nào trong `src/runtime/`** (grep toàn repo: chỉ xuất hiện ở chính file đó dòng 1319
   trong block `__main__`, và trong tests). Nghĩa là trên live chat path, độ-đùa của
   lượt user hiện tại **không bao giờ được tính toán**.

2. **[CODE-PROVEN] `playfulness`/`playful_safety` mà writer nhận về là MOOD NỘI TẠI
   của Eris, không phản ánh câu đùa user vừa gửi.** `affective_voice_state.playfulness`
   lấy từ `live.get("playfulness")` của affect dynamics nội tại
   (`src/runtime/affective_voice_state.py:249`), hoặc fallback
   `personality_mood["mischief"]*0.62 + playful_pressure*0.38` (`:265`). Nguồn `mischief`
   là **boredom nền** (`src/runtime/mental_process_runtime.py:157`:
   `mischief = boredom*0.6 + 0.2`), không phải tín hiệu từ user. Không có đường nào
   bơm "user vừa đùa" vào `playful_pressure`/`mischief`.

3. **[CODE-PROVEN] Theo thiết kế Root→writer, writer KHÔNG được phép tự chế humor.**
   Writer gói move của Root rồi dặn surface worker: "Realize this move with natural
   cadence... **do not add a new topic, steering question, teaching step or
   continuation**" (`src/runtime/conversation/runtime_writer.py:338-343`). Nên nếu Root
   không chọn move nghịch/trêu thì writer chỉ diễn đạt trung tính.

4. **[CODE-PROVEN] Root CÓ được phép chọn humor, nhưng điều kiện kích hoạt lại treo vào
   affect/relationship nội tại (vốn không biết user vừa đùa).** System prompt Root nói
   "Khi user đùa bằng câu lặp/ít chữ, bạn có thể bắt nhịp..."
   (`src/runtime/conversation/agent.py`, khối prompt ~dòng 654-656) và "Nếu affect đang
   vui/playful, intent có thể nghịch hơn" (`agent.py:699`). Nhưng "affect vui/playful"
   Root nhìn thấy đến từ `affective_voice_state` (mood nội tại, điểm #2), và payload Root
   **không chứa bất kỳ tín hiệu phân loại humor của lượt user** (allowlist
   `_bounded_context` tại `agent.py:797-823` không có trường affect-của-user nào; chỉ có
   `affective_voice_state` = mood Eris). Việc "bắt joke" do đó phụ thuộc hoàn toàn vào
   khả năng model Root tự đọc được tông đùa từ `event.text` thô — không có scaffold.

**Kết luận một dòng:** hệ thống **không phát hiện** humor của user ở chat path, và tín
hiệu `playful` mà các tầng dùng là mood nội tại của Eris (phần lớn do boredom), nên một
lượt user hài hước **không làm tăng xác suất Root chọn move trêu/dry-humor**. Nếu Root
(DeepSeek) không tự bắt được tông đùa từ text thô, cả pipeline mặc định về trung tính.

**Điều cần đo trước khi sửa (theo doc, OPEN item):** affect cold-start — đo
`affective_voice_state.playfulness`/`playful_safety` đầu phiên vs phiên đã ấm
(mục 3 dưới) trước khi nâng sàn playfulness.

---

## 1. Humor của user có được PHÁT HIỆN không? Move/delivery trêu có được CHỌN cho chat path không?

### 1a. Có classifier đo playfulness — nhưng không chạy trên chat path [CODE-PROVEN]

- `AffectSemanticSignal` có trục `playfulness` (`src/cortex/affect_semantics.py:166`) và
  `playful_distress`, cùng mô tả "Câu có tính đùa, chill, khịa nhẹ không."
  (`affect_semantics.py:150-151`).
- Nhóm phrase cho playfulness: `haha/hehe/lol/chill/dua/khia/vui vui/meo`
  (`affect_semantics.py:703-711`). Đây là matcher không dấu, nhẹ.
- `AffectSemanticClassifier.analyze(...)` là entry (`affect_semantics.py:208`).
- **Caller thực tế:** chỉ `RelationshipDynamics.infer_event`
  (`src/cortex/relationship_dynamics.py:647-651`) và `memory_query_compiler.py:96`
  (compiler ký ức, không phải chọn move), cùng vài self-use trong chính file
  (`:861, :865, :869`).
- **`infer_event` không được gọi ở runtime chat.** Grep `\.infer_event\(` loại test
  chỉ trả về `relationship_dynamics.py:1319` (block demo `__main__`). Không có call site
  trong `src/runtime/`. → trên đường chat, playfulness của lượt user **không được tính**.

Ghi chú: `src/runtime/chat_cycle.py:923` có gọi `engine.analyze(...)` nhưng đó là
`SourceGroundingEngine` (grounding/vision), **không phải** AffectSemanticClassifier
(`chat_cycle.py:905-932`, `_build_chat_source_grounding_report`). Đừng nhầm hai `analyze`.

### 1b. delivery_hint có mang giá trị dry_tease trên chat path không? [CODE-PROVEN]

- `delivery_hint` mặc định rỗng và chú thích ví dụ `dry_tease/soft_tease/focused/low_quiet`
  (`src/domain/decision.py:33`).
- Trên V12 chat path, `delivery_hint` của Decision **không do affect-của-user set**. Giá
  trị đến từ: (a) LLM surface tự khai trong payload rồi được sanitize
  (`src/parser_grounding/decision.py:1397`, allowlist gồm `dry_tease/soft_tease` tại
  `:944-967`); hoặc (b) alias tĩnh theo animation
  (`_SEMANTIC_ANIMATION_STAGE_ALIASES`, `parser_grounding/decision.py:15-22` — nhưng tập
  này chỉ map sang `warm_soft/low_quiet/curious_soft`, **không có** `dry_tease`).
- Writer V12 không gán delivery_hint theo tông user; nó truyền move Root cho surface và
  surface tự điền (`runtime_writer.py:_realize_v03`). Không có bước nào biến "user đùa" →
  "delivery_hint=dry_tease".

### 1c. Tầng staging CÓ thể tạo dry_tease — nhưng chỉ khuếch đại move đã quyết, không khởi nguồn từ joke user [CODE-PROVEN]

- `SpeechDeliveryPlanner.plan(...)` (`src/runtime/speech_delivery_planner.py:122`) chọn
  `voice_style = dry_tease/soft_tease` khi `_looks_teasing(hay, signals)` đúng
  (`:147-149`).
- Nhưng `hay` được ghép từ **output** của Eris: `text + intent + explicit_emotion +
  signals.stance` (`speech_delivery_planner.py:138`), KHÔNG chứa câu user.
- `_looks_teasing` match token trong `hay` (`tease/playful/trêu/cà khịa...`,
  `:230`) hoặc dựa `signals.valence/restraint` (`:231-233`); `AffectSignals` lấy từ
  **internal_state** của Eris (`affect_signals_from`, `speech_delivery_planner.py:101-112`).
- Caller: `stage_contracts.py:350` `self.delivery_planner.plan(... performance.display_text
  ..., intent=decision.intent ...)`. → planner chỉ bắt được trêu nếu **Root đã viết câu
  trêu / đã set intent trêu**. Nó không thể "nghe" joke của user để tự đổi sang dry_tease.

**Trả lời mục này:** user humor **không được detect** trên chat path; move/delivery trêu
**chỉ được chọn** nếu Root tự quyết (dựa trên text thô + mood nội tại), không có tín hiệu
phân loại humor nào hỗ trợ. Đây là nguyên nhân gốc hạng 1.

---

## 2. Xếp hạng nguyên nhân gốc

**#1 — Không có khâu phát hiện humor của user trên chat path [CODE-PROVEN].**
Bằng chứng: §1a (`affect_semantics.py:166,703-711,208`;
`relationship_dynamics.py:647-651`; `infer_event` không có caller runtime). Hệ quả: Root
không nhận tín hiệu "user vừa đùa", writer bị cấm tự chế (§#3), nên mặc định trung tính.

**#2 — `playful`/`playful_safety` writer nhận là mood nội tại, không phải phản ứng với
joke user [CODE-PROVEN].**
Bằng chứng: `affective_voice_state.py:249,265`; nguồn mischief = boredom
(`mental_process_runtime.py:157`). Hệ quả: dù user đùa, `playfulness` gửi cho writer/Root
không nhích lên; lúc phiên còn "nguội" thì playfulness thấp → giọng phẳng (liên quan
affect cold-start, §3).

**#3 — Phân vai Root→writer khiến writer không thể "cứu" một move trung tính thành hài
[CODE-PROVEN / DESIGN].**
Bằng chứng: `runtime_writer.py:338-343` (cấm thêm topic/continuation, chỉ "realize").
Doc xác nhận Root quyết move, writer diễn đạt (knowledge doc mục 2, bảng mục 3). Hệ quả:
nếu #1/#2 làm Root chọn move trung tính, writer khóa luôn sự nhạt đó.

**#4 — Surface lane TẮT thinking theo thiết kế [DESIGN, một phần CODE-PROVEN; tác động
lên humor là HYPOTHESIS-LIVE].**
Bằng chứng: `runtime_writer.py:411-414` đặt `reasoning_effort="low"`,
`thinking_mode="disabled"` cho lane user-visible (có comment giải thích để trả lời nhanh).
Doc nói surface/writer tắt thinking theo thiết kế trong khi Root cao (knowledge doc mục 4,
mục 8 "surface disabled"). **Không overclaim:** writer chỉ diễn đạt move đã khóa nên tắt
thinking ở writer hợp lý; việc "không kịp hiểu joke" nằm ở **Root** (nơi quyết move).
Cần trace live xem Root có enable thinking và có bắt tông đùa không (mục 8 doc ghi Root
thinking enabled/high).

**KHÔNG phải nguyên nhân (đã loại) [CODE-PROVEN]:**
- `rewrite_text_with_local_style` (verifier style một chiều, `service.py:2215`): **không
  có caller nào trong `src/`** (grep chỉ ra định nghĩa, không call site). Dormant → không
  làm phẳng humor. `_style_rewrite_is_safe` (`service.py:2159-2225`) cũng chỉ chạy nếu
  hàm trên chạy.
- `_guard_chat_output` là no-op, "Main model output is not rewritten before parsing"
  (`service.py:487-494`) → không swap câu sau lưng.
- `banned_filler.py`: chỉ chặn 9 câu "presence ping" rỗng
  (`banned_filler.py:21-36`), không đụng tới hài hước.

---

## 3. social_fatigue / exposure_recoil / affect cold-start có giữ Eris ở trạng thái ít-playful không? (số thật)

### 3a. action_memory: suppression của tease trên chat path là GIÁN TIẾP và YẾU [CODE-PROVEN]

- `tease`, `random_chatter` nằm trong `SOCIAL_ACTIONS` (`src/cortex/action_memory.py:45-53`).
  Mỗi lần dùng action social: `social_fatigue += 0.10` (`:316-318`).
- Nhưng `ActionMemoryState` **không có field playfulness**, và không tìm thấy caller nào
  đọc `social_fatigue` để trừ điểm trực tiếp cho `tease` trên V12 chat path (các số
  "giảm hỏi/tease" chỉ là mô tả docstring ở `:102`, không phải code chấm điểm move).
- Trên channel `chat`, `infer_rhythm_phase` trả `execute` trừ khi
  `exposure_recoil >= 0.55` → `recoil` (`action_memory.py:273-278`). Tức rhythm chat gần
  như luôn là `execute`, không phải trạng thái playful. Đây là **bias trung tính-hoá
  gián tiếp** cho chat (phase=execute nghe như "đang làm việc", không trêu).

Decay/tích (số thật, `action_memory.py:190-205`): hằng `k = min(1, elapsed/240)`;
mỗi chu kỳ `social_fatigue *= (1 - 0.45k)`, `exposure_recoil *= (1 - 0.55k)`,
`boredom *= (1 - 0.20k)`. Tích khi dùng: social +0.10, exposure +0.18 (EXPOSURE_ACTIONS,
`:45-52,310-314`). `tease` KHÔNG thuộc EXPOSURE_ACTIONS nên không tự tăng recoil.

### 3b. Affect cold-start: sàn playfulness đầu phiên THẤP [CODE-PROVEN cho công thức; mức live là HYPOTHESIS-LIVE]

- Nếu chưa có affect event V43 nào (`has_dynamic_affect == False`, đầu phiên),
  `playfulness = mischief*0.62 + playful_pressure*0.38`
  (`affective_voice_state.py:265`). `playful_pressure` default **0.0**
  (`src/cortex/internal_state.py:985`). `mischief` baseline từ personality ≈ 0.16
  (`src/runtime/ai_orchestrated/personality.py:114`). → playfulness đầu phiên
  ≈ `0.16*0.62 ≈ 0.10`, rất thấp.
- Khi đã ấm (`has_dynamic_affect == True`), playfulness = `live.get("playfulness")`
  (`affective_voice_state.py:249`) — nguồn chính vẫn là `mischief = boredom*0.6 + 0.2`
  (`mental_process_runtime.py:157`), nên cần boredom tích lên mới có playful. Không có
  đường "user đùa → playful tăng".
- `playful_safety` (relationship) = `getattr(relationship, "playful_safety", 0.0)`
  (`affective_voice_state.py:281`), mặc định 0.0 nếu relationship chưa ấm.

→ **Đầu phiên và khi chưa chán, playfulness/playful_safety thấp**, khớp với quan sát
"nói humor thì Eris chán". Doc liệt kê affect cold-start là OPEN item cần **đo trước khi
sửa** (knowledge doc mục 6, item 1) — giữ nguyên precondition đó.

---

## 4. Bằng chứng live cần thu để xác nhận

Thư mục tồn tại và đang ghi: `C:/eris_debug/deepseek_raw/` có các
`events_*.jsonl` (đã liệt kê file, mới nhất quanh 14-15/10). Cần đối chiếu **cho đúng
lượt user hài hước**:

1. **Raw writer reply vs final text** trong `deepseek_raw/events_*.jsonl`: xem câu writer
   trả có sẵn tông trêu không, hay bản thân writer đã trung tính (nếu writer đã trung
   tính → lỗi nằm ở Root chọn move, khớp #1/#3).
2. **Run-log fields** cần theo dõi cho lượt đó:
   - `delivery_hint` (kỳ vọng thấy `focused`/rỗng thay vì `dry_tease/soft_tease` khi user
     đùa) — xem `decision.to_payload` (`domain/decision.py:144`).
   - `affective_voice_state`: `playfulness`, `playful_safety`, `dry_humor_trait`,
     `expressive_drive` (log qua `prompt_context`, `affective_voice_state.py:161-191`).
     Kỳ vọng playfulness thấp ở đầu phiên.
   - `rhythm_phase` (kỳ vọng `execute` trên chat, `action_memory.py:273-276`).
   - Root step log `[root-agent] step=.. action=move` (`agent.py`, trong `decide`) để
     xác nhận Root chọn `move` chứ không gọi capability, và `intent/delivery` của move.
   - Trong log user dán 10:05–10:08: các field `mode=deepen/branch`, `energy=...`,
     `life=developing` là **conversation trajectory** — xem khi user đùa, mode có rơi về
     `deepen/branch` trung tính không, energy có thấp không.
3. So **early-session vs warmed**: lấy 2 cụm lượt đùa (một ngay đầu phiên, một sau khi đã
   chat lâu) rồi so `playfulness`/`playful_safety` — đây chính là phép đo cold-start doc
   yêu cầu.

---

## 5. Hướng sửa ứng viên (MÔ TẢ, chưa áp dụng — mỗi hướng kèm file:line + rủi ro)

> Tất cả giữ nguyên biên grounding/evidence/action/language/single-speaker như doc dặn.

**A. Phát hiện humor của user rồi đưa thành tín hiệu CHO ROOT (đánh thẳng #1).**
Gọi `AffectSemanticClassifier.analyze(user_text)` trên chat path (hoặc tái dùng
`RelationshipDynamics.infer_event`) và đưa `playfulness/playful_distress` vào
`runtime_context` cho Root qua một key mới, đồng thời thêm key đó vào allowlist
`_bounded_context` (`src/runtime/conversation/agent.py:797-823`). Điểm classify hợp lý:
nơi đã dựng `runtime_context` cho writer/Root (`context_assembler.py:~90-205`).
Rủi ro: thêm một tín hiệu mà model có thể "diễn" humor máy móc; phải truyền dạng **score
mềm**, không phải lệnh "hãy đùa" (doc cảnh báo label cứng mời model diễn,
`affect_semantics.py:290-294`). Chi phí: thêm một lần phân tích rule nhẹ mỗi lượt.

**B. Cho user-humor nhích `playful_pressure`/`playfulness` TẠM THỜI của phiên.**
Hiện playfulness chỉ sinh từ boredom (`mental_process_runtime.py:157`;
`affective_voice_state.py:249,265`). Có thể cộng một impulse playfulness khi user đùa
(đường affect event, xem `live2d_body/stage_state.py:419,576` và
`affective_dynamics_runtime.py:184-189` dùng `impulse["playfulness"]`). Rủi ro: dễ làm
Eris "nhây" quá; cần decay nhanh và cap. **Precondition (doc mục 6):** đo cold-start
trước khi nâng sàn.

**C. Nới nhẹ gợi ý Root để nó chủ động đọc tông đùa từ `event.text`.**
Prompt Root đã có câu "Khi user đùa... bạn có thể bắt nhịp" (`agent.py:654-656`) nhưng
không có tín hiệu kèm theo. Có thể bổ sung (sau khi có A) một dòng tham chiếu score
playfulness. Rủi ro thấp (chỉ prompt), nhưng **không đủ một mình** nếu thiếu A/B vì model
vẫn phải tự suy từ text thô.

**D. Cho phép delivery_hint mang dry_tease trên chat path khi có tín hiệu humor.**
Hiện `_SEMANTIC_ANIMATION_STAGE_ALIASES` không map sang dry_tease
(`parser_grounding/decision.py:15-22`); chỉ surface LLM tự khai mới ra dry_tease
(`:944-967`). Nếu A/B đã làm Root chọn move trêu, chuỗi `SpeechDeliveryPlanner`
(`speech_delivery_planner.py:147-152`) sẽ tự lên dry_tease vì `hay` lúc đó chứa câu trêu.
Vậy D có thể **không cần** nếu A/B thành công. Rủi ro nếu ép cứng: diễn trêu vô cớ.

**Không nên:** đụng vào length/truncation (user đã bác), hay bật lại
`rewrite_text_with_local_style` (verifier một chiều, doc cảnh báo làm phẳng).

---

## 6. Phân lớp bằng chứng (nhắc lại ranh giới)

- **[REQUIREMENT]** Giữ hài khô/trêu nhẹ/tự giễu; không auto-flatten; chấm theo ngữ cảnh
  (knowledge doc mục 1-2). Khiếu nại user hiện tại chính là vi phạm requirement này.
- **[DESIGN]** Root quyết move, writer chỉ diễn đạt; surface tắt thinking; affect là
  authority cho hướng/cường độ (doc mục 2; `runtime_writer.py:338-343,411-414`;
  `eris_voice_contract.py`).
- **[HISTORICAL-CORRECTED]** "Executive chắc chắn thinking OFF", "companion route mỗi
  lượt" v.v. đã bị đính chính (doc mục 5); không dùng làm căn cứ. Affect cold-start vẫn
  là OPEN, chưa xác nhận còn lỗi (doc mục 6) — báo cáo này cung cấp bằng chứng code mới
  cho cold-start nhưng **chưa có số live**.
- **[CODE-PROVEN]** Toàn bộ §1, §2 (#1-#3 và phần loại trừ), §3a, công thức §3b: đọc
  trực tiếp source checkout hiện tại.
- **[HYPOTHESIS-LIVE]** Mức playfulness thật đầu phiên vs ấm; Root có bắt tông đùa từ
  text thô hay không; writer raw đã trung tính sẵn hay chưa — cần §4 trace để chốt.

---

## Phụ lục: trích dẫn chính

- `src/cortex/affect_semantics.py:166` trục `playfulness`; `:703-711` phrase playfulness;
  `:208` `analyze`; `:290-294` cảnh báo không dùng label cứng.
- `src/cortex/relationship_dynamics.py:647-651` nơi duy nhất gọi classifier; `:1319` demo.
- `src/runtime/affective_voice_state.py:249` playfulness từ live affect; `:265` fallback
  mischief+playful_pressure; `:281` playful_safety.
- `src/runtime/mental_process_runtime.py:157` mischief = boredom*0.6 + 0.2.
- `src/cortex/internal_state.py:985` playful_pressure default 0.0.
- `src/runtime/ai_orchestrated/personality.py:114` mischief baseline 0.16.
- `src/runtime/conversation/runtime_writer.py:338-343` writer bị cấm tự chế; `:411-414`
  reasoning_effort=low, thinking_mode=disabled.
- `src/runtime/conversation/agent.py:654-656` "user đùa → bắt nhịp"; `:699` "affect
  vui/playful → nghịch hơn"; `:797-823` allowlist context cho Root (không có affect user).
- `src/runtime/speech_delivery_planner.py:138` `hay` từ output Eris; `:147-152` dry_tease;
  `:228-233` `_looks_teasing`; `:101-112` signals từ internal_state.
- `src/parser_grounding/decision.py:15-22` alias stage (không có dry_tease); `:944-967`
  allowlist delivery_hint gồm dry_tease (chỉ khi surface LLM tự khai).
- `src/llm/service.py:487-494` `_guard_chat_output` no-op; `:2215` `rewrite_text_with_local_style`
  (không caller trong src); `:2159-2225` `_style_rewrite_is_safe`.
- `src/cortex/banned_filler.py:21-36` tập câu bị chặn (chỉ presence ping).
- `src/cortex/action_memory.py:45-53` SOCIAL/EXPOSURE actions; `:190-205` decay;
  `:273-278` rhythm chat=execute.
- Live evidence: `C:/eris_debug/deepseek_raw/events_*.jsonl` (tồn tại, đang ghi).
