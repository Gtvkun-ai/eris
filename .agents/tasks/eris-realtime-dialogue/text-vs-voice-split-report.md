# Báo cáo: vì sao chat text hiện ra nhưng voice không đến (điều tra read-only)

Ngày điều tra: 2026-10-18. Phạm vi: **chỉ đọc source**, không sửa code, không
restart, không gọi provider live. Mọi claim có trích `file:line` của checkout
hiện tại `c:/Users/Gtvkun/Documents/GitHub/eris`.

Phân tầng bằng chứng theo AGENTS.md: **[REQ]** yêu cầu sản phẩm, **[CODE]** đọc
source đã xác minh trong checkout này, **[HIST]** trạng thái lịch sử từ knowledge
docs (có thể đã bị đính chính), **[LIVE]** quan sát từ log phiên 2026-10-18 do
user cung cấp (chưa tự xác thực file log).

---

## 1. Câu trả lời tóm tắt

**Có, text bubble và audio KHÔNG atomic với nhau dưới preemption.** Text hiển
thị và audio đi theo **hai đường phát khác nhau, ở hai thời điểm khác nhau** trong
cùng một lượt:

- **Text hiển thị (bubble/Live2D overlay)** được phát **ngay tại commit**, qua
  `stage_segment` event trên `StageEventBus`, **trước khi** TTS bắt đầu synth.
  Event này mang `display_text` và được mirror thẳng tới renderer Live2D
  (UDP :4252) tức thì. [CODE]
- **Audio** chỉ được dispatch **sau đó**, bất đồng bộ, và chỉ "đến" khi
  ElevenLabs/Gemini trả WAV và phát `audio_start`. [CODE]

Khi một user turn mới `enter_chat_mode` chen vào giữa hai thời điểm đó, nó
`supersede_all()` TTS (hủy audio đang synth) nhưng **không thu hồi** được
`stage_segment` đã bắn đi. Kết quả: bubble đã nằm trên màn hình, audio bị
`audio_cancelled`, Live2D nhận edge `interrupted`, trace ghi
`tts=cancelled outcome=cancelled`. Đây **đúng** với hình dạng log user báo. [CODE+LIVE]

Nói cách khác: **publish text không được rollback khi audio bị hủy.** Preemption
chỉ hủy được những gì chưa phát (audio còn đang buffer) chứ không hủy được stage
segment đã gửi.

---

## 2. Thứ tự chính xác trong một lượt committed (deliverable #1)

Tất cả nằm trong `RuntimeConversationDeliveryAdapter.deliver()` →
`_send_decision_to_body()`.

### 2.1 Delivery adapter gọi transport một lần
`src/runtime/conversation/delivery_adapter.py:182-206` — adapter guard preemption
(`v03_preempted_before_dispatch`) rồi gọi `send = self.host._send_decision_to_body`.
Đây là **một** cửa phát ngôn duy nhất; cả text lẫn audio đều đi qua hàm này.

### 2.2 Bên trong `_send_decision_to_body`, thứ tự phát là:
File `src/runtime/public_output_runtime.py`:

1. **`send_panel_payload()`** — `public_output_runtime.py:805` (lane panel, không
   liên quan bubble/audio, luôn hiện ngay).
2. **`send_stage_protocol_segments()`** — `public_output_runtime.py:808`. Đây là
   **điểm phát TEXT ra overlay**. Comment ngay trên dòng này (806-808) nói rõ:
   *"Show the committed public surface immediately; TTS playback can lag or fail
   independently, but chat should not look stuck after text exists."* Hàm này
   (`public_output_runtime.py:542-570`) gọi `bus.emit(stage_segment_event(frame,...))`.
3. Nếu `sync_text` tắt (legacy): `send_text_payload("immediate")` —
   `public_output_runtime.py:810-812`.
4. **Chỉ sau đó** TTS mới được dispatch: `dispatcher.dispatch_tts(stage_frames,
   ..., on_first_start=on_first_audio_start, on_event=handle_tts_event)`
   (nhánh `if _tts ... bool(payload.get("should_speak")) and stage_frames`,
   `public_output_runtime.py:813` trở đi). Audio là **bất đồng bộ**; `audio_start`
   chỉ đến khi provider trả WAV.

### 2.3 `stage_segment` thực sự là nguồn của bubble text
- `stage_segment_event()` đặt `display_text` = thứ "UI nên hiện", `tts_text` chỉ
  để debug/sync: `src/runtime/stage_protocol_adapter.py:33-64` (kèm docstring
  36-38).
- `StageEventBus.emit()` gửi payload qua `transport.send_json` **và** mirror
  thẳng tới Live2D renderer qua UDP ngay lập tức:
  `src/runtime/stage_event_bus.py:54-73` và `_mirror_live2d()` 89-104. Docstring
  45-50 ghi rõ mirror này để "miệng không đứng im như ảnh PNG" — tức là đường
  realtime độc lập với Godot forward.

### 2.4 Đường TEXT thứ hai (UDP chat body) bị hoãn tới audio
- `sync_text_with_tts_enabled()` mặc định **bật** (`ERIS_TTS_SYNC_TEXT=1`):
  `src/runtime/tts_sync_policy.py:19-22`.
- Khi bật, `send_text_payload()` (UDP body, `transport.send_json(body_payload)`,
  def tại `public_output_runtime.py:571`) chỉ chạy khi `audio_start`
  (`on_first_audio_start`, nhánh `if sync_text: send_text_payload("audio_start")`),
  HOẶC khi audio fail/cancel qua `tts_event_releases_deferred_text` (nhánh cuối
  `handle_tts_event`), HOẶC khi timeout 30s (`schedule_text_payload_release`, def
  tại `public_output_runtime.py:614`; `_DEFAULT_TEXT_SYNC_TIMEOUT_SECONDS=30.0`
  tại `tts_sync_policy.py:14`).

**Điểm mấu chốt:** `sync_text` CHỈ hoãn đường UDP body thứ hai (bước 3). Nó
**KHÔNG** hoãn `stage_segment` (bước 2). Bubble overlay được vẽ từ stage_segment,
nên nó xuất hiện ngay ở commit dù `sync_text` bật.

### 2.5 Test trong repo xác nhận bất đối xứng này
`src/tests/test_basic_settings_main_brain.py:249-355`
(`test_send_decision_to_body_emits_stage_text_before_waiting_for_tts`), chạy với
`ERIS_TTS_SYNC_TEXT=1`, assert chính xác hai điều:
- stage bus **CÓ** event `stage_segment` với `display_text == "bubble text"`
  (dòng 348-353);
- transport UDP body **KHÔNG** có message text đó (dòng 354).

Tức là: với sync bật, text đã ra overlay (stage) nhưng chưa ra UDP body. Hành vi
"text ra sớm hơn audio" là **thiết kế có chủ đích và được test khóa lại**. [CODE]

---

## 3. Preemption hủy audio nhưng không rollback text (deliverable #2)

### 3.1 enter_chat_mode hủy những gì
`src/runtime/chat_cycle.py:36-67` — `_preempt_for_classified_user_turn`:
- `cancel_audio=True` → `lifecycle_for(self).interrupt(reason="new_user_input")`
  (public_lifecycle.py:110-116) **và** `_supersede_tts_for_new_user_turn(...)`
  (chat_cycle.py:45-52).
- `cancel_generation=True` (mặc định) → `preempt_discovery(reason="enter_chat_mode")`
  và `llm_service.cancel_pending_requests(reason="enter_chat_mode")`
  (chat_cycle.py:54-66). Dòng `[LLM CANCEL] epoch=2 reason=enter_chat_mode` user
  thấy phát từ `src/llm/service.py:224`.

### 3.2 supersede_all làm gì với audio
`_supersede_tts_for_new_user_turn` → `tts.supersede_all(reason=...)`:
`src/runtime/public_output_runtime.py:183-191`. `supersede_all` tăng
`_speech_epoch`, xóa `_speech_turn_id`, rồi `_cancel_backends(only_interruptible=False)`:
`src/runtime/tts_engine.py:3122-3128` và `_cancel_backends` 3076-3103 (hủy cả
task-manager lẫn worker). Task-manager phát lifecycle `audio_cancelled`
(reason `speech_superseded`/`stale_turn_*`): `src/runtime/tts_task_manager.py:337-388`.

### 3.3 Ai thu hồi text? → Không ai
Không có đường code nào gửi "un-show"/rollback cho `stage_segment` đã emit.
Cụ thể:
- `StageEventBus` cố ý "mỏng": không queue, không retry, không rollback —
  `stage_event_bus.py:30-32` (docstring). Một khi `emit()` đã `send_json` +
  `_mirror_live2d`, payload đã rời tiến trình.
- Khi audio bị hủy, thứ duy nhất đi tới overlay là **edge Live2D `interrupted`**
  (map `audio_cancelled → "interrupted"` trong `live2d_edge` của
  `handle_tts_event`, `public_output_runtime.py:748-756`). Đây là tín hiệu "ngắt
  animation miệng", **không phải** lệnh "xóa bubble text".
- Public lifecycle chuyển `INTERRUPTED` (nhánh `elif event_type ==
  "audio_cancelled"` trong `handle_tts_event`; public_lifecycle.py:24-34, 86) —
  cũng là state máy, không xóa text đã hiển thị.

### 3.4 Hai kết cục của đường UDP body thứ hai dưới cancel
`handle_tts_event` mở đầu bằng `if not v03_current(): ... return`
(`public_output_runtime.py:678-707`). Vì `supersede_all` + `cancel_generation`
làm generation/epoch cũ stale, có hai nhánh:

- **Nếu callback `audio_cancelled` tới khi lượt ĐÃ stale** (v03 không current):
  hàm return sớm, chỉ ghi receipt `cancelled` (`note_public_delivery_outcome`,
  685-704). **Đường UDP body thứ hai không bao giờ được release.** Nhưng bubble
  overlay **đã hiện từ stage_segment** ở bước 2.2 → user thấy text, không nghe
  audio. Khớp log. [CODE]
- **Nếu `audio_cancelled` tới khi lượt còn current**: tới nhánh
  `tts_event_releases_deferred_text(audio_cancelled)=True`
  (`tts_sync_policy.py:35-42`) → `send_text_payload("audio_failed")` (nhánh cuối
  `handle_tts_event`) → UDP body text cũng được bắn ra. Khi đó
  **cả hai** đường text đều hiện, audio vẫn hủy.

Cả hai nhánh đều cho cùng triệu chứng: **text thấy, audio không.** Sự khác biệt
chỉ là text đến overlay qua một hay hai đường. **Không nhánh nào rollback text.** [CODE]

### 3.5 Kết luận atomicity
Text-publish (stage_segment, commit-time) và audio-delivery (async TTS) **không
atomic** dưới preemption. Guard preemption chỉ bảo vệ **trước** dispatch
(`v03_preempted_before_dispatch`, delivery_adapter.py:177-182,196-200) và chặn
**đường UDP body thứ hai** chạy sau khi stale. Nó **không** bảo vệ được
`stage_segment` đã emit ở bước §2.2, vì bước đó chạy trước và không thể thu hồi. [CODE]

---

## 4. Vì sao lượt này text hiện mà audio không (deliverable #3)

Hình dạng lượt user báo (log 2026-10-18 ~10:07) [LIVE, ánh xạ sang CODE]:

1. Writer commit (`commit=1`), delivery `delivery:5522b375...` bắt đầu →
   `mark_delivery_started` (kernel.py:841-860), rồi `deliver()` →
   `_send_decision_to_body`.
2. Trong `_send_decision_to_body`, **`send_stage_protocol_segments()` chạy ngay**
   (public_output_runtime.py:808) → `stage_segment` với `display_text` ra overlay
   + mirror Live2D. **Bubble xuất hiện ở đây.** TTS vừa mới `AUDIO_BUFFERING`,
   `on_first_start`/`audio_start` **chưa** xảy ra.
3. User gõ câu mới → `_enter_chat_cycle` log *"Entered chat mode; pending user
   input, audio kept until interrupt classification"* (chat_cycle.py:38); sau khi
   phân loại, `_preempt_for_classified_user_turn(cancel_audio=True,
   cancel_generation=True)`.
4. `supersede_all` hủy TTS đang synth (tts_engine.py:3122-3128) → task-manager
   phát `audio_cancelled` (tts_task_manager.py:352-357) → Live2D edge
   `interrupted` (public_output_runtime.py:750, "recv=interrupted" user thấy).
5. `cancel_generation` → `[LLM CANCEL] epoch=2 reason=enter_chat_mode`
   (service.py:224).
6. Delivery settle `cancelled`, trace terminal
   `commit=1 tts=cancelled outcome=cancelled`
   (autonomous_trace.py:164-179 compact logger; kernel.py:869-875
   `tts_cancelled`).

Vì bubble đã được phát ở **bước 2** (trước khi audio start), còn audio bị hủy ở
**bước 4** (trước khi có `audio_start`), nên **text tồn tại, audio biến mất**.
Đây là hệ quả trực tiếp của việc hai kênh không atomic, **không phải** lỗi
provider ElevenLabs (khớp với nhận định brief: không có disconnect/429/5xx cho
lượt này). [CODE+LIVE]

---

## 5. Đối chiếu với knowledge docs — kết luận lịch sử liên quan (deliverable #4)

- **[REQ]** "Eris phải có âm thanh khi nói" và "bubble Việt + voice Nhật có hợp
  đồng riêng" — mục 1 & 11 của
  `docs/knowledge/2026-10-14-eris-runtime-lessons.md`. Triệu chứng này **vi phạm
  REQ**: một lượt committed hiển thị text mà không phát tiếng. User nói đúng khi
  đòi hai cái phải ra cùng nhau.
- **[HIST→CODE xác nhận còn đúng]** "ChatCycle chưa nhận cancel_generation" (mục
  8 lessons; run-audit mục 6, `chat_cycle.py:37-61`). Checkout hiện tại **đã**
  tách `cancel_audio`/`cancel_generation` và `_preempt_for_classified_user_turn`
  nhận cả hai, mặc định `cancel_generation=True` (chat_cycle.py:36-66). Tức gap
  lịch sử này đã được vá ở phần signature; nhưng điều đó **không** giải quyết
  bất đối xứng text/audio — nó chỉ bảo đảm generation bị hủy, càng khiến nhánh
  "lượt đã stale" ở §3.4 xảy ra, nên UDP body thứ hai thường **không** được
  release, trong khi stage_segment vẫn đã hiện.
- **[HIST, cảnh báo]** "cancel bị tính thành provider failure, có thể mở circuit
  breaker" (lessons mục 8; run-audit mục 3, tts_engine.py quanh 1073-1103,
  tts_circuit_breaker.py). Đây là **vấn đề khác** (hạch toán breaker), **không**
  phải nguyên nhân text-vs-voice split của lượt này. Không trộn hai thứ: lượt
  này audio bị hủy do preemption, không do breaker. Chưa xác thực breaker mở live.
- **[HIST]** "fallback filler JA không bảo đảm mọi câu có tiếng" (lessons mục 2,
  "Fail-soft"). Phù hợp: ngay cả khi TTS khỏe, preemption vẫn làm mất audio của
  lượt bị chen.
- **[HIST→đính chính]** Bảng mục 5 lessons: "Fallback chỉ hiện text là phương án
  đã chốt" đã bị user **bác**; phương án cuối giữ voice. Vì vậy **không** được
  coi triệu chứng "chỉ còn text" là trạng thái chấp nhận được.

Phân tầng: các dòng `file:line` ở §2–§4 là **[CODE]** đã đọc trong checkout này.
Hình dạng log bước-6 là **[LIVE]** do user mô tả, tôi ánh xạ sang code chứ chưa
mở file log phiên 2026-10-18 để tự đếm dòng.

---

## 6. Giới hạn chứng minh tĩnh & bằng chứng live cần thêm (deliverable #5)

Chứng minh được **từ source**: hai kênh phát ở hai thời điểm; stage_segment phát
trước và không rollback; preemption hủy audio; test khóa hành vi "text trước
audio". Điều này đủ để giải thích triệu chứng.

**Chưa chứng minh được chỉ bằng đọc tĩnh** (cần trace/event live để chốt nhánh
chính xác):
1. Lượt đó rơi vào **nhánh §3.4 nào** — `audio_cancelled` tới khi lượt đã stale
   (chỉ stage_segment hiện) hay còn current (cả UDP body cũng hiện). Cần log
   `handle_tts_event` + thứ tự `v03_current()` tại thời điểm callback.
2. Thời điểm tương đối chính xác giữa `stage_segment` emit và
   `supersede_all`/`audio_cancelled` (cần timestamp của hai event trong cùng file
   `eris_observability.jsonl`/`autonomous_trace.jsonl`).
3. `audio_start` có **từng** xảy ra trước khi hủy không (nếu có, một phần audio
   đã phát — khác với "audio hoàn toàn không đến"). Brief nói không có
   `audio_playback_started`, cần xác nhận trên trace của chính `delivery:5522b375`.

Cách xác nhận: lọc `autonomous_trace.jsonl` theo `trace_id=5522b375...` và đọc
chuỗi event `tts_dispatch → audio_* → outcome`; đối chiếu timestamp
`stage_segment` với `audio_cancelled`.

---

## 7. Khuyến nghị (không triển khai — chỉ đề xuất)

Mục tiêu theo [REQ]: text và voice của **một lượt committed** phải đồng xuất hiện,
hoặc cùng bị thu hồi. Các hướng (chưa code, cần quyết định thiết kế riêng):

1. **Hoãn stage_segment text giống UDP body.** Hiện `send_stage_protocol_segments`
   chạy vô điều kiện ở commit (public_output_runtime.py:839). Có thể gate phần
   **display_text** của stage_segment sau `audio_start` (dùng chính cơ chế
   `sync_text`/`send_text_payload`), chỉ giữ phần motion/show_plan chạy sớm nếu
   cần animation. Rủi ro: Live2D/overlay có thể cần segment sớm để chuẩn bị; phải
   tách "text hiển thị" khỏi "chuẩn bị sân khấu".
2. **Thêm rollback khi INTERRUPTED trước audio_start.** Khi lifecycle đi
   `CONTENT_COMMITTED/AUDIO_BUFFERING → INTERRUPTED` mà **chưa** qua `SPEAKING`,
   phát một stage event "clear_bubble/retract" để overlay gỡ text chưa từng có
   tiếng. Cần StageEventBus/renderer hỗ trợ edge thu hồi (hiện chưa có —
   stage_event_bus.py:30-32 nói bus không rollback).
3. **Giữ text nếu đó là lựa chọn sản phẩm**, nhưng khi đó phải **bảo đảm audio**
   cho lượt bị chen (ví dụ cho phép phát nốt audio ngắn trước khi nhường) — điều
   này mâu thuẫn với barge-in UX, nên cần user quyết định ranh giới.

Khuyến nghị kỹ thuật an toàn nhất, ít đổi hành vi barge-in: **hướng (1)** — đưa
display_text của stage_segment vào cùng gate `audio_start` như UDP body, để một
preemption trước `audio_start` làm **cả hai** kênh text đều chưa hiện. Việc này
cần đọc thêm renderer Godot/Live2D để chắc overlay không phụ thuộc stage_segment
sớm cho mục đích khác.

---

## Phụ lục: trích dẫn nguồn chính

- `src/runtime/chat_cycle.py:36-67` — enter_chat_mode, tách cancel_audio/cancel_generation.
- `src/runtime/conversation/delivery_adapter.py:177-206` — cửa phát duy nhất, guard preempt.
- `src/runtime/public_output_runtime.py:542-570` (send_stage_protocol_segments),
  `571-613` (send_text_payload), `614-625` (schedule_text_payload_release),
  `678-808` (handle_tts_event def + call site), `805-812` (thứ tự panel/stage/text),
  `813+` (nhánh TTS dispatch).
- `src/runtime/tts_sync_policy.py:14-42` — mặc định sync bật; release-on-fail/cancel.
- `src/runtime/stage_protocol_adapter.py:33-64` — stage_segment mang display_text.
- `src/runtime/stage_event_bus.py:30-32,54-104` — bus mỏng, emit + mirror Live2D, không rollback.
- `src/runtime/tts_engine.py:3076-3128` — supersede_all/_cancel_backends.
- `src/runtime/tts_task_manager.py:337-388` — phát audio_cancelled.
- `src/runtime/public_lifecycle.py:24-34,66-116` — state machine INTERRUPTED/DEGRADED.
- `src/runtime/conversation/kernel.py:841-875` — mark_delivery_started/settle (tts_cancelled).
- `src/llm/service.py:224` — `[LLM CANCEL] epoch=%d reason=%s`.
- `src/runtime/ai_orchestrated/autonomous_trace.py:164-179` — public trace compact (commit/tts/outcome).
- `src/tests/test_basic_settings_main_brain.py:249-355` — test khóa "stage text trước, UDP body sau".
