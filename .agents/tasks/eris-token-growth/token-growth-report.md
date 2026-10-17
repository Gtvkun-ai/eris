# Vì sao token của một phiên chat Eris phình lên khủng khiếp ở các lượt sau

Điều tra read-only. Repo dev: `c:\Users\Gtvkun\Documents\GitHub\eris`.
Bản chạy portable: `C:\Users\Gtvkun\Documents\eris`. Không sửa code, không chạy app.

## Tóm tắt kết luận (đọc trước)

Nguồn phình token lớn nhất và tăng **tuyến tính theo số lượt** là **phiên hội
thoại Root bền (`RootConversationSession`) kết hợp với cách gateway Whale2API
dựng prompt**:

1. `RootConversationSession` giữ MỘT chuỗi `self._messages` sống suốt phiên.
   Mỗi lượt Root nó **append thêm 2 message** (`user` step payload + `assistant`
   raw reply) vào chuỗi đó, không bao giờ cắt bớt phần đầu (chỉ reset khi
   lỗi/timeout hoặc khi vượt context cap mới re-prime).
   Nguồn: `src/runtime/conversation/root_session.py:329` (`self._messages = messages + [assistant]`).

2. Gateway `tools/whale2api` dựng trường `prompt` bằng cách **nối phẳng TOÀN BỘ
   mảng messages** (system + mọi user/assistant/tool) thành một chuỗi text, KHÔNG
   cắt cửa sổ, KHÔNG tóm tắt, KHÔNG giới hạn số lượt. Trần context là 896K/2.85M
   token — chỉ để *từ chối* khi quá lớn, không phải để *cắt*.
   Nguồn: `tools/whale2api/internal/prompt/messages.go:26` (`MessagesPrepareWithThinking`),
   `tools/whale2api/internal/promptcompat/prompt_build.go:12` (`BuildOpenAIPrompt`),
   `tools/whale2api/internal/completionruntime/context_limit.go` + `config/context_limits.go:15`.

Hệ quả: ở lượt thứ N, prompt gửi lên DeepSeek = (khối Self bootstrap ~116k ký tự)
+ (toàn bộ 2·(N−1) message của các lượt trước) + (step payload lượt N). Billing
đếm nguyên chuỗi phẳng này mỗi lượt (`internal/assistantturn/turn.go:184`
`BuildUsage` → `util.CountPromptTokens`). Đây đúng là hành vi quan sát trong audit
phiên 00:19 (`docs/knowledge/2026-10-15-run-agent-loop-tts-audit.md` Mục 5):
request bytes **364837 → 392681 → 406861 → 421974** qua bốn request liên tiếp.

Chi phí cố định lớn nhất mỗi lượt là **khối Self ~116k ký tự** nằm ở
`self._messages[1]` — nạp một lần nhưng vì gateway nối phẳng cả chuỗi nên nó bị
**gửi lại trong mọi request của phiên** (không phải "chỉ nạp một lần" trên wire).

Cơ chế delta (`root_delta_sent`) có thật và giảm phần *mới thêm* mỗi lượt (chỉ
gửi history mới + self thay đổi), **nhưng không rút ngắn transcript tích luỹ** đã
nằm trong `self._messages`. Vì vậy delta làm chậm tốc độ phình, không chặn phình.

Reconcile 16/18 entries (Mục 8 lessons) là **gia tốc cục bộ**: khi receipt
pending→cancelled, delta chuyển sang `recent_public_history_reconcile` và nhét lại
nguyên cửa sổ history vào một message mới (vẫn append vào chuỗi đang dài), gây
nhảy bậc payload. Không phải "16 lượt mới".

Các lane nền (observer, inner, seed, curator, verifier...) **không dùng** session
tích luỹ này; chúng là one-shot với cửa sổ history bị cắt cứng (`[-4:]`, `[-6:]`,
`[-8:]`). Chúng là chi phí *cố định mỗi lượt* (nhân theo số lane), không tăng
tuyến tính theo chiều dài phiên.

---

## Bằng chứng theo từng câu hỏi

### A. Mỗi request LLM trong một phiên gửi đi những gì?

**Đường Root (phiên bền) — đây là đường phình:**

- `agent.py` dựng `payload` mỗi step gồm `recent_public_history[-32:]`, event,
  note, runtime_context, tool_results.
  `src/runtime/conversation/agent.py:705` (`"recent_public_history": [... x in recent_history[-32:]]`).
- Nhưng `RootConversationSession.ask` **loại** `recent_public_history` và
  `runtime_context` khỏi payload trước khi gửi, chỉ thêm delta:
  `root_session.py` — `step_payload = {k: v for k, v in payload.items() if k not in {"recent_public_history", "runtime_context"}}`,
  rồi set `recent_public_history_delta` hoặc `recent_public_history_reconcile`,
  `runtime_context_delta`, `self_changes_since_last_step`.
- Chuỗi gửi đi thực tế là `self._messages + [user step_payload]`:
  `root_session.py:316` (`messages = self._messages + [{"role":"user", ...}]`).
  `self._messages` chứa: `[system, Self-bootstrap-user, assistant-ack, user1,
  assistant1, user2, assistant2, ...]` — lớn dần mỗi lượt.
- Router chuyển nguyên `conversation_messages` xuống client, không tự cắt:
  `src/runtime/ai_orchestrated/model_router.py:1518-1521` (`messages=[dict(m) for m in conversation_messages]`).

**Tại gateway (bước quyết định):** client gửi mảng `messages` qua endpoint
OpenAI-compatible; gateway nối phẳng toàn bộ:

- `tools/whale2api/internal/promptcompat/prompt_build.go:12` →
  `prompt.MessagesPrepareWithThinking(messages, ...)`.
- `tools/whale2api/internal/prompt/messages.go:26-77`: duyệt **mọi** message,
  merge message cùng role, bọc marker rồi `strings.Join(parts, "")`. Không có
  bước nào bỏ bớt lượt cũ, giới hạn số message, hay tóm tắt.
- Trần chỉ để từ chối, không để cắt: `context_limit.go:108`
  (`contextGateErrorForEstimate` chỉ *return error* khi vượt `logicalContextLimitTokens`),
  mặc định 2.85M logical / 896K user-facing (`config/context_limits.go:15`).

→ **Trả lời A:** mỗi request Root gửi lại nguyên transcript tích luỹ của cả phiên
(dưới dạng chuỗi `self._messages` ngày càng dài) cộng khối Self bootstrap. History
KHÔNG bị cắt/tóm tắt/giới hạn cửa sổ ở cả tầng Eris (cho lane Root) lẫn gateway.
Cơ chế duy nhất giới hạn là re-prime khi vượt context cap (90k token cho lane
root, xem C) — tức là chỉ "xả" khi đã rất lớn.

### B. "root-session full Self loaded sections=4 chars=116010" nghĩa là gì?

- Log phát ra ở `root_session.py:235`:
  `self._log("info", "[root-session] full Self loaded; sections=%d chars=%d", len(self_context), len(messages[1]["content"]))`.
- `sections=4` = số nguồn Self mà `_read_self` gom: `mind_state` (từ
  `ai_state_reducer.snapshot().to_dict()`), `subject_self` (`subject_service.self_view()`),
  `memory_state`, `long_term_memory`. Nguồn: `root_session.py:28-77` (`_read_self`).
  Chú thích trong code nói rõ "KHÔNG lọc top-k", "Có thể rất dài ở lần nạp đầu".
- `chars=116010` = độ dài JSON của `messages[1]["content"]`, tức message user
  bootstrap chứa `eris_self_full`. Khối này được đặt vào `self._messages` tại
  `root_session.py:232` và **ở lại đó suốt phiên**.

→ **Trả lời B:** đây là ~116k ký tự Self nạp MỘT LẦN vào bộ nhớ phiên. Nhưng vì
gateway nối phẳng cả `self._messages` mỗi request (câu A), khối Self này **đi kèm
MỖI request** của phiên cho tới khi phiên re-prime hoặc reset. Đó là chi phí
**cố định mỗi lượt** rất lớn (ước lượng ~29k–39k token chỉ riêng Self, theo
heuristic chars/3÷ của `estimate_tokens`), nhân theo số request của cả phiên.
Lưu ý giới hạn: 116010 là độ dài *ký tự JSON*, token thật phụ thuộc tokenizer
upstream; chưa đo token thật trên wire trong điều tra này.

### C. Cơ chế root_delta_sent / delta vs full gửi gì?

- Delta tính ở `root_session.ask`:
  - `self_delta = _changed(self._self, self_now)` — chỉ field Self mới/đổi
    (`root_session.py` `_changed`, có tombstone cho field bị xoá).
  - History: tìm overlap suffix/prefix giữa `self._last_history` và cửa sổ hiện
    tại; nếu nối tiếp được thì chỉ gửi `recent_public_history_delta = history[overlap:]`;
    nếu history bị rewrite thì gửi `recent_public_history_reconcile`.
    Nguồn: `root_session.py` khối `overlap`/`new_history`/`history_key`.
  - `runtime_context_delta`, `recent_public_delivery_updates` (chỉ status đổi).
- Log: `root_session.py` cuối `ask`:
  `"[root-session] root_delta_sent steps=%d self_fields=%d public_turns=%d"`.
  `public_turns = len(new_history)` = số lượt history **mới** gửi lượt này, KHÔNG
  phải tổng độ dài transcript. `steps = (len(self._messages)-1)//2` = tổng số
  lượt đã tích luỹ trong phiên — chỉ số này mới phản ánh độ phình.

→ **Trả lời C:** delta **thật sự giảm phần dữ liệu MỚI mỗi lượt** (không replay
32 câu history, không gửi lại nguyên Self). Nhưng delta chỉ áp cho phần *append
thêm*; nó **không rút gọn** `self._messages` đã tích luỹ. Transcript cũ (bao gồm
Self bootstrap + mọi cặp user/assistant trước) vẫn nằm nguyên trong chuỗi và vẫn
bị gateway nối phẳng gửi lại. Vậy delta làm *đường cong phình thoải hơn*, không
*phẳng hoá* nó. Payload vẫn tăng tuyến tính theo số lượt.

### D. Các lane nền — mỗi lượt bao nhiêu request, mang bao nhiêu context?

Các lane nền KHÔNG đi qua `RootConversationSession`; chúng gọi `_call` với
`conversation_messages=None`, nên router dựng payload one-shot `[system, user]`
mới mỗi lần (`model_router.py:1522-1525`). Cửa sổ history của chúng bị cắt cứng:

- **post_observer / post_observer_deep**: `recent_public_history = recent_history[-4:]`.
  Nguồn: `model_router.py:2532` (payload observer), lane set ở `:2562`/`:2641`.
  Timeout mặc định ~90s (`ERIS_POST_OBSERVER_HTTP_TIMEOUT_SEC`). Đây cũng chính
  là nguồn 8 warning `PROVIDER CIRCUIT` của curator trong audit (Mục 4), là
  timeout chứ không phải phình token.
- **executive_cortex (các bước plan/observe)**: history cắt `[-6:]` / `[-8:]`.
  Nguồn: `src/runtime/ai_orchestrated/executive_cortex.py:689, 1815, 2133`.
- **claim verifier** (`public_claim_verifier`): có tồn tại
  (`src/runtime/conversation/claim_verifier.py:312`) nhưng theo lessons Mục 5 +
  `agent.py` finalize trực tiếp (`agent.py` nhánh `kind=="move"` return
  `NextConversationMove` ngay, không chạy vòng self-verify thứ hai). Vậy verifier
  không chạy mặc định trên đường chat chính.
- **surface writer** (`generate_public_reply`): dựng `[system, *chat_history, user]`
  với `chat_history = recent_history` (≤32, mỗi entry content đã cắt), đi one-shot
  qua `create_chat_completion` → preflight hard-cap (budget DeepSeek, KHÔNG được
  nới 90k vì `root_session_prompt_cap` chỉ nới cho lane `root_conversation`).
  Nguồn: `model_router.py:1855-1859`; `src/llm/token_budget.py` `root_session_prompt_cap`.

→ **Trả lời D:** mỗi lượt user kích hoạt nhiều request LLM (ít nhất: 1 Root +
1 surface writer + ≥1 observer; cộng các lane nền khác tuỳ trigger như inner/seed/
curator). Nhưng mỗi lane nền mang context **bị cắt cửa sổ cố định**, nên tổng của
chúng là chi phí **cố định mỗi lượt** (hằng × số lane), KHÔNG tăng theo chiều dài
phiên. Chỉ lane Root tăng tuyến tính. **Giới hạn:** chưa đếm được con số request
chính xác mỗi lượt từ trace trong điều tra này (các lane dispatch nằm ngoài
`orchestrator.handle`/`kernel`); con số lane cụ thể cần đối chiếu observability
`remote_calls_per_user_turn` — mà Mục 4 lessons cảnh báo chỉ số này không bao gồm
call local đi ngoài broker.

### E. Reconcile 16 entries khi receipt pending→cancelled

- Cơ chế còn tồn tại nguyên trong code hiện tại:
  `root_session.ask` chọn `history_key = "recent_public_history_reconcile"` khi
  `previous` không rỗng và `overlap == 0` (history bị rewrite, không nối tiếp
  được). Khi đó `new_history = history` (nguyên cửa sổ ≤32), nhét vào một message
  user mới và **vẫn append vào `self._messages` đang dài**.
- Nguồn gây rewrite: khi `delivery_status` của một câu đổi pending→cancelled,
  projection `_chat_history_for_llm` chèn nhãn `[Đã hiển thị; âm thanh bị ngắt...]`
  vào `content` (nhưng Root nhận `raw_content`), đồng thời phá overlap
  suffix/prefix → buộc reconcile.
  Nguồn: `src/runtime/prompt_context_builder.py` `_chat_history_for_llm`
  (khối `status in {"pending","cancelled","failed"}` chèn `context_note`).
- Khớp quan sát audit Mục 5: request 109 reconcile 16 entries, request cuối
  reconcile 18 entries; messages 32→34→36→38; bytes 364837→392681→406861→421974.

→ **Trả lời E:** cơ chế còn sống. Nó không tạo "16 lượt mới" mà là một **cú nhảy
bậc một lần** cho lượt bị reconcile: thay vì gửi delta nhỏ, nó gửi lại nguyên cửa
sổ history (tối đa 32 entry) và cộng vào chuỗi tích luỹ. Trong một phiên có nhiều
lần hủy audio (preemption liên tục như phiên 00:19), reconcile lặp lại nhiều lần,
mỗi lần làm payload nhảy một bậc — cộng hưởng với phình tuyến tính của session.
Lưu ý (theo AGENTS.md + lessons): reconcile **chưa được chứng minh** làm lệch nội
dung/cá tính câu trả lời; đây thuần là vấn đề kích thước payload.

### F. Token dự phòng / padding / lặp context do gateway tự thêm?

- Padding billing: `util.CountPromptTokens` cộng `conservativePromptPadding(base)`
  = `base/50` (tối thiểu 4). Nguồn: `tools/whale2api/internal/util/token_count.go:16,30`.
  → ~+2% token mỗi request, chỉ ở phần *đếm/hạch toán usage*, không thêm vào prompt
  thật. Nhỏ, không phải nguồn chính.
- Khối "token dự phòng cho file context tự tạo" đã bị bỏ theo lessons Mục 9 (dev
  source). Không thấy nó trong `messages.go`/`prompt_build.go` bản dev.
- **Khác biệt dev vs portable (quan trọng):** `messages.go` bản dev và bản
  portable KHÁC NHAU (SHA-256 khác). Bản portable
  (`C:\Users\Gtvkun\Documents\eris\tools\whale2api\internal\prompt\messages.go`)
  vẫn còn `outputIntegrityGuardPrompt` + hàm `prependOutputIntegrityGuard` (chèn
  một system prompt tiếng Trung vào đầu mảng) — tức hành vi mà lessons Mục 9 nói
  "đã bỏ" **chưa bỏ trong cây source portable**. Nếu binary đang chạy build từ
  cây portable, mỗi request bị cộng thêm khối guard cố định ở đầu prompt. Đây là
  chi phí *cố định mỗi lượt* (nhỏ so với Self/transcript).
  - Dù vậy, **cả hai bản đều nối phẳng toàn bộ messages** (bản portable
    `strings.Join(parts, "\n\n")`), nên kết luận phình tuyến tính không đổi theo
    bản nào.

→ **Trả lời F:** có hai khoản gateway tự thêm — padding usage ~2% (chỉ đếm) và
(ở bản portable) khối output-integrity guard cố định đầu prompt. Cả hai nhỏ và
cố định; không phải nguyên nhân phình theo lượt.

---

## Bảng xếp hạng nguồn gây token tăng trong 1 phiên

| Hạng | Nguồn | Phân loại | Bằng chứng |
|---|---|---|---|
| 1 | Transcript Root tích luỹ (`self._messages` lớn dần + gateway nối phẳng toàn bộ) | **Tăng tuyến tính theo lượt** | `root_session.py:316,329`; `messages.go:26`; audit Mục 5 (bytes 364k→422k) |
| 2 | Khối Self bootstrap ~116k ký tự gửi lại mỗi request | **Chi phí cố định MỖI lượt** (rất lớn) | `root_session.py:217-235`; `_read_self` |
| 3 | Reconcile pending→cancelled nhét lại nguyên cửa sổ history vào chuỗi | **Nhảy bậc (một lần/mỗi lần hủy)**, cộng dồn vào #1 | `root_session.py` nhánh `reconcile`; `prompt_context_builder.py` `_chat_history_for_llm`; audit Mục 5 |
| 4 | Các lane nền (surface writer, observer, executive, inner/seed/curator) | **Cố định mỗi lượt** (hằng × số lane, cửa sổ cắt cứng) | `model_router.py:2532,1855`; `executive_cortex.py:689,1815,2133` |
| 5 | Output-integrity guard (chỉ bản portable) | **Cố định mỗi lượt** (nhỏ) | portable `messages.go` `prependOutputIntegrityGuard` |
| 6 | Padding usage billing `base/50` | **Cố định ~2%** (chỉ hạch toán) | `util/token_count.go:16,30` |

---

## Khuyến nghị sửa (chưa triển khai)

1. **Cắt cửa sổ transcript trong `RootConversationSession`.** Hiện session chỉ
   "xả" khi vượt context cap (90k token) rồi re-prime toàn bộ — tức để nó phình
   gần tối đa rồi mới reset. Thay bằng cửa sổ trượt: giữ Self bootstrap + K cặp
   user/assistant gần nhất, nén/loại phần giữa, dùng identity ổn định cho các lượt
   cũ (đúng gợi ý Mục 5 audit: "history status update bằng identity ổn định thay
   vì replay toàn history").
   Vị trí: `src/runtime/conversation/root_session.py` (`ask`/`_prime`).

2. **Đừng giữ nguyên khối Self 116k trong mọi request.** Cân nhắc nạp Self một
   lần như "ký ức hệ thống" phía gateway/caller (hoặc tóm tắt Self sau bootstrap),
   để các lượt sau tham chiếu bằng delta thay vì tái gửi toàn bộ. Giữ nguyên yêu
   cầu sản phẩm "đọc toàn bộ Self, không top-k" ở *lần nạp đầu*, không ở mọi lượt.

3. **Giảm tần suất reconcile.** Dùng định danh delivery ổn định + cập nhật status
   cơ học (`recent_public_delivery_updates` đã có) thay vì để thay đổi
   `delivery_status` phá overlap và ép gửi lại nguyên cửa sổ. Tránh chèn
   `context_note` vào `content` theo cách phá prefix/suffix overlap.
   Vị trí: `prompt_context_builder.py` `_chat_history_for_llm` + `root_session.ask` overlap.

4. **Nếu muốn kiểm soát ở gateway:** thêm cửa sổ/tóm tắt history trong
   `MessagesPrepare` cho lane chat (hiện hoàn toàn không có). Nhưng ưu tiên sửa ở
   tầng Eris vì gateway không biết đâu là Self/history/delta.

5. **Đồng bộ source gateway dev↔portable** rồi rebuild binary. `messages.go`
   đang khác nhau; cần xác định binary đang chạy build từ cây nào trước khi tin
   rằng hành vi Mục 9 (bỏ guard/file-context) đã có hiệu lực live.

## Giới hạn điều tra (chưa xác minh)

- Chưa đo token THẬT trên wire cho phiên hiện tại; dùng độ dài ký tự + bytes
  request từ audit cũ (phiên 00:19) làm bằng chứng định lượng.
- Chưa xác định binary gateway đang chạy build từ cây dev hay portable (chỉ biết
  source hai cây khác nhau ở `messages.go`). Các file Python runtime (`root_session.py`,
  `prompt_context_builder.py`) thì trùng byte dev↔portable.
- Chưa đếm chính xác số request LLM mỗi lượt từ trace (các lane dispatch nằm ngoài
  phạm vi file đã đọc). Kết luận lane nền "bị cắt cửa sổ" dựa trên payload builder,
  không phải đếm trace.
- Reconcile được xác nhận gây phình payload (khớp audit), nhưng **không** được
  xác nhận gây lệch cá tính/nội dung (theo lessons Mục 5/8).
