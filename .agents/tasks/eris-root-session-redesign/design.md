# Thiết kế: tách "true state" khỏi "derived prompt" cho Root conversation session

Ngày: 2026-10-16. Trạng thái: **thiết kế, chưa code**. Repo dev đọc source:
`c:\Users\Gtvkun\Documents\GitHub\eris` (HEAD `c3805cc6`, branch `main`). Bản
portable đang chạy: `C:\Users\Gtvkun\Documents\eris`.

Mọi dòng gắn nhãn **[đọc source]** là quan sát tĩnh trên checkout hiện tại
(file+line). Mọi dòng gắn nhãn **[giả định thiết kế]** là lựa chọn thiết kế,
không phải sự thật về code. Mọi dòng gắn nhãn **[chưa xác minh]** cần kiểm trước
khi code.

---

## 0. Premise bắt buộc phải chốt TRƯỚC khi code (step zero)

Hai điều kiện tiên quyết; nếu sai, phần gateway/cache của thiết kế không có hiệu
lực live:

### 0.1 messages.go dev ≠ portable — chưa biết binary chạy từ cây nào

- **[đọc source]** Dev `tools/whale2api/internal/prompt/messages.go`:
  `MessagesPrepareWithThinking` nối phẳng mọi message bằng role-marker
  (`::sys::`/`::user::`/`::asst::`...) rồi `strings.Join(parts, "")`
  (messages.go:26-77). **Không** có `outputIntegrityGuardPrompt`.
- **[đọc source]** Portable `C:\Users\Gtvkun\Documents\eris\...\messages.go`:
  dùng marker fullwidth DeepSeek (`<｜System｜>`...), `strings.Join(parts,
  "\n\n")`, VÀ còn `outputIntegrityGuardPrompt` +
  `prependOutputIntegrityGuard` (chèn một system prompt tiếng Trung vào đầu
  mảng, messages.go:68-96 bản portable). Đây đúng là hành vi mà
  `docs/knowledge/2026-10-14-eris-runtime-lessons.md` Mục 9 nói "đã bỏ" ở cây
  dev — **cây portable chưa bỏ**.
- Hai file khác nhau SHA-256 (khớp token-growth-report §F). **[chưa xác minh]**
  binary gateway đang phục vụ build từ cây nào.
- **Hệ quả cho thiết kế:** phần "sửa mess.go để đặt cache boundary" (§4) chỉ có
  tác dụng live nếu sửa đúng cây đã build ra binary đang chạy. **Việc đầu tiên
  của giai đoạn code gateway là xác định cây nguồn của binary** (so SHA-256
  binary trong container Compose `whale2api` với binary build từ mỗi cây; hoặc
  đọc build metadata/`version.go`). Mục 9 lessons ghi image cũ được giữ ở tag
  `eris-whale2api-backup:before-plain-text-20261015` — dùng để đối chiếu.

### 0.2 Upstream DeepSeek Web KHÔNG giữ context giữa các request — prefix cache thật sự không khả dụng ở transport hiện tại

Đây là phát hiện quyết định hình dạng §4.

- **[đọc source]** Mỗi request, gateway tạo một session upstream MỚI
  (`ds.CreateSession`) trong `StartCompletion`
  (`internal/completionruntime/nonstream.go:82`), build payload với
  `chat_session_id = sessionID` mới (`internal/promptcompat/standard_request.go:56-77`
  `CompletionPayload`), rồi **auto-xóa session đó** ngay sau khi trả lời:
  handler `defer h.autoDeleteRemoteSession(...)`
  (`internal/httpapi/openai/chat/handler_chat.go:34-39`;
  `internal/httpapi/openai/responses/auto_delete.go:12-29`
  gọi `DeleteSessionForToken`).
- Nghĩa là **không có context server-side nào sống qua request**: toàn bộ prompt
  (gồm cả khối Self) được nhét vào field `prompt` text của một session dùng-một-
  lần, upstream tokenize lại từ đầu MỖI lượt. `X-Session-ID` của Eris
  (`src/llm/client.py:160-221`, `_web_session_header`) chỉ là **account
  affinity + SessionGuard key** để ghim lượt vào một account gateway, **không**
  phải khóa prefix-cache upstream.
- **[chưa xác minh]** DeepSeek Web upstream có hỗ trợ prompt-prefix caching
  (giảm giá token cho prefix lặp) hay không. API `/v1/chat/completions` của
  DeepSeek *platform* (api.deepseek.com) có "context caching" tự động, nhưng
  đường Root đi là **DeepSeek Web qua Whale2API localhost**, không phải platform
  API (`root_session.start` chặn `api.deepseek.com`, chỉ warm-up localhost —
  root_session.py:131-134). Context caching của platform **không áp dụng** cho
  transport Web hiện tại.
- **Kết luận premise:** Option A (dựa vào prefix cache upstream) **không khả thi
  với transport Web hiện tại**. Thiết kế phải đặt cache boundary ở tầng Eris +
  gateway (Option B là đường chính), xem §4. Nếu sau này chuyển Root sang
  DeepSeek platform API thì mới mở lại Option A.

---

## 1. Bản đồ code hiện tại (mọi dòng [đọc source])

### 1.1 self._messages được dựng / append / gửi ở đâu

- Khởi tạo rỗng: `src/runtime/conversation/root_session.py:99`
  (`self._messages: list[dict[str, str]] = []`).
- Prime (nạp Self một lần): `root_session.py:211-235` `_prime`. Dựng
  `messages = [system, {user: bootstrap chứa eris_self_full}]`
  (root_session.py:216-230), gọi `_call`, rồi
  `self._messages = messages + [{"role":"assistant", "content": original}]`
  (root_session.py:231). Log `full Self loaded; sections=%d chars=%d` ở
  root_session.py:235 (chars = `len(messages[1]["content"])`, tức khối Self).
- `_read_self`: gom 4 nguồn — `mind_state`, `subject_self`, `memory_state`,
  `long_term_memory` (root_session.py:33-77). Chú thích "KHÔNG lọc top-k", "Có
  thể rất dài ở lần nạp đầu" (root_session.py:59-60). `sections=4` = 4 nguồn
  này. `chars≈116010` = độ dài JSON của bootstrap user message.
- Append mỗi lượt: trong `ask`, `messages = self._messages + [{user:
  step_payload}]` (root_session.py:303 và lại ở 331 sau khi re-prime), và sau
  khi có reply, `self._messages = messages + [{"role":"assistant", "content":
  original}]` (root_session.py:331). → **append 2 message/lượt, sống suốt phiên**.
- Reset chỉ khi: lỗi/exception (`_clear()` ở root_session.py:150-158, và trong
  except của `ask` ~340-342) hoặc khi `not self._fits(...)` → re-prime toàn bộ
  (root_session.py:312-330).
- `_fits`: cap = `hard_cap_for_provider(provider)`; với deepseek localhost nới
  lên `max(cap, ERIS_ROOT_SESSION_PROMPT_CAP_TOKENS=90000)` (root_session.py:
  160-178). Tức session chỉ "xả" khi gần chạm ~90k token — để nó phình gần tối
  đa rồi mới reset.

### 1.2 Delta protocol hiện tại

Trong `root_session.ask` (root_session.py:239-343):

- **self_delta**: `self_delta = _changed(self._self, self_now)`
  (root_session.py:247). `_changed` (root_session.py:63-85) chỉ trả field
  mới/đổi, dùng tombstone `{"__erased_from_self": True}` cho field bị xóa và
  `{"__value_now_null": True}` cho giá trị thành null. Gắn vào payload tại
  `step_payload["self_changes_since_last_step"] = self_delta`
  (root_session.py:296).
- **history delta/reconcile**: tìm overlap suffix/prefix giữa `self._last_history`
  và `history` hiện tại (vòng `for length in range(...)` root_session.py:283-286).
  Nếu nối tiếp được → `recent_public_history_delta = history[overlap:]`
  (root_session.py:287-290). Nếu `overlap == 0` và có previous →
  **`recent_public_history_reconcile = history` (NGUYÊN cửa sổ)**
  (root_session.py:291-293). Gắn vào payload ở root_session.py:299-300.
- **runtime_context_delta**: `_changed(self._last_context, current_ctx)`
  sau khi loại các field bị nạp lại (`personality_context`,
  `personality_summary`, `relationship_context`, `previous_public_excerpt`,
  `memory_context`) (root_session.py:296-298).
- **recent_public_delivery_updates**: chỉ status đổi so với
  `self._last_delivery_status` (root_session.py:266-270, 301-302). Đây là delta
  cơ học bằng `delivery_id`, không replay.
- **step_payload** = payload gốc trừ `recent_public_history` và
  `runtime_context` (root_session.py:299).
- Log cuối: `root_delta_sent steps=%d self_fields=%d public_turns=%d`
  (root_session.py:336-338). `steps=(len(self._messages)-1)//2` = tổng lượt tích
  lũy; `public_turns=len(new_history)` = số lượt history MỚI lượt này (không
  phải tổng).

**Vì sao reconcile phá overlap:** `_chat_history_for_llm`
(`src/runtime/prompt_context_builder.py:313-351`) khi assistant có
`delivery_status ∈ {pending, cancelled, failed}` thì chèn `context_note`
(vd `[Đã hiển thị; TTS chưa xác nhận phát xong]` cho pending) vào **`content`**
(dòng 334-345), nhưng giữ `raw_content` = lời gốc (dòng 346-349).
`root_session.ask` so overlap trên
**`raw_content`** (root_session.py:259-261 dùng `item.get("raw_content",
item.get("content"))`). Vậy khi receipt flip, `raw_content` KHÔNG đổi — overlap
đáng ra vẫn khớp. **[chưa xác minh đầy đủ]** cơ chế chính phá overlap trong code
HEAD hiện tại: ứng viên là (a) cửa sổ history trượt khiến prefix cũ bị đẩy ra khi
`history_id` không đủ ổn định giữa process/limit khác nhau, hoặc (b) đổi
`delivery_status` làm thay đổi tập `statuses`/thứ tự. token-growth-report §E và
degrade-report §2.5 ghi reconcile 16→18 entries là quan sát từ audit cũ
(checkout `e9cc50e5`); trên HEAD `c3805cc6` so-sánh dùng `raw_content` nên cần
re-verify bằng trace mới. **Dù nguyên nhân chính xác là gì, thiết kế state mới
dưới đây làm reconcile-resend BẤT KHẢ THI về mặt cấu trúc** (xem §3), nên không
phụ thuộc việc chốt nguyên nhân cũ.

### 1.3 Client gửi messages tới gateway

- `root_session._call` → `router.invoke_structured_worker(..., cognitive_lane=
  "root_conversation", conversation_messages=messages, ...)`
  (root_session.py:180-205).
- Router: `model_router.py:1518-1527` — nếu `conversation_messages is not None`
  thì gửi NGUYÊN `[dict(m) for m in conversation_messages]` xuống
  `client.create_chat_completion(messages=...)`, **không tự cắt cửa sổ**.
- Client gửi: `src/llm/client.py:747-926` (`create_chat_completion` của
  OpenAI-compatible client). Header `X-Session-ID` chỉ set khi
  `web_session_mode` phù hợp (client.py:874-926), là session-affinity key.
- **Preflight/degrade:** `_brokered_post` (client.py:359-422): `supports_input_
  degrade` yêu cầu **KHÔNG** có `X-Session-ID` persistent (client.py:360-366).
  Khi degrade bật và broker cấp budget nhỏ hơn, gọi `_enforce_prompt_cap`
  (client.py:410-414) → cắt như §1.4.

### 1.4 compress-delete-persona (gốc "hóa ngu")

- `enforce_prompt_cap` (`src/llm/token_budget.py:370-421`): (1) bảo vệ mọi
  `role=system` + 5 lượt gần nhất; (2) bỏ history cũ ngoài vùng bảo vệ; (3) nếu
  vẫn vượt → `compress_system_message` cho từng system message; (4) nếu vẫn vượt
  → `_truncate_to_cap`. (Số dòng con ±, theo HEAD `c3805cc6`.)
- `compress_system_message` (token_budget.py:338-367): **XÓA HẲN** block chứa
  `"PrivateMind speech bias"`, block chứa `"Nhật ký nội tâm hiện tại"`
  /`"recently_resolved"`/`"Đã nguôi gần đây"`; và **THAY** block persona
  (`"Bạn là ERIS"`/`"Bạn là Eris"`, nếu > 250 ký tự) bằng đoạn generic ngắn.
  → mất cá tính/nội tâm.
- `_shrink_system_by_blocks` (token_budget.py:245-287) + `_system_block_priority`
  (token_budget.py:198-243): hard markers (TurnFrame/ResponseContract/
  `[grounding]`/`[dynamic_policy]`/`latest visible` = 100, không bao giờ bỏ),
  medium (state_style/capability/voice policy = 60), **optional (private mind/
  thought_stream/nhật ký nội tâm/inner diary/recently_resolved/content seed/
  ambient = 10, bỏ trước)**. Grounding được bảo vệ; **persona mềm bị cắt trước**.
- **Điều kiện bật:** chỉ khi prompt vượt cap. Với Root localhost, cap ≈ 850k
  (provider `local`, token_budget.py:112-158) hoặc nới 90k cho lane
  `root_conversation` (`root_session_prompt_cap`, token_budget.py:441-468).
  Request Root quan sát ~242k-284k byte (~60-80k token) < cap ⇒ preflight
  hard-cap **ít khi** bật localhost. Dễ bật khi fallback official DeepSeek
  (budget 200k) hoặc lane siết (`chat`=4800, token_pressure). → degrade-report
  §2.1-2.2.

### 1.5 Lane nền KHÔNG dùng session này

- **[đọc source]** Các lane nền gọi `_call` với `conversation_messages=None`
  (mặc định; model_router.py:1496, 1612), nên router dựng payload one-shot
  `[system, user]` (model_router.py:1522-1525). Chỉ Root đi qua
  `RootConversationSession` (`agent.py:195`, `agent.py:265` gọi
  `self._root_session.ask`). Surface writer/observer/executive/inner/seed/
  curator KHÔNG đi qua session tích lũy (token-growth-report §D). → thay đổi
  session Root **không** ảnh hưởng các lane này (xác nhận không collateral).

---

## 2. STATE mới: hình dạng chính xác

Nguyên tắc: `self._messages` (append-only text) **biến mất**. Thay bằng
**structured state** mà prompt được RE-RENDER mỗi lượt từ đó. Trạng thái sống
trong `RootConversationSession`.

```python
# [giả định thiết kế] — mô tả cấu trúc, chưa phải code cuối.

@dataclass
class SelfReference:
    """Identity Eris, nạp MỘT lần ở prime. Bất biến trong vòng đời session."""
    content_json: str          # JSON của eris_self_full (~116k chars), nguyên văn
    sections: int              # số nguồn (hiện 4)
    char_len: int              # len(content_json), cho log/telemetry
    fingerprint: str           # sha256(content_json)[:16] — để biết Self đã đổi
    ack_reply_raw: str         # raw wire reply của bootstrap ack (kind=no_reply)

@dataclass
class TurnRecord:
    """Một lượt hội thoại trong history, là DỮ LIỆU, không phải text."""
    turn_id: str               # ID ỔN ĐỊNH, xem §2.1
    role: str                  # "user" | "assistant"
    content: str               # lời gốc (== raw_content, KHÔNG chèn context_note)
    delivery_id: str | None    # chỉ assistant có; None nếu không track delivery
    status: str                # "none" | "pending" | "delivered" | "cancelled" | "failed"
    kind: str                  # "public" | "autonomous" (phân biệt độc thoại)

class RootSessionState:
    self_ref: SelfReference | None
    turns: list[TurnRecord]            # THAY cho phần user/assistant của _messages
    runtime_context: dict[str, Any]    # context động hiện tại (full, không delta tích lũy)
    system_prompt: str                 # system contract hiện tại
    last_self_snapshot: dict[str, Any] # self_now của LƯỢT TRƯỚC; baseline cho _changed (§2.3)
    last_context: dict[str, Any]       # runtime_context của lượt trước; baseline cho _changed
    last_reply_raw: str                # raw wire reply Root lượt trước (byte-khớp SessionGuard; xem §2.4)
    # Bỏ: self._messages, self._last_history, self._last_delivery_status,
    #     self._last_context, self._self, self._last_history (chúng là tạo-tác
    #     của giao thức delta/append-only cũ)
```

**Lưu ý về `steps[]` (đã BỎ khỏi state — xem finding #2 / §2.4):** phiên bản
trước của thiết kế có `RootSessionState.steps: list[StepRecord]`. Nó bị bỏ vì
projector (§3.1) không bao giờ render `steps`; để nó trong state hoặc là dead
state hoặc, nếu buộc render, sẽ tái diễn phình tuyến tính. `reply_raw` (byte-khớp
SessionGuard) được giữ dưới dạng **một field vô hướng `last_reply_raw`** (chỉ
lượt gần nhất), không phải list tích lũy — xem §2.4.

### 2.1 turn_id ổn định qua status flip — điểm then chốt

- **[đọc source]** Hiện `history_id` được gán ở `_chat_history_for_llm`
  (prompt_context_builder.py:329-331: `item["history_id"] = f"history:
  {uuid4}"`) và ở `_append_chat_history` (prompt_context_builder.py:395). ID
  đã ổn định cho một turn trong một process. `delivery_id` cũng ổn định
  (prompt_context_builder.py:355).
- **[giả định thiết kế]** `turn_id` của `TurnRecord` = **lấy trực tiếp từ
  `history_id`** mà `_chat_history_for_llm` cung cấp (đã có sẵn, chỉ cần dùng
  làm khóa). Projector KHÔNG bao giờ phái sinh id từ nội dung/thứ tự/status.
  Khi status của một delivery flip (pending→cancelled), **chỉ field
  `TurnRecord.status` đổi tại chỗ bằng khóa `delivery_id`** — `turn_id`,
  `content`, vị trí trong `turns` KHÔNG đổi.
- Hệ quả: không còn khái niệm "overlap suffix/prefix" (đã xóa cùng delta cũ),
  nên không còn nhánh "overlap gãy → reconcile cả cửa sổ". Đây là cách làm
  reconcile-resend **bất khả thi về cấu trúc**, không phải vá.

**[giả định thiết kế]** `turn_id` được gán **MỘT lần tại điểm nhập state** (khi
caller đẩy một turn vào `RootSessionState.turns`): nếu turn đã có `history_id`
ổn định thì dùng nguyên; nếu thiếu (history nạp lại từ process trước), state tự
sinh một id ổn định một lần và lưu vào `TurnRecord.turn_id`. **KHÔNG** để
`_chat_history_for_llm` tái sinh id mỗi lần build (nếu không, mỗi build sẽ ra id
mới và phá chính tính ổn định mà §2.1 dựa vào — xem finding #11). Nói cách khác:
quyền sở hữu id chuyển từ "builder sinh mỗi build" sang "state giữ bền". Projector
đọc `turn_id` từ state, không tự phái sinh.

### 2.2 Self lưu ở đâu

- `self_ref: SelfReference` nạp một lần ở `_prime`. Nội dung Self (`content_json`)
  **không** còn nằm trong một message user tích lũy; nó là **tham chiếu bất biến
  mà projector đặt ở đầu prompt (message 1-3, §3.1)**. Giữ yêu cầu sản phẩm
  "đọc toàn bộ Self, không top-k" ở lần nạp đầu (lessons Mục 1; token-growth
  khuyến nghị 2): `content_json` là nguyên văn `_read_self`, không tóm tắt.
- **Về "cache boundary":** message 1-3 là **prefix bất biến mỗi lượt** — chúng
  là *ứng viên* cache boundary NẾU B1 (session bền) khả thi (§4.2). Nhưng với
  transport Web hiện tại, **chưa có cache boundary nào có hiệu lực**: §0.2 và
  §4.1 kết luận upstream Web không giữ context nên prefix vẫn bị re-gửi + re-count
  mỗi lượt. Projector **không giả định** boundary tồn tại; nguồn tiết kiệm chắc
  chắn là §3 (chặn phình history), không phải cache Self (xem finding #6).
- Self thay đổi runtime (reducer cập nhật) vẫn đi qua **delta nhỏ**
  `self_changes_since_last_step` như hiện tại — xem §2.3 cho baseline đúng.
  `_read_self` + `_changed` được giữ nguyên (root_session.py:33-77 `_read_self`,
  63-85 `_changed`).

### 2.3 Baseline của self-delta: so với LƯỢT TRƯỚC, không phải prime (finding #1)

- **[đọc source]** `_changed(previous, current)` (root_session.py:63-85) so hai
  snapshot và chỉ trả field mới/đổi. Code cũ dùng `previous = self._self`, một
  field được cập nhật MỖI lượt (`self._self = self_now`) → delta là "đổi so với
  lượt trước". Khi bỏ `self._self`, baseline phải được giữ ở nơi khác.
- **[giả định thiết kế]** Baseline = `state.last_self_snapshot` (field mới ở §2):
  ```
  self_now = _read_self(host)
  self_delta = _changed(state.last_self_snapshot, self_now)   # đổi so với LƯỢT TRƯỚC
  # ... build + gửi payload ...
  state.last_self_snapshot = self_now                         # cập nhật sau khi gửi
  ```
  **`self_ref.content_json` (Self lúc prime, bất biến) KHÔNG được dùng làm
  baseline delta** — nếu dùng, delta sẽ là "toàn bộ thay đổi kể từ prime" và
  phình dần theo phiên (đúng bệnh ta đang chữa). `self_ref` chỉ phục vụ prefix
  bất biến (§3.1 điểm 2). Tương tự, `runtime_context_delta =
  _changed(state.last_context, current_ctx)` và cập nhật `state.last_context`
  sau khi gửi.
- Test bảo vệ: `test_self_delta_is_vs_last_turn` (§6.2).

### 2.4 Vì sao bỏ `steps[]`, và `reply_raw` được giữ ở đâu (finding #2)

- Projector (§3.1) dựng prompt từ `self_ref` + `turns` (window) + step payload
  hiện tại; nó **không** render chuỗi `StepRecord` nào. Không nguồn nào
  (token-growth §1/§C, degrade-report, brief) yêu cầu Root thấy lại chuỗi quyết
  định cũ trong prompt; ngược lại, mục tiêu là **chặn phình**, nên đưa `steps[]`
  vào prompt đi ngược mục tiêu. Vì vậy **bỏ `steps[]` khỏi state** (dead state
  nếu giữ mà không render; tái phình nếu render).
- **`reply_raw` vẫn cần cho SessionGuard V3 byte-khớp** (lessons Mục 7: reply
  raw của Root phải khớp byte để resync). Nhưng chỉ cần **reply raw của lượt gần
  nhất**, không phải cả chuỗi. Vì vậy giữ nó dưới dạng field vô hướng
  `state.last_reply_raw` (§2), cập nhật sau mỗi `ask`. Nó **không đi vào
  prompt** (projector không đọc nó); nó chỉ phục vụ byte-sink/SessionGuard ở
  tầng client/model_router như hành vi hiện tại (root_session.py:231/331 lưu
  reply raw; model_router raw sink). `StepRecord` không còn tồn tại trong thiết
  kế này.

### 2.5 Vòng đời của `SelfReference.fingerprint` (finding #10)

`fingerprint = sha256(content_json)[:16]`. Vì `self_ref` bất biến trong một
phiên, fingerprint dùng vào hai việc, nói rõ để không là field chết:

1. **`X-Whale2-Prefix-Id`** cho B2 (§4.2) — khóa content-addressed prefix store
   ở gateway (chỉ có ý nghĩa khi B2 chạy).
2. **Telemetry/log** (`sections`, `char_len`, `fingerprint`) để đối chiếu phiên.

**Không** dùng fingerprint để tự re-prime giữa phiên (Self cố ý bất biến trong
vòng đời session; nếu owner-state Self đổi lớn, việc nạp lại là một **session
mới** chứ không phải mutate `self_ref` giữa chừng — giữ nguyên bất biến "một
session nạp Self một lần", root_session.py:35-37 chú thích "chỉ session mới nạp
lại toàn bộ Self"). Nếu sau này muốn re-prime nóng, đó là thay đổi riêng, không
thuộc thiết kế này.

---

## 3. PROJECTOR: pure function render(state) -> messages[]

### 3.1 Chữ ký và hợp đồng

```python
# [giả định thiết kế]
def project_root_messages(state: RootSessionState, *, window_k: int) -> list[dict[str, str]]:
    """Pure function: cùng state + window_k luôn cho cùng messages.

    KHÔNG đọc clock, không gọi _read_self (self đã nằm trong state), không mutate
    state, không có side effect. Idempotent và size-bounded theo window_k.
    """
```

Thứ tự message trả về (quyết định để tối đa ổn định prefix):

1. `{"role": "system", "content": state.system_prompt}` — contract tĩnh, đứng đầu.
2. `{"role": "user", "content": <bootstrap chứa self_ref.content_json + instruction>}`
   — khối Self BẤT BIẾN, byte-khớp với `_prime` hiện tại (root_session.py:216-231).
3. `{"role": "assistant", "content": state.self_ref.ack_reply_raw}` — ack
   `kind=no_reply` (giữ cho SessionGuard byte-khớp như hiện tại).
4. Với mỗi turn trong `window(state.turns, window_k)`: render thành message
   `{role, content}`, trong đó content của assistant đã mang **status** render
   thuần (§3.3). Turn cũ ngoài window: xem §3.4.
5. Message cuối: `{"role": "user", "content": <step_payload lượt hiện tại>}`
   — chứa event/note/tool_results + `self_changes_since_last_step` +
   `runtime_context_delta`. **KHÔNG** còn `recent_public_history_delta`/
   `reconcile` (history nay nằm ở các message điểm 4), và **KHÔNG** còn
   `recent_public_delivery_updates` cho turn in-window (status đã render thuần
   trong window — xem §3.3 về nguồn-sự-thật-đơn).

**Điểm 1-3 là prefix bất biến mỗi lượt.** Chúng là *ứng viên* cache boundary
NẾU B1 khả thi (§4.2); với transport Web hiện tại chúng vẫn re-gửi + re-count
mỗi lượt (§0.2). Projector không giả định boundary tồn tại (finding #6).

### 3.2 Window rule và giá trị K

- **Rule (định nghĩa tường minh để không mơ hồ — finding #7):** window =
  **2K turn thô gần nhất trong `state.turns`**, tức `turns[-2K:]`, **bất kể
  role/kind**. K là tham số "số cặp danh nghĩa"; triển khai KHÔNG cố ghép cặp
  (user, assistant) — vì chuỗi có thể không xen kẽ đều (autonomous turn là Root
  tự nói, không có user ghép cặp; `_append_chat_history`
  prompt_context_builder.py:383-408 append assistant autonomous không kèm user).
  Autonomous turn tính như một turn thường. Lấy `turns[-2K:]` loại bỏ mọi nhập
  nhằng "đếm cặp".
- **[giả định thiết kế] K = 12 (→ giữ 24 turn thô gần nhất).** Căn cứ:
  - **[đọc source]** Caller cung cấp cửa sổ `recent_public_history[-32:]`
    (agent.py:705-716) và `_chat_history_for_llm(limit=16)` mặc định
    (prompt_context_builder.py:313, `valid_entries[-limit:]`). Audit cũ quan sát
    `public_turns=16` (lessons Mục 8). 24 turn thô (≈12 cặp) nằm trong vùng
    history mà hệ thống vốn đã mang, không mở rộng ngữ cảnh, chỉ **chặn trần**.
  - **[đọc source]** Budget: mỗi public turn content bị cắt `[:12000]` ký tự ở
    payload Root (agent.py:709) và `[:180]` cho id. Thực tế content hội thoại
    ngắn hơn nhiều. 24 turn ở mức vài nghìn token — nhỏ so với Self ~30-39k token
    (token-growth §B) và dưới cap 90k với biên lớn.
  - 24 turn thô ≲ 32 (cửa sổ caller) để projector **chủ động** cắt chứ không chờ
    caller; đồng thời đủ dài để không mất mạch hội thoại điển hình
    (degrade-report §7 cảnh báo đừng để window quá ngắn). K là **env-tunable**
    (`ERIS_ROOT_SESSION_WINDOW_PAIRS`, default 12) để điều chỉnh theo đo đạc
    (§6) mà không sửa code.
- **Guaranteed size-bounded (bound đo trên list projector, tầng Eris):** số
  message projector trả ra = 3 (Self prefix) + `len(turns[-2K:])` (≤ 2·K) + 1
  (step hiện tại) + ≤1 (identity-carry message §3.4) = **hằng số theo K**, KHÔNG
  phụ thuộc độ dài phiên.
- **Lưu ý wire ≤ bound (finding #5):** gateway `MessagesPrepareWithThinking`
  **merge các message cùng role liền nhau** (messages.go:40-44:
  `merged[len-1].Text += "\n\n" + msg.Text`). Vì vậy **số block trên wire có thể
  NHỎ HƠN** bound ở trên khi hai message liền kề cùng role bị gộp. Bound tuyên bố
  là bound ở **tầng list Python của projector** (nơi `test_projector_bounded`
  §6.2 assert), không phải số block wire. Để tránh gộp **ngữ nghĩa** sai, xem
  §3.4 (chốt role của identity-carry).

### 3.3 Render turn theo status — một nguồn sự thật duy nhất (finding #3)

**Nguồn sự thật đơn:** status của một turn render **CHỈ** từ
`TurnRecord.status` của chính turn đó trong window. `recent_public_delivery_updates`
(delta status cũ, root_session.py:266-270) bị **BỎ** vì giờ dư thừa — status
đã nằm trong window và được render thuần, nên không cần một kênh delta thứ hai
ở message cuối. Loại bỏ kênh thứ hai làm **không thể** có cửa sổ Root thấy hai
giá trị khác nhau cho cùng `delivery_id` (đúng yêu cầu brief: xóa "nhiều cách
diễn giải").

Quy tắc render (hàm thuần của `TurnRecord.status`):

- `status == "delivered"` hoặc `"none"`: render `content` gốc.
- `status ∈ {"pending", "cancelled", "failed"}`: render content gốc **kèm một
  nhãn trạng thái tách biệt** để Root biết câu chưa chắc đã phát. Dùng chính các
  nhãn hiện có (prompt_context_builder.py:336-342) để giữ ngữ nghĩa đã quen:
  `pending → "[Đã hiển thị; TTS chưa xác nhận phát xong]"`,
  `cancelled → "[Đã hiển thị; âm thanh bị ngắt giữa chừng]"`,
  `failed → "[Đã hiển thị; phát âm thanh thất bại]"`.
- **Khác biệt then chốt với code cũ:** nhãn là HÀM THUẦN của `status` tại thời
  điểm render — khi status flip, projector tự render lại nhãn, KHÔNG cần
  "reconcile" gì, KHÔNG đổi `turn_id`, KHÔNG đổi `content` gốc, KHÔNG đổi vị trí
  turn trong window. Đây là chuyển `context_note` của prompt_context_builder.py:
  334-345 từ "mutate content, gửi lại cả cửa sổ khi overlap gãy" sang "derived
  mỗi lần render từ một field".
- **[giả định thiết kế]** `TurnRecord.content` luôn là **lời gốc** (==
  `raw_content`, không chèn nhãn). Nhãn trạng thái được projector nối **sau**
  content khi render (hoặc đặt trong field riêng của JSON turn nếu format turn
  là JSON) — không chèn vào đầu câu để khỏi đổi ngữ nghĩa (giữ tinh thần
  agent.py:709). Ràng buộc cứng: **status không bao giờ là một phần của khóa
  định danh**; chỉ `turn_id` + `delivery_id` định danh, `status` chỉ ảnh hưởng
  phần hiển thị.
- **Thứ tự cập nhật state khi flip:** flip chỉ gán `TurnRecord.status` tại chỗ
  qua khóa `delivery_id` trong `state.turns`; không chạm `turn_id`/`content`/thứ
  tự. Lần `ask` kế tiếp projector đọc state đã cập nhật → nhãn mới xuất hiện ngay,
  không có đường thứ hai nào mang giá trị cũ. Test: `test_status_single_source`
  + `test_status_flip_no_resend` (§6.2).

### 3.4 Turn cũ rời window: identity-carry, không drop câm

- **[giả định thiết kế]** Khi `len(state.turns) > 2K`, các turn cũ nhất bị đẩy
  khỏi window **không bị xóa im lặng**. Projector chèn **một message tóm tắt
  định danh ổn định** ngay trước window.
- **Role của carry = `system` (chốt — finding #5).** KHÔNG dùng `role=user`:
  turn đầu window có thể là `user`, và gateway merge same-role liền nhau
  (messages.go:40-44) sẽ **trộn** carry vào turn user đầu window, làm lệch ngữ
  nghĩa và làm số block wire khác bound. Dùng `role=system` cho carry: nó không
  liền kề một system khác (các system ở message 1 cách xa bởi Self+ack+window),
  nên không bị merge với window; đồng thời "ghi chú về lịch sử trước đó" hợp
  vai system hơn vai user. Message carry:
  `{"role": "system", "content": "<đã có N lượt trước đó trong phiên này; các
  turn gần nhất giữ ở dưới>"}`.
- Nội dung carry phải **phái sinh thuần** từ các `TurnRecord` bị loại (đếm số
  lượt bị loại; tùy chọn liệt kê `turn_id`), KHÔNG gọi LLM, KHÔNG tóm tắt động
  (giữ pure + idempotent). Lý do không drop hẳn: degrade-report §7 và RISKS (§8)
  — mất mạch khi window ngắn. Lý do không tóm tắt bằng LLM: lessons Mục 2 cấm
  "tưởng tượng một snapshot runtime thay cho cuộc sống Eris"; token-growth
  khuyến nghị 1 nói dùng "identity ổn định cho lượt cũ".
- **[giả định thiết kế]** Mặc định tối giản: chỉ carry **đếm số lượt bị loại**
  (một số nguyên), không carry nội dung. Nếu đo thấy mất mạch (§6), nâng lên
  carry dòng đầu rất ngắn của vài turn gần ranh giới. Chốt cụ thể khi có số đo.

### 3.5-overflow: nhánh `not _fits` cho state mới (finding #4)

Vì output projector đã **bounded theo K** (§3.2), nó không còn tự phình tới cap
như append-only cũ. Do đó `_fits(project(state, K))` chỉ false trong hai trường
hợp biên, và mỗi trường hợp có xử lý tường minh (thay cho "re-prime toàn bộ" của
code cũ, root_session.py:306-320 — khái niệm re-prime không còn ý nghĩa khi
state đã tách):

- **(a) Self vượt cap một mình** (`self_ref.content_json` + 3 message prefix đã
  vượt): projector/`ask` trả **`None`** → caller rơi về **fallback one-shot**
  (agent.py:265-290, như `_prime` cũ trả None khi "full Self vượt cap",
  root_session.py:214). Không cắt Self (giữ yêu cầu sản phẩm "full Self no
  top-k").
- **(b) các turn trong window quá dài** (Self vừa, nhưng 2K turn × tới 12000 ký
  tự vượt phần còn lại của cap): **giảm K tạm thời** `K' = max(2, K // 2)` rồi
  `project(state, K')` lại, lặp giảm tới khi fit hoặc K'=2. **KHÔNG re-prime**:
  `self_ref` giữ nguyên, `turns` giữ nguyên (chỉ window hẹp lại cho lượt này).
  Nếu K'=2 vẫn không fit (một turn đơn lẻ quá dài), để `_truncate_to_cap`
  (token_budget.py:290-339, block-preserving) làm lưới cuối — guard an toàn vẫn
  nguyên (§7).
- Chốt: thử (b) trước (giảm K), chỉ trả None theo (a) khi ngay cả Self một mình
  đã vượt. Hai nhánh loại trừ nhau theo thứ tự kiểm: kiểm (a) trước (prefix-only
  size), rồi (b).

### 3.6 Idempotent & bounded — vì sao đúng

- Pure: không clock, không I/O, không mutate (đã ràng buộc ở chữ ký). Gọi 2 lần
  cùng `(state, K)` → cùng list (idempotent). Chú ý: `self_delta`/
  `context_delta`/cập nhật `last_self_snapshot` (§2.3) **không** nằm trong
  projector — chúng là bước chuẩn bị `step_payload` trong `ask` (có side effect
  cập nhật baseline), còn `project_root_messages` chỉ nhận state đã sẵn + payload
  đã dựng. Giữ projector thuần tuyệt đối.
- Bounded: §3.2 — số message ở tầng list = 3 + `len(turns[-2K:])` + 1 (+≤1 carry),
  hằng theo K; wire ≤ bound do gateway merge same-role.
- Không có nhánh "reconcile": history luôn render từ `turns[-2K:]` cố định.
  Receipt flip chỉ đổi `TurnRecord.status`; projector render lại nhãn trạng thái
  — payload không "nhảy bậc" vì số turn trong window không đổi (một nguồn sự
  thật, §3.3).

---

## 4. CACHE BOUNDARY tại gateway

Mục tiêu: trả **chi phí token của Self một lần**, không re-count mỗi lượt. Prefix
bất biến mỗi lượt = message 1-3 của projector (system contract + Self bootstrap +
ack).

### 4.1 Vì sao Option A (prefix cache upstream) KHÔNG khả dụng hiện tại

Theo premise §0.2: gateway tạo session upstream mới + auto-delete mỗi request
(`nonstream.go:82`, `handler_chat.go:34-39`, `auto_delete.go:12-29`); DeepSeek
Web không giữ context; transport Web không phải platform API nên không có
context-caching tự động. Vậy không có gì để "cache prefix" ở upstream với kiến
trúc transport hiện tại. **[chưa xác minh]** nếu đo được DeepSeek Web thật sự
tính phí prefix lặp rẻ hơn (ít có khả năng), mới cân nhắc lại; mặc định coi là
không.

### 4.2 Option B (ĐƯỜNG CHÍNH): cache prefix phía gateway + đóng gói Self một lần ở caller

Hai lớp bổ sung nhau; cả hai nằm ở tầng ta kiểm soát (Eris + Whale2API), không
phụ thuộc upstream.

**Lớp B1 — Projector không re-gửi Self khi fingerprint không đổi, dùng session
remote bền.** Hiện mỗi request Root tạo session upstream mới nên Self PHẢI đi
kèm. Để Self "nạp một lần" có nghĩa trên wire, gateway cần một **chế độ session
bền cho lane root_conversation**: giữ session upstream sống qua các lượt của một
hội thoại thay vì auto-delete, và chỉ gửi phần Self ở lượt đầu.

- **[đọc source]** Hạ tầng session-affinity đã có: `X-Session-ID`
  (client.py:874-926) + SessionGuard (`GLOBAL_WEB_SESSION_GUARD.reserve`,
  client.py:913-926). Nhưng handler hiện **luôn** auto-delete
  (`defer autoDeleteRemoteSession`, handler_chat.go:34-39). → cần **tắt
  auto-delete cho session bền** và tái dùng `chat_session_id` upstream.
- **[giả định thiết kế]** messages.go/handler phải thay đổi:
  1. Handler chat (`internal/httpapi/openai/chat/handler_chat.go`) + responses:
     khi request mang header đánh dấu lane bền (vd `X-Whale2-Persist: root`
     hoặc tái dùng `X-Session-ID` làm khóa map tới một `chat_session_id` upstream
     đã tạo), **không** `autoDeleteRemoteSession` ở cuối; thay vào đó map
     `X-Session-ID` → `chat_session_id` + `parent_message_id` upstream và tái
     dùng ở lượt sau (`CompletionPayload` hiện set `parent_message_id: nil`,
     standard_request.go:74-77 — cần truyền id lượt trước để nối tiếp upstream).
  2. `MessagesPrepareWithThinking` (messages.go:26): khi session bền đã có Self
     ở lượt trước, caller chỉ gửi phần tăng thêm (step payload + window), KHÔNG
     gửi lại message Self. Render phẳng chỉ phần mới.
- **[đọc source] Bằng chứng DeepSeek Web CÓ cơ chế nối tiếp theo
  `parent_message_id`:** `ClonePayloadForAssistantRetry`
  (`internal/httpapi/openai/shared/empty_retry.go:34-47`) đã set
  `parent_message_id` để "submit retry như một follow-up turn trong CÙNG session
  DeepSeek" (chú thích dòng 34-36). Nghĩa là gateway **đã** biết cách gửi lượt
  nối tiếp vào một session Web sống. B1 tái dùng chính cơ chế này cho lane
  root_conversation, thay vì chỉ dùng khi retry. Đây **giảm** rủi ro B1 nhưng
  không xóa (xem dưới).
- **Rủi ro B1 còn lại:** **[chưa xác minh]** session Web sống được bao nhiêu
  lượt trước khi upstream hết hạn/đổi account, và SessionGuard V3 có hủy chuỗi
  khi một reply lỗi/bị cắt không (lessons Mục 7: "một reply lỗi/bị cắt làm hủy
  chuỗi"). Nếu Web không nối tiếp ổn định qua nhiều lượt, B1 thất bại → rơi về
  B2. Phải đo trên transport thật trước khi dựa vào B1 để bỏ gửi Self.

**Lớp B2 — nếu session bền không khả thi: giảm chi phí Self bằng tham chiếu nén
ở gateway (fallback trong fallback).** Giữ transport dùng-một-lần hiện tại nhưng
cắt token Self lặp lại:

- **[giả định thiết kế]** Thêm **content-addressed prefix store** trong gateway:
  lượt đầu caller gửi Self đầy đủ kèm `X-Whale2-Prefix-Id: <sha256(self)>`;
  gateway lưu (session-affinity account, prefix-id) → nội dung Self. Lượt sau
  caller chỉ gửi `X-Whale2-Prefix-Id`, gateway **nở lại** Self vào đầu `prompt`
  trước khi gọi upstream. Trên wire tới upstream, Self vẫn đi mỗi lượt (vì Web
  không cache) — **B2 KHÔNG giảm token upstream**, chỉ giảm **payload Eris→gateway
  và tránh re-serialize/re-count ở tầng Eris**. Nói thẳng: với transport Web hiện
  tại, **token upstream của Self không thể tránh re-count** trừ khi B1 (session
  bền) hoặc chuyển platform API. Đây là giới hạn thật, không che giấu.
- Vì vậy **ưu tiên B1**; B2 chỉ thu lợi ở biên Eris↔gateway. **Lợi ích token
  upstream chính của toàn thiết kế không đến từ cache Self mà đến từ §3 (chặn
  phình history tuyến tính) — đó mới là nguồn tiết kiệm chắc chắn.** Phải ghi
  rõ điều này để không hứa sai.

### 4.3 Khuyến nghị chốt

- **Giai đoạn 1 (chắc chắn thu lợi, không phụ thuộc gateway):** triển khai §2+§3
  ở tầng Eris. Riêng việc thay append-only bằng projector window-K đã chặn phình
  tuyến tính và xóa reconcile-resend — đo được ngay (§6). **Không cần chạm
  gateway để có lợi ích chính.**
- **Giai đoạn 2 (sau khi chốt premise §0.1):** thử B1 (session bền) để Self
  không re-gửi. Nếu B1 không ổn định trên DeepSeek Web, dừng ở B2 cho biên Eris
  và ghi nhận token Self upstream vẫn re-count (chấp nhận, vì §3 đã là nguồn tiết
  kiệm chính).
- messages.go cần sửa đúng cây đã build binary đang chạy (§0.1).

---

## 5. Backward compatibility & migration

- **Delta protocol cũ:**
  - `self_changes_since_last_step` + `runtime_context_delta`: **GIỮ**, nhưng
    baseline đổi sang lượt-trước-qua-state (`last_self_snapshot`/`last_context`,
    §2.3), không phải field tích lũy.
  - `recent_public_history_delta` / `recent_public_history_reconcile`: **BỎ
    HẲN** — history nay render trong window từ `turns` (§3.1 điểm 4). Khái niệm
    reconcile biến mất ở phía gửi.
  - `recent_public_delivery_updates`: **BỎ HẲN** — status đã render thuần trong
    window, một nguồn sự thật duy nhất (§3.3, finding #3). Không còn kênh delta
    status thứ hai.
- **Schema Root (`ROOT_STEP_SCHEMA`, agent.py):** KHÔNG đổi (7 oneOf giữ nguyên).
  Thiết kế chỉ đổi cách dựng `messages`, không đổi output contract.
- **Migration:** thay thế nội tạng `RootConversationSession` (`_messages`,
  `_self`, `_last_history`, `_last_delivery_status`, `_last_context` →
  `RootSessionState{self_ref, turns, runtime_context, system_prompt,
  last_self_snapshot, last_context, last_reply_raw}` + projector). `steps[]`
  KHÔNG tồn tại (finding #2). API ngoài giữ nguyên: `start`, `ask` (agent.py:265),
  `preload_self` (agent.py:198). `ask` vẫn trả `dict | None` cùng ngữ nghĩa.
  `_prime` đổi để nạp `SelfReference` thay vì set `_messages`.
- **`_fits` và overflow:** `_fits` (root_session.py:160-178) giữ, nay áp lên
  **output projector** `project(state, K)` thay cho `_messages + [...]`. Nhánh
  `not _fits` theo **§3.5-overflow** (giảm K tạm, hoặc trả None nếu Self một
  mình vượt cap) — thay cho re-prime toàn bộ của code cũ (finding #4).
- **Lane nền:** không đổi (xác nhận §1.5 — chúng không dùng session này). Không
  collateral.
- **Fallback one-shot (agent.py:265-290 khi `ask` trả None):** giữ nguyên. Khi
  session chưa warm/lỗi, caller vẫn rơi về `invoke(...)` one-shot với
  `ROOT_BATCH_STEP_SCHEMA`.

---

## 6. VERIFICATION PLAN

### 6.1 Đo token trước/sau trên cùng kịch bản nhiều lượt

- Kịch bản: một phiên chat ≥ 20 lượt user liên tiếp, có ít nhất 3 lần
  pending→cancelled (preemption) để kích hoạt đường reconcile cũ. Chạy trên
  localhost DeepSeek Web.
- Đo: `estimated_input_tokens` (preflight `[LLM PREFLIGHT]` log,
  token_budget.py:preflight) và request bytes trên wire PID gateway, theo từng
  lượt. **Trước:** kỳ vọng tăng tuyến tính + nhảy bậc tại lượt cancelled
  (baseline từ audit: 364k→392k→406k→421k byte, lessons Mục 8/§5). **Sau:**
  kỳ vọng **phẳng** (hằng ≈ Self + ≤2·K turn + step), không nhảy bậc tại
  cancelled.
- **Ngưỡng pass/fail định lượng (finding #9):** vì Self ~30-39k token
  (token-growth §B) dominant, cộng ≤24 turn × vài trăm token + step, kỳ vọng
  input tokens **ổn định trong khoảng ~35k-45k token/lượt** (không tăng theo
  lượt). **FAIL** nếu input tokens lượt 20 vượt lượt 5 quá **+10%** (vẫn tuyến
  tính), hoặc nếu có bất kỳ bước nhảy > +15% tại một lượt cancelled đơn lẻ.
  **PASS** nếu đường token phẳng trong ±5% sau khi phiên ấm (bỏ 2-3 lượt đầu
  warm-up). Con số 35k-45k là kỳ vọng dựa trên ước lượng Self; chốt lại ngưỡng
  tuyệt đối sau khi đo Self thật trên HEAD (Self char_len quan sát ~116k ký tự
  → ~30-39k token tùy tokenizer).
- Metric có sẵn: `GLOBAL_OBSERVABILITY.record_prompt_budget` (token_budget.py
  trong `preflight`) — dùng `before_tokens/after_tokens` để so.

### 6.2 Test chứng minh projector idempotent & bounded (unit)

- `test_projector_idempotent`: dựng `RootSessionState` cố định, gọi
  `project_root_messages(state, window_k=K)` hai lần → assert hai list bằng nhau
  (byte-khớp JSON).
- `test_projector_bounded`: tạo state với 100 turns → assert
  `len(messages) == 3 + min(2*K, len(turns)) + 1 (+1 nếu có identity-carry)`,
  độc lập số turn. Assert đo trên **list projector (tầng Eris)**, không trên số
  block wire (gateway có thể merge same-role — finding #5).
- `test_status_flip_no_resend`: lấy state, project; flip một
  `TurnRecord.status` pending→cancelled bằng `delivery_id`; project lại →
  assert (a) `turn_id`/vị trí/`content` các turn KHÔNG đổi; (b) chỉ dòng trạng
  thái của đúng turn đó đổi; (c) **số message không đổi** (không có cú nhảy cả
  cửa sổ). Đây là test chứng minh reconcile-resend đã biến mất.
- `test_window_drop_carries_identity`: >2K turn → assert có đúng một message
  identity-carry `role=system` ngay trước window, và các turn bị loại không làm
  đổi phần còn lại (các turn in-window byte-khớp).
- `test_self_invariant`: Self content byte-khớp giữa các lần project khi
  `self_ref.fingerprint` không đổi.
- **`test_self_delta_is_vs_last_turn` (finding #12 / #1):** chạy hai lượt; ở
  lượt 1 đặt một field Self, ở lượt 2 đổi một field khác. Assert `self_delta`
  lượt 2 **chỉ** chứa field đổi giữa lượt 1→2 (dùng baseline `last_self_snapshot`),
  KHÔNG chứa field đã có từ prime (chứng minh delta không phình từ prime).
- **`test_status_single_source` (finding #12 / #3):** flip một
  `TurnRecord.status`; assert `step_payload` lượt kế **không** chứa
  `recent_public_delivery_updates` (kênh thứ hai đã bỏ), và nhãn trạng thái của
  đúng turn đó xuất hiện trong window — chứng minh status chỉ đến từ một nguồn.
- **`test_window_is_raw_turns` (finding #7):** dựng state với chuỗi role không
  xen kẽ (vd autonomous assistant liên tiếp) + >2K turn; assert window =
  `turns[-2K:]` chính xác, không phụ thuộc cách ghép cặp.
- **`test_turn_id_stable_on_reload` (finding #11):** nạp một turn thiếu
  `history_id` vào state hai lần (mô phỏng rebuild); assert `turn_id` không đổi
  giữa hai lần (state giữ id, builder không tái sinh).

### 6.3 Xác nhận reconcile-resend đã biến mất (integration)

- Chạy kịch bản 6.1 với fake router ghi lại mọi `conversation_messages`. Assert
  **không** payload nào chứa khóa `recent_public_history_reconcile`, và số
  message mỗi lượt ≤ trần §3.2. (Test với fake router chứng minh contract, KHÔNG
  chứng minh latency/cá tính live — lessons Mục 2; cần thêm 6.1 live cho token.)

### 6.4 Guard an toàn vẫn còn (xem §7)

- Test rằng khi prompt (giả) vượt cap, `compress_system_message` vẫn còn như
  lưới cuối (không bị xóa), và grounding/contract vẫn ưu tiên 100
  (token_budget.py `_system_block_priority`). Thiết kế KHÔNG đổi các hàm này;
  test là regression bảo vệ.

---

## 7. SAFETY BOUNDARIES được giữ nguyên

Thiết kế **không** nới lỏng guard nào:

- **grounding / action-claim / secret-redaction / language / single-speaker:**
  nằm ở runtime_writer + prepare/dispatch + token_budget priority (hard markers
  100), KHÔNG ở `RootConversationSession`. Projector chỉ dựng messages Root; nó
  **không** chạm các guard này. (degrade-report §3.4 language guard
  public_output_artifact.py:139-142 giữ nguyên.)
- **TurnFrame / ResponseContract / [grounding] / [dynamic_policy]:** vẫn trong
  `system` message (projector điểm 1) và vẫn được `_system_block_priority`=100
  bảo vệ nếu compress chạy. Không đổi.
- **compress_system_message giữ làm lưới cuối (secondary, như brief cho phép):**
  KHÔNG xóa. Nhưng vì §3 làm prompt không còn phình tới cap trong đường localhost
  bình thường, nhánh này gần như không chạy → persona không bị xóa vì hệ thống
  không rơi vào trạng-thái-phải-chọn (đúng nguyên tắc brief: giữ persona bằng
  cách không bao giờ phải chọn, không bằng đổi điểm ưu tiên).
  - **[giả định thiết kế, secondary]** ĐỀ XUẤT PHỤ: nếu muốn thêm an toàn, đổi
    `compress_system_message` để **persona bị nén SAU** diary/PrivateMind (hiện
    đã vậy) và cân nhắc đưa persona vào nhóm medium thay vì bị thay generic
    ngay — nhưng đây là thứ yếu, chỉ làm nếu đo thấy compress vẫn trip sau §3.
- **Byte-khớp SessionGuard V3:** reply raw của Root vẫn lưu nguyên văn
  (`state.last_reply_raw`, giữ hành vi root_session.py:331 + model_router raw
  sink; §2.4). Projector tái dựng ack/Self byte-khớp bootstrap cũ.

---

## 8. RISKS & TRADEOFFS

- **Window quá ngắn → Root mất context cũ.** K=12 là [giả định], cần §6 live để
  xác nhận không mất mạch. Giảm thiểu bằng identity-carry (§3.4) + env-tunable K.
  Nếu đo thấy mất mạch, nâng K hoặc nâng mức carry (đếm → dòng đầu). Rủi ro
  ngược: K quá lớn làm mất lợi ích bounded — cân bằng theo số đo, không đoán.
- **B1 (session bền) phụ thuộc hành vi DeepSeek Web chưa xác minh.** Nếu Web
  không nối `parent_message_id` ổn định hoặc SessionGuard hủy chuỗi khi có reply
  lỗi (lessons Mục 7), B1 thất bại. Giảm thiểu: §4.3 tách giai đoạn — lợi ích
  chính (§3) không phụ thuộc B1; B1 là tối ưu thêm, có thể bỏ.
- **Token Self upstream vẫn re-count nếu dừng ở B2.** Nói thẳng ở §4.2: với
  transport Web dùng-một-lần, token Self không tránh được trừ khi B1 hoặc
  platform API. Thiết kế không hứa giảm token Self upstream nếu B1 không chạy;
  nguồn tiết kiệm chắc chắn là chặn phình history (§3).
- **Nguyên nhân chính xác phá overlap cũ chưa chốt trên HEAD (§1.2).** Rủi ro:
  nếu reconcile-resend trên HEAD do nguyên nhân khác audit cũ, thiết kế vẫn xóa
  nó (projector không có nhánh reconcile) nhưng cần test 6.3 để chứng minh thực
  tế, không chỉ lý thuyết.
- **Thay đổi lõi `RootConversationSession`** rủi ro regression ở warm-up/resync.
  Giảm thiểu: giữ API ngoài + fallback one-shot (§5); test idempotent/bounded
  trước khi bật.
- **Error-before-delivery feedback (brief: MAY):** rơi ra tự nhiên từ state —
  `TurnRecord.status` có `"failed"`, và có thể thêm status cho lỗi
  prepare/writer trước delivery. **[giả định thiết kế]** Thiết kế state hỗ trợ
  nó (field status đã tồn tại), nhưng **đường ghi** status "failed trước
  delivery" vào `turns` nằm ngoài projector (ở kernel/dispatch, degrade-report
  §2.4 + khuyến nghị 2). Vì vậy: cấu trúc đã sẵn sàng, nhưng **nối dây feedback
  là follow-up riêng** nếu không muốn mở rộng scope lượt này. Ghi nhận, không
  bắt buộc trong giai đoạn 1.

---

## 9. OUT OF SCOPE (xác nhận theo brief)

- "Mất tiếng do preempt khi message mới đến" (backchannel/STEERING
  misclassification ở ingress) — bệnh khác, thuốc khác (degrade-report §3.5).
  Thiết kế này KHÔNG chạm.
- Thay đổi `compress_system_message` priority là **thứ yếu/tùy chọn** (§7), không
  phải mục tiêu chính.

---

## 10. Tóm tắt quyết định đã CHỐT (để implementer khỏi tự quyết)

1. State: `RootSessionState{self_ref, turns[], runtime_context, system_prompt,
   last_self_snapshot, last_context, last_reply_raw}` thay `self._messages`.
   **KHÔNG có `steps[]`** (finding #2). `turn_id` gán một lần tại điểm nhập
   state, bền qua rebuild/status-flip (finding #11).
2. Projector: pure, window = **`turns[-2K:]` (2K turn thô, K=12 danh nghĩa, bất
   kể role/kind — finding #7)**, env `ERIS_ROOT_SESSION_WINDOW_PAIRS`. Số message
   ở tầng list bounded = 3 + min(2K, len(turns)) + 1 (+1 carry); wire ≤ bound do
   gateway merge same-role (finding #5). Turn cũ → identity-carry **role=system**
   (finding #5), mặc định chỉ đếm số lượt bị loại. Status render thuần theo
   `TurnRecord.status`, không phá id. Overflow: giảm K tạm, hoặc None nếu Self
   vượt cap một mình (finding #4).
3. Reconcile-resend: **xóa khỏi tồn tại** (projector không có nhánh reconcile).
   Status **một nguồn sự thật duy nhất** trong window; **bỏ** cả
   `recent_public_history_delta/reconcile` lẫn `recent_public_delivery_updates`
   (finding #3). Giữ `self_changes_since_last_step` + `runtime_context_delta`,
   baseline = lượt-trước qua `last_self_snapshot`/`last_context` (finding #1).
4. Cache boundary: Option A (prefix cache upstream) **không khả thi** với
   transport Web hiện tại (§0.2). Đường chính là §3 (chặn phình) + §4 B1 (session
   bền, giai đoạn 2, sau khi chốt premise §0.1); B2 chỉ lợi biên Eris↔gateway.
5. Giữ nguyên: schema Root, API session, fallback one-shot, mọi guard an toàn,
   compress làm lưới cuối, lane nền.
6. Premise phải chốt trước code gateway: (a) binary gateway build từ cây dev hay
   portable; (b) đã xác nhận Web không giữ context (đã đọc source: tạo+auto-delete
   session mỗi request).

---

## Phụ lục: tham chiếu file+line đã đọc (bằng chứng)

Số dòng theo HEAD `c3805cc6` (±1 cho các block dài; đã re-verify các điểm review
nêu drift ở finding #8).

- `src/runtime/conversation/root_session.py`: 33-77 `_read_self`; **63-85
  `_changed`**; 99 init `_messages`; 150-158 `_clear`; 160-178 `_fits`; 180-205
  `_call`; 207-237 `_prime` (216-231 bootstrap messages + reassign, 235 log);
  239-343 `ask` (247 self_delta, 256-270 history/statuses + raw_content,
  283-293 overlap/reconcile, 296-302 payload, 303/331 append messages, 331
  reassign `_messages`, 336-338 log).
- `src/llm/token_budget.py`: 112-158 `hard_cap_for_provider`; 198-243
  `_system_block_priority`; **245-287 `_shrink_system_by_blocks`**; **290-339
  `_truncate_to_cap`**; **338-367 `compress_system_message`**; 370-421
  `enforce_prompt_cap`; 441-468 `root_session_prompt_cap`; `preflight`
  (record_prompt_budget).
- `src/runtime/conversation/agent.py`: 18 import; 198 `preload_self`; 265 `ask`;
  265-290 `ask` + fallback one-shot; 705-719 payload `recent_public_history[-32:]`
  (709 content `[:12000]`).
- `src/runtime/prompt_context_builder.py`: 313-351 `_chat_history_for_llm`
  (329-331 history_id tái sinh nếu thiếu — finding #11; 334-345 context_note
  vào `content`, 346-349 raw_content giữ gốc; 348-350 delivery_id/status);
  383-408 `_append_chat_history`.
- `src/runtime/ai_orchestrated/model_router.py`: 1495-1527 `_call`
  (conversation_messages pass-through, không cắt); 1605-1644
  `invoke_structured_worker`.
- `src/llm/client.py`: 160-221 `_web_session_header`; 359-422 `_brokered_post`
  (360-366 supports_input_degrade cần không X-Session-ID; 410-414
  `_enforce_prompt_cap`); 747-926 `create_chat_completion` (874-926 X-Session-ID/
  SessionGuard reserve).
- Gateway dev `tools/whale2api/internal/prompt/messages.go`: 26-77
  `MessagesPrepareWithThinking` nối phẳng `strings.Join(parts, "")`; **40-44
  merge same-role liền nhau** (`merged[len-1].Text += "\n\n" + msg.Text`) —
  finding #5.
- Gateway `internal/httpapi/openai/shared/empty_retry.go`: 34-47
  `ClonePayloadForAssistantRetry` set `parent_message_id` để submit lượt nối
  tiếp trong cùng session DeepSeek — bằng chứng cơ chế B1 (§4.2) đã tồn tại.
- Gateway portable `C:\Users\Gtvkun\Documents\eris\...\messages.go`:
  `outputIntegrityGuardPrompt` + `prependOutputIntegrityGuard`, join `"\n\n"`.
- Gateway `internal/completionruntime/nonstream.go`: 82 `CreateSession`;
  `StartResult/NonStreamResult.SessionID`.
- Gateway `internal/promptcompat/standard_request.go`: 56-77 `CompletionPayload`
  (`chat_session_id`, `parent_message_id: nil`).
- Gateway `internal/httpapi/openai/chat/handler_chat.go`: 34-39 `defer
  autoDeleteRemoteSession` (defer ở ~36, hàm ở 136); `internal/httpapi/openai/
  responses/auto_delete.go`: 12-29 `DeleteSessionForToken`.

---

## 11. Phản hồi review (design-review.json, verdict CHANGES_REQUESTED)

Vòng revise này xử lý toàn bộ 12 finding. Mỗi mục ghi cách xử lý và vị trí đã
sửa. Re-verify các số dòng review nêu trực tiếp trên HEAD `c3805cc6`:
`_changed` = root_session.py:63-85 (xác nhận), `_shrink_system_by_blocks` =
token_budget.py:245-287 (xác nhận), `compress_system_message` = 338-367 (xác
nhận), `history_id` tái sinh = prompt_context_builder.py:329-331 (xác nhận),
merge same-role gateway = messages.go:40-44 (xác nhận).

| # | Sev | Xử lý | Ở đâu |
|---|---|---|---|
| 1 | HIGH | **Addressed.** Thêm `RootSessionState.last_self_snapshot` (+ `last_context`); chốt `self_delta = _changed(last_self_snapshot, self_now)`, cập nhật sau khi gửi; `self_ref.content_json` KHÔNG làm baseline. | §2 (state), §2.3 (mới) |
| 2 | HIGH | **Addressed (chọn A — bỏ `steps[]`).** `steps[]` là dead state (projector không render); đưa vào prompt đi ngược mục tiêu chặn phình. `reply_raw` giữ dưới dạng field vô hướng `last_reply_raw` cho SessionGuard byte-match, không vào prompt. | §2 (state), §2.4 (mới), §5, §10.1 |
| 3 | HIGH | **Addressed (chốt một nguồn).** Status render **chỉ** từ `TurnRecord.status` in-window; **bỏ** `recent_public_delivery_updates`. Thêm thứ tự cập nhật state khi flip. | §3.1 điểm 5, §3.3, §5, §10.3 |
| 4 | MED | **Addressed.** Thêm §3.5-overflow: Self vượt cap một mình → None (fallback one-shot); turn in-window quá dài → giảm K tạm (K//2, min 2), không re-prime. Kiểm (a) trước (b). | §3.5-overflow (mới), §5 |
| 5 | MED | **Addressed.** Identity-carry chốt `role=system` (tránh gateway merge với turn user đầu window). Bound đo trên list projector tầng Eris; wire ≤ bound do merge same-role. | §3.2 (lưu ý wire), §3.4, §6.2 |
| 6 | MED | **Addressed.** §2.2/§3.1 đổi sang ngôn ngữ điều kiện: message 1-3 là prefix bất biến, *ứng viên* cache boundary NẾU B1; transport Web hiện tại vẫn re-gửi/re-count mỗi lượt. Projector không giả định boundary. | §2.2, §3.1 (cuối) |
| 7 | MED | **Addressed.** Window = `turns[-2K:]` (2K turn thô, bất kể role/kind); K là số cặp danh nghĩa. Autonomous turn tính như turn thường. Thêm `test_window_is_raw_turns`. | §3.2, §6.2 |
| 8 | NIT | **Addressed.** Sửa số dòng: `_changed` 63-85, `_shrink_system_by_blocks` 245-287, `_truncate_to_cap` 290-339, `compress_system_message` 338-367, `enforce_prompt_cap` 370-421; nhãn pending đúng chuỗi thực. | §1.2, §1.4, phụ lục |
| 9 | NIT | **Addressed.** Thêm ngưỡng định lượng: ~35k-45k token/lượt (Self dominant), FAIL nếu lượt 20 > lượt 5 quá +10% hoặc nhảy > +15% tại cancelled; PASS nếu phẳng ±5% sau warm-up. | §6.1 |
| 10 | NIT | **Addressed.** Chốt fingerprint dùng cho `X-Whale2-Prefix-Id` (B2) + telemetry; KHÔNG re-prime giữa phiên (Self bất biến trong vòng đời session; đổi lớn → session mới). | §2.5 (mới) |
| 11 | NIT | **Addressed.** `turn_id` gán một lần tại điểm nhập state, lưu `TurnRecord.turn_id`; builder không tái sinh id mỗi build. Thêm `test_turn_id_stable_on_reload`. | §2.1, §6.2 |
| 12 | NIT | **Addressed.** Thêm `test_self_delta_is_vs_last_turn` (chứng minh #1) và `test_status_single_source` (chứng minh #3). | §6.2 |

Không có finding nào bị backlog hay bác bỏ; tất cả được chọn phương án align với
yêu cầu gốc (chặn phình token, xóa reconcile-resend về cấu trúc, giữ full Self
no top-k, giữ mọi guard an toàn). Finding #2 chọn phương án (A) đúng khuyến nghị
reviewer và đúng mục tiêu brief. Finding #5/#7 chốt cụ thể các điểm "nhiều cách
code hợp lệ" để implementer không phải tự quyết.
