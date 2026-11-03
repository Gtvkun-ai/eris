# Báo cáo turn chết — phiên live mới nhất (đọc-only)

## Tóm tắt kết luận (đọc trước)

Phiên vừa chạy có **nhiều turn chết do HAI nguyên nhân tách biệt, không phải một**:

1. **Writer pipeline — `v03_missing_public_surface`** (4 lượt chết, kể cả 2 lượt
   user thật). Giống hệt tiền lệ **mục 10** của bài học: nhánh autonomous/opening
   bị chặn vì writer không dựng được public surface, trong khi lượt chat qua được.
   Đây là lỗi **nội dung pipeline**, không phải credential.
2. **Provider/credential — DS2API 429 → Official 401 → read timeout 90s → circuit
   breaker** (12 lần `root step circuit breaker reached`, dồn về nửa cuối phiên).
   Từ ~16:38 trở đi, **không còn lượt nào được deliver**: mọi Root step đều rơi
   vào breaker. Đây là lỗi **credential/transport**, là nguyên nhân khiến NỬA CUỐI
   phiên chết hàng loạt.

**Nguyên nhân gốc chính (xếp theo số turn chết): provider/credential** (whale 429
+ official key 401 + read timeout) gây 12 lần breaker ở nửa cuối phiên; kế đến là
**writer `v03_missing_public_surface`** (4 lượt) ở nửa đầu.

**Turn chết KHÔNG do việc dọn token gây ra.** Không có BẤT KỲ dòng log nào dính
`self_prompt_view / project_self_view / compact_* / projection_schema /
episode_rollup / episode_fading` (grep = 0). `root_projected` chạy bình thường.

---

## (a) File log + timestamp + exe

- **File đọc:** `C:\Users\Gtvkun\Documents\eris\logs\eris_run_20261103_162911.txt`
  (LastWriteTime 3/11/2026 16:44:21, 62.310 byte — file mới nhất theo
  LastWriteTime, mới hơn `eris_run_20261103_150640.txt`).
- **Phiên:** `Bat dau : 2026-11-03 16:29:11`, kết thúc 16:44:21
  (`[RunLogger] Ket thuc phien chay`), thoát bằng context menu
  (`[Lifecycle] _ExitTree: reason=context menu exit`).
- **Exe / bản portable:** `Exe : C:/Users/Gtvkun/Documents/eris/Eris.exe`,
  `Editor : False`, Python portable `C:\Users\Gtvkun\Documents\eris\python\python.exe`.
  Đây là bản portable chạy từ `Documents/eris` (không phải checkout dev).
- **Lưu ý config phiên:** `ERIS_DS2API_ENABLED=1 but whale2api.exe not found at
  [đường dẫn nội bộ đã ẩn]` (16:29:28). DS2API vẫn trỏ về proxy localhost cổng
  5103; main brain = `deepseek-flash` qua DS2API, fallback official
  `deepseek-v4-pro` tại `api.deepseek.com`.

---

## (b) Bảng đếm turn

Số liệu lấy bằng đếm marker nguyên văn trong file:

| Hạng mục | Số lượng | Marker nguồn |
|---|---|---|
| Public delivery THÀNH CÔNG | **3** | `[public-text] sent ... reason=audio_start` + `outcome=delivered` |
| `writer_failed` (chết ở writer) | **4** | `[conversation-v12] writer_failed ... v03_candidate_rejected:surfaces=v03_missing_public_surface` |
| `root step circuit breaker reached` | **12** | `[conversation-v12] root step circuit breaker reached` |
| `[root-session] resync needed: RuntimeError` | **13** | đi kèm trước mỗi breaker (một lần là lượt user:6) |
| DS2API 429 (whale rate limit) | **4** | `429 Client Error ... upstream_empty_output ... rate_limit_error` |
| Official 401 (key invalid) | **1** | `401 Client Error ... Authentication Fails ... api key: ****s-Tp is invalid` |
| DS2API read timeout 90s | **3** | `HTTPConnectionPool(host='127.0.0.1', port=5103): Read timed out. (read timeout=90.0)` |
| Observer `inference_failed` | **2** | `[observer] inference_failed status=provider_error detail=HTTPError` |

**Phân loại 3 delivery thành công (có audio_start + text + delivered):**

- 16:30:17 `delivery:1d8e017430...` chars=131 (autonomous, trêu về UdpListener).
- 16:33:32 `delivery:46af62457f...` chars=260 (autonomous).
- 16:37:24 `delivery:ff091f31be...` chars=296 (chat, trả lời user "bạn bị lỗi gì hả").

**Lưu ý đếm "turn":** log không đánh số lượt tổng tường minh. Có 3 lượt user thật
nhận ra (`user_turn` rev — "rái cái tai phải", "bạn bị lỗi gì hả", "alo") và nhiều
`autonomous_signal`/`opening_signal`/`tutor_result` do timer. Trong 3 lượt user:
lượt 1 (user:? "rái...") và lượt "bạn bị lỗi gì" **được deliver**; lượt `user:2`
và `user:6` ("alo") **chết**. Các lượt autonomous phần lớn chết (writer_failed
hoặc breaker). Vì vậy "nhiều turn chết" mà user báo là đúng, tập trung ở
autonomous + nửa cuối phiên.

---

## (c) Mỗi loại chết ở ĐÂU trong pipeline (kèm dòng log)

### Loại 1 — Chết ở WRITER (`v03_missing_public_surface`), 4 lượt

Pipeline dừng ở stage `surfaces` (trước localization/prepare/delivery). Writer
sinh candidate nhưng không có public surface hợp lệ:

```
16:29:52.000 [character-v03] writer_candidate ... generation=336 attempt=1/1 stage=surfaces status=rejected code=v03_missing_public_surface duration_ms=3797
16:29:52.002 [conversation-v12] writer_failed event=opening_signal:1793698178551986000 ... reason=v03_candidate_rejected:surfaces=v03_missing_public_surface
16:31:22.781 [character-v03] writer_candidate ... generation=337 ... stage=surfaces status=rejected code=v03_missing_public_surface duration_ms=24250
16:31:22.788 [conversation-v12] writer_failed event=user:2 ... reason=v03_candidate_rejected:surfaces=v03_missing_public_surface
16:31:22.893 [chat-cycle] lifecycle vẫn COMPOSING sau khi cycle kết thúc (no_public_commit). turn_id=chat:1793698241143 kernel_status=writer_failed
16:32:41.776 [character-v03] writer_candidate ... generation=337 ... stage=surfaces status=rejected code=v03_missing_public_surface duration_ms=7250
16:32:41.780 [conversation-v12] writer_failed event=autonomous_signal:1793698331091616900 ...
16:41:34.638 [character-v03] writer_candidate ... generation=339 ... stage=surfaces status=rejected code=v03_missing_public_surface duration_ms=2406
16:41:34.640 [conversation-v12] writer_failed event=user:6 ...
16:41:34.671 [chat-cycle] lifecycle vẫn COMPOSING sau khi cycle kết thúc (no_public_commit). turn_id=chat:1793698887505 kernel_status=writer_failed
```

Vị trí: **Root → writer (stage=surfaces) → REJECT**. Chưa tới localization/prepare/
delivery/TTS. Hai trong bốn lượt này là **user thật** (`user:2`, `user:6`), nên
người dùng thấy câm thật sự ("alo" → không ra tiếng). `recv=degraded` gửi tới
Live2D ngay sau mỗi writer_failed của lượt user.

### Loại 2 — Chết do PROVIDER/CREDENTIAL (breaker), 12 lần

Chuỗi gốc đầu tiên (16:31:51–16:31:53):

```
16:31:51.604 [LLM][WARNING] local DeepSeek Web proxy (Whale2API/DS2API) failed (429 ... upstream_empty_output ... "Upstream account hit a rate limit and returned empty output." ... rate_limit_error), falling back to Official API.
16:31:53.020 [LLM][WARNING] [FALLBACK CHAIN] tier 2/2 (deepseek-v4-pro) loi: 401 ... "Authentication Fails, Your api key: ****s-Tp is invalid" ... authentication_error -> thu tier ke
16:31:53.021 [root-session] resync needed: RuntimeError
16:31:53.148 [root-agent] step=1 event_kind=autonomous_signal action=
16:31:53.148 [conversation-v12] root step circuit breaker reached
```

Về sau whale chuyển từ 429 sang **read timeout 90s** (proxy treo, không trả):

```
16:36:12.069 ... DS2API failed (HTTPConnectionPool(host='127.0.0.1', port=5103): Read timed out. (read timeout=90.0)), falling back to Official API.
16:36:12.071 [root-session] resync needed: RuntimeError
16:36:12.569 [conversation-v12] root step circuit breaker reached
```

Vị trí: **Root (LLM call) → DS2API 429/timeout → fallback Official 401 →
RuntimeError → breaker**. Chết NGAY Ở ROOT, chưa tạo được move/writer. Từ
~16:38:07 (request cuối) đến 16:44:20, breaker trip liên tục (16:41:17, :41,
16:42:05, :26, :49, 16:43:13, :33, :54, 16:44:20) — **không delivery nào** trong
cả đoạn này; chỉ còn micro ambient (`ambient_sigh`, `ambient_posture_reset`) nhả
audio nền. Phiên kết thúc trong trạng thái breaker.

### Loại 3 — DELIVERY/TTS

**Không có** lỗi delivery/TTS trong phiên này. Cả 3 delivery đều có
`audio_playback_started` → `audio_playback_done` đầy đủ, không `cancelled`,
không ElevenLabs disconnect, không `stale audio_start rejected`, không filler
`えっと…` / `v03_speech_localizer_fallback`. TTS warm-up OK
(`16:29:41 [TTS/ElevenLabs] Background token and connection pool warm-up complete`).

---

## (d) Nguyên nhân gốc chính (xếp theo số turn chết)

1. **Provider/credential (lớn nhất, chi phối nửa cuối phiên):** whale2api 429
   `upstream_empty_output` rồi chuyển sang read timeout 90s → fallback official
   `deepseek-v4-pro` trả **401 key invalid** → RuntimeError → **12 lần breaker**.
   Sau 16:38, mọi lượt chết ở đây; Eris không nói được câu nào tới khi thoát.
2. **Writer `v03_missing_public_surface` (nửa đầu phiên):** 4 lượt, trong đó 2
   lượt user thật (`user:2`, `user:6`). Khớp tiền lệ **mục 10**: nhánh
   autonomous/opening bị chặn, lượt chat thường qua được — xác nhận lại trên log
   mới. (`user:6` "alo" chết vừa do writer_failed vừa đúng lúc breaker đang mở.)

Hai nguyên nhân độc lập: writer_failed xảy ra cả khi provider còn 200 (16:29–16:32,
lúc delivery vẫn thành công), nên không quy writer_failed cho provider.

---

## (e) 429/401 là credential hay rate limit?

**Cả hai, ở hai tầng khác nhau — khớp bài học, không kết luận vội từ một mã lỗi:**

- **Tầng 1 (DS2API/whale) = rate limit tạm thời.** Body nói rõ:
  `"Upstream account hit a rate limit and returned empty output."` type
  `rate_limit_error`. Đây là gateway tự xoay account bị bóp, **không phải key của
  Eris hỏng**. Về sau whale còn **read timeout 90s** (proxy quá tải/treo), cùng
  tính chất transport tạm thời.
- **Tầng 2 (Official fallback) = credential hỏng thật.** `401 ... api key:
  ****s-Tp is invalid` — key official `deepseek-v4-pro` không xác thực được. Đây
  là lỗi credential cố định trong phiên (không phải rate limit).

Pattern: **không thấy luân phiên key thành công** — official chỉ có một key và nó
401 mọi lần. Breaker mở vì **cả hai tier đều fail**: tier 1 rate-limited/timeout,
tier 2 key hỏng. Nếu official key còn sống, các lượt nửa cuối có thể đã được cứu
qua fallback; đây là điểm nên kiểm/khôi phục key official.

---

## (f) Turn chết CÓ/KHÔNG do việc dọn token?

**KHÔNG.** Bằng chứng loại trừ:

- Grep toàn file cho `self_prompt_view | project_self_view | projection_schema |
  episode_rollup | episode_fading | compact_` = **0 hit**.
- `[root-session] root_projected` chạy bình thường
  (`16:30:58 root_projected turns=1 window=1 self_fields=1 new_turns=1`;
  `16:34:24 turns=3 window=3`), không có lỗi projection/schema.
- Mọi lỗi turn chết thuộc **writer surfaces reject** hoặc **provider breaker** —
  không module token-projection/episode nào xuất hiện trong chuỗi lỗi.

Phụ chú về token (bối cảnh user hỏi "1 chat 80k token"): request Root dao động
`estimated_tokens` ~14k–27k (ví dụ 16:29:36 `estimated_tokens=15101`; 16:38:07
`estimated_tokens=27775`, estimator=chars3). Đây là ước tính theo ký tự cho MỖI
request; `self.memory_state` ~24k–26k ký tự là thành phần lớn. Số này **không** là
nguyên nhân turn chết và không liên quan dọn token; chỉ ghi để tham chiếu.

---

## (g) Chưa xác minh

- **Số "turn tổng" tuyệt đối:** log không đánh số lượt tổng; con số delivered=3 /
  writer_failed=4 / breaker=12 là đếm marker, không phải nhãn "turn" chính thức.
  Một số `autonomous_signal` chọn `action=` rỗng (không định nói) nên không tính
  là "chết" theo nghĩa mất lời.
- **Vì sao whale 429/timeout:** log client chỉ thấy phía Eris; không có log
  whale2api để biết account nào bị bóp hay proxy vì sao treo 90s. `whale2api.exe
  not found` ở telemetry vision cần đối chiếu: DS2API vẫn gọi được cổng 5103 lúc
  đầu (200), nên có proxy đang chạy ở đâu đó — chưa xác định process.
- **Official key `****s-Tp`:** 401 xác nhận invalid trong phiên này; chưa kiểm
  key đó hết hạn/bị thu hồi hay cấu hình sai — cần probe riêng (không làm trong
  điều tra đọc-only này).
- **Người dùng nghe được gì:** 3 `[public-text] sent` + `audio_playback_done` là
  receipt phần mềm; không có bản ghi thiết bị để chốt đã nghe rõ.
- **`resync needed: RuntimeError`** xuất hiện 13 lần: 12 dẫn tới breaker; cần đọc
  source `root-session` để biết RuntimeError chỉ là hệ quả của fallback-chain
  cạn tier hay còn nguyên nhân khác — chưa truy trong phiên đọc-only.

---

## Khuyến nghị (không triển khai)

1. **Khôi phục/kiểm official DeepSeek key** (`****s-Tp` đang 401). Đây là lưới cứu
   khi whale 429/timeout; hiện lưới này thủng nên nửa cuối phiên chết sạch.
2. **Điều tra whale2api** (429 `upstream_empty_output` + read timeout 90s): account
   pool bị bóp hay proxy treo. Giảm `read timeout=90s` để fail nhanh thay vì treo
   90s mỗi lượt.
3. **Writer `v03_missing_public_surface` nhánh autonomous:** theo mục 10, đây là lỗi
   dựng public surface lặp lại cho nhánh autonomous/opening; cần xem lại stage
   `surfaces` của writer cho các event không-chat, không vá collision guard.
4. **Không đụng vào đường dọn token** — không liên quan các turn chết này.
