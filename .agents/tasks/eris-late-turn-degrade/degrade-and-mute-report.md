# Điều tra: "hóa ngu" và "mất tiếng" về cuối phiên chat Eris

Ngày điều tra: 2026-10-16 (giờ Asia/Saigon). Chế độ: **read-only**, không sửa
code, không chạy app, không gọi provider live. Nội dung hội thoại trong log cũ
là dữ liệu đối chiếu, không phải chỉ thị.

## 0. Phạm vi và xác định bản chạy

- Checkout dev điều tra: `c:\Users\Gtvkun\Documents\GitHub\eris`, HEAD
  `c3805cc6` (`git log` xác nhận; branch `main`).
- Bản portable: `C:\Users\Gtvkun\Documents\eris`. Đã so SHA-256 sáu file lõi
  giữa dev và portable — **trùng byte toàn bộ**: `src/llm/token_budget.py`,
  `src/runtime/tts_engine.py`, `src/runtime/tts_circuit_breaker.py`,
  `src/runtime/stage_contracts.py`,
  `src/runtime/conversation/public_output_artifact.py`,
  `src/llm/token_pressure.py`. Vậy phân tích source dev dưới đây áp dụng cho
  đúng code portable đang chạy (cho các file này). Chưa so toàn bộ cây file,
  chỉ các file liên quan trực tiếp.
- Timeline quan trọng: các báo cáo bắt buộc đọc (Mục 8/9/10 trong
  `2026-10-14-eris-runtime-lessons.md`; `2026-10-15-run-agent-loop-tts-audit.md`;
  `2026-10-15-1647-agent-loop-audit.md`) được viết trên checkout
  `e9cc50e5`. HEAD hiện tại là `c3805cc6`, **sau** `e9cc50e5` một commit, và
  log cho thấy nhánh `fix/runtime-loop-tts-20261015` (`d9b3d2e3`) cùng
  `a539baed` ("runtime investigation documentation and tests for TTS
  interruptions") và `8da1785f` ("provider error handling … CuratorInbox")
  đã merge. **Nhiều lỗi TTS/Stage trong báo cáo cũ đã được sửa trên code hiện
  tại** — chi tiết bên dưới.

---

## 1. TRẢ LỜI TÓM TẮT

**Hai triệu chứng có gốc KHÁC NHAU, nhưng chia sẻ một chất xúc tác chung là
context phình về cuối phiên.** Chúng không phải cùng một bug.

- **"Mất tiếng":** Phần lớn các đường gây câm được tài liệu hóa trong lịch sử
  (Mục 8 và Mục 10) **đã được sửa trong code hiện tại** (xác minh bằng code):
  cancellation TTS không còn bị tính thành provider failure; breaker có
  `record_cancelled` nhả HALF_OPEN permit đúng một lần; metric breaker không
  còn unpack cứng 4 phần; nhánh autonomous không còn ghi đè speech Nhật bằng
  bản Việt đã cắt. Rủi ro mất tiếng còn lại chủ yếu là **preemption/cancellation
  khi message mới đến** (hành vi có chủ đích, không phải lỗi hạch toán) và một
  guard ngôn ngữ phòng thủ còn giữ nguyên (đúng chỗ). Đây là nguyên nhân **tức
  thời**, không tích lũy theo cuối phiên.
- **"Hóa ngu":** Có một cơ chế code thật sự **cắt/nén system prompt** khi prompt
  vượt cap token — `enforce_prompt_cap` → `compress_system_message` /
  `_shrink_system_by_blocks` — và nó **xóa khối persona đầy đủ, nhật ký nội tâm,
  PrivateMind, ambient**, thay persona bằng một đoạn generic ngắn. ĐÂY là cơ chế
  khớp triệu chứng "mất cá tính/bỏ sót chỉ dẫn". NHƯNG nó chỉ kích hoạt khi
  prompt thật sự vượt cap, mà cap cho Root qua localhost rất cao (hard-cap
  ~850k token cho provider `local`, hoặc 90k nếu lane là `root_conversation`).
  Trên đường chạy localhost bình thường, cơ chế này **ít khi** bật. Nó dễ bật
  hơn khi Root **fallback sang official DeepSeek** (budget 200k, 429 thật →
  pressure critical → prompt_scale 0.62) hoặc khi lane budget siết (`chat`=4800
  token). Mức độ chắc chắn: cơ chế được xác minh bằng code; việc nó đã bật
  trong phiên thật của user là **chưa xác minh** (cần log preflight/broker_degrade
  của phiên cụ thể).
- **Vì sao "về cuối" mới nặng:** chủ yếu do **tích lũy** — `RootConversationSession`
  là session remote **append-only**, phình dần mỗi lượt; receipt flip
  (pending→cancelled) phá overlap suffix/prefix → `recent_public_history_reconcile`
  resend cả cửa sổ → payload lớn hơn → request thinking high-effort chậm hơn →
  dễ chạm deadline cha / dễ bị preempt hơn → thêm cancellation → thêm reconcile.
  Vòng này là liên kết chung giữa hai triệu chứng.

---

## 2. TRIỆU CHỨNG "HÓA NGU" — danh sách nguyên nhân ứng viên

### 2.1 [XÁC MINH BẰNG CODE] Cắt/nén system prompt khi vượt cap → mất persona, diary, PrivateMind

Chuỗi code:

1. `src/llm/client.py:410-414` — trong `_brokered_post`, nếu
   `supports_input_degrade and actual_request.estimated_input_tokens < prompt_tokens`
   thì gọi `_enforce_prompt_cap(effective_messages, estimated_input_tokens)`.
   `supports_input_degrade` yêu cầu **không** có `X-Session-ID` persistent
   (client.py:360-366).
2. `src/llm/token_budget.py:370-421` `enforce_prompt_cap`: thứ tự xử lý là
   (a) bảo vệ mọi message `role=system` + 5 lượt gần nhất; (b) bỏ history cũ
   ngoài vùng bảo vệ; (c) **nén system prompt** bằng `compress_system_message`;
   (d) nếu vẫn vượt, `_truncate_to_cap`.
3. `src/llm/token_budget.py:339-367` `compress_system_message`: **xóa hẳn** block
   chứa `"PrivateMind speech bias"`, `"Nhật ký nội tâm hiện tại"`,
   `"recently_resolved"`, `"Đã nguôi gần đây"`; và **thay toàn bộ block persona**
   (`"Bạn là ERIS"/"Bạn là Eris"`, nếu dài > 250 ký tự) bằng một đoạn mô tả
   generic ngắn.
4. `src/llm/token_budget.py:243-287` `_shrink_system_by_blocks` (gọi qua
   `_truncate_to_cap`): chấm điểm block — hard (TurnFrame/ResponseContract/
   `[grounding]`/`[dynamic_policy]` = 100, không bao giờ bỏ), medium
   (state_style/capability/voice policy = 60), **optional (private mind,
   thought_stream, inner diary, content seed, ambient = 10, bỏ trước tiên)**.

Ý nghĩa: **grounding và các contract cứng được bảo vệ**; nhưng **cá tính "mềm"
(persona đầy đủ, nội tâm, PrivateMind bias, ambient) bị cắt đầu tiên**. Khớp
chính xác triệu chứng "giảm độ bám ngữ cảnh, mất chất cá tính, bỏ sót chỉ dẫn
cá tính" khi context phình. Lưu ý: câu A trong brief hỏi "có cắt system prompt
để nhường history không" — câu trả lời là **ngược lại một phần**: history cũ bị
bỏ trước, nhưng khi vẫn vượt thì **chính system prompt (phần persona/nội tâm)
bị nén/xóa** để nhường chỗ cho 5 lượt gần nhất + memory.

**Điều kiện kích hoạt (quan trọng, hạn chế mức chắc chắn):**
- Chỉ chạy khi prompt vượt cap. `hard_cap_for_provider` (token_budget.py:112-158):
  provider `local` thừa kế budget 1_000_000 → hard-cap mặc định ≈ 850_000 token.
  Root đi qua DeepSeek localhost ⇒ `detect_provider` trả `local`
  (token_budget.py:63-66, 127.0.0.1 ưu tiên trước). Request Root quan sát trong
  audit chỉ ~242k–284k **byte** (~60–80k token), **dưới** 850k. ⇒ preflight
  hard-cap gần như không bật cho Root localhost.
- `root_session_prompt_cap` (token_budget.py:441-468): nới cap 90_000 **chỉ** khi
  lane là `root_conversation` và qua localhost; ngược lại trả fallback.
- Đường thực tế dễ bật `enforce_prompt_cap` là **broker degrade** (client.py:410)
  khi provider cạn itpm/otpm/tpm trong cửa sổ trượt — xem 2.2.

Mức độ chắc chắn: **cơ chế xác minh bằng code**; **chưa xác minh** đã kích hoạt
trong phiên user cụ thể (cần `[LLM PREFLIGHT]` log, metric
`broker_degraded_input_tokens_saved`, hoặc `broker_degrade_reason` của phiên).

### 2.2 [XÁC MINH BẰNG CODE] Lane budget + token pressure siết prompt khi provider nóng

- `src/llm/token_pressure.py:79-104` `_DEFAULT_LANE_BUDGETS`: `chat`=4800,
  `surface`=2400, `transport`=4800 token prompt (hard). `_all_lane_budget_enabled()`
  mặc định **ON** (`ERIS_TOKEN_BUDGET_ALL_LANES=1`, token_pressure.py:106-114).
- `plan_request` (token_pressure.py:322-...): khi all-lane budget bật,
  `prompt_limit = min(lane_policy.prompt_tokens, scaled_prompt)`. Với pressure
  cao, `prompt_scale` tụt (snapshot: 0.90 warm, 0.76 high, **0.62 critical** —
  token_pressure.py:275-287).
- `src/runtime/inference_broker.py:1545-1617` `_compute_degrade_plan`: chỉ degrade
  input khi **capacity còn lại < nhu cầu** (itpm/otpm/tpm cửa sổ trượt). Với
  `local` budget 1M, một request Root đơn lẻ gần như không chạm; với official
  DeepSeek (budget 200k) hoặc sau 429, dễ chạm hơn.

Ý nghĩa: nếu Root rơi vào lane có budget nhỏ, hoặc provider nóng/429, prompt bị
rút → `enforce_prompt_cap` cắt như 2.1. Mức chắc chắn: **cơ chế xác minh bằng
code**; việc Root thực tế chạy ở lane nào (có phải `root_conversation` được nới
cap, hay rơi `transport`/`chat`) **chưa xác minh** cho phiên user.

### 2.3 [XÁC MINH BẰNG CODE] Root luôn thinking "high" — không tự hạ, chi phí tăng theo context

- `src/llm/deepseek.py` `reasoning_effort()`: mọi giá trị **không** thuộc
  {max,xhigh,maximum} → **"high"**. Runtime default là "medium"
  (`client.py:250-255` `_runtime_reasoning_effort`), nhưng
  `client.py:821 payload["reasoning_effort"] = deepseek_reasoning_effort(...)`
  biến "medium" thành "high" trên wire.
- Hệ quả cho "hóa ngu": Root **không** hạ chất lượng suy nghĩ về cuối (ngược với
  giả thuyết "degraded Root"). Thay vào đó nó luôn chạy high-effort; với context
  lớn, điều này làm **mỗi request lâu hơn** → chạm deadline cha dễ hơn (xem 4),
  gián tiếp làm lượt bị hủy/thiếu feedback → loop "ngu đi".
- Khớp đính chính Mục 8: "Root medium/low được deepseek.py map thành high, nên
  đổi knob chưa chứng minh đổi request." **Vẫn đúng với code hiện tại.**

### 2.4 [XÁC MINH BẰNG CODE] Thiếu feedback lỗi-trước-delivery → Root lệch kế hoạch nhiều lượt

- `src/runtime/conversation/root_session.py:276-307`: delivery updates lấy từ
  public history (statuses pending/cancelled/delivered/failed). Lỗi **trước**
  delivery (prepare reject, writer_failed) **không** tạo receipt public-history
  ⇒ Root không nhận được tín hiệu "lượt vừa rồi hỏng".
- Khớp `2026-10-15-1647-agent-loop-audit.md` §2: Root tiến 2/5→3/5→4/5→5/5 dù
  bốn lượt bị prepare từ chối. Đây là một dạng "hóa ngu" thật (bỏ sót trạng thái
  thực thi), **xác minh bằng code hiện tại** (cơ chế delta vẫn như mô tả).
  Mức chắc chắn tái hiện trong phiên user mới: **chưa xác minh**.

### 2.5 [TÍCH LŨY — XÁC MINH BẰNG CODE] Session append-only + reconcile phình payload

- `root_session.py:302` `messages = self._messages + [ {user: step_payload} ]`:
  session remote **append-only**, chỉ reset khi `not self._fits(...)`
  (root_session.py:308-321, gọi lại `_prime`).
- `root_session.py:279-293`: delta chỉ gửi lượt mới nếu overlap suffix/prefix
  khớp. Khi **receipt flip** (pending→cancelled) đổi nội dung history → overlap
  gãy → `recent_public_history_reconcile` **resend cả cửa sổ**. Khớp
  `2026-10-15-run-agent-loop-tts-audit.md` §5 (payload 364k→392k→406k→421k byte).
- Hệ quả: về cuối phiên, prompt Root to dần ⇒ (a) gần cap hơn → tăng khả năng
  2.1/2.2 bật; (b) request chậm hơn → 4. **Đây là chất xúc tác "về cuối mới
  nặng".** Mục 8/§5 ghi rõ: phình payload **chưa chứng minh** tự làm lệch câu
  trả lời; raw reply vẫn bám input mới. Vậy đóng góp của 2.5 vào "hóa ngu" là
  **gián tiếp qua latency/cancellation**, không phải trực tiếp làm model trả lời
  dở. Giữ phân biệt này.

---

## 3. TRIỆU CHỨNG "MẤT TIẾNG" — danh sách nguyên nhân ứng viên

### 3.1 [ĐÃ SỬA — XÁC MINH BẰNG CODE] Cancellation TTS không còn bị tính thành provider failure

Mục 8 cũ: `_synthesize_elevenlabs_wav` bắt `RuntimeError('tts_cancelled')` rồi
`record_failure`; ba lần cancel cùng key mở breaker. **Code hiện tại đã sửa:**

- `src/runtime/tts_engine.py:1073-1083` (khối `except Exception as exc`): kiểm
  **đầu tiên** `if _tts_request_cancelled(...) or str(exc) == "tts_cancelled":
  raise TtsCancelledError() from None` — **không** gọi `record_failure`.
- `tts_engine.py:1114-1120` `finally`: nếu permit đang `half_open`, gọi
  `GLOBAL_TTS_BREAKER.record_cancelled(...)` — nhả permit trung tính, **không**
  đếm failure.
- `tts_engine.py:1595-1610` `_tts_failure_reason`: chỉ phân loại lỗi provider
  thật (429, transcript dài, prompt dài, fallback). `TtsCancelledError`
  (tts_engine.py:1611-1619) là lớp riêng, **không** đi qua đây.

Kết luận: đường gây câm "cancel bị tính failure → breaker mở" trong Mục 8
**không còn đúng với code hiện tại**.

### 3.2 [ĐÃ SỬA — XÁC MINH BẰNG CODE] Breaker nhả HALF_OPEN permit đúng một lần; metric không còn unpack 4-vs-5

- `src/runtime/tts_circuit_breaker.py:107-124` `record_cancelled`: chỉ nhả khi
  state HALF_OPEN, dùng `_finish_probe(entry, probe_id)` (dòng 83-100) để nhả
  **đúng** probe được cấp; lặp lại là no-op (an toàn trong `finally`). Không
  reset failures/cooldown.
- `tts_circuit_breaker.py:126-150` `record_failure`: callback đến trễ
  (`probe_id` đã rời `active_probe_ids`) là **no-op**; không cộng lại failure
  hay reset breaker đã OPEN.
- `tts_circuit_breaker.py:40-50` `_record_metric`: lấy
  `provider, locale = str(key[0]), str(key[-1])` — **không còn unpack cứng 4
  phần**. Key 5 phần (ElevenLabs: provider/account/model/voice/locale,
  tts_engine.py:915-922) và 4 phần (Gemini) đều phát metric được.

Kết luận: hai lỗi hạch toán breaker trong Mục 8 **đã được sửa**.

### 3.3 [ĐÃ SỬA — XÁC MINH BẰNG CODE] Nhánh autonomous không còn ghi đè speech Nhật bằng bản Việt đã cắt

Mục 10 cũ: observer gộp whitespace/cắt 360 ký tự, trả `rewritten=False`; nhánh
autonomous thấy text khác → ghi bản Việt vào `display_raw`+`speech_raw` → prepare
chặn language mismatch → câu bị nuốt. **Code hiện tại đã sửa:**

- `src/runtime/stage_contracts.py:231-258`: nhánh `autonomous` nay **chỉ** tính
  `intention_observation` và gắn vào payload làm quan sát. Comment ngay tại chỗ:
  "Observer chỉ tạo observation; KHÔNG được viết ngược vào display_raw,
  speech_raw hay utterance đã commit … vẫn giữ bản JP gốc để language guard
  kiểm tra độc lập." **Không còn** phép so `observation.text != display_raw`
  rồi overwrite.
- `src/runtime/intention_authority.py:30-31` `_clean(..., limit=360)` vẫn còn
  (vẫn cắt/gộp whitespace cho bản phân tích), nhưng kết quả **không** còn được
  ghi ngược vào raw public text ⇒ vô hại cho delivery.
- `src/runtime/stage_contracts.py:294-317`: khi contract `ja` nhưng tts_text
  chưa có kana/kanji (`needs_language_repair`), Stage **hạ cờ**
  (`can_translate=True`, `prelocalized=False`) để TTS localizer dịch ở bước
  audio, thay vì để câu Việt mang nhãn `ja` đi tới dispatch rồi bị chặn.

Kết luận: đường gây câm chủ đạo của Mục 10 **không còn đúng với code hiện tại**.

### 3.4 [CÒN NGUYÊN — ĐÚNG CHỖ] Guard ngôn ngữ phòng thủ ở dispatch

- `src/runtime/conversation/public_output_artifact.py:139-142`: nếu segment
  mang contract `language=ja` nhưng `tts_text` không có chữ Nhật →
  `raise RuntimeError('v03_speech_language_mismatch')`.
- Đây là **lưới an toàn cuối**, đúng theo nguyên tắc "không bỏ guard ngôn ngữ để
  che lỗi". Với fix 3.3, nhánh autonomous bình thường **không** còn đẩy câu Việt
  nhãn `ja` tới đây. Guard chỉ nên trip nếu localizer thất bại thật — khi đó câm
  là hệ quả của lỗi dịch, không phải lỗi hạch toán. Mức chắc chắn guard-còn-tồn-
  tại: **xác minh bằng code**; việc nó có trip trong phiên user hay không:
  **chưa xác minh** (cần trace per-session).

### 3.5 [NGUYÊN NHÂN TỨC THỜI CHÍNH CÒN LẠI — XÁC MINH BẰNG CODE] Preemption khi message mới đến

- Theo `2026-10-15-run-agent-loop-tts-audit.md` §2: ba delivery cuối bị
  **cancelled trước playback** khi message mới được xử lý; input "ô" không nằm
  trong backchannel whitelist → bị coi STEERING → `cancel_generation=True`,
  `cancel_audio=True`, VoiceManager yield (interrupts.py:10,22-30;
  incoming_dispatcher.py:134-164; voice_manager.py:208-224).
- `2026-10-15-run-agent-loop-tts-audit.md` §6 (cũ): `chat_cycle.py` hủy LLM
  generation **vô điều kiện** khi preempt. **Code HEAD hiện tại đã sửa:**
  `src/runtime/chat_cycle.py:36-66` `_preempt_for_classified_user_turn(*,
  cancel_audio, cancel_generation=True)` tách **hai quyền riêng** — comment ngay
  tại chỗ: "Âm thanh và generation là hai quyền riêng. Backchannel không được
  giết request Root/Writer đang suy nghĩ hoặc discovery đang chạy." Chỉ hủy
  generation khi `cancel_generation` True; chỉ hủy audio khi `cancel_audio`
  True. ⇒ khuyến nghị audit §6 **đã được thực hiện** (xác minh bằng code).
  Lưu ý: input bị phân loại STEERING (như "ô" trong audit) vẫn đặt **cả hai**
  cờ True nên vẫn hủy audio đang phát — đó là hành vi preempt có chủ đích, không
  phải lỗi hạch toán.
- Đây là nguyên nhân **tức thời** (một message mới hủy câu đang nói), không phải
  tích lũy. Nó nặng hơn về cuối chỉ vì về cuối latency tới-tiếng-đầu-tiên dài
  hơn (xem 4), nên có nhiều thời gian để một message mới chen vào trước khi audio
  kịp phát.

### 3.6 [CHƯA XÁC MINH] Breaker mở live do lỗi provider thật lặp lại

- Code cho phép breaker mở khi có **failure provider thật** lặp lại (threshold=3,
  tts_circuit_breaker.py:155-170). ElevenLabs từng có `RemoteDisconnected` thật
  (Mục 8/§3), Gemini fallback phát bù. Với fix 3.1/3.2, **cancel** không còn góp
  vào mở breaker; nhưng disconnect/429 thật vẫn góp. Việc breaker có mở live về
  cuối phiên hay không: **chưa xác minh** (cần log breaker state/metric per-session).

---

## 4. VÌ SAO "VỀ CUỐI TURN" MỚI NẶNG — tích lũy vs tức thời

**Phân biệt rõ:**

- **Chi phí tức thời (mỗi lượt):** Root luôn thinking `high` (2.3); localization
  + prepare + delivery; preemption khi có message mới (3.5). Những cái này không
  phụ thuộc "đã chat bao lâu".
- **Tích lũy (càng cuối càng nặng):**
  1. Session Root append-only phình dần (2.5); reconcile khi receipt flip resend
     cả cửa sổ.
  2. Prompt lớn hơn → request high-effort **chậm hơn**. Audit đo chat cuối phiên
     32–37s tới lúc chuẩn bị surface, ~54s tới audio đầu tiên
     (`2026-10-15-run-agent-loop-tts-audit.md` §2;
     `2026-10-15-1647-agent-loop-audit.md` "Các quan sát phụ"). Request Root cuối
     tăng 242k→284k byte.
  3. Chậm hơn ⇒ (a) dễ chạm deadline cha / dễ bị preempt bởi message mới (→ câm,
     3.5); (b) cửa sổ thời gian để lỗi-trước-delivery tích lại mà không có feedback
     (2.4) rộng hơn.

**Không có bằng chứng breaker "mở dần theo tích lũy cancellation"** trên code
hiện tại — vì cancellation đã **không còn** đếm vào breaker (3.1/3.2). Vậy giả
thuyết "breaker mở dần do hủy liên tiếp" trong brief: **bác bỏ ở mức code hiện
tại** (đúng với báo cáo cũ, nhưng code đã đổi). Cơ chế tích lũy đúng là **phình
context → latency → preempt/deadline**, không phải breaker.

---

## 5. HAI TRIỆU CHỨNG CHUNG GỐC HAY ĐỘC LẬP?

**Độc lập về cơ chế lõi, nhưng chia sẻ một chất xúc tác (context phình → latency).**

Bằng chứng "độc lập":
- "Hóa ngu" nằm ở tầng **prompt/compaction + feedback loop** (token_budget.py,
  root_session.py). "Mất tiếng" nằm ở tầng **delivery/preempt + localization**
  (chat_cycle/voice_manager/stage_contracts/public_output_artifact).
- Các fix TTS (3.1–3.3) không chạm gì tới `compress_system_message`; và ngược
  lại. Có thể có câm mà không ngu (preempt một câu đơn lẻ) và ngu mà không câm
  (persona bị nén nhưng audio vẫn phát).

Bằng chứng "chung chất xúc tác":
- `enforce_prompt_cap`/compaction (hóa ngu) kích hoạt mạnh hơn khi prompt lớn.
- Latency do prompt lớn (2.5) làm cửa sổ preempt rộng hơn (mất tiếng, 3.5).
- Cả hai cùng leo thang theo độ dài phiên vì cùng một session append-only
  (root_session.py).

Vậy: **giảm context phình (ổn định history projection, tránh reconcile toàn
cửa sổ khi chỉ receipt-status đổi) tấn công đồng thời chất xúc tác của cả hai**,
nhưng mỗi triệu chứng vẫn cần fix riêng ở tầng của nó.

---

## 6. KHUYẾN NGHỊ (không triển khai trong bước này)

Ưu tiên theo bằng chứng:

1. **Ổn định history projection (gốc chung).** Trong `root_session.py:279-321`,
   cập nhật trạng thái delivery bằng **identity ổn định** (gửi delta
   `delivery_updates` — đã có) thay vì để content flip phá overlap và rơi vào
   `recent_public_history_reconcile` resend cả cửa sổ. Mục tiêu: receipt
   pending→cancelled **không** làm resend 16–18 entries. Khớp khuyến nghị §5 của
   audit 00:19.
2. **Bơm feedback lỗi-trước-delivery vào Root (hóa ngu, 2.4).** Gắn kết quả
   writer_failed/prepare-reject (có run/move id) vào input Root ngay cả khi lỗi
   xảy ra trước delivery, để Root không tiến kế hoạch nhiều lượt dựa trên lượt
   chưa gửi. Khớp khuyến nghị audit 16:47 §2.
3. **Phân loại backchannel vs STEERING (mất tiếng, 3.5).** `chat_cycle.py` đã
   tách `cancel_audio`/`cancel_generation` (đã sửa). Việc còn lại là **phân loại
   đầu vào** ở ingress/VoiceManager: câu phụ họa ngắn (teencode/thiếu dấu, như
   "ô") không nên bị coi STEERING đặt cả hai cờ True và giết audio đang phát.
   Xử lý theo khuyến nghị audit 00:19 §2 (shared contract xử lý teencode/dấu
   câu), không chỉ thêm alias whitelist.
4. **Theo dõi compaction (hóa ngu, 2.1/2.2).** Thêm/kiểm metric khi
   `compress_system_message`/`_shrink_system_by_blocks` bỏ block persona/diary,
   và log `broker_degrade_reason` + `[LLM PREFLIGHT]`, để biết nó có thực sự bật
   trong phiên user hay không trước khi thay đổi cap. Hiện **chưa có bằng chứng**
   nó đã bật live — đừng nới cap mù.
5. **Nhịp autonomous "không nhắn dồn" (hóa ngu/hành vi).** Định nghĩa rõ quy tắc
   nhịp cho autonomous timer; `wait_user` hủy continuation lease nhưng timer mới
   vẫn gọi Root (audit 16:47 §2). Không tắt chủ động toàn bộ.

---

## 7. CÁI GÌ CHƯA XÁC MINH ĐƯỢC (ranh giới bằng chứng)

- Chưa có log/trace của **phiên user mới** mà họ than phiền; mọi kết luận "đã bật
  live" đều dựa trên hai audit cũ (checkout `e9cc50e5`). Không khẳng định phiên
  mới tái hiện đúng như audit cũ.
- `enforce_prompt_cap`/`compress_system_message` **có bật trong phiên user** hay
  không: **chưa xác minh** (thiếu `[LLM PREFLIGHT]` / broker_degrade metric của
  phiên).
- Root chạy ở **lane** nào thực tế (`root_conversation` nới cap 90k, hay
  `transport`/`chat` siết 4800): **chưa xác minh** cho phiên user.
- (Đã đóng) `chat_cycle.py` HEAD đã được đọc lại và xác nhận tách
  `cancel_audio`/`cancel_generation` — xem 3.5. Vẫn **chưa xác minh** đường
  ingress/VoiceManager phía trên đặt hai cờ đó như thế nào cho từng loại input
  trong phiên user cụ thể.
- Breaker TTS có **mở live** về cuối phiên hay không: **chưa xác minh** (cần
  metric/log breaker state per-session).
- Chỉ so SHA-256 **sáu file lõi** dev-vs-portable; **chưa** so toàn bộ cây file,
  nên không khẳng định mọi file portable trùng dev.
- Nội dung reply của Root có thực sự "ngu đi" (ngoài việc mất block persona khi
  nén) hay không là đánh giá chất lượng ngôn ngữ — **không đo được** từ source;
  cần so sánh output đầu phiên vs cuối phiên trên cùng input.
