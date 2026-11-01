# Khả thi: Eris trình bày theo nhịp cuốn chiếu (incremental cadence)

Ngày điều tra: 2026-11-02. Chế độ: **ĐỌC-ONLY** (không sửa, không build, không chạy app).
Phạm vi đọc: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev), log live
`C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261101_134229.txt` (phiên 2026-11-01),
báo cáo trước `.agents/tasks/eris-tutor-routing/tutor-gating-feasibility.md`, và
`docs/knowledge/2026-10-14-eris-runtime-lessons.md` (hợp đồng 'text chờ voice' 18/10).

Vấn đề đang xét là **NHỊP TRÌNH BÀY (cadence)** — Eris nhồi cả khối dài vào MỘT bubble
+ một lần TTS, thay vì nói một ý ngắn rồi chạy dần. Đây là vấn đề **TÁCH BIỆT** với
routing Tutor đã điều tra trước. Mỗi khẳng định có file:dòng.

---

## Tóm tắt câu trả lời (đọc trước)

1. **Root KHÔNG bị khóa cứng ở 1-move/lượt.** Đã tồn tại sẵn một cơ chế cuốn chiếu
   đúng kiến trúc: **continuation lease** (`NextConversationMove.after ∈
   {wait_user, may_continue, continue_self}`, schema `agent.py:45`). Khi Root chọn
   `may_continue`/`continue_self`, `ContinuationLeaseScheduler`
   (`continuation.py:82-140`) lên lịch một lần Root **tự thức dậy** sau 1.2s (hoặc
   0.15s với `continue_self`), re-evaluate từ ngữ cảnh mới nhất và phát **nhịp kế
   tiếp** — mỗi nhịp là một move riêng → một bubble riêng → một `audio_start` riêng.
   Đây chính là nhịp "nói một tí rồi chạy dần" như Kiro, và nó tôn trọng hợp đồng
   text-chờ-voice vì mỗi bubble vẫn commit theo `audio_start` của chính nó.

2. **Triệu chứng trong log KHÔNG phải do thiếu cơ chế, mà do Root CHỌN `wait_user`
   với một `say` dài.** Lượt phân số: `[root-agent] step=1 event_kind=user_turn
   action=move` (log 13:46:28), rồi `[public-text] sent ... chars=1259`
   (log 13:47:20, một bubble 1259 ký tự, `seq=0`, một delivery). Root finalize ngay
   ở step 1 bằng một move dài, after mặc định `wait_user` → không có nhịp nối nào.

3. **Prompt Root HIỆN ĐÃ khuyến khích cuốn chiếu** nhưng chỉ ở mức bias yếu, và cách
   diễn đạt của nó vô tình dạy model gộp dài: `root_prompt_contract.py` nói "Khi mạch
   còn mở… nghiêng về after=may_continue" NHƯNG cũng nói "say mô tả **đầy đủ** điều
   writer cần truyền đạt" và cấm runtime áp "max_sentences/speech budget". Không có
   bất kỳ chỉ dẫn nào bảo Root "nói ngắn từng nhịp". Model DeepSeek do đó mặc định
   nhét trọn bài giảng vào một `say` rồi `wait_user`.

4. **Cách elegant nhất = dùng lại continuation lease đã có + nâng bias prompt thành
   chỉ dẫn cadence cụ thể** (xem §Kết luận). KHÔNG nên dùng intra-move segmentation
   (`stage_output.py` SentenceSegmenter) làm cadence: segment chỉ chia TTS/mouth-sync
   TRONG một turn, vẫn **một bubble, một delivery_id** — nó không tạo nhịp cuốn chiếu
   nhìn thấy được và không cho Root "nghĩ lại giữa các nhịp".

5. **Rủi ro continuation:** đã có circuit breaker (`max_consecutive_self_wakes=24`,
   `max_chain_seconds=120s`, `continuation.py:49-51,104-117`) + fail-soft; rủi ro
   chính là **độ trễ cộng dồn** (mỗi nhịp = 1 vòng Root ~10-22s + 1 synth ElevenLabs)
   và **collision/preempt** khi user chen giữa chuỗi nhịp. Có cơ chế speculative
   prepare + preempt sẵn giảm nhẹ.

6. **Chỉ nên bật rộng (mọi lúc Eris định nói dài), KHÔNG giới hạn riêng lúc dạy học.**
   Cadence là phong cách trình bày của Eris, không phải tính năng sư phạm; prompt đã
   khung nó là "cá tính quyết số nhịp nối" (`root_prompt_contract.py`). Nhưng nên neo
   mạnh nhất vào các tình huống giảng/liệt kê nhiều bước (ví dụ fraction) vì đó là nơi
   bức tường chữ đau nhất.

---

## Bằng chứng

### 1. Một 'lượt' Root sinh bao nhiêu đơn vị nói? (move → bubble → TTS)

**Một move = một bubble = một delivery = (thường) một request TTS.** Nhưng một move
CÓ THỂ bị chia thành nhiều TTS *segment* bên trong — segment KHÔNG phải bubble riêng.

- `NextConversationMove` có đúng một `say` (schema `agent.py:44`,
  `contracts.py:71`). Writer realize nó thành một `RenderedConversationMove`
  (lane-map `.agents/tasks/eris-lane-map/lane-map-report.md:30`).
- Delivery tạo một `delivery_id` duy nhất cho move (`kernel.py:317`
  `delivery_id=f"delivery:{uuid...}"`).
- Bubble public text được commit **đúng một lần** khi `audio_start` của delivery đến:
  `public_output_runtime.py:698-717` (`send_text_payload`, `release_reason ==
  "audio_start"` → transition "SPEAKING") và `:780` `_record_public_turn(...)` —
  commit toàn bộ `body_payload["text"]` của move, không theo segment.
- **TTS segmentation TỒN TẠI nhưng chỉ chia audio, không chia bubble:**
  `stage_output.py:302 frames_for_tts()` có thể trả nhiều `StageFrame` với
  `segment_id` tăng dần (`:435`), nhưng tất cả **giữ nguyên một `turn_id`/
  `delivery_id`** (dùng `replace(frame, segment_id=index,...)`). Các segment chỉ sinh
  nhiều `audio_start`/`audio_done` cho mouth-sync (`public_output_runtime.py:857-911`
  xử lý `segment_id`/`final_segment`), còn bubble vẫn commit một lần ở `audio_start`
  đầu tiên.
- **Quan trọng:** với ElevenLabs và turn thường, segmentation bị TẮT để tránh latency:
  `stage_output.py:335-340` — `if _tts_provider()=="elevenlabs" and not
  explicit_opening and len(tts_text) <= _provider_transcript_limit(): return (frame,)`.
  Transcript limit ElevenLabs = **900 ký tự** (`tts_budget.py:37,55,71-72`).

→ **Kết luận §1:** một move = một bubble (một lần commit text). Intra-move segment chỉ
chia audio/mouth, không tạo "đơn vị nói" nhìn thấy tách biệt. Muốn nhiều bong bóng
ngắn nối nhau thì phải có **nhiều move**, không phải nhiều segment.

### 2. Root có phát NHIỀU move liên tiếp trong một lượt user không? (continuation)

**Có — qua continuation lease, nhưng là nhiều *lượt* nối nhau, không phải nhiều move
trong cùng một lần `decide`.**

- Nhánh finalize `agent.py:336`: `if kind == "move" or (event.kind=="user_turn" and
  (raw.get("intent") or raw.get("say"))): ... return NextConversationMove`. Một lần
  `decide()` chỉ trả **đúng một** `ConversationDecision` (agent.py docstring dòng
  1-12: "public boundary cuối vẫn luôn là đúng một ConversationDecision"). Vậy trong
  MỘT lần decide không thể phát 2 move.
- **Nhưng** move mang `after`: `agent.py:45` enum `{wait_user, may_continue,
  continue_self}`; `contracts.py:30-36` `ConversationAfter`.
- Sau khi move phát xong, kernel lên lịch continuation: `ContinuationLeaseScheduler
  .schedule(..., after=...)` (`continuation.py:82-140`). Nếu `after==wait_user` →
  cancel lease, dừng (`continuation.py:94-97`). Nếu `may_continue`/`continue_self` →
  tạo lease với `due_at = now + delay` (delay 1.2s cho may_continue, 0.15s cho
  continue_self: `continuation.py:86-88,118-120`).
- Driver tick lease: `orchestrator.py:1247-1251` — `lease = kernel.continuation.peek(sid);
  if lease is not None and lease.due_at <= time.time(): self._run_v12_signal(
  "autonomous_signal")`. `_run_v12_signal` với `autonomous_signal` gọi
  `kernel.handle_due_continuation(...)` (`orchestrator.py:1181-1185`).
- `handle_due_continuation` (`kernel.py:584-...`) `claim_due` lease
  (`continuation.py:261`), tạo `ConversationEvent.continuation_due(...)`
  (`kernel.py:528`) rồi chạy lại Root → writer → delivery. Mỗi vòng là một move/bubble
  MỚI. Root re-evaluate từ history/receipt mới nhất (continuation.py docstring dòng
  4-6: "Khi lease đến hạn, caller phải gọi lại RootAgent để quyết định từ ngữ cảnh mới
  nhất").
- Có cả **speculative prepare**: `orchestrator.py:929-933` chuẩn bị candidate Root→
  Writer song song cho lease kế tiếp (`kernel.prepare_continuation_candidate`,
  `kernel.py:513-542`) để giảm độ trễ nhịp nối; delivery vẫn qua adapter gốc
  (`_deliver_prepared_continuation`, `kernel.py:543-583`).

**Bằng chứng live rằng cơ chế này CHẠY:** trong log, Eris mở phiên bằng một monologue
(13:43:17 `step=1 event_kind=opening_signal action=move`, bubble chars=425 delivered
13:44:13), rồi **tự nối một nhịp thứ hai** 13:44:32 `step=1 event_kind=autonomous_signal
action=move` (ví dụ bẫy Borwein, public trace goal="Nối tiếp ý vừa nói…"). Đó chính là
continuation. **Vấn đề:** cả hai nhịp đều là bubble DÀI (một monologue trọn vẹn mỗi
nhịp), không phải nhịp ngắn cuốn chiếu.

→ **Kết luận §2:** Root KHÔNG khóa 1-move/lượt. Cơ chế nối nhiều move (continuation
lease) tồn tại, chạy live, có breaker và speculative prepare. Thiếu sót KHÔNG ở cơ chế
mà ở việc Root (a) hay chọn `wait_user`, và (b) khi có nối thì mỗi nhịp vẫn dài.

### 3. Tầng delivery có tách câu/chunk/stream để commit dần không?

**Có SentenceSegmenter, nhưng nó KHÔNG commit bubble dần — và bị tắt cho ElevenLabs
turn thường.**

- `SentenceSegmenter.split` (`stage_output.py:138-181`): tách theo ranh giới câu
  `(?<=[.!?。！？])\s+` (`:22`), chỉ tách khi `len >= min_split_chars` (default 58,
  `:41`), rebalance tối đa `max_tts_segments` (default 8, `stage_profiles.py:38`).
- `frames_for_tts` (`stage_output.py:302-446`): với ElevenLabs + turn thường +
  `len(tts_text) <= 900` → trả một frame duy nhất (`:335-340`). Chỉ khi vượt 900 ký tự
  (hoặc opening typed, hoặc provider Gemini) mới chia segment (`:401-446`).
- Dù chia segment, **text chờ voice vẫn đúng từng segment**:
  `public_output_runtime.py:605-608` commit bubble mặc định theo `audio_start`
  (`sync_text_with_tts_enabled()`), và segment-level `audio_done` chỉ đóng delivery khi
  `segment >= total-1` (`:857-861`, `final_segment` logic `:873-911`). Hợp đồng 18/10
  (`docs/knowledge/...:mục 'text chờ voice'`) được tôn trọng: mỗi segment có
  `audio_start` riêng tại ranh giới phát PCM.

**Nghịch lý cần lưu ý (giới hạn điều tra):** bubble live là **1259 ký tự** (log
13:47:20) > 900 (limit ElevenLabs). Theo `stage_output.py:335-340`, điều kiện
`len <= limit` KHÔNG thỏa → đáng lẽ rơi xuống nhánh chia segment (`:401-446`). Nhưng log
chỉ có `seq=0`, một `audio_playback_started`, một commit text. Hai khả năng (CHƯA xác
minh được từ log, cần phiên có observability segment):
  (a) con số `chars=1259` là độ dài **display/bubble** tiếng Việt, còn `tts_text` (có
      thể đã lọc/khác) <= 900 nên vẫn một segment — hoàn toàn khớp vì
      `stage_output.py:337` đo `frame.tts_text`, không đo display;
  (b) hoặc một nhánh prepared (`prepared.segments`, `public_output_runtime.py:600`) đã
      cố định một segment từ trước.
  → Dù là (a) hay (b), **một move vẫn ra một bubble**. Không tìm thấy đường nào biến một
    `say` dài thành NHIỀU bubble commit dần.

→ **Kết luận §3:** segmentation hiện có phục vụ mouth-sync/latency TTS, KHÔNG phải cadence
trình bày. Nó commit trong một delivery, một bubble. Không dùng được làm cuốn chiếu.

### 4. Cách nào đúng kiến trúc nhất để cuốn chiếu?

Ba cách như brief nêu, đánh giá từng cách:

**(a) Root phát nhiều move ngắn liên tiếp qua continuation — ĐÚNG KIẾN TRÚC NHẤT.**
- **Điểm chèn:** không cần code mới ở tầng cơ chế — lease + driver đã đủ
  (`continuation.py`, `orchestrator.py:1181-1185,1247-1251`,
  `kernel.py:584+`). Chỉ cần Root (i) viết `say` NGẮN (một ý), (ii) chọn
  `after=may_continue`/`continue_self`. Đây là quyết định của model, điều khiển bằng
  **prompt** (`root_prompt_contract.py`).
- **Phá hợp đồng text-chờ-voice?** KHÔNG. Mỗi move là delivery riêng, bubble vẫn commit
  theo `audio_start` của chính nó (`public_output_runtime.py:698-717`).
- **Phá single_writer?** KHÔNG. Mỗi nhịp vẫn qua đúng một writer
  (lane-map `:30`). Mỗi move một writer.realize.
- **Live2D mouth sync?** Giữ nguyên: mỗi delivery có `audio_start`/`audio_done` riêng,
  Live2D nhận edge theo turn_id/segment_id như cũ (`public_output_runtime.py:857-911`).
- **Đánh đổi:** độ trễ cộng dồn (xem §5). Đây là đánh đổi "elegant nhưng chậm hơn" —
  giống Kiro nói từng đoạn: người dùng thấy nhịp tự nhiên, tổng thời gian có thể dài hơn.

**(b) Một move, delivery tự chunk `say` thành nhiều bubble theo câu — SAI MỤC TIÊU.**
- Điểm chèn giả định: `stage_output.py:302 frames_for_tts` + làm
  `public_output_runtime.py` commit bubble PER segment thay vì per delivery.
- **Vấn đề 1 (kiến trúc):** segment hiện cố ý **giữ một `turn_id`/`delivery_id`** và
  một public-turn record (`:780`). Để mỗi segment thành một bubble phải phá cấu trúc
  delivery/receipt một-turn-một-delivery và sửa `_record_public_turn`, ledger, và
  reconcile history — đụng đúng vùng bài học runtime cảnh báo (receipt/public-turn
  ledger, `docs/knowledge/...:mục 8`). Rủi ro cao.
- **Vấn đề 2 (không có "nghĩ lại"):** chunk cùng một `say` chỉ cắt văn bản Root đã viết
  sẵn một lần. Nó KHÔNG cho Root quan sát phản ứng/đổi hướng giữa các nhịp — mất đúng
  cái "elegant" mà user mô tả (Kiro nói một tí *rồi mới* chạy tiếp theo ngữ cảnh).
- **Vấn đề 3 (latency không giảm):** vẫn phải synth cả `say` dài; chia bubble sau synth
  không làm Eris "bắt đầu nói sớm hơn".
- → Không khuyến nghị làm cadence chính. Chỉ hữu ích như cải thiện phụ cho mouth-sync.

**(c) Prompt bảo model viết `say` ngắn lại — CẦN, nhưng một mình KHÔNG đủ.**
- Điểm chèn: `root_prompt_contract.py` ROOT_SYSTEM_CORE. Hiện prompt nói "say mô tả
  **đầy đủ** điều writer cần truyền đạt" — vô tình cổ vũ gộp dài. Và dù có câu
  "nghiêng về may_continue", model vẫn gộp vì không có chỉ dẫn "mỗi nhịp một ý ngắn".
- Một mình (c) là bias yếu (bài học runtime: prompt không đảm bảo model tuân). Nhưng
  (a) **phụ thuộc** (c): continuation chỉ tạo cuốn chiếu nếu mỗi nhịp thực sự ngắn.
- → (c) là điều kiện cần cho (a). Hai cái đi cùng nhau: **(a)+(c)** là phương án.

→ **Kết luận §4:** cách elegant = **(a) tái dùng continuation lease + (c) sửa prompt để
mỗi `say` là MỘT ý ngắn và chủ động chọn `may_continue` khi còn ý kế**. Không phá
text-chờ-voice, single_writer hay Live2D. (b) bị loại vì sai mục tiêu và rủi ro cao.

### 5. Rủi ro: latency, vỡ nhịp voice, collision/preempt

- **Latency cộng dồn (rủi ro lớn nhất).** Mỗi nhịp = 1 vòng Root (live đo ~10-22s:
  writer_candidate duration_ms=5375/21890/10639 trong log) + 1 synth ElevenLabs. Nhiều
  nhịp ngắn → nhiều round-trip. Giảm nhẹ: (i) speculative prepare đã có
  (`orchestrator.py:929-933`, chuẩn bị nhịp kế song song trong khi nhịp hiện phát);
  (ii) `continue_self` delay chỉ 0.15s (`continuation.py:88`). **Nhưng** bài học
  runtime (`docs/knowledge/...:mục 8`) cảnh báo DeepSeek Root medium/low bị map thành
  high và vòng Root chậm — nên mỗi nhịp vẫn tốn thời gian suy nghĩ thật; cần đo live.
- **Breaker chống runaway.** `max_consecutive_self_wakes=24`, `max_chain_seconds=120s`
  (`continuation.py:49-51`); vượt → cancel lease, dừng chuỗi (`:104-117`). Nhiều nhịp
  ngắn tiêu nhanh hơn ngân sách self-wake, nhưng 24 nhịp đủ cho một bài giảng cuốn chiếu.
- **Collision/preempt khi user chen giữa chuỗi.** Đã có sẵn: `still_active()` kiểm tra
  trong Root loop (`agent.py:245,331` trả `root_turn_preempted`), và
  `cancel_session_with_open_loop` bảo toàn ý đang nói dở vào OpenLoopStore
  (`continuation.py:183-239`). Bài học runtime (`docs/knowledge/...:mục 8`) nêu: một số
  input ("ô", enter_chat_mode) hủy audio — nhiều bubble nghĩa nhiều điểm có thể bị hủy
  giữa chừng; cần bảo đảm hủy một nhịp không làm hỏng việc resume các nhịp sau.
- **Live2D mouth + audio_start từng segment.** Trong phương án (a) mỗi nhịp là delivery
  riêng nên mouth-sync độc lập, không có vấn đề ghép segment. (Vấn đề mouth-sync chỉ
  phát sinh nếu chọn (b) chia segment nội move.) Hợp đồng text-chờ-voice giữ nguyên.
- **vỡ nhịp voice / stale audio.** `public_output_runtime.py:846-851` đã từ chối
  `audio_start` cũ ("stale audio_start rejected… voice/text ownership diverged"). Nhiều
  delivery nối nhau làm tăng số ranh giới generation/turn — cần kiểm generation guard
  (`kernel.py` phase CONTINUATION_PENDING/WAITING_USER, `:392-397,554-564`) chịu được
  nhịp nhanh.

→ **Giảm rủi ro tổng:** dùng `may_continue` (1.2s, có speculative prepare) làm mặc định
cho cuốn chiếu; để dành `continue_self` (0.15s, chen cả khi user đang gõ) cho các nhịp
thật sự liền mạch. Bật/đo bằng phiên live, theo dõi breaker và latency per-nhịp.

### 6. Áp dụng mọi lúc nói dài hay chỉ khi dạy học?

- Prompt đã khung cadence là **phong cách/cá tính** của Eris, không phải cơ chế sư phạm:
  `root_prompt_contract.py` — "Chính cá tính và cảm nhận ngữ cảnh của bạn quyết số nhịp
  nối, không có quota ngôn ngữ". Continuation lease là hạ tầng chung, không gắn tutor.
- Giới hạn riêng lúc dạy học sẽ (i) cần một cổng phát hiện "đang dạy" (giống
  `_explicit_pedagogical_activation`, mà báo cáo tutor-gating đã chỉ ra là thiếu chính
  xác — `tutor-gating-feasibility.md §4`), (ii) làm cadence giật cục (chỗ có chỗ không),
  phá cảm giác nhân vật nhất quán.
- Ngược lại, bật rộng cho mọi tình huống nói dài đúng tinh thần user ("như Kiro nói một
  tí rồi chạy dần") và đúng khung prompt hiện tại.

→ **Kết luận §6:** bật rộng (prompt-level, không cổng cứng theo chủ đề). Nhưng chỉ dẫn
prompt nên nêu VÍ DỤ các tình huống dễ gây bức tường chữ (giảng bài, liệt kê nhiều
bước, ra đề) để model neo mạnh hơn ở đó — không tạo flag runtime riêng cho tutor.

---

## Kết luận & khuyến nghị

### (1) Root có bị khóa 1-move/lượt không?
**KHÔNG.** Một lần `decide()` trả một move, nhưng `after=may_continue`/`continue_self`
+ `ContinuationLeaseScheduler` cho phép nối nhiều move/bubble liên tiếp trong cùng mạch,
có breaker và speculative prepare. Cơ chế đã chạy live (log 13:44:32 là một continuation
thật). Thiếu sót là Root **chọn `wait_user` + `say` dài**, không phải thiếu cơ chế.

### (2) Cách elegant nhất + file:dòng sửa
Phương án **(a)+(c): tái dùng continuation lease, điều khiển bằng prompt.** Không cần
xây cơ chế mới; không phá text-chờ-voice/single_writer/Live2D.

- **`src/runtime/conversation/root_prompt_contract.py`** — ROOT_SYSTEM_CORE (chuỗi
  `ROOT_SYSTEM_CORE`, dòng 5 trở đi). Hai sửa đổi prompt:
  1. Đổi câu "say mô tả **đầy đủ** điều writer cần truyền đạt" → chỉ dẫn mỗi `say` là
     **MỘT ý/một nhịp ngắn**, không nhồi cả lời giải/bài giảng vào một move. (Câu hiện
     tại ở đoạn "Khi finalize move: intent mô tả mục đích semantic; say mô tả đầy đủ…".)
  2. Nâng câu "nghiêng về after=may_continue" thành chỉ dẫn CỤ THỂ cho tình huống dài:
     khi còn nhiều ý (giảng bài, liệt kê bước, ra đề), nói ý đầu rồi `after=may_continue`
     để tự nối nhịp kế, thay vì gộp. Vẫn giữ nguyên nguyên tắc "cá tính quyết số nhịp,
     không quota" (tránh phá điều khoản "Không tạo max_sentences/speech budget" cuối prompt).
  Đây là **bias prompt (yếu)** nhưng đúng chỗ và đủ để kích cơ chế đã có. Không đụng code cơ chế.

- **(Tùy chọn, mạnh hơn — chỉ nếu prompt không đủ)** nếu phiên live cho thấy model vẫn
  gộp dài bất chấp prompt, cân nhắc **gate mềm trong `src/runtime/conversation/agent.py`
  quanh nhánh finalize `:336`**: khi `say` vượt một ngưỡng độ dài VÀ `after==wait_user`
  VÀ chưa ép lần nào, append một directive vào `tool_results` gợi ý Root chia nhịp +
  `continue`, fail-soft finalize nếu model vẫn gộp (cùng khuôn soft-forcing mà
  `tutor-gating-feasibility.md §2a` mô tả cho routing). Đây là thay đổi **cơ chế (mạnh)**
  nhưng rủi ro phá cá tính/latency cao hơn — chỉ làm sau khi prompt chứng minh không đủ.
  KHÔNG dùng intra-move segmentation (phương án b) làm cadence.

### (3) Rủi ro + cách giảm
- *Latency cộng dồn* → dùng `may_continue` (có speculative prepare
  `orchestrator.py:929-933`) làm mặc định; `continue_self` cho nhịp liền; đo per-nhịp.
- *Runaway* → breaker `continuation.py:49-51,104-117` đã giới hạn 24 nhịp/120s.
- *User chen giữa chuỗi* → preempt (`agent.py:331`) + OpenLoopStore
  (`continuation.py:183-239`) đã có; kiểm nhịp nhanh không làm hỏng resume.
- *Text-chờ-voice* → KHÔNG đụng; mỗi bubble commit theo `audio_start` riêng
  (`public_output_runtime.py:698-717`), hợp đồng 18/10 giữ nguyên.

### (4) Độ lớn thay đổi
**Nhỏ (S)** cho phương án khuyến nghị: chỉ sửa chữ trong `root_prompt_contract.py`
(2 đoạn). KHÔNG đụng continuation/kernel/delivery/TTS/Live2D. Nếu phải thêm gate mềm ở
`agent.py` (tùy chọn (2)), nâng lên **vừa (M)**: ~20-40 dòng + guard + log, như khuôn
soft-forcing của báo cáo tutor trước.

### (5) Phải xác minh bằng phiên live
Bắt buộc. Lý do (bài học runtime + §5): vấn đề là **lựa chọn của model** (chọn
`wait_user`/gộp dài), test fixture ép router không tái hiện. Phiên live cần cho thấy:
khi user hỏi câu cần giảng dài, log có **nhiều** `[root-agent] ... action=move` nối nhau
qua `continuation_due`/`autonomous_signal`, mỗi `[public-text] sent ... chars=<nhỏ>`
(ví dụ < 300) thay vì một bubble 1259 ký tự, và breaker/latency chấp nhận được. Đồng thời
kiểm `after` thực tế của move (không có log field `after` hiện tại — có thể cần thêm một
dòng log loại `after` ở `agent.py` quanh `:336` để quan sát, KHÔNG serialize nội dung).

---

## Phân tầng bằng chứng
- *Đọc source:* agent.py:1-12 (một decision/lượt), 44-45 (schema say/after), 245/331/336
  (finalize + preempt); contracts.py:30-36,71 (ConversationAfter, say); continuation.py:
  4-6 (re-evaluate contract), 49-51 (breaker const), 82-140 (schedule), 104-117 (breaker),
  118-120 (delay), 183-239 (open-loop preempt), 261 (claim_due); kernel.py:317 (delivery_id),
  513-542 (prepare_continuation_candidate), 543-583 (deliver prepared), 584+ (handle_due),
  392-397,554-564 (phase guard); orchestrator.py:929-933 (speculative prepare),
  1181-1185 (handle_due_continuation call), 1247-1251 (lease tick driver);
  stage_output.py:22 (sentence regex), 41 (min_split), 138-181 (SentenceSegmenter),
  302-446 (frames_for_tts), 335-340 (ElevenLabs single-frame shortcut), 401-446 (split path);
  stage_profiles.py:17-39 (profile defaults logical_segment_tts=True, max_tts_segments=8,
  min_split_chars=58); tts_budget.py:37,55,64-74 (ElevenLabs limit 900);
  public_output_runtime.py:600-608 (frames_for_tts call + segment_count), 698-780
  (send_text_payload commit một lần theo audio_start), 846-861 (stale audio_start reject +
  final_segment), 857-911 (segment-level mouth/clock); root_prompt_contract.py
  (ROOT_SYSTEM_CORE: khuyến khích may_continue + "say đầy đủ" + cấm max_sentences).
- *Quan sát live* (`eris_run_20261101_134229.txt`): architecture C v28,
  semantic_authority=conversation_kernel_v12 (13:42:55); opening move bubble chars=425
  seq=0 (13:43:17 → 13:44:13); continuation nhịp 2 autonomous_signal action=move
  (13:44:32, Borwein, goal="Nối tiếp ý…"); lượt phân số user_turn step=1 action=move
  (13:46:28) → một bubble chars=1259 seq=0 (13:47:20). Chứng minh: cơ chế continuation
  chạy, nhưng mỗi nhịp dài và lượt dạy chọn một bubble khổng lồ.
- *Giới hạn chưa xác minh:* vì sao bubble 1259 ký tự (>900) vẫn một segment — khả năng
  `chars` là độ dài display Việt còn `tts_text` <= 900 (stage_output.py:337 đo tts_text);
  log không đủ phân biệt. Không có log field `after` để xác nhận trực tiếp Root chọn
  `wait_user` — suy ra từ việc không có continuation nối sau lượt phân số trước khi app thoát.
- *Lịch sử đã đối chiếu:* `tutor-gating-feasibility.md §5` đã nói "bức tường chữ là vấn
  đề tách biệt với routing" và gợi ý sửa prompt tách-kênh; báo cáo này bổ sung rằng cơ
  chế cuốn chiếu ĐÚNG là continuation lease (không phải presentation_blocks, cũng không
  phải intra-move segmentation), và chốt điểm sửa prompt cụ thể ở root_prompt_contract.py.
