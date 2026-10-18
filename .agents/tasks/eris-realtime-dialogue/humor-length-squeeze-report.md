# Eris – Hài khô & độ dài câu: có cơ chế nào "bóp" output không?

Điều tra READ-ONLY. Mọi claim trích `file:line` của checkout hiện tại
(`c:/Users/Gtvkun/Documents/GitHub/eris`). Không sửa code, không chạy runtime,
không gọi provider. Câu hỏi của user gồm 2 phần:

1. Khi USER gửi câu hài khô/deadpan, OUTPUT của Eris có bị ra quá ngắn / phẳng?
2. Có prompt hay guard nào "bóp" câu ngắn lại — cap độ dài, cắt chuỗi, hay một
   lớp style/sanitizer viết lại làm trung tính hoá các câu hài không?
   ("tutor prompt bóp à").

---

## 0. Trả lời tóm tắt (đọc trước)

- **Không tìm thấy cơ chế ĐANG CHẠY trên đường chat trực tiếp nào cắt độ dài,
  truncate, hay viết lại/trung tính hoá câu hài của Eris.** Mọi lớp "viết lại
  câu" (style rewrite, guard-violation rewrite, felt-expansion reroll) hiện
  **dormant hoặc bị tắt cứng** (mục 2). Mọi `[:160]/[:180]/[:240]/[:360]` trong
  đường conversation đều nằm trên **metadata/telemetry/history-projection**,
  KHÔNG trên public display/speech text (mục 4).

- **Prompt chủ động BẢO VỆ độ dài và hài khô, không bóp.** Voice contract V39
  nói thẳng: "Độ dài đi theo nội dung và cognitive energy của lượt, **không theo
  một mục tiêu concise cố định**", và "Dry humor là một khả năng tự nhiên,
  **không phải ngoại lệ cần ba điều kiện**"
  ([eris_voice_contract.py:30, :37](../../src/runtime/eris_voice_contract.py)).
  Root prompt cấm chính nó tạo "speech budget, max_sentences, desired_shape"
  ([agent.py:703-705](../../src/runtime/conversation/agent.py)).

- **Nhưng CÓ các yếu tố thiết kế có thể khiến câu chat ngắn/nông hơn** — không
  phải một cái cap, mà là cấu hình lane: writer chạy `reasoning_effort="low"` +
  `thinking_mode="disabled"` mặc định ([runtime_writer.py:421-423](../../src/runtime/conversation/runtime_writer.py)),
  và root_context dặn writer "không tự nghĩ thêm chủ đề… CTA hay lời mời mới",
  "một mẩu câu cụt… là được" ([runtime_writer.py:383-388](../../src/runtime/conversation/runtime_writer.py)).
  Đây là **design-intent** (surface thinking tắt để trả lời nhanh), không phải
  cap độ dài — xem mục 3 và 6.

- **Phần 1 (dry-humor input → reply ngắn/phẳng) KHÔNG thể chứng minh chỉ bằng
  đọc code tĩnh.** Độ dài/độ hài câu cuối do chính model (Root chọn `say`/affect,
  Writer diễn đạt) quyết, không do một guard cắt. Cần transcript live (raw writer
  reply vs text hiển thị cuối) để kết luận — xem mục 5 + "Bằng chứng còn thiếu".

- **"tutor prompt bóp": không đúng với đường chat thường.** Sentence budget
  (`max_sentences`/`max_ideas`) CHỈ áp khi có `teaching_directive` (đường dạy
  học) hoặc trên autonomous Surface worker (`surface_voice_rules`). Chat
  user_turn bình thường không đi qua hai đường này (mục 3).

---

## 1. Ba lớp "viết lại câu" — đều KHÔNG chạy trên chat path

### 1a. `_style_rewrite_is_safe` + `rewrite_text_with_local_style` — DORMANT

Lead trong brief đúng là tồn tại các bound cứng:
[service.py:2159-2214](../../src/llm/service.py)

- `if not original: return len(rewritten) <= 180` (service.py:2165)
- `if len(rewritten) > max(280, int(len(original) * 2.2)): return False` (2168)
- token-overlap `< 0.28` → reject (2184-2185)
- rhetorical-question cue / claim-trigger → reject (2176-2213)

**Nhưng hàm bọc `rewrite_text_with_local_style` chỉ chạy khi `self.style_client`
khác None** ([service.py:2216-2217](../../src/llm/service.py)). `style_client`
chỉ được build khi `legacy_model_lanes_enabled()` — mà flag này **default False**
([architecture_flags.py:35-37](../../src/runtime/architecture_flags.py);
runtime_settings_store.py:43 `"legacy_model_lanes_enabled": False`;
vision.py:119-124 build style_client "if legacy_model_lanes_enabled() else None").

**Và không có caller production.** Tìm toàn repo `rewrite_text_with_local_style`
chỉ thấy định nghĩa + experiments/tests; không có call site trong `src/runtime`.
→ Trên bản chạy mặc định, `style_client is None`, hàm trả `decision` nguyên vẹn
và còn log `skipped=no_style_client`. **Đây là code compat/dormant, không bóp
câu chat.**

### 1b. `rewrite_guard_violation_text` — TẮT CỨNG bởi generation sovereignty

[service.py:2287-2316](../../src/llm/service.py): ngay đầu hàm
```
from runtime.final_passthrough_policy import generation_sovereignty_enabled
if generation_sovereignty_enabled():
    return original_text
```
`generation_sovereignty_enabled()` **hardcode `return True`**
([final_passthrough_policy.py:15-19](../../src/runtime/final_passthrough_policy.py),
có comment: "production thì luôn True"). → Hàm trả câu gốc, không viết lại.

### 1c. Felt-expansion reroll (nở câu phẳng) — cũng TẮT CỨNG

[service.py:2401-2414](../../src/llm/service.py): cùng guard
`if generation_sovereignty_enabled(): return original_text`. Hàm này vốn để
*nở* câu bị phẳng (max_tokens=200), nhưng cũng không chạy ở production.

### 1d. `_guard_chat_output` — no-op

[service.py:485-491](../../src/llm/service.py): comment "Compatibility no-op.
Main model output is not rewritten before parsing." Trả `raw_json` nguyên văn.
Đây chính là câu comment mà brief yêu cầu đối chiếu (service.py:487): nó khớp
với kiến trúc generation-sovereignty — **main model output không bị rewrite
trước khi parse**, và cả ba lớp rewrite hậu kỳ ở trên đều đã bị vô hiệu.

**Kết luận mục 1:** không có lớp style/sanitizer nào viết lại hay cắt câu hài
trên đường chat đang chạy. Các bound `<=180 / 280 / 2.2x` là của code dormant.

---

## 2. Generation sovereignty: raw public text là bất biến sau parse

[final_passthrough_policy.py](../../src/runtime/final_passthrough_policy.py):
sau Decision hợp lệ đầu tiên, semantic public text thuộc main model; các lớp
hậu kỳ chỉ *quan sát* (`audit_only`, im lặng trừ khi `ERIS_VERBOSE_POLICY_AUDIT=1`),
điều khiển tool/motion/transport và redact secret — **không viết lại câu**.
`PublicSpeechSnapshot.restore` (policy.py:88-104) khôi phục text gốc nếu lớp sau
lỡ đổi. Đây là lớp kiến trúc chốt chặn mọi "squeeze/flatten" hậu kỳ.

---

## 3. Writer prompt & cấu hình lane: nói gì về ĐỘ DÀI và HÀI

### 3a. Prompt bảo vệ độ dài và hài (quote nguyên văn)

Voice core V39 ([eris_voice_contract.py:23-30](../../src/runtime/eris_voice_contract.py)):
> "...Độ dài đi theo nội dung và cognitive energy của lượt, không theo một mục
> tiêu concise cố định."

Style rule về hài ([eris_voice_contract.py:37](../../src/runtime/eris_voice_contract.py)):
> "Dry humor là một khả năng tự nhiên, không phải ngoại lệ cần ba điều kiện. Khi
> playful_safety đủ cao, được phép đùa cheeky, trêu nhẹ, innuendo tinh tế hoặc
> dry humor có cạnh..."

Style rule về nhịp ([eris_voice_contract.py:35](../../src/runtime/eris_voice_contract.py)):
> "Cho phép nhịp câu không hoàn toàn đối xứng: câu ngắn xen câu dài hơn, fragment
> tự nhiên... Đừng cố làm mọi reply tròn như biên bản."

Prompt writer lắp ráp các hằng này + `STANCE_PUBLIC_RULES_VI`
([model_router.py:1690-1717 `_public_reply_prompt`](../../src/runtime/ai_orchestrated/model_router.py)).
Prompt KHÔNG chứa chỉ thị "ngắn gọn/một câu/súc tích/concise" cho chat. Nó dặn
"Personality context... để nó đổi cadence, độ gần, mức tự bộc lộ và **cạnh hài**"
(model_router.py:1711).

### 3b. root_context có nghiêng writer về "ngắn/không nở"

[runtime_writer.py:381-388](../../src/runtime/conversation/runtime_writer.py):
> "...Realize this move with natural cadence. **Small reactions, fragments or
> expressive pauses are fine**; do not add a new topic, steering question,
> teaching step or continuation..."

Đây giữ đúng quyền "ý do Root quyết, writer chỉ diễn đạt" và tránh writer tự
phình chủ đề. Nó **cho phép** câu cụt chứ không **ép** cụt. Không có số cap.

### 3c. Lane surface: thinking TẮT, effort LOW (design-intent, ảnh hưởng chiều sâu)

[runtime_writer.py:415-423](../../src/runtime/conversation/runtime_writer.py):
```
"reasoning_effort": runtime_context.get("reasoning_effort", "low"),
"thinking_mode":   runtime_context.get("thinking_mode", "disabled"),
```
Comment tại chỗ: "Default thinking TẮT cho lane user-visible để trả lời nhanh
(thinking ON làm chậm 1.5–2× và nới cửa drop)". Khớp knowledge doc mục 3/4
(surface thinking disabled by design; Root vẫn high).
→ **Design-intent, chưa verify live**: writer tắt thinking *có thể* làm câu nông
hơn một writer có thinking, nhưng đây là lựa chọn kiến trúc (tốc độ), KHÔNG phải
length cap. Không overclaim nó làm câu "ngắn đi"; nó làm câu "ít suy luận tầng
sâu đi" — hai thứ khác nhau.

### 3d. `max_tokens` của writer = 720 (rewrite 620)

[model_router.py:1884](../../src/runtime/ai_orchestrated/model_router.py):
`"max_tokens": (620 if locked_semantic_frame else 720)`. 720 token là rộng cho
một câu chat; comment nói chỉ cắt metadata tree cũ, không nhắm giới hạn văn phong.
Không coi đây là "bóp ngắn" trừ khi live trace cho thấy reply chạm trần 720 rồi
bị cắt (chưa có bằng chứng đó).

### 3e. Sentence budget CHỈ ở teaching/autonomous, KHÔNG ở chat thường

- `max_sentences`/`max_ideas` chỉ enforce khi có `TeachingDirective` hợp lệ +
  `stop_after_chunk` ([model_router.py:1816-1840 projection](../../src/runtime/ai_orchestrated/model_router.py),
  validate tại :1130-1136 `teaching_writer_sentence_budget_exceeded`).
- `surface_voice_rules(max_sentences)` (budget 1..3, default 1) là cho
  **autonomous Surface worker** ([eris_voice_contract.py:60-79](../../src/runtime/eris_voice_contract.py)),
  không phải chat user_turn. Rule còn tự dặn "do not optimize for brevity itself".
- Chat user_turn đi qua `RuntimeConversationWriter.realize` →
  `generate_public_reply` **không truyền `teaching_directive`**
  ([runtime_writer.py:345-443](../../src/runtime/conversation/runtime_writer.py)),
  nên không dính sentence budget.

→ **"tutor prompt bóp" không đúng cho chat thường.** Tutor (`background_tutor`)
và teaching directive chỉ bóp số câu khi Eris đang *dạy học*, không phải khi
đáp một câu đùa. ("tutor" trong app_logging.py:91-92 chỉ là tên lane khởi động.)

---

## 4. Tất cả cap ký tự trong đường conversation đều là metadata, không phải câu nói

Grep `[:160]/[:180]/[:240]/[:360]/truncate/max_length` trong
`src/runtime/conversation/**`:

- `move_outcomes.py:88-89`: `say_hint=str(say)[:360]`, `intent[:240]`,
  `reason[:160]` — đây là **history/receipt projection**, không phải text phát ra.
- `agent.py:731`: history `content[:12000]` (rất rộng), id fields `[:180]`.
- `context_assembler.py:395-397`, `claim_evidence.py:262,347`: cap **context
  nạp vào prompt** (memory/evidence), không cap output.
- `kernel.py`, `continuation.py`, `delivery_adapter.py`: `[:180]` toàn trên
  `session_id/run_id/move_id/delivery_id/user_text(log)` — ID & telemetry.

**Public display/speech text đi qua không cap:** `_realize_v03` dùng
`prepared.display_text`/`prepared.speech_text` nguyên văn
([runtime_writer.py:300-312](../../src/runtime/conversation/runtime_writer.py)).
`validate_prepared` còn **từ chối** nếu text sau prepare khác text model
(`v03_candidate_tampered`, [public_output_artifact.py:198-219](../../src/runtime/conversation/public_output_artifact.py)),
và comment ":148-149" ghi rõ "UDP sender không được tự truncate câu v0.3". Giới
hạn duy nhất là `MAX_UDP_PAYLOAD_BYTES` → **raise overflow, không âm thầm cắt**
(public_output_artifact.py:153-155).

---

## 5. IntentionObserver & Stage: ĐÃ SỬA so với knowledge doc (đính chính lịch sử)

Knowledge doc mục 10 + audit 16:47 nói IntentionObserver "gộp whitespace / CẮT
display còn **360 ký tự**" rồi Stage ghi bản đã cắt vào `display_raw`/`speech_raw`.
**Code hiện tại KHÔNG còn hành vi đó:**

- [intention_authority.py:30-31](../../src/runtime/intention_authority.py):
  `_clean(value, limit=360)` vẫn tồn tại, NHƯNG tại `validate`
  (intention_authority.py:181-183): `normalized = _norm(_clean(original))` — bản
  360 ký tự chỉ dùng cho **phát hiện claim**; `IntentionObservation.text` trả
  `original` (nguyên văn, intention_authority.py:214, 223). Comment :181 ghi:
  "Raw public text là bất biến. Bản 360 ký tự chỉ phục vụ phát hiện claim."
  `rewritten=False`, `body_only=False` cố định.
- [stage_contracts.py:231-258](../../src/runtime/stage_contracts.py): nhánh
  `autonomous` gọi `self.intention_observer.validate(display_raw, ...)` rồi
  **chỉ ghi observation vào payload**; comment :252-256 ghi rõ: "Observer chỉ
  tạo observation; KHÔNG được viết ngược vào display_raw, speech_raw hay
  utterance đã commit. Kể cả bản phân tích bị cắt... vẫn giữ bản JP gốc." Không
  còn so `observation.text != display_raw` để overwrite như audit cũ mô tả.
- `behavior_observation.py:291` gọi observer với `text=_clean(..., 360)` làm
  **phân tích** ([behavior_observation.py:270+](../../src/runtime/behavior_observation.py)),
  tạo `BehaviorSignal` (feedback lượt sau) — comment ":287" "This is analysis,
  never an editor." Không chạm text phát ra.

**→ Đính chính:** kết luận lịch sử "observer cắt display 360 ký tự làm câm/đổi
câu" đã được **sửa trong code hiện tại**. 360 ký tự giờ chỉ là cửa sổ dò claim,
không cắt câu hiển thị/nói. (Lỗi câm JA của phiên 16:47 thuộc đường language
mismatch, không phải length squeeze — và nhánh overwrite đó cũng đã gỡ.)

---

## 6. BanterArbiter, banned_filler, micro_policy — có chạm chat không?

- **BanterArbiter** ([banter_arbiter.py:101+](../../src/runtime/banter_arbiter.py),
  env `ERIS_BANTER_ARBITER` default on): **không có call site production** trong
  đường chat (chỉ định nghĩa + test). Dù chạy, nó *thêm* repair/aside có duyên,
  không cắt độ dài. Không phải nguồn squeeze.
- **banned_filler** ([cortex/banned_filler.py](../../src/cortex/banned_filler.py)):
  `BANNED_FILLER_LINES/HOLLOW_PRESENCE_LINES/STALE_MICRO_TEMPLATES` được dùng bởi
  `micro_repeat_guard.py:15`, `utterance_selector.py:19`, `service.py:18`. Đây là
  kho câu đệm rỗng để **chống lặp** (anti-repeat), không phải bộ lọc cắt hài.
- **MicroLinePolicy / SemanticRepeatGuard** được *khởi tạo* ở
  `coordinator_bootstrap.py:584-586` nhưng grep `micro_line_policy.` /
  `.evaluate(` trong `src/runtime/**` **không có lần gọi nào** → wired-but-unused
  trên đường chat. `UtteranceSelector` cũng chỉ được định nghĩa, không có caller
  runtime.

→ Các lớp này **không chạy** như một sanitizer trên câu chat trực tiếp. Nếu sau
này bật autonomous micro-line, chúng mới tác động (và chủ yếu là chống lặp, có
thể vô tình phạt câu hài lặp lại — nhưng hiện không trong luồng chat).

---

## 7. Phân tầng kết luận theo yêu cầu brief

### (a) Cơ chế CHỨNG MINH chạy trên live chat path & cắt/flatten câu
**Không có.** Không tìm thấy length cap, truncation, hay rewrite/sanitizer nào
đang hoạt động cắt hoặc trung tính hoá câu chat. Integrity check còn chủ động
*chặn* mọi sửa đổi hậu-prepare (mục 4).

### (b) Code dormant / compat (tồn tại nhưng không chạy)
- `rewrite_text_with_local_style` + bound `<=180 / 280 / 2.2x / overlap 0.28`
  (service.py:2159-2286) — gated sau `style_client`/`legacy_model_lanes_enabled`
  (default off), không caller.
- `rewrite_guard_violation_text`, felt-expansion reroll (service.py:2287+, 2401+)
  — tắt cứng bởi `generation_sovereignty_enabled()==True`.
- IntentionObserver overwrite + 360-clip-vào-display: **đã gỡ** (mục 5).
- BanterArbiter / MicroLinePolicy / UtteranceSelector — không caller trên chat.

### (c) Cap chỉ ở DEBUG/log/metadata (vô hại với câu phát ra)
- `say_hint[:360]`, `intent[:240]`, `reason[:160]` (move_outcomes.py:88-89);
  history `content[:12000]`, id `[:180]` (agent.py:731); context/evidence caps
  (context_assembler.py, claim_evidence.py). Tất cả là projection/telemetry.

---

## 8. Phần 1 của user (hài khô → reply ngắn/phẳng): đánh giá & bằng chứng còn thiếu

Không thể chứng minh từ code tĩnh rằng input hài khô → reply ngắn/phẳng, vì:

- Độ dài/độ hài câu cuối do **model quyết** (Root chọn `say` + affect; Writer
  diễn đạt), và prompt lại *khuyến khích* hài + độ dài theo nội dung (mục 3a).
  Không có guard nào cắt sau đó (mục 1, 4).
- Các yếu tố có thể làm câu *nông/ngắn hơn* là **gián tiếp & design-intent**,
  chưa đo live:
  1. Writer `thinking_mode=disabled`, `reasoning_effort=low` (3c) → ít tầng
     suy luận, có thể bớt "nở" ý hài.
  2. root_context dặn writer không thêm chủ đề/CTA và cho phép fragment (3b) →
     nếu Root giao `say` cụt, writer giữ cụt.
  3. `delivery` hint do Root chọn (vd "gọn") đi vào `turn.move.delivery`
     (delivery_adapter.py:89,346) — Root tự chọn theo affect; nếu Root hiểu lệch
     tín hiệu hài của user thành "đáp gọn", câu sẽ ngắn. Đây là quyết định Root,
     không phải cap runtime.
  4. Playfulness/affect cold-start: knowledge doc mục 6 còn để mở việc "đo đầu
     phiên vs phiên ấm trước khi tăng sàn playfulness" — nếu `playful_safety`
     thấp lúc mới mở, hài sẽ bị kìm bởi chính model (không phải verifier).

**Bằng chứng live cần để xác nhận phần 1** (theo knowledge doc mục 12, nguồn
`C:/eris_debug/deepseek_raw/`):
- So **raw writer reply** (`text`/`speech_text` trong `events_*.jsonl`) với
  **text hiển thị cuối** trên cùng turn: nếu hai cái giống nhau → không có
  squeeze hậu kỳ (khớp phát hiện ngày 17/10 rằng 12/12 cặp text==speech_text).
- Với các turn user gửi câu hài: trích `say`/`delivery` của Root (raw executive
  reply) và affect state (`affective_voice_state`, `playful_safety`) để xem câu
  ngắn là do Root giao ý cụt / affect thấp hay do writer. Không có cơ chế cắt
  nào ở giữa để đổ lỗi.

---

## 9. Candidate fix (CHỈ mô tả — nếu muốn câu hài dày/đậm hơn)

Không có "harmful squeeze" để gỡ. Các hướng dưới là **tinh chỉnh biểu đạt**, mỗi
hướng kèm rủi ro; chưa áp dụng.

1. **Bật thinking nhẹ cho surface khi affect playful cao** —
   `runtime_context["thinking_mode"]`/`reasoning_effort` ở
   [runtime_writer.py:421-423](../../src/runtime/conversation/runtime_writer.py).
   Rủi ro: chậm 1.5–2× và "nới cửa drop" đúng như comment cảnh báo; chỉ nên gate
   theo affect, không bật toàn cục.
2. **Cho Root chọn `delivery` dày hơn khi phát hiện user đang đùa** — chỉnh Root
   prompt/affect mapping ([agent.py:606-705](../../src/runtime/conversation/agent.py)),
   KHÔNG thêm quota (prompt đang cấm max_sentences, agent.py:703-705). Rủi ro:
   dễ biến thành "cố hài" khi mood không hỗ trợ — trái style rule :37.
3. **Đo & nâng sàn `playful_safety` cold-start** (knowledge doc mục 6). Rủi ro:
   playful_safety gắn với ranh giới an toàn quan hệ; đừng tách hài khỏi an toàn
   một cách thô. Cần đo đầu phiên vs phiên ấm trước.

**KHÔNG nên:** gỡ generation-sovereignty, integrity check, hay language/evidence
guard để "cho câu dài hơn" — knowledge doc cảnh báo bỏ verifier là mất bảo vệ,
và các guard public/evidence/action/language/single-speaker phải giữ nguyên.

---

## 10. Đính chính / xác nhận với knowledge docs

- **ĐÍNH CHÍNH** (doc mục 10 & audit 16:47): "IntentionObserver cắt display 360
  ký tự + Stage ghi đè display_raw/speech_raw". Code hiện tại: observer trả
  `text=original` (intention_authority.py:214,223; comment :181) và Stage có
  comment cấm viết ngược (stage_contracts.py:252-256). Hành vi cắt/overwrite đã
  được gỡ trên đường này.
- **XÁC NHẬN** (doc mục 2 & final_passthrough): "prompt ủng hộ cá tính vẫn có
  thể bị verifier một chiều/sanitizer làm phẳng". Đúng là *từng* có các lớp
  rewrite; hiện chúng đã bị tắt cứng (sovereignty=True) hoặc dormant (style
  lane off). Rủi ro flattening hậu kỳ hiện **đã được chặn** ở kiến trúc — nhưng
  flattening vẫn có thể đến từ **chính model** (affect thấp, Root giao ý cụt),
  không phải từ guard. Đây là chỗ cần transcript live để tách bạch.
- **XÁC NHẬN** (doc mục 3/4): surface thinking disabled by design; Root vẫn
  high — khớp runtime_writer.py:421-423 và không mâu thuẫn code đọc được.

---

### Phạm vi & giới hạn
Chỉ đọc source checkout hiện tại; không chạy runtime, không có transcript live
mới trong lần này. Không khẳng định bản portable người dùng đang mở trùng byte
với checkout (knowledge doc luôn yêu cầu kiểm process/executable thật). Phần 1
của user cần raw-vs-final live để chốt; phần 2 (có cơ chế bóp không) đã trả lời
được bằng code: không có cơ chế đang chạy nào bóp độ dài/làm phẳng câu chat.
