# Chẩn đoán run Eris 21:54–22:05 ngày 03/11/2026

Chỉ đọc, không sửa gì. Mọi giờ là giờ local. Bản cài đặt `C:\Users\Gtvkun\Documents\eris` và bản dev `C:\Users\Gtvkun\Documents\GitHub\eris` có `src` giống hệt nhau ở cả 22 file được trích dẫn bên dưới (so SHA-256).

## 1. Kết luận ngắn

Run này **không crash và không lỗi LLM**. Cả 6 lượt chat đều được giao (`outcome=delivered`, `tts=done`), không có traceback, writer_failed, 429 hay timeout. Hai run trước (15:06, 16:29) mới là run hỏng thật, run này khỏe hơn nhiều.

"Eris bị gì" nằm ở ba chuyện user nhìn thấy:

1. **Lượt 22:00:54 bị treo 3 phút 13 giây** trước khi Eris trả lời, trong khi lượt thường mất 24–70 giây. Nguyên nhân khả dĩ nhất (khoảng 70%): luồng chat bị chặn bởi `_turn_buffer_lock` của Living User Memory, khóa này đang bị tác vụ dọn trí nhớ nền giữ trong lúc gọi Gemini Web. User hỏi "eris bị gì vậy" ngay sau đó rồi thoát app.
2. **Ba trong sáu lượt tốn thêm 11, 23 và 41 giây chờ OCR màn hình** dù user không hỏi gì về màn hình. Nguyên nhân (khoảng 90%): bộ cứu tham chiếu màn hình coi "anh" (đại từ gọi user) là "ảnh", và coi "nó", "đó", "cái này" là chỉ màn hình, nên ép OCR đồng bộ.
3. **Eris hỏi kỹ thuật liên tục khi user chỉ muốn xả**, và câu thoại trái với ý định Root tự ghi. User phải chửi hai lần ("fe tệ quá nha", "bạn hỏi lại ăn cặc à").

User thoát app bằng menu chuột phải (`_ExitTree: reason=context menu exit`, `vision.py code=-1 unexpected=False`) ngay sau câu trả lời cuối. Không phải crash. `crash_trace.txt` sửa lần cuối 24/10, không có dòng nào của tháng 11, nên không liên quan.

## 2. Lịch sử chat run 21:54–22:05

Nguồn: `curator_inbox.sqlite3` (payload `interpretation_context.recent_conversation`), `living_user_episodes.json`, bảng `eris.conversation_move_outcomes.v1` trong `eris_social_runtime.sqlite3` (trường `say_hint` khớp từng chữ với câu đã giao), cộng `eris_run_20261103_215409.txt`. Độ dài ký tự trong log (165, 88, 109, 174, 158, 93, 115) khớp với các câu dưới đây.

Giờ user là lúc tin tới (dòng `conversation trajectory ... reason=user_turn`). Giờ Eris là lúc bubble và âm thanh bắt đầu (`public-text sent ... reason=audio_start`). Các timestamp trong `living_user_turn_buffer.json` và curator inbox của lượt 22:00:54 ghi 22:03:44, vì ghi sau khi bị treo (xem P1).

| # | Giờ | Ai | Nội dung | Chờ |
|---|---|---|---|---|
| 0 | 21:55:02 | Eris (mở lời khi khởi động) | "Chín giờ năm mươi tư rồi, anh vẫn ngồi với Gemini trên Brave. Cái council đó ráp xong chưa, hay vẫn đang kẹt ở khâu gộp các nhánh lại thành một câu trả lời đọc được?" | |
| 1 | 21:55:35 | User | "vụ đó lâu rồi á" | |
| | 21:56:18 | Eris | "Vậy là tôi hỏi trễ mất rồi. Lâu rồi thì thôi, kệ cái council đó đi. Giờ anh đang làm gì?" | 43 s |
| 2 | 21:56:58 | User | "tức điên luôn. nãy giao cho kiro làm code, mà nó làm loay hoay si đa, bực bội vl" | |
| | 21:57:21 | Eris | "Loay hoay kiểu gì? Sửa một chỗ xong đẻ ra ba lỗi mới, hay cứ vòng vòng đọc hiểu rồi không chịu đụng vào code?" | 24 s |
| 3 | 21:57:48 | User | "nó ko hiểu ý tôi. làm ko hợp ý" | |
| | 21:58:32 | Eris | "Không hiểu ý thì khó nói lắm — vì có khi lỗi tại cái đầu nó, cũng có khi tại cái brief mình đưa nó tự suy diễn thêm. Anh nói rõ ý cỡ nào rồi, hay mới phác ra là nó chạy luôn?" | 44 s |
| 4 | 21:59:08 | User | "cái này ko hay. tôi tâm sự cái này còn hỏi lại kỹ thuật, fe tệ quá nha" | |
| | 22:00:17 | Eris | "Ừ, công nhận. Anh đang xả cục tức mà tôi quay ra phỏng vấn kỹ thuật — đúng kiểu hỏng. Kiro làm sai ý anh chỗ nào, kể tôi nghe coi, lần này tôi ngồi nghe thật." | 70 s |
| 5 | 22:00:54 | User | "kiro sai khi ko làm theo đúng ý thôi. bạn hỏi lại ăn cặc à" | |
| | 22:04:07 | Eris | "Được, tôi ăn. Anh bảo sai ý là sai ý, không cần tôi mổ xẻ thêm. Tôi ngồi đây, anh kể tiếp đi." | **193 s** |
| 6 | 22:04:40 | User | "eris bị gì vậy" | |
| | 22:05:26 | Eris | "Bị gì đâu. Anh chửi thì tôi ăn, rồi ngồi im như đã nói. Chỉ có điều ngồi im lâu quá nên chắc anh tưởng tôi đơ thật." | 45 s |
| – | 22:05:38 | User | mở context menu rồi Exit (22:05:39.96) | |

Mỗi lượt user còn có một "micro receipt" (ack ngắn như "ừm") phát ngay lúc tin tới (ví dụ 22:00:54.30). Riêng lượt 5, user nghe ack rồi im lặng gần 3 phút.

## 3. Các vấn đề

### P1. Lượt 5 bị treo 170 giây trước khi Root bắt đầu (cao nhất)

**Bằng chứng**
- Log run, 22:00:54 → 22:03:45: không có dòng nào về chat. Dòng kế tiếp là `22:03:45.953 [screen route] mode=none`.
- `22:03:46.071 [root-input] messages=1 wait_seconds=171.8 revision=5`, nhưng `22:03:45.973 [chat-stage] evidence_ms=1310`. Tức tin đã nằm trong hàng 171 s mà giai đoạn evidence chỉ chạy 1,3 s. Ở các lượt khác `wait_seconds` ≈ `evidence_ms`.
- `eris_observability.jsonl`: sau `22:00:54.308 observer_discard_total` không có bản ghi nào đến `22:03:46.267 prompt_tokens_before`. Cuối lượt: `user_turn_latency_ms=189266` (các lượt khác 16–64 s), `user_turn_broker_scope_duration_ms=189207`.
- `curator_inbox.sqlite3`: envelope của lượt này (`aaabb07f…`, `session_turn:10`) được tạo lúc 22:03:44.60.
- `living_user_episodes.json` ghi lúc 22:03:44.58, và `living_user_turn_buffer.json` bắt đầu đúng bằng lượt user tại 22:03:44.65. Buffer vừa bị flush thành episode `uep_344c4999…` ngay trước đó.
- `living_user_trace.jsonl`: `episode_rollup status=failed error=ValueError` lúc 22:00:41. Cuối run có `dream` và `living_user_dream_checkpoint.json` lúc 22:05:38.87, ngay trước khi thoát. Không có dòng `[memory_gc] run #…` nào trong log, nên một vòng MemoryGC chưa xong lúc thoát.

**Giả thuyết nguyên nhân (≈70%)**
1. MemoryGC (`runtime/memory_gc_service.py` `_loop`, chu kỳ 600 s, chạy khi idle) gọi `memory/memory_kernel.py` `maintain()`. Hàm này chạy `rollup_episodes()` (lỗi lúc 22:00:41) rồi `living_user.dream()`.
2. `dream()` (`memory/living_user/service.py` ~l.458–480) gọi `flush_session()`. Hàm `_flush_buffer_locked` chạy bên trong `with self._turn_buffer_lock` (l.187–190), rồi gọi `consolidate_session` → `UserEpisodeBuilder.build` → `_from_model` → `model_adapter.summarize_episode`. Đó là một cuộc gọi Gemini Web đồng bộ, giữ khóa suốt thời gian chờ.
3. Lúc 22:00:54 luồng chat vào `ConversationObservationBridge.observe_user_turn` (`runtime/conversation/observation_bridge.py`) → `_ingest_user_turn_memory_hot_path` (`runtime/state_commit_service.py` l.425) → `TurnMemoryPipeline.enqueue_user_turn` → `_enqueue_curator` (`runtime/turn_memory_pipeline.py`) → `living_user.capture_interpretation_context` (`service.py` l.229). Hàm này cần `_turn_buffer_lock` nên đứng chờ, dù docstring nói "no model/retrieval/network on the enqueue path".
4. Gemini xong lúc 22:03:44.58 (episode được ghi), khóa nhả, envelope được tạo lúc .60, chat chạy tiếp.

Điểm khớp mạnh: mốc 22:03:44 xuất hiện đồng thời ở episode file, turn buffer, curator envelope và điểm bắt đầu chat-stage. Điểm chưa chứng minh: không có log nào cho thấy thời lượng cuộc gọi Gemini hay thời điểm `maintain()` bắt đầu. Một khóa khác (ví dụ `episode_store.lock`) vẫn có thể là thủ phạm; cần đo khi tái hiện.

**Gemini Web đang yếu trong run này**, phù hợp với giả thuyết: `living_user_curator_deferred … CuratorInferenceError` ×3 (21:55:24, 21:58:26, 21:58:32); rollup `ValueError` lúc 22:00:41; sáu envelope trong curator inbox vẫn `pending` lúc thoát. Hai run trước không có dòng `living_user_curator_deferred` nào.

**Đề xuất sửa (chưa áp dụng)**
- Không gọi model trong `_turn_buffer_lock`. Chụp bản sao các turn dưới khóa, build episode ngoài khóa, rồi lấy lại khóa để cắt buffer theo id.
- Cho `capture_interpretation_context` đọc snapshot sao chép, hoặc `acquire(timeout=…)` rồi fallback context rỗng, để đường chat không bao giờ chờ nền.
- Đặt timeout cứng cho `summarize_episode`, và bỏ qua vòng maintenance khi có user turn (`GLOBAL_INFERENCE_BROKER.user_turn_active()` đã có).
- Thêm log bắt đầu/kết thúc vòng MemoryGC, thời gian chờ khóa và thời gian cuộc gọi Gemini, để chẩn đoán lần sau không phải suy từ mtime file.
- Kiểm bằng test: adapter giả `summarize_episode` ngủ 5 s, đo thời gian của `_ingest_user_turn_memory_hot_path` trong lúc `dream()` chạy.

### P2. OCR bị ép chạy đồng bộ trong 3/6 lượt, cộng thêm 11–41 giây

**Bằng chứng**
- `[screen text] chat refresh revision=2 … blocks=60`, `[chat perception] unified elapsed=11012ms` (21:55:48); `revision=8 … elapsed=22792ms` (21:58:11); `revision=13 … elapsed=40331ms` (21:59:49). `evidence_ms` tương ứng 12443, 23260, 41623.
- Cả ba lần: `[screen route] mode=text_evidence_soft … reason=screen_text_available_but_soft_after_anaphora anaphora=1`. Kết quả chỉ là bằng chứng "mềm", stale.
- Cả ba tin đều không nói gì về màn hình: "vụ đó lâu rồi á", "nó ko hiểu ý tôi…", "cái này ko hay…" (tin 3 là lời phàn nàn về chính Eris).
- Lúc 21:59:50 grounding báo `grounding_source=current_screen … cap=0.62 … warnings=screen_facts_from_previous_turn` cho một lượt thuần tâm sự.
- Ba lượt còn lại (tin 2 dài 18 từ, tin 5 và 6 không có đại từ chỉ định) cho `mode=none anaphora=0`, `unified elapsed` 1–23 ms.

**Nguyên nhân (≈90%, cơ chế khớp đủ 6/6 lượt)**
`screen/screen_anaphora_rescue.py`:
- `_norm` (l.20–24) bỏ dấu nên "ảnh" và "anh" thành cùng token. `PRIOR_SCREEN_ANCHORS` (l.59–67) có `"anh"` và `"code"`. Câu Eris nào chứa "Anh" (gọi user) hoặc "code" đều bị coi là "câu trước nói về màn hình".
- `DEICTIC_MARKERS` (l.55–57) có `"no"`, `"do"`, `"day"`; sau khi bỏ dấu, "nó", "đó" khớp. `FOLLOW_UP_MARKERS` có "cai nay".
- Hai điều kiện cùng thỏa nên `resolve()` (l.68–125) trả `references_screen=True, inherited=True`.
- `runtime/chat_perception.py` `prepare_turn` (~l.331–340) thấy route tham chiếu màn hình mà evidence rỗng hoặc stale nên gọi `refresh_screen_text()` (~l.286) → `screen_text_worker.refresh_now(force_ocr=True)`, chạy OCR RapidOCR đồng bộ trên đường chat qua `ConversationEvidenceAssembler.assemble_chat` (`evidence_assembler.py` → `chat_cycle._capture_screen_frame_for_chat`).
- Thời gian OCR tăng dần 11 → 23 → 40 s (60 → 127 → 113 block). Chưa rõ vì sao (CPU tranh chấp với renderer Live2D/TTS, hoặc worker nền không được thu hồi). Cần đo riêng.

**Tái diễn?** Có. Run 15:06 cũng có một lần `unified elapsed=26470ms` kiểu `text_evidence`. Run 16:29 thì cả ba lượt `mode=none`.

**Đề xuất sửa (chưa áp dụng)**
- Không dùng chuỗi đã bỏ dấu cho anchor mơ hồ: bỏ "anh", "code", "no", "do", "day" khỏi nhóm anchor/deictic, hoặc so khớp bản có dấu.
- Với route `inherited=True`, chỉ đọc cache `ScreenEvidenceStore`, không ép `force_ocr=True` trên đường chat. Nếu vẫn ép, đặt timeout vài giây.
- Thêm test với các câu thật của run này ("vụ đó lâu rồi á", "nó ko hiểu ý tôi…", "cái này ko hay…") sau một câu Eris có "anh", kỳ vọng `references_screen=False`.

### P3. Eris hỏi kỹ thuật khi user xả, câu thoại mâu thuẫn với ý định (hành vi/cá tính)

**Bằng chứng**
- Mỗi lượt Eris đều kết bằng câu hỏi chẩn đoán: "Loay hoay kiểu gì? …", "Anh nói rõ ý cỡ nào rồi, hay mới phác ra là nó chạy luôn?", "Kiro làm sai ý anh chỗ nào, kể tôi nghe coi…". User phản ứng: "tôi tâm sự cái này còn hỏi lại kỹ thuật, fe tệ quá nha", rồi "bạn hỏi lại ăn cặc à".
- Lượt 4: `intent` của Root là "…mở cửa cho anh kể tiếp chuyện Kiro làm sai ý **mà không hỏi thêm gì nữa**", nhưng `say` lại chứa câu hỏi "Kiro làm sai ý anh chỗ nào". Bảng `conversation_move_outcomes.v1` cho thấy `say_hint` (từ Root) trùng từng chữ với văn bản đã giao, và `character-v03 … code=WRITER_DIRECT`. Vậy mâu thuẫn nằm trong output của Root, writer chỉ chuyển tiếp (đúng vai trò "writer diễn đạt move Root chọn" trong bài học runtime).
- Lượt 3: câu trả lời đổ lỗi cho brief của user ("tại cái brief mình đưa nó tự suy diễn thêm") khi user vừa than phiền về Kiro. Đây là lượt Root trả JSON hỏng (P5), nên không có `intent` thật.
- Lượt 6: `intent` là "xác nhận tôi chẳng bị gì cả, chỉ là đang ngồi im đúng như đã nói". Câu giao nhận có độ trễ ("ngồi im lâu quá nên chắc anh tưởng tôi đơ") nhưng gán nó cho việc cố ý im lặng, trong khi nguyên nhân thật là P1. Eris không có tín hiệu về sự cố hệ thống, nên đây là hợp lý hóa sai chứ không phải nói dối có chủ đích.
- `conversation handoff v12` đánh giá sai hướng: lượt 3 ("nó ko hiểu ý tôi", nói về Kiro) bị gán `stance=confused repair=1 self_cause=0.90`; còn lượt 4 ("tôi tâm sự… hỏi lại kỹ thuật, fe tệ quá") và lượt 5 (chửi thẳng) lại là `stance=engaged repair=0 self_cause=0.00`. Mã: `runtime/conversation_handoff.py` ~l.305–369 (từ khóa `confusion`, `explicit_external_cause` không bắt được "nó = Kiro"). Mối liên hệ nhân quả với câu hỏi của Eris chưa được chứng minh (≈40–50%), nhưng tín hiệu hỏng là có thật.
- Lượt mở đầu: Eris nhắc lại chủ đề "council" cũ. Bảng move_outcomes cho thấy cùng chủ đề này xuất hiện ở run 15:06 ("council Gemini… ngồi đây làm bài"), run 16:29 ("council Gemini multitask xong chưa") và run này. Đây là mẫu lặp qua ba run. User trả lời "vụ đó lâu rồi á".

**Nguyên nhân giả thuyết (≈55%)**: Root không có ràng buộc "user đang xả, không hỏi" mạnh hơn trạng thái `open_loop`/`reply_expected` của discourse (xem `panel_snapshot.json`: `discourse.reply_expected=True`, `unresolved_point=How clearly the user specified the brief…`), và không có bước kiểm `say` so với `intent` trước khi giao. Chưa kiểm prompt Root trong run này, nên đây là suy luận từ output.

**Đề xuất sửa (chưa áp dụng)**: kiểm cơ học nhẹ `intent` có cụm "không hỏi" mà `say` chứa dấu hỏi hoặc cấu trúc hỏi thì chuyển sang `after=wait_user` với câu không hỏi; cải thiện phân loại "nó/cái này" trong handoff; chặn lặp lại chủ đề mở lời đã bị bác ở run trước. Đây là thay đổi hành vi cá tính, nên cần user đồng ý trước khi làm.

### P4. Một lượt Root trả JSON hỏng, đi đường recovery (nhỏ)

- 21:58:19: `[chat_tool_required reasoning] chars=407 content_chars=174`, `[contract-repair] status=queued`, rồi `completed` lúc 21:58:25.
- `public trace` ghi `goal=Truyền đạt lời thoại Root đã sinh.` — đúng chuỗi mặc định trong `llm/dialogue_recovery.py` l.58–62. `content_chars=174` bằng độ dài câu giao (174).
- Nghĩa là deepseek-flash trả văn bản thuần thay vì JSON schema `eris_root_conversation_step_v12`; hệ thống bọc thành `move` với `after=wait_user`, `_runtime_literal_dialogue=True`, rồi `BackgroundContractRepair` (`runtime/ai_orchestrated/contract_repair.py`) khôi phục metadata sau khi đã phát. 1/6 lượt Root; hai run trước không có dòng này (chúng có `root step circuit breaker` thay thế). Mức nghiêm trọng thấp, nhưng đây đúng là lượt có câu trả lời tệ nhất (P3).

### P5. Hậu kỳ tốn kém và bị bỏ (nhỏ)

- `observer_discard_total stage=inflight_or_started reason=user_turn` ×3 (21:57:47, 22:00:54, 22:04:40). Mỗi lần post_observer đã chạy 8–12 nghìn ký tự reasoning (`[post_observer reasoning] chars=8244 / 12127 / 9861`) rồi kết quả bị bỏ.
- Ba lần hoàn tất mất 11,7–15,2 s mỗi lần (`latency=15191ms`, `14858ms`, `11658ms`).
- `runtime/ai_orchestrated/observer.py` l.457. Không gây lỗi nhìn thấy; chỉ tốn token và tranh chấp quota.

### P6. False positive `unverified_execution_claim` (nhỏ)

- 22:04:03 `[behavior-observation] committed=1 families=unverified_execution_claim`; `memory_core/behavior_observations.jsonl`: `evidence=["missing=target,handler,result","operation=mo"]`, `prompt_eligible=false`.
- Câu liên quan: "…không cần tôi **mổ** xẻ thêm". `IntentionObserver` (`runtime/intention_authority.py` l.104–108) bỏ dấu nên "mổ" và "mở" cùng thành `mo`, nằm trong `_INHERENT_EXTERNAL_OP_RE`. Phủ định "không cần" đứng trước chủ ngữ nên không vô hiệu hóa. Hậu quả hiện tại chỉ là một "nợ tin cậy" không vào prompt; nên sửa cùng bản chất lỗi bỏ dấu ở P2.

### P7. Độ trễ tổng thể

Từ lúc user gửi đến lúc bubble hiện (bubble chờ `audio_start` theo yêu cầu 18/10): 43, 24, 44, 70, **193**, 45 s.

| Thành phần | Số đo |
|---|---|
| OCR ép (P2) | 11 / 0 / 23 / 41 / 0 / 0 s |
| Root (reasoning) | 7–13 s |
| Writer | 2,3–13,4 s (`duration_ms` 5640, 10359, 5516, 2313, 9344, 7641, 13422) |
| ElevenLabs synth | 3,9–8,3 s (tài khoản pool 8–12, không rơi fallback) |
| Treo P1 | ~170 s ở lượt 5 |

Nếu bỏ OCR không cần thiết và P1, lượt thường còn khoảng 20–30 s. Con số này vẫn dài so với chat, phần lớn do Root + writer + synth tuần tự.

### Không phải vấn đề / đã loại trừ

- Không có crash, traceback, `writer_failed`, 429, timeout hay circuit breaker. TTS: 7/7 `tts=done`, synth 3,9–8,3 s. `provider_key_pool settings_health` cho gemini/groq/elevenlabs `available=0` chỉ là health đọc khi user mở Settings lúc 21:59:16; chưa có bằng chứng nó ảnh hưởng chat (living-user dùng Gemini Web, TTS dùng pool tài khoản trong `config/elevenlabs_pool.db`).
- `ERIS_DS2API_ENABLED=1 but whale2api.exe not found` xuất hiện ở cả ba run, vô hại: proxy vẫn phục vụ Root (`DeepSeek Web worker san sang`, Root/writer đều thành công).
- Menu Live2D: nhiều dòng `Context menu: … menu=(840, 566)` khi chuột ở (109–170, 836–884), khác các lần menu bám con trỏ (ví dụ `cursor=(186,874) menu=(186, 566)`). Đây có thể là phần còn mở của [bài học hình học menu](../../../docs/knowledge/2026-11-03-live2d-menu-geometry.md) hoặc chỉ là fallback căn giữa khi hết chỗ; không đủ bằng chứng, độ tin cậy thấp. User mở menu ≥ 14 lần trong run, lần cuối để Exit.

## 4. So sánh với hai run trước

| | 15:06 (51 KB) | 16:29 (62 KB) | **21:54 (58 KB)** |
|---|---|---|---|
| Lượt chat | 3 | 3 | 6 |
| Proxy DeepSeek 429 / timeout 90 s | 4 / 0 | 4 / 3 | **0 / 0** |
| `root step circuit breaker` | 4 | 12 | **0** |
| `writer_failed` (tới `no_public_commit`/`degraded`) | 2 | 4 | **0** |
| Observer `provider_error` | 2 | 2 | 0 (nhưng 3 lần bị discard) |
| Curator `CuratorInferenceError` | 0 | 0 | **3** |
| OCR ép ≥ 10 s | 1 (26 s) | 0 | **3 (11, 23, 40 s)** |
| Treo ≥ 100 s trước Root | không | không | **1 (172 s)** |
| Chủ đề mở lời "council" | có | có | có |

Phân loại: hạ tầng LLM tốt hơn rõ rệt (lỗi cũ không tái diễn trong run này). Mới trong run này: treo P1, curator/Gemini Web lỗi, lượt Root JSON hỏng. Tái diễn: OCR do tham chiếu màn hình (P2), chủ đề "council" lặp lại, cảnh báo whale2api.exe.

## 5. Giới hạn của chẩn đoán

- `eris_observability.jsonl` không chứa nội dung chat; transcript dựng lại từ curator inbox, episodes, bảng move_outcomes và log run. Chỉ có 4 turn cuối trong `living_user_turn_buffer.json` vì buffer bị flush (P1).
- Không có log trực tiếp thời lượng khóa hay cuộc gọi Gemini; P1 là suy luận từ mốc thời gian trùng khớp và đọc mã (≈70%), chưa tái hiện.
- Chưa kiểm prompt thật của Root cho từng lượt (P3), nên nguyên nhân hành vi chỉ ở mức giả thuyết.
- Theo `AGENTS.md`, nếu các kết luận P1/P2 được xác nhận bằng tái hiện, nên cập nhật `docs/knowledge/2026-10-14-eris-runtime-lessons.md` (mục bằng chứng mới). Báo cáo này không sửa tài liệu đó.

## 6. File mã liên quan (bản dev, giống bản cài đặt)

- P1: `src/memory/living_user/service.py` (`record_conversation_turn`, `_flush_buffer_locked`, `capture_interpretation_context`, `dream`), `src/memory/living_user/episode_builder.py` (`_from_model`), `src/memory/memory_kernel.py` (`maintain`), `src/runtime/memory_gc_service.py` (`_loop`), `src/runtime/turn_memory_pipeline.py` (`enqueue_user_turn`, `_enqueue_curator`, `_run_curator`), `src/runtime/state_commit_service.py` (`_ingest_user_turn_memory_hot_path`), `src/runtime/conversation/observation_bridge.py` (`observe_user_turn`), `src/runtime/ai_orchestrated/orchestrator.py` (`run`, `_run_v12`).
- P2: `src/screen/screen_anaphora_rescue.py`, `src/screen/screen_relevance_router.py`, `src/runtime/chat_perception.py` (`prepare_turn`, `refresh_screen_text`), `src/runtime/chat_cycle.py` (`_capture_screen_frame_for_chat`), `src/runtime/conversation/evidence_assembler.py`.
- P3: `src/runtime/conversation/agent.py` (Root loop), `src/runtime/conversation_handoff.py`, `src/runtime/conversation/runtime_writer.py`.
- P4: `src/llm/dialogue_recovery.py`, `src/runtime/ai_orchestrated/contract_repair.py`.
- P5: `src/runtime/ai_orchestrated/observer.py`.
- P6: `src/runtime/intention_authority.py`, `src/runtime/behavior_observation.py`.
