# Eris chậm — phân rã độ trễ phiên dạy phân số (16:08–16:22, 01/11/2026)

Điều tra READ-ONLY. Nguồn: `eris_run_20261101_160853.txt`, `eris_observability.jsonl`
(cửa sổ epoch 1793524130–1793524980), đối chiếu `eris_run_20261101_134229.txt`.
Không sửa/build/chạy app. Mọi con số trích từ dòng log cụ thể; suy luận đánh dấu [SUY LUẬN].

---

## Tóm tắt (đọc trước)

Cảm giác "chậm điên" của phiên này **không** do một nguyên nhân. Mỗi lượt user → tiếng
đầu tiên mất **~14–22 giây ở trạng thái bình thường**, và **tăng vọt lên ~110 giây một lần**
(lượt 2) vì một sự cố riêng. Phân rã theo thứ tự đóng góp:

1. **Nguyên nhân CHÍNH (bình thường, mỗi lượt): hai vòng LLM nối tiếp trên critical path —
   Root reasoning (~6–16s) + Writer (~4–10s) + TTS synth (~5–19s)**. Đây là ~90% thời gian
   của một lượt "khỏe". Root chạy ở `reasoning_effort=high` cho MỌI lượt (xác nhận bằng source),
   payload 41–45k token mỗi lượt, nên không có cách nào nhanh dưới ~10s cho riêng Root.
2. **Nguyên nhân phụ nhưng là cú sốc lớn nhất: memory/curator (Living User Memory) thỉnh thoảng
   chẹn critical path ~42–43 giây** (`memory_context_ms=43176` ở lượt 2). Tái hiện ở phiên
   134229 (`memory_context_ms=41986`). Đây là thứ biến một lượt 20s thành một lượt ~110s.
3. **TTS ElevenLabs phiên này CHẬM HƠN điều tra cũ**: synth 5.3–18.6s (median ~6.8s), một lần
   `failed`. Điều tra 18/10 đo 3.4–3.8s. TTS giờ là khối thứ hai sau LLM.
4. **Cộng dồn nhịp continuation**: phiên có nhiều nhịp `autonomous_signal`/`continuation_due`
   nối nhau; mỗi nhịp là một vòng Root (im lặng ~15–40s) **kể cả khi kết thúc `no_reply`** (không
   phát tiếng). User cảm giác "đợi lâu rồi chả thấy nói gì".
5. **KHÔNG phải nguyên nhân phiên này: chờ token/IPv6 98s**. Không có gap refresh Firebase/IPv6;
   `broker_queue_wait_ms` luôn < 10ms; speech bind warm xong lúc 16:09:25. Cú 98s ở
   `user_turn_broker_scope_duration_ms` lượt 2 là **tổng scope lượt** (gồm cả 80s user gõ bài +
   42s memory), KHÔNG phải token refresh.

**Quick win dễ nhất, rủi ro thấp nhất:** bỏ memory/curator khỏi critical path (defer/timeout cứng
~1–2s thay vì để nó chẹn 42s). Giảm được cú sốc lớn nhất mà không đụng chất lượng reasoning.

---

## 1. Phân rã per-turn (user → first audio)

Mốc đọc từ run log. "First audio" = `recv=audio_playback_started` (đồng bộ bubble theo audio
theo yêu cầu sản phẩm). Lượt đánh số theo `[post observer] turn=`.

| # | User turn | Nội dung | user_turn → audio_start | context/memory_ms | Root reasoning (request→action) | Writer duration_ms | Writer→audio (synth+dispatch) | Ghi chú |
|---|---|---|---|---|---|---|---|---|
| T0 | 16:09:37 (opening) | startup_prime | — (autonomous, bị cancel) | ctx 356 / mem 149 | ~9.9s (16:09:27.9→37.8) | 5719 | — | tts=cancelled lúc 16:09:53 (user gõ bài mới) |
| T1/2 | 16:09:53 | "dạy tôi phân số…" | **~110s** (16:09:53→16:11:43) | **ctx 43349 / mem 43176** | ~9.8s (16:11:13.8→23.9) | 7735 | ~12s (16:11:31.9→43.5) | gồm 80.4s user gõ + 42s memory + proxy Read timeout 9.19s |
| T3 | 16:12:22 (auto) | nối nhịp bài chia | ~32s (16:12:22→54.1) | ctx 157 / mem 93 | ~6s (16:12:22.5→28.5) | 7094 | ~9s | delivered |
| T4 | 16:13:24 (auto) | no_reply | im ~6s rồi im | ctx 113 / mem 68 | ~5.9s | — (no_reply) | — | KHÔNG phát tiếng, vẫn tốn 1 vòng Root |
| T5 | 16:13:34 | "19/12 và 3/2" | ~34s (16:13:34→14:07.8) | ctx 3450 / mem 3383 | ~10s (16:13:40→50.2) | 6047 | ~12s | mem 3.4s (nhẹ) |
| T6 | 16:15:04 | "khoan, quy đồng…" | **~44s** (16:15:04→15:47.9) | ctx 332 / mem 294 | ~11.4s (16:15:07→18.4) | **9733** | **~19.5s** (16:15:28.3→47.9) | writer + synth đều chậm; broker 18.6s |
| T8 | 16:17:48 | "ok hiểu rồi, cảm ơn" | ~23s (16:17:48→18:10.9) | ctx 363 / mem 303 | ~7s (16:17:54→18:01.4) | 3827 | ~5.7s | lượt "khỏe" nhất |
| T10 | 16:18:51 | "tối nay mày…" | ~35s (16:18:51→19:26.4) | ctx 986 / mem 946 | ~15.5s (16:18:55.6→19:11.1) | 7891 | ~7.4s | Root reasoning dài (2659 chars thinking) |
| T12 | 16:19:57 (auto) | continuation | nhiều nhịp no_reply rồi move | ctx 241/189 | 3 vòng Root (16:19:58, 20:22, 20:44) | 6186 | ~6s | 2 nhịp no_reply trước khi nói |
| T13 | 16:21:35 | "vừa xem vừa chơi á" | ~41s (16:21:35→22:16.2) | ctx 481 / **mem evidence 14699** | ~8s | 8890 | ~8s | OCR screen route 11.9s + evidence 14.7s |

**Kết luận mục 1:** lượt "khỏe" = **~20–35s** (Root ~6–15s + Writer ~4–10s + synth ~5–19s nối tiếp).
Phần lớn nằm ở **ba vòng gọi LLM/TTS tuần tự**, không ở một stage đơn. Lượt 2 (~110s) và lượt 6
(~44s) là outlier do memory spike / writer+synth cùng chậm.

---

## 2. Chờ mạng / token refresh — KHÔNG phải thủ phạm phiên này

- Speech engine warm xong sớm: `[TTS/ElevenLabs] Background token and connection pool warm-up
  complete` lúc **16:09:25**, trước lượt user đầu. `provider_health_snapshot event=speech_bind`
  lúc 16:09:21 báo `speech.ready=true, worker_ready=true`.
- Mọi `broker_queue_wait_ms` trong phiên đều **< 10ms** (1.5–8.7ms). Không có hàng đợi.
- **Không có** record Firebase/securetoken/IPv6 timeout nào trong cửa sổ phiên (đã grep
  `firebase|token|refresh` trên observability của phiên — chỉ ra token_pressure, không phải
  refresh network). Cơ chế 8×IPv6 timeout 12s = 98s của điều tra 18/10 KHÔNG tái hiện ở đây.
- Con số `user_turn_broker_scope_duration_ms=98750ms` ở lượt 2 **dễ bị đọc nhầm thành token 98s**.
  Thực ra nó đo từ `broker_user_turn_begin` (16:09:53, lúc user bắt đầu) đến `broker_user_turn_end`
  (16:11:32) — tức **bao trùm 80.4s user GÕ bài + 42s memory + reasoning**, không phải thời gian
  một request mạng. Xác nhận: `[root-input] wait_seconds=80.4` ở 16:11:13 = thời gian chờ user.
- **Một sự kiện mạng thật duy nhất:** `local DeepSeek Web proxy (Whale2API/DS2API) failed
  (… port=5103 Read timed out read timeout=9.19s), falling back to Official API` lúc **16:11:23**.
  Đây là gateway Docker :5103 timeout đúng 9.19s rồi fallback sang Official DeepSeek. Chỉ xảy ra
  1 lần, nằm trong lượt 2 (đã chậm sẵn vì memory).

[SUY LUẬN] Vì phiên này dùng key/account đã warm và không chọn account hết hạn giữa chừng, đường
token né được bẫy IPv6. Không loại trừ bẫy 98s tái xuất ở phiên khác khi account bị refresh lạnh.

---

## 3. Model nghĩ lâu — CÓ, và bị ép `high` cho mọi lượt

- Thời gian Root (từ `[root-session] request_size` → `[root-agent] … action`): **~6–16s mỗi lượt**.
  Ví dụ: T1 9.8s, T6 11.4s, T10 15.5s. Reasoning content lớn: T10 `chat_tool_required reasoning
  chars=2659`; lượt 2 `chars=2196`.
- **Root luôn chạy thinking cao.** `src/llm/deepseek.py::reasoning_effort()` ép mọi giá trị không
  phải `max/xhigh/maximum` → `"high"` (default env cũng `"high"`):
  ```python
  raw = str(requested or os.environ.get("ERIS_DEEPSEEK_REASONING_EFFORT","high") or "high")...
  if raw in {"max","xhigh","maximum"}: return "max"
  return "high"
  ```
  → Đổi knob medium/low ở tầng trên **không có tác dụng**; request vẫn đi với high. Khớp mục 8
  runtime-lessons ("DeepSeek Root medium/low → high"). Đây là nguồn "nghĩ lâu" có thật, nhưng là
  **cố ý** (user coi trọng chiều sâu) nên không phải bug thuần.
- Writer (`character-v03 writer_candidate duration_ms`): **3827–9733ms** phiên này (so với phiên
  134229 có lượt 21890ms — writer cũng có thể phình). Writer là vòng LLM THỨ HAI nối sau Root.
- Observer (`post observer latency`): **11129–15394ms** mỗi lượt, nhưng chạy NỀN sau commit, không
  chẹn audio của lượt hiện tại — [SUY LUẬN] không tính vào "user → first audio" nhưng ăn CPU/định
  tuyến provider cùng lúc, có thể làm chậm gián tiếp.
- Tất cả lane đi `model=deepseek-flash provider=local` (observability `input_tokens_by_lane`).

---

## 4. TTS synth — chậm hơn điều tra cũ, một lần fail

`broker_request_duration_ms` lane `tts_current_turn` trong phiên:

| Thời điểm | provider | duration_ms | reason |
|---|---|---|---|
| 16:09:53 | elevenlabs_account_12 | 6718 | **failed** |
| 16:11:43 | account_10 | 9805 | completed |
| 16:12:53 | account_9 | 6814 | completed |
| 16:14:07 | account_12 | 10914 | completed |
| 16:15:47 | account_12 | **18591** | completed |
| 16:18:10 | account_11 | 5263 | completed |
| 16:19:26 | account_11 | 6576 | completed |
| 16:21:06 | account_12 | 5631 | completed |
| 16:22:16 | account_11 | 7589 | completed |

- Synth **5.3–18.6s, median ~6.8s**. Điều tra 18/10 đo chỉ **3.4–3.8s** → TTS hiện **chậm gấp đôi
  trở lên**, cộng thêm biến thiên lớn (một lượt 18.6s). Đây là khối thời gian thứ hai sau LLM.
- **Một lần `reason=failed`** (16:09:53, account_12) — trùng lượt bị user cancel (tts=cancelled).
  [SUY LUẬN] khả năng là cancellation bị tính nhầm thành failure, đúng như cảnh báo mục 8
  runtime-lessons ("TTS cancellation bị tính sai thành provider failure"). Không thấy disconnect
  ElevenLabs hay fallback Gemini trong phiên (không có record `fallback`/`disconnect`).
- Queue wait luôn ~0 → không nghẽn broker; chậm nằm ở chính request synth upstream.

---

## 5. Cộng dồn nhịp continuation — có, làm user "đợi mà không nghe gì"

- Phiên đầy nhịp tự phát: `event_kind=autonomous_signal` (T3, T4, nhiều lần quanh 16:17, 16:20)
  và `continuation_due` (16:20:05, 16:22:52). Nhiều nhịp kết thúc **`action=no_reply`** — tức tốn
  trọn một vòng Root (~6–10s im lặng, có khi 42s nếu dính memory spike) mà **không phát tiếng**.
- Ví dụ rõ: 16:17:06 → 16:17:27 → 16:17:37 là **ba vòng Root liên tiếp đều `no_reply`** sau lượt
  "khoan quy đồng", xen một `micro:ambient_sigh`. Từ 16:19:57 → 16:20:54 là **ba vòng** (no_reply,
  no_reply, rồi mới move). Mỗi vòng = một request Root 41–45k token.
- "Một lượt cảm giác" của user = (nhịp phản hồi chính) + (các nhịp continuation nối tiếp). [SUY LUẬN]
  với cadence rải nhịp, user hỏi một câu có thể thấy: im ~20s → nghe 1 câu → im thêm vài vòng Root →
  đôi khi mới có câu nối. Tổng "tới khi yên" dài hơn nhiều so với một câu trả lời đơn.
- **Cadence mới CÓ làm cảm giác tệ hơn** ở chỗ: các vòng `no_reply` không tạo ra tiếng nhưng vẫn
  giữ hệ thống bận (Root high + observer nền), nên user vừa đợi lâu vừa không có phản hồi nghe được.

---

## 6. Payload nặng — có tương quan, nhưng không phải nút thắt đơn lẻ

- `[root-session] request_size` mỗi lượt Root: **estimated_tokens 41.9k–45.3k**, message_chars gồm
  một khối **Self ~81.408 ký tự** (`self loaded sections=4 chars=81408`) NHỒI MỖI LƯỢT. Fingerprint
  đổi mỗi lượt (`31c5418f…` → `bd578a3b…`) → Self được dựng lại, không cache.
- Thành phần Self nặng nhất (`self_component_chars`): `self.memory_state` 72.616, `memory.living_user`
  52.829, `living_user.profile` 34.537, `self.mind_state` 7.182, `memory.agent_mind` 7.852. Tức
  **Living User Memory chiếm phần lớn payload** — cùng hệ với thủ phạm mục 2.
- Observability: lane `chat_tool_required` (Root) `input_tokens_by_lane ≈ 42–45k`, `output 1200`;
  `chat_main ≈ 10k`; `post_observer ≈ 1.3–8.4k`. `token_pressure_ratio` chỉ ~0.03–0.11 (cap 1e9)
  → **không bị trim**, nghĩa là toàn bộ 42k token được gửi upstream mỗi lượt.
- [SUY LUẬN] Payload 42–45k token tương quan với Root 6–16s (prompt dài → prefill lâu), nhưng vì
  cùng cỡ ở mọi lượt mà thời gian Root vẫn dao động 6→16s, phần dao động là do thinking/high chứ
  không chỉ payload. Payload nặng là hằng số cộng thêm, không phải biến gây outlier.

---

## 7. Gateway whale2api (:5103) — có đo được, không phải nút thắt chính

- Startup cảnh báo `ERIS_DS2API_ENABLED=1 but whale2api.exe not found` — đúng thiết kế: gateway
  chạy bằng Docker compose (xác nhận `eris_setup.py`: "Gateway gio chay bang Docker… docker compose
  up -d", port 9090/5010; `.exe` cũ bị cảnh báo nên xoá). Eris gọi proxy local tại **127.0.0.1:5103**.
- Thời gian gateway: **không có record timing riêng của gateway** trong observability (chỉ có
  per-lane token). Bằng chứng duy nhất là lần **Read timeout 9.19s lúc 16:11:23** rồi fallback
  Official API. → gateway có một cú treo ~9s trong phiên, nhưng **chỉ 1 lần**, và client có cơ chế
  fallback. [SUY LUẬN] read timeout 9.19s là ngưỡng cấu hình của client proxy (giá trị in ra khớp
  một timeout ~9.2s); các lượt khác gateway trả trong thời gian Root bình thường nên không thấy.
- Không có bằng chứng gateway là điểm nghẽn lặp lại; nó chỉ góp 1 cú ~9s vào lượt 2 (vốn đã ~110s).

---

## Kết luận & hướng giảm (ưu tiên quick win)

### Nguyên nhân CHÍNH (bình thường)
**Pipeline tuần tự 3 vòng: Root(high) → Writer → TTS synth**, chiếm ~90% của mỗi lượt khỏe
(~20–35s). Đây là kiến trúc, không phải lỗi đơn.

### Nguyên nhân phụ nhưng gây cú sốc lớn nhất
**Memory/curator (Living User Memory) chẹn critical path ~42s** (`memory_context_ms≈43k` ở lượt 2;
tái hiện phiên 134229). Biến lượt 20s → 110s.

### Nguyên nhân phụ khác
- **TTS synth chậm gấp 2+ so với cũ** (median 6.8s, outlier 18.6s) + 1 lần fail (có thể là cancel
  bị tính nhầm).
- **Nhiều vòng continuation `no_reply`** tốn Root nhưng không phát tiếng → cảm giác đợi vô ích.
- **Payload 42–45k token/lượt** (Self + Living User nhồi mỗi lượt, không cache) → nền prefill cao.

### Hướng giảm theo thứ tự dễ/rủi ro

| # | Hướng | Giảm được | Độ lớn | Rủi ro |
|---|---|---|---|---|
| 1 | **Đưa memory build ra khỏi critical path**: timeout cứng ~1–2s cho `memory_kernel.build_public_context`, dùng bản cache/degraded nếu quá hạn (defer curator xuống nền). | Cú sốc 42s | Lớn (quick win) | Thấp — đã có đường `degraded`; giữ evidence như mục 8 nhắc (đừng biến curator thành optional rồi bỏ việc) |
| 2 | **Cache/diff Self per phiên** thay vì nhồi 81k ký tự mỗi lượt khi fingerprint không đổi phần tĩnh. | ~prefill mỗi lượt | Vừa | Thấp–vừa (phải giữ đúng projection tới Root) |
| 3 | **Giảm số nhịp `no_reply`**: nâng ngưỡng continuation để Root không chạy full vòng chỉ để trả no_reply. | Nhiều vòng Root/phiên | Vừa | Vừa — đụng cadence/cá tính, cần đo cảm giác |
| 4 | **Sửa đếm cancel ≠ failure ở TTS broker** (nhả HALF_OPEN permit đúng 1 lần) để tránh account bị né oan. | Ổn định synth | Nhỏ–vừa | Vừa (đã có regression bảo vệ, xem mục 8) |
| 5 | **Điều tra TTS synth chậm lên 6–18s** (so 3–4s cũ): account/model/`eleven_v3` hay mạng upstream. | Khối synth | Vừa | Cần probe riêng; ngoài phạm vi doc-only này |
| 6 | Thinking `high` là **cố ý** — không hạ trừ khi user đồng ý đánh đổi chiều sâu. Nếu hạ, phải sửa `reasoning_effort()` (hiện ép high) chứ đổi knob tầng trên vô dụng. | Root 6–16s | Lớn nhưng đụng sản phẩm | Cao (chất lượng/cá tính) |

### Cadence mới có làm tệ hơn không?
**Có, một phần.** Rải nhịp tạo thêm các vòng Root `no_reply` (không phát tiếng) xen giữa, nên user
vừa đợi pipeline 3 vòng cho câu chính, vừa đợi thêm vài vòng Root im lặng. Nó không phải nguyên
nhân gốc của độ chậm mỗi câu, nhưng khuếch đại cảm giác "đợi lâu mà chả nói gì".

---

## Ghi chú bằng chứng & giới hạn
- Mọi mốc per-stage lấy từ `eris_run_20261101_160853.txt`; broker/token từ `eris_observability.jsonl`
  (cửa sổ epoch 1793524130–1793524980, khớp `micro:receipt:17935244xx` trong run log).
- Đối chiếu `eris_run_20261101_134229.txt`: cùng pattern (memory_context_ms≈42s, writer tới 21.9s,
  wait_seconds=61.8) → hành vi chậm là hệ thống, không phải one-off.
- `reasoning_effort()` đọc từ source dev `src/llm/deepseek.py`; chưa xác nhận bản portable đang chạy
  trùng byte cho file này (các điều tra trước xác nhận nhiều file portable trùng dev, nhưng không
  kiểm riêng file này lần này). [SUY LUẬN] cho mapping high.
- Không đo được thời gian nội bộ gateway Docker (:5103) vì observability không ghi per-request
  gateway; chỉ có 1 Read timeout 9.19s quan sát trực tiếp.
- Observer latency (11–15s) chạy nền sau commit; không tính vào "user→first audio" nhưng [SUY LUẬN]
  tiêu tài nguyên provider song song.
- Nội dung nguồn đã được diễn giải lại cho phù hợp giấy phép khi cần.
