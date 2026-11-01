# Gateway whale2api có nhớ hội thoại không? — probe stateful/stateless

Ngày điều tra: 2026-11-01. Chế độ: **READ-ONLY + PING THẬT** (gọi gateway bằng
credential user; KHÔNG sửa source/config, KHÔNG build, KHÔNG bật/tắt gateway,
KHÔNG khởi động app Eris).

Phạm vi: source checkout `c:\Users\Gtvkun\Documents\GitHub\eris` (dev); gateway
`http://127.0.0.1:5103/v1`, model `deepseek-flash`, auth Bearer
`ERIS_DS_COMPANION_API_KEY` (fingerprint SHA-256[:8] = `4bb78ee5`, len 35).

Phân tầng: **[CODE]** đọc source (file:dòng); **[PING]** kết quả gọi endpoint thật;
**[SUY LUẬN]** suy từ bằng chứng. Credential đã CHE: chỉ lưu tên biến + fingerprint.

---

## TÓM TẮT CÂU TRẢ LỜI (đọc trước)

**Gateway whale2api STATELESS. Ý tưởng "ghim 1 account DeepSeek, gửi ngữ cảnh MỘT
LẦN rồi các lượt sau chỉ gửi tin mới để DeepSeek Web tự nhớ" KHÔNG khả thi với
gateway hiện tại — không phải vì thiếu account pinning, mà vì mỗi call là một
cuộc hội thoại DeepSeek MỚI, dựng lại từ đầu từ `messages` client gửi.**

Bằng chứng quyết định (`[PING]` 2 call liên tiếp, cùng key, KHÔNG gửi lại lịch sử):

| Call | Gửi gì | Trả lời | Nhớ "Khoa"? |
|---|---|---|---|
| noheader_call1 | "Tên tôi là Khoa, nhớ nhé." | "Chào Khoa! Mình đã nhớ tên bạn rồi nhé…" | — (chỉ xác nhận) |
| noheader_call2 | "Tên tôi là gì?" (KHÔNG kèm lịch sử) | "Tên tôi là **DeepSeek**, trợ lý AI…" | **KHÔNG** |
| session_call1 | "Tên tôi là Khoa…" + `X-Session-ID`+`X-Whale2-Affinity-Key` | "Chào Khoa! Mình đã nhớ…" | — |
| session_call2 | "Tên tôi là gì?" + CÙNG session header, KHÔNG kèm lịch sử | "Tên tôi là Trợ lý AI." | **KHÔNG** |

→ Call 2 trả lời "DeepSeek"/"Trợ lý AI" thay vì "Khoa" ⇒ gateway **không giữ
server-side memory**. Gửi kèm `X-Session-ID`/affinity **KHÔNG thay đổi gì** (vẫn
quên) ⇒ gateway BỎ QUA các header phiên đó.

**Tại sao:** `[CODE]` mỗi payload upstream có `parent_message_id: nil` và một
`chat_session_id` DeepSeek tạo MỚI mỗi call; `defer autoDeleteRemoteSession` dọn
phiên sau call. Không có handler nào trong gateway đọc `X-Session-ID` hay
`X-Whale2-Affinity-Key`. Client Eris cũng LUÔN gửi **full `messages` array** mỗi
lượt — kể cả khi có session lease, nó chỉ đổi giá trị header, không cắt lịch sử.

**Ý nghĩa cho latency:** ý user KHÔNG giảm được token/latency như kỳ vọng, vì
bản thân continuity của Eris nằm trong payload 42-45k token (Self 81k + Living
User Memory) do CLIENT nhồi mỗi lượt — không phải do thiếu nhớ phía gateway.
Muốn giảm token phải cắt ở client (cache Self, memory lane riêng như
`latency-breakdown.md` mục Kết luận đề xuất), KHÔNG phải đẩy nhớ sang DeepSeek Web.

**Đính chính giả định "DeepSeek Web có nhớ":** đúng, trang web deepseek.com có
nhớ trong một đoạn chat — NHƯNG Eris KHÔNG đi qua UI web đó. Eris đi qua gateway
whale2api (reverse-engineered API), và đường API này mỗi call mở phiên mới rồi
xoá, nên tính nhớ của UI web không áp dụng.

---

## BẰNG CHỨNG

### Q1. Gateway có session không — đọc source

**Client Eris gửi gì (full messages, stateless từ phía client):**

- `[CODE]` `src/llm/client.py:912-936`: trong vòng gửi, client dựng
  `request_headers` rồi gọi `_brokered_post(..., messages=messages, json=candidate)`.
  `messages` là **toàn bộ** mảng hội thoại; `WebSessionGuard.reserve(...)` chỉ
  quyết định GIÁ TRỊ `X-Session-ID`/affinity, **không hề cắt bớt `messages`**.
  → Dù session có được tái dùng hay không, client vẫn gửi đủ lịch sử.
- `[CODE]` `src/llm/web_session_guard.py:69-125` `reserve()`: chỉ cho tái dùng
  một `session_id` khi `messages` mới **đúng bằng** transcript đã commit + MỘT
  user turn mới (`len == prev+1`, `messages[:-1] == transcript`, phần tử cuối là
  `user`). Mọi thay đổi system/schema/memory/history ⇒ sinh `session_id` mới có
  nonce. Docstring (dòng 1-16) nêu rõ đây là lớp phòng vệ CLIENT; và cảnh báo
  "gateway cũ có thể chỉ chuyển user message cuối khi X-Session-ID đã tồn tại" —
  tức giả định một gateway stateful mà bản hiện tại KHÔNG triển khai (xem dưới).
- `[CODE]` `src/llm/client.py:58-96`: `_PERSISTENT_WEB_SESSION_LANES` và
  `_CHAT_AFFINITY_LANES` tồn tại cho chat lanes; `_web_session_header()`
  (dòng 149-214) và `_chat_affinity_key()` (dòng 216-247) chỉ phát header khi
  có `ERIS_RUNTIME_SESSION_ID`. **[SUY LUẬN]** đây là hạ tầng client cho ý
  "pin account + phiên bền", nhưng gateway hiện bỏ qua nên nó là no-op thực tế.

**Gateway whale2api xử lý ra sao (stateless per-call):**

- `[CODE]` `tools/whale2api/internal/promptcompat/standard_request.go:56-98`
  `CompletionPayload(sessionID)`: payload upstream luôn đặt
  `"parent_message_id": nil` (dòng 77) và `"prompt": r.FinalPrompt` (dòng 78).
  `FinalPrompt` dựng từ toàn bộ `messages` request. → Mỗi call là một lượt mở
  đầu (không nối message DeepSeek trước đó).
- `[CODE]` `tools/whale2api/internal/completionruntime/nonstream.go:81-95`
  `StartCompletion`: gọi `ds.CreateSession(...)` tạo `chat_session_id` **MỚI**
  cho mỗi request rồi `CompletionPayload(sessionID)`.
- `[CODE]` `tools/whale2api/internal/httpapi/openai/chat/handler_chat.go:35-39`:
  `defer h.autoDeleteRemoteSession(r.Context(), a, sessionID)` — xoá phiên
  DeepSeek sau mỗi request khi `AutoDeleteMode != "none"`.
- `[CODE]` `tools/whale2api/internal/config/store.go:34-37`: default
  `AutoDelete: {Mode: "none"}`. **[SUY LUẬN]** mặc định không chủ động xoá, nhưng
  vì `parent_message_id` luôn nil và `chat_session_id` tạo mới mỗi call, phiên cũ
  không bao giờ được nối lại dù còn tồn tại trên server.
- `[CODE]` `parent_message_id` chỉ được đặt > 0 trong nhánh **retry nội bộ của
  CÙNG một call** (empty-output retry), `shared/empty_retry.go:34-47`
  `ClonePayloadForAssistantRetry` — không phải cơ chế nhớ xuyên lượt user.
- **[CODE] Không có handler nào đọc header phiên:** grep `r.Header.Get(` trong
  `tools/whale2api/internal/httpapi/**` chỉ ra `Content-Type`, `X-Model-Type`
  (upload), `X-Whale2-Test-Trace` (trace). **KHÔNG** có `X-Session-ID` hay
  `X-Whale2-Affinity-Key`. grep toàn repo gateway cho các tên header đó = 0 match
  ở code xử lý request. → Header client gửi bị bỏ qua hoàn toàn.

**[SUY LUẬN]** `X-Whale2-Affinity-Key` nhằm ghim 1 account cho các lượt liên
tiếp (comment client FEAT-001), nhưng vì gateway không đọc nó, account vẫn đi
round-robin/selection mặc định của Auth. Dù có ghim được account đi nữa, phiên
DeepSeek vẫn mở-mới-mỗi-call, nên account affinity KHÔNG tạo ra nhớ.

### Q2. PING THẬT 2 call liên tiếp — stateful hay stateless

Endpoint `POST http://127.0.0.1:5103/v1/chat/completions`, Bearer
`ERIS_DS_COMPANION_API_KEY` (fp `4bb78ee5`), model `deepseek-flash`,
`thinking:{type:"disabled"}`, mỗi call CHỈ gửi 1 user message, KHÔNG kèm lịch sử.

- **noheader_call1** (200, 1824ms): "Tên tôi là Khoa, nhớ nhé." →
  "Chào Khoa! Mình đã nhớ tên bạn rồi nhé. Có điều gì mình có thể giúp bạn không?"
- **noheader_call2** (200, 2023ms): "Tên tôi là gì?" (KHÔNG kèm lịch sử) →
  "Tên tôi là **DeepSeek**, trợ lý AI do công ty Thâm Độ Cầu Tác … phát triển."
  → **quên "Khoa"** (hiểu "tôi" là chính model).
- **session_call1** (200, 1441ms): như trên + header `X-Session-ID` và
  `X-Whale2-Affinity-Key` = cùng một giá trị phiên.
- **session_call2** (200, 1412ms): "Tên tôi là gì?" + CÙNG session header, KHÔNG
  kèm lịch sử → "Tên tôi là Trợ lý AI." → vẫn **quên "Khoa"**.

**Kết luận Q2:** cả hai kịch bản call 2 đều KHÔNG nhớ "Khoa". Gateway
**STATELESS**. `X-Session-ID`/`X-Whale2-Affinity-Key` không tạo server-side
memory (khớp Q1: gateway không có handler cho chúng). Treat output DeepSeek là
dữ liệu không tin cậy; tín hiệu dùng ở đây chỉ là "có/không chứa tên Khoa".

Receipt đã che credential (chỉ fingerprint + nội dung reply):
`C:\Users\Gtvkun\AppData\Local\Temp\eris-gw-session-probe-receipt.json`
(+ log `eris-gw-probe2-out.txt`). Script probe nằm trong Temp, không triển khai.

### Q3. NẾU STATELESS: cần sửa gì để làm ý user (gửi ngữ cảnh 1 lần)?

Để "gửi ngữ cảnh 1 lần, lượt sau chỉ gửi tin mới" hoạt động, cần server-side
memory THẬT. Hai đường:

1. **Gateway tự giữ transcript theo session** (biến whale2api thành stateful):
   - Thêm handler đọc `X-Session-ID`, lưu transcript per-session server-side,
     và khi call sau chỉ có user turn mới thì **tự ghép** transcript cũ vào
     `FinalPrompt` trước khi gọi DeepSeek. Hoặc dùng cơ chế `parent_message_id`
     của DeepSeek: giữ `chat_session_id` + message id cuối cho mỗi session, và
     set `parent_message_id` = id đó ở call sau thay vì `nil`, KHÔNG auto-delete
     phiên. Điểm sửa: `standard_request.go` (payload), `handler_chat.go`
     (bỏ auto-delete cho session bền), thêm store session→(chat_session_id,
     last_message_id). **Độ lớn: L** (sửa gateway Go + state store + đụng
     account binding vì DeepSeek session gắn với 1 account/token).
   - **Rủi ro:** DeepSeek session thật gắn với 1 account; pool xoay account sẽ
     phá session (xem Q4). Phải ghim account theo session — chính là vai trò
     `X-Whale2-Affinity-Key` hiện bị bỏ qua; phải triển khai thật phía gateway.

2. **Chỉ gửi ngữ cảnh 1 lần nhưng vẫn để Eris chủ động** (không cần gateway đổi):
   - Thực chất đây là bài toán CLIENT: thay vì nhồi full Self+memory 42-45k mỗi
     lượt, cache phần tĩnh và chỉ gửi delta. Đây là hướng của
     `latency-breakdown.md` (cache Self, memory lane riêng, timeout curator).
     **Độ lớn: M**, rủi ro thấp hơn, và GIỮ được quyết định/cá tính ở Root.

**[SUY LUẬN]** DeepSeek Web API (qua whale2api) CÓ khái niệm `chat_session_id` +
`parent_message_id` (bằng chứng: `standard_request.go`, `empty_retry.go` dùng
`parent_message_id` cho retry trong-call). Nên về lý thuyết gateway CÓ THỂ được
nâng cấp để nối lượt bằng `parent_message_id`. Nhưng đó là thay đổi gateway lớn,
và vẫn vướng ràng buộc account + mất-nhớ-dài-hạn (Q5).

### Q4. NẾU STATEFUL: ghim account khả thi tới đâu?

Gateway hiện **stateless** nên câu này mang tính giả định. Nếu sau này làm
stateful theo đường `parent_message_id`:

- **[CODE]** `src/llm/deepseek_workers.py:122-190`: mỗi role có thể dùng role key
  riêng hoặc shared `ERIS_DS2API_API_KEY`. Companion/chat mặc định dùng chung
  gateway key. Account pool nằm phía gateway (Auth.Determine chọn account theo
  token pool).
- **Account pool PHÁ session:** một DeepSeek `chat_session_id` gắn với MỘT
  account/token (phiên tạo bởi `CreateSession` dùng `a.DeepSeekToken`). Nếu
  gateway xoay account giữa các lượt, `parent_message_id` của account cũ KHÔNG
  dùng được với account mới ⇒ mất nhớ. Vì vậy muốn stateful phải ghim account
  theo session (đúng mục đích `X-Whale2-Affinity-Key`, hiện chưa triển khai
  phía gateway). Độ lớn tăng thêm vì phải sửa cả Auth/account selection.

### Q5. Đánh đổi với Living User Memory (nhớ dài hạn)

- Session DeepSeek (nếu có) chỉ nhớ trong MỘT cuộc chat/đời session. Living User
  Memory của Eris (`self.memory_state`, `memory.living_user`,
  `living_user.profile` — xem `latency-breakdown.md` mục 6) nhớ xuyên nhiều
  ngày/phiên, có provenance và recall do curator quản.
- Nếu đẩy nhớ sang session DeepSeek: **mất nhớ dài hạn** khi session hết hạn/
  reset/đổi account, và mất lớp admission/provenance của curator. Ý này tối đa
  chỉ thay được "nhớ trong phiên", KHÔNG thay được "nhớ dài hạn".
- **[SUY LUẬN]** Vì vậy ngay cả khi gateway thành stateful, Eris vẫn phải giữ
  Living User Memory ở client và vẫn phải seed nó vào ngữ cảnh — nên khoản token
  nặng nhất (Living User Memory) KHÔNG biến mất. Ý user không giải được gốc token.

### Q6. KẾT LUẬN

**(a) Stateful hay stateless:** **STATELESS** — bằng chứng ping: call 2 không
nhớ "Khoa" ở cả 2 kịch bản (có/không header phiên); bằng chứng source:
`parent_message_id: nil` + `chat_session_id` mới mỗi call + auto-delete + không
có handler `X-Session-ID`/affinity.

**(b) "Gửi ngữ cảnh 1 lần" khả thi không:** KHÔNG với gateway hiện tại. Để làm
được phải nâng gateway thành stateful (giữ `chat_session_id`+`parent_message_id`,
bỏ auto-delete, ghim account theo session) — **độ lớn L, rủi ro cao** (đụng
account pool, Go gateway, và vẫn vướng (c)). Client cũng phải đổi để chỉ gửi
delta (hiện luôn gửi full `messages`).

**(c) Giữ Living User Memory dài hạn:** KHÔNG qua session DeepSeek. Session chỉ
nhớ trong phiên; nhớ dài hạn vẫn phải ở client. Nên khoản token Living User
Memory (phần nặng nhất) không giảm nhờ ý này.

**(d) Ước lượng giảm token/latency NẾU làm được:** thấp và không chắc. Phần
"chat history" mà session có thể gánh hộ là NHỎ so với Self 81k + Living User
Memory client nhồi mỗi lượt (payload 42-45k token — `latency-breakdown.md` mục 6).
Vì nhớ dài hạn vẫn phải gửi, phần cắt được chủ yếu là lịch sử lượt gần — không
phải nguồn token chính. **[SUY LUẬN]** giảm token thực tế khiêm tốn, không tương
xứng rủi ro.

**(e) Độ lớn + rủi ro:** L (gateway Go + account binding + client delta) với
rủi ro mất nhớ dài hạn, mất provenance curator, và phá vỡ khi pool xoay account.

**Khuyến nghị (không implement ở đây):** KHÔNG theo đường "đẩy nhớ sang DeepSeek
Web session". Thay vào đó theo `latency-breakdown.md`: (1) đưa memory/curator ra
khỏi critical path (timeout cứng ~1-2s, degraded cache) — cú sốc 42s; (2) cache
Self per-phiên thay vì dựng lại 81k ký tự mỗi lượt. Hai hướng này giảm đúng
nguồn token/latency ở CLIENT mà không đụng chất lượng/cá tính và không phụ thuộc
một gateway stateful chưa tồn tại.

---

## PHÂN TẦNG BẰNG CHỨNG
- **[CODE] client:** `src/llm/client.py:58-96,149-247,912-936`;
  `src/llm/web_session_guard.py:1-16,69-125`; `src/llm/deepseek_workers.py:122-190`.
- **[CODE] gateway:** `tools/whale2api/internal/promptcompat/standard_request.go:56-98`
  (`parent_message_id:nil`); `.../completionruntime/nonstream.go:81-95`
  (`CreateSession` mỗi call); `.../httpapi/openai/chat/handler_chat.go:35-39,136-158`
  (auto-delete); `.../config/store.go:34-37` (default `Mode:none`);
  `.../httpapi/openai/shared/empty_retry.go:29-47` (`parent_message_id` chỉ cho
  retry trong-call). grep `r.Header.Get(` gateway = chỉ Content-Type/X-Model-Type/
  X-Whale2-Test-Trace; `X-Session-ID`/`X-Whale2-Affinity-Key` = 0 handler.
- **[PING]** gateway :5103, key fp `4bb78ee5`: 4 call /chat/completions, cả 4 đều
  200; call 2 (có/không header phiên) đều KHÔNG nhớ "Khoa". Receipt che credential:
  `C:\Users\Gtvkun\AppData\Local\Temp\eris-gw-session-probe-receipt.json`.
- **[SUY LUẬN]** account pinning phá session khi stateful; token cắt được nhỏ so
  với Living User Memory client nhồi; nên ý user không giải gốc latency.
- Nội dung nguồn đã được diễn giải lại cho phù hợp giấy phép khi cần.
