# Eris hiện trạng & điểm yếu trên đường tiến tới đối thoại thời gian thực

Ngày điều tra: 2026-10-17. Phạm vi: đọc source trong checkout
`c:/Users/Gtvkun/Documents/GitHub/eris` (read-only, không chạy live, không sửa code).
Mục tiêu người dùng: nâng Eris thành **hệ thống đối thoại thời gian thực**
(full-duplex, nghe–nghĩ–nói chồng lấn) để hai bên trò chuyện trôi chảy 10–15 phút
mà không thấy mình đang luân phiên "gửi câu hỏi rồi chờ AI trả lời".

Ký hiệu bằng chứng:
- `[CODE]` = đọc trực tiếp trong source, trích file + dòng/symbol.
- `[SUY LUẬN]` = suy ra từ cấu trúc code, chưa có log/live xác nhận.
- `[KHÔNG TÌM THẤY]` = tìm nhưng không có trong repo.

Lưu ý theo AGENTS.md: tài liệu runtime-lessons phân biệt yêu cầu / thiết kế /
trạng thái lịch sử; một số kết luận cũ đã bị đính chính. Báo cáo này đối chiếu
với code hiện tại, không coi báo cáo cũ là fact tuyệt đối.

---

## 1. Tóm tắt điểm đau lớn nhất (3–5 gạch đầu dòng)

- **Không có tai.** Toàn bộ input là **text** gửi qua UDP message `type=chat`.
  Không có module mic / VAD / ASR / streaming STT nào trong repo
  (`[KHÔNG TÌM THẤY]` getUserMedia, MediaRecorder, whisper, speech_to_text,
  SpeechRecognition). Vì vậy "nghe khi đang nói", "nghe streaming" và
  "nhận diện lượt nói bằng âm thanh" **chưa tồn tại ở tầng cảm giác** — mọi cơ
  chế turn-taking hiện có chỉ kích hoạt khi đã có *text hoàn chỉnh của một lượt*.

- **Kiến trúc nền là request–response tuần tự theo lượt.** `ConversationKernel`
  là single authority: mỗi `user_turn` tăng `generation`, hủy lease continuation,
  discard delivery cũ, rồi chạy tuần tự Root → Writer → delivery. `_chat_processing`
  là một cờ khóa: lượt tiếp theo đến giữa chừng bị **xếp hàng (burst queue)**,
  không xử lý song song. Đây là rào cản căn bản nhất cho nghe–nghĩ–nói chồng lấn.

- **Có barge-in, nhưng là "text barge-in" theo lượt, không phải audio barge-in
  thời gian thực.** Khi message `chat` mới tới, hệ thống phân loại
  backchannel/stop/steering rồi mới hủy TTS + generation. User phải *gửi xong một
  dòng text* thì Eris mới biết bị chen; không có đường cắt lời ngay khi user vừa
  "bật tiếng".

- **Đã có khung turn-taking chờ sẵn phần cứng chưa có.** `VoiceManager` +
  `user_control_runtime` đã hiện thực state machine `on_vad_start / on_asr_partial
  / on_asr_final`, phân biệt backchannel vs correction, mở "tentative interrupt".
  Nhưng **không có producer** phát các event `vad_start/partial_asr/final_asr` —
  đây là hợp đồng protocol frontend bỏ trống. Phần khó nhất (nghe) chưa được nối.

- **Chưa có đường phản hồi NHANH riêng cho "Hả?/Ừm?/Rồi sao?".** Backchannel của
  *user* được nhận ra để **giữ** audio Eris, nhưng Eris không có fast-path để tự
  *phát* một backchannel ngắn mà bỏ qua vòng Root → Writer → localize → TTS. Mọi
  phát ngôn công khai đều đi qua cùng pipeline dài.

---

## 2. Bảng 8 khả năng

| # | Khả năng | Trạng thái | Bằng chứng (file + dòng/symbol) |
|---|---|---|---|
| 1 | Nghe khi đang nói (barge-in) | **YẾU** (chỉ text-level) | `incoming_dispatcher.py:_handle_chat` (≈124–167) phân loại interrupt rồi gọi `_preempt_for_classified_user_turn`; `chat_cycle.py:_preempt_for_classified_user_turn` (≈37–72) gọi `lifecycle.interrupt` + `_supersede_tts_for_new_user_turn`. `[CODE]` Cần có *text* trước; không có barge-in bằng tiếng. `[SUY LUẬN]` |
| 2 | ASR / nghe streaming | **THIẾU** | `[KHÔNG TÌM THẤY]` mic/VAD/ASR/STT producer. Input = UDP `type=chat` text: `incoming_dispatcher.py:_routes` (≈104–122), `chat_cycle.py:_poll_ready_chat_events` (≈ "msg.get('type')=='chat'"). `[CODE]` |
| 3 | Turn-taking / nhận diện lượt | **YẾU** (scaffold, không có nguồn tín hiệu) | `voice_manager.py` (toàn file: `on_vad_start/on_asr_partial/on_asr_final`), `user_control_runtime.py:_handle_voice_observation_event` (≈297–360) tiêu thụ `vad_start/partial_asr/final_asr`. Quyết định "đến lượt Eris" nằm ở `kernel.py` (generation + `RunPhase`) và `interaction_clock` (`speech_floor_busy`). `[CODE]` Không ai phát các event đó → `[SUY LUẬN]` turn-taking thực tế chỉ dựa trên ranh giới message text. |
| 4 | Phản hồi ngắn / backchannel (đường nhanh của Eris) | **THIẾU** | `conversation/interrupts.py:_BACKCHANNELS` (≈15–19) chỉ dùng để nhận backchannel *của user* và **giữ** audio (`incoming_dispatcher.py` ≈141–150). `[KHÔNG TÌM THẤY]` fast-path để Eris *tự phát* "Hả?/Ừm?" bỏ qua Root→Writer→TTS. Mọi phát ngôn đi qua `delivery_adapter.py:deliver` + `tts_task_manager`. `[CODE]` |
| 5 | Chuẩn bị lượt tiếp (speculative) | **HIỆN CÓ** (nhưng theo lượt, không incremental) | `continuation.py:offer_speculative/take_speculative` (≈126–148), `kernel.py:prepare_continuation_candidate` (≈ "prepare_only=True") + `_deliver_prepared_continuation`. Nấu sẵn *cả câu* gắn vào 1 lease/generation; user turn mới làm invalid. `[CODE]` |
| 6 | TTS ngắt được giữa chừng | **HIỆN CÓ** | `tts_task_manager.py:cancel_current` (≈ dùng `cancel_event`/`playback_stop`), per-segment `_speech_task_is_current`, `voice_manager.py:_cancel_audio` gọi `supersede_all`. Breaker đã tách hủy khỏi lỗi: `tts_circuit_breaker.py:record_cancelled`; `tts_engine.py` raise `TtsCancelledError` *trước* `record_failure` (≈1080–1124, 1827–1986). `[CODE]` |
| 7 | Giữ mạch sau khi bị ngắt | **YẾU** | Continuation lease chỉ khôi phục *quyền re-evaluate*, **không** lưu câu đang định nói: `continuation.py` docstring (≈1–17) + `_speculative` chỉ ở RAM, `schedule()` với `WAIT_USER` thì `cancel_session`. `interrupt_reaction_policy.py` sinh context cho lượt sau, nhưng "intended move" cũ không được bảo toàn. `[CODE]` |
| 8 | Kiến trúc nền (rào cản căn bản) | **RÀO CẢN** | `kernel.py:_handle_event_once`: user_turn → `generation+1`, `cancel_session`, `_discard_session_deliveries`; `handle_event` serialize theo `event_id` (`_events_inflight`); `chat_cycle.py:_run_chat_cycle` dùng `_chat_processing` + burst queue. Một event xử lý trọn vẹn tại một thời điểm. `[CODE]` |

---

## 3. "Mô phỏng Eris đang yếu như nào" (thuật lại dựa trên code thật)

**Bối cảnh:** input hiện tại là text. Giả định đã có một frontend gõ/gửi text
(và TTS phát tiếng Eris qua Live2D body UDP). Diễn tiến thật theo code:

**Cảnh A — User chen lời khi Eris đang nói.**
Eris đang phát một lượt nhiều câu qua `TtsTaskManager` (các segment synth song
song, phát theo thứ tự — `tts_task_manager.py:_playback_loop`). User muốn chen.
Nhưng hệ thống **chỉ biết** khi user *gửi xong một dòng text* `type=chat`. Lúc đó
`_handle_chat` gọi `classify_interrupt`:
- Nếu là backchannel ("ừ", "đúng rồi", "ok"…) **và** `speech_floor_busy`, hệ
  thống giữ nguyên audio, không tạo lượt thứ hai (`incoming_dispatcher.py` ≈141–150).
  Đây là hành vi đúng và mượt.
- Nếu là "stop"/"khoan"/"dừng" hoặc câu có nghĩa (steering), hệ thống hủy audio +
  hủy generation, tăng `generation` ở kernel, discard delivery cũ, rồi chạy lượt
  mới.
→ Kết luận: user **không thể cắt lời bằng tiếng nói** đang khi Eris đọc; phải gõ/gửi
một message hoàn chỉnh. Độ "tức thì" phụ thuộc user gõ nhanh hay chậm, không phải
độ trễ audio. `[CODE] + [SUY LUẬN]`

**Cảnh B — User ngập ngừng ("Ý tôi là... ờ...").**
Không có VAD/ASR nên hệ thống **không phân biệt được** "user đang nghĩ" với "user
đã nói xong". Với text: khi chưa có message mới, Eris coi như tới lượt mình. Nếu
user gõ rời rạc nhiều dòng sát nhau, `_merge_rapid_chat_burst`
(`chat_cycle.py`, cửa sổ `rapid_burst_window` ≈1.2s) gom lại thành một lượt. Đây
là xử lý "ngập ngừng" duy nhất, và nó thao tác trên **text đã gửi**, không trên
nhịp nói. `[CODE]`

**Cảnh C — Muốn bật "Hả?" thật nhanh.**
Eris không có đường tắt. Để thốt ra một tiếng ngắn, vẫn phải: Root quyết move →
Writer realize bề mặt → (chế độ Nhật) localize → `TtsTaskManager` synth → phát.
`[CODE]` `delivery_adapter.py:deliver` + `tts_task_manager`. Thêm nữa,
`_prebuffer_window` cố ý **đợi** một cửa sổ segment sẵn sàng trước khi mở loa để
tránh dead-air, nên ngay cả câu ngắn cũng gánh startup của cả pipeline. Hệ quả:
không có nhịp "ậm ừ" tức thời như người thật. `[CODE] + [SUY LUẬN]` (chưa đo live
độ trễ thực tế của một câu ngắn).

**Cảnh D — Sau khi bị ngắt, Eris còn nhớ định nói gì không?**
Phần lớn là **không**. Continuation lease chỉ cho Eris *quyền tự đánh giá lại và
có thể nói tiếp*, nhưng khi user turn mới tới thì `generation` đổi và candidate
speculative bị bỏ (`continuation.py:schedule` + `_speculative` chỉ RAM). "Ý định
cũ" không được lưu như một open-loop để quay lại. `interrupt_reaction_policy` có
thể nhắc "đừng làm màu chuyện bị chen", nhưng không giữ nội dung Eris đang định
triển khai. `[CODE]`

---

## 4. Gợi ý hướng nâng cấp (mơ hồ được) — ghép thêm vs xây tầng mới

Đánh dấu **[GHÉP THÊM]** = tận dụng bộ máy sẵn có; **[TẦNG MỚI]** = phải xây lớp
chưa tồn tại.

- **[TẦNG MỚI] Tai streaming (VAD + ASR partial).** Đây là mảnh thiếu lớn nhất và
  là tiền đề cho mọi thứ "thời gian thực". Cần một nguồn audio (mic) + VAD +
  ASR phát event `vad_start/partial_asr/final_asr` đúng hợp đồng mà `VoiceManager`
  đã chờ. Tin tốt: **giao diện tiêu thụ đã có sẵn** (`user_control_runtime`,
  `voice_manager`), nên phần runtime turn-taking cơ học phần lớn là ghép nối.

- **[GHÉP THÊM] Audio barge-in sớm.** Khi có `vad_start`, gọi `interrupt_signal`/
  tentative interrupt (đã có) để *giảm gain/duck* hoặc dừng mềm TTS trước khi có
  transcript, thay vì đợi text hoàn chỉnh. Cơ chế hủy TTS per-segment
  (`cancel_current`, `supersede_all`) đã đủ mạnh; chỉ cần kéo trigger lên sớm hơn.

- **[TẦNG MỚI / GHÉP THÊM] Fast-path backchannel của Eris.** Một đường phát ngôn
  rất ngắn ("Ừm?", "Rồi sao?", "Nghe đây") **không** đi qua Root→Writer→localize.
  Có thể dựng như một micro-lane: catalog câu ngắn + TTS preset/cache (hạ tầng
  cache WAV đã có trong `tts_task_manager`), do Root chỉ cần "ra tín hiệu" chứ
  không soạn lời. Phần phát là [GHÉP THÊM]; phần cho Root quyền chọn fast-path là
  [TẦNG MỚI] nhỏ.

- **[TẦNG MỚI] Incremental dialogue (nghe–nghĩ–nói chồng lấn).** Đây là thay đổi
  kiến trúc lớn: hiện Root chỉ chạy khi có event trọn vẹn và kernel xử lý tuần
  tự. Incremental cần Root/Writer tiêu thụ **ASR partial** và chuẩn bị/bắt đầu
  nói khi "đủ ngữ cảnh", cập nhật hoặc dừng khi có thông tin mới. Speculative
  continuation hiện có là *tiền đề* nhưng chưa đủ: nó nấu **cả câu theo lượt**,
  không phải phát dần theo input tăng dần.

- **[GHÉP THÊM] Giữ mạch sau ngắt (intended move / open loops).** Khi preempt,
  lưu lại "ý định đang dở" (intent + vài gạch đầu dòng) vào một bộ nhớ ngắn hạn
  để lượt sau Root có thể chủ động quay lại ("khoan, nãy tôi đang định nói…").
  Điểm móc tự nhiên: mở rộng `ContinuationLease`/`interrupt_reaction_policy` thay
  vì bỏ sạch candidate khi đổi generation.

- **[GHÉP THÊM] Ngưỡng chủ động tự do hơn nhưng bám cá tính** (theo ý user ở các
  message gốc). Đã có continuation `after=may_continue/continue_self` và
  autonomous timer; có thể hạ ngưỡng/đổi nhịp để Eris "lắm lời" khi mood, dựa
  trên `active_concern`/`expression_urge` sẵn có, thay vì thêm social governor
  luật cứng (đúng với mong muốn "một RootAgent duy nhất quyết định").

---

## 5. Câu hỏi mở cho research sau

1. **Chọn ASR/VAD nào** (on-device streaming vs cloud) để đạt độ trễ partial đủ
   thấp cho backchannel, và nối vào hợp đồng `vad_start/partial_asr/final_asr`
   hiện có ở đâu (frontend Live2D? một worker audio riêng?).
2. **Ngưỡng barge-in:** khi nào `vad_start` nên duck/dừng TTS ngay, khi nào chờ
   `partial_asr` đủ nghĩa? Hiện `on_asr_partial` yêu cầu ≥2 token nghĩa hoặc
   correction marker — có phù hợp cho tiếng Việt thiếu dấu/teencode không?
3. **Incremental có cần đổi `ConversationKernel`** từ "một event trọn vẹn" sang
   "stream event có thể hủy/cập nhật" không, hay bọc một lớp điều phối phía trên
   mà giữ kernel tuần tự? Ảnh hưởng tới các guard generation/receipt ra sao?
4. **Fast-path backchannel**: Root nên "ra tín hiệu backchannel" bằng cơ chế nào
   để không phá nguyên tắc single speech authority? Preset/cache câu ngắn nên
   dựng ở TTS layer hay ở một lane riêng?
5. **Giữ mạch sau ngắt** nên lưu ở đâu để sống qua đổi generation mà không tạo
   "ghost speech" (đúng lo ngại trong `continuation.py`)? Lưu intent thay vì câu
   chữ có đủ để Eris quay lại tự nhiên không?
6. **Đo độ trễ thật**: báo cáo này chưa chạy live. Cần đo P50/P95 của một câu
   ngắn qua pipeline hiện tại (`user_turn_latency_ms` đã được ghi ở
   `chat_cycle.py`) để biết fast-path tiết kiệm bao nhiêu.
7. **Chế độ tiếng Việt vs Nhật**: ở mode Việt bỏ localizer Nhật (theo
   runtime-lessons §11–12); fast-path/incremental cần nhất quán với bất đối xứng
   VI/JA này.

---

## 6. Giới hạn của điều tra này

- **Read-only, không chạy live.** Mọi kết luận về độ trễ, cảm giác "theo lượt" và
  hành vi barge-in thực tế là `[SUY LUẬN]` từ source; chưa có trace/log phiên nào
  trong lần điều tra này xác nhận.
- Không khẳng định đã đọc hết ~300 file trong `src/runtime`. Tập trung vào đường
  input → kernel → delivery → TTS và các module turn-taking/continuation/interrupt
  liên quan trực tiếp 8 khả năng. Các lane nền (observer/inner/curator) không
  thuộc phạm vi câu hỏi này.
- Đối chiếu runtime-lessons: xác nhận lại rằng **hủy TTS đã được tách khỏi
  provider failure** ở code hiện tại (`record_cancelled` + raise `TtsCancelledError`
  trước `record_failure`), cải thiện so với cảnh báo cũ ở mục 8/10 của tài liệu
  tri thức. Chưa xác nhận live là breaker không còn mở nhầm.
