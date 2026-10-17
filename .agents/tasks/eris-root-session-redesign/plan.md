# Plan triển khai: tách "true state" khỏi "derived prompt" cho RootConversationSession

> Plan tự chứa cho một coding agent. Đọc plan này + file design là đủ để code,
> KHÔNG cần ngữ cảnh hội thoại. Mọi quyết định thiết kế đã chốt; đừng tự quyết lại.

## 0. Bối cảnh một đoạn

Repo: `c:\Users\Gtvkun\Documents\GitHub\eris` (dev checkout, HEAD `c3805cc6`,
branch `main`). Bản chạy portable: `C:\Users\Gtvkun\Documents\eris`.

Vấn đề (đã xác minh bằng code trong hai report điều tra): `RootConversationSession`
giữ một chuỗi `self._messages` append-only sống suốt phiên (append 2 message mỗi
lượt, chỉ reset khi chạm trần ~90k token). Gateway Whale2API nối phẳng toàn bộ
mảng messages vào field prompt mỗi request. Hệ quả: token tăng tuyến tính theo
lượt; khối Self ~116k ký tự gửi lại mỗi request; receipt flip pending→cancelled
phá overlap → resend cả cửa sổ history (nhảy bậc payload); khi prompt vượt cap,
`compress_system_message` xóa persona/nội tâm trước grounding → "hóa ngu".

Giải pháp: thay chuỗi append-only bằng **structured state** + **pure-function
projector** render prompt từ state mỗi lượt, window bị chặn trên. Khi đó
reconcile-resend bất khả thi về cấu trúc, token phẳng, và prompt không còn chạm
cap nên nhánh xóa-persona gần như không chạy.

## 1. Tài liệu BẮT BUỘC đọc trước khi code

Theo thứ tự:

1. `.agents/tasks/eris-root-session-redesign/design.md` — **thiết kế đã APPROVED,
   là nguồn sự thật.** Plan này chỉ là lịch thực thi; nếu mâu thuẫn, design.md
   thắng. Đọc kỹ §2 (STATE), §3 (projector), §3.5-overflow, §5 (migration),
   §6 (verification), §7 (safety), §10 (quyết định đã chốt), §11 (bảng finding).
2. `.agents/tasks/eris-root-session-redesign/design-review.md` — review verdict
   APPROVED, 4 NIT còn mở (ghi ở §6 plan này).
3. `.agents/tasks/eris-token-growth/token-growth-report.md` — bằng chứng token.
4. `.agents/tasks/eris-late-turn-degrade/degrade-and-mute-report.md` — bằng chứng
   "hóa ngu"/"mất tiếng".
5. `docs/knowledge/2026-10-14-eris-runtime-lessons.md` — tri thức dự án. Đặc biệt
   Mục 1 (yêu cầu sản phẩm phải giữ), Mục 2 (lần theo đường chạy thật), Mục 7
   (SessionGuard byte-khớp), Mục 8/9/10.
6. `AGENTS.md` (repo root) — quy tắc: đối chiếu trạng thái lịch sử với code hiện
   tại; báo cáo cũ có thể đã bị đính chính.

## 2. Nguyên tắc không được vi phạm

- **Full Self, không top-k.** Self (`_read_self`, root_session.py:33-77) nạp đầy
  đủ ở lần prime; KHÔNG tóm tắt/cắt Self để giảm token. (lessons Mục 1.)
- **Mọi guard an toàn giữ nguyên:** grounding, action-claim, secret-redaction,
  language, single-speaker, TurnFrame/ResponseContract/[grounding]/[dynamic_policy].
  Projector KHÔNG chạm chúng. `compress_system_message` GIỮ làm lưới cuối (không
  xóa). (design §7.)
- **Schema Root (`ROOT_STEP_SCHEMA`) KHÔNG đổi.** Chỉ đổi cách dựng `messages`,
  không đổi output contract. (design §5.)
- **API ngoài của session giữ nguyên:** `start`, `ask`, `preload_self`. `ask`
  vẫn trả `dict | None` cùng ngữ nghĩa. (design §5.)
- **Lane nền KHÔNG đụng tới** (observer/surface/executive/inner/seed/curator dùng
  one-shot `conversation_messages=None`, không qua session này — design §1.5).
- **SessionGuard V3 byte-khớp:** reply raw của Root phải lưu nguyên văn. (Mục 7.)
- Mọi claim về code phải kèm file+line; phân biệt "đã đọc source" vs "giả định".

## 3. Phạm vi

TRONG: token phình, reconcile-resend, nén-xóa-persona (gián tiếp — giảm vì prompt
không còn chạm cap).

NGOÀI: "mất tiếng do preempt khi message mới đến" (lỗi phân loại backchannel/
STEERING ở ingress — bệnh khác). Nối-dây feedback lỗi-trước-delivery vào Root là
**follow-up riêng** (state đã hỗ trợ qua `TurnRecord.status="failed"`, nhưng
đường ghi nằm ở kernel/dispatch, ngoài projector — design §8 mục cuối).

## 4. Hai giai đoạn (QUAN TRỌNG: làm Giai đoạn 1 trước, đo, rồi mới cân nhắc 2)

### Giai đoạn 1 — tầng Eris, KHÔNG chạm gateway (làm trước, lợi ích chính)
Thay nội tạng `RootConversationSession` + projector. Riêng cái này đã chặn phình
tuyến tính và xóa reconcile-resend, đo được ngay. KHÔNG cần sửa gateway để có lợi
ích này.

### Giai đoạn 2 — gateway session bền (CHỈ làm sau khi chốt tiền đề + đo B1)
Để Self không re-gửi mỗi lượt. Phụ thuộc hai tiền đề:
- **Tiền đề (a):** xác định binary gateway đang chạy build từ cây dev hay portable.
  `messages.go` hai cây khác SHA-256; portable còn `outputIntegrityGuardPrompt` +
  `prependOutputIntegrityGuard`. Nếu sửa sai cây, thay đổi gateway không có hiệu
  lực live. (design §0.1.) Cách chốt: so SHA-256 binary trong container Compose
  `whale2api` với binary build từ mỗi cây, hoặc đọc build metadata. Image backup:
  tag `eris-whale2api-backup:before-plain-text-20261015`.
- **Tiền đề (b, đã xác nhận):** DeepSeek Web tạo + auto-delete session mỗi request
  (`nonstream.go:82`, `handler_chat.go:34-39`, `auto_delete.go:12-29`) → prefix
  cache upstream KHÔNG khả dụng. Session bền (B1) tái dùng cơ chế
  `parent_message_id` đã có ở `empty_retry.go:34-47`.

**Nếu người giao chỉ muốn một đợt: làm Giai đoạn 1 trọn vẹn, dừng, báo cáo số đo
token. KHÔNG tự ý làm Giai đoạn 2.**

## 5. Các bước Giai đoạn 1 (theo thứ tự)

File chính sửa: `src/runtime/conversation/root_session.py`.
Có thể tạo file mới: `src/runtime/conversation/root_session_projector.py` cho
projector (giữ nó pure, dễ test độc lập).

### Bước 1 — Định nghĩa state (design §2)
- `SelfReference` dataclass: `content_json`, `sections`, `char_len`,
  `fingerprint = sha256(content_json)[:16]`, `ack_reply_raw`.
- `TurnRecord` dataclass: `turn_id`, `role`, `content` (lời gốc == raw_content,
  KHÔNG chèn nhãn), `delivery_id`, `status` ∈ {none,pending,delivered,cancelled,
  failed}, `kind` ∈ {public,autonomous}.
- `RootSessionState`: `self_ref`, `turns: list[TurnRecord]`, `runtime_context`,
  `system_prompt`, `last_self_snapshot`, `last_context`, `last_reply_raw`.
- **KHÔNG tạo `steps[]`** (finding #2 — dead state). `reply_raw` chỉ giữ lượt gần
  nhất ở `last_reply_raw` (vô hướng), KHÔNG vào prompt.
- `turn_id`: gán MỘT lần tại điểm nhập state. Nếu turn đã có `history_id`
  (prompt_context_builder.py:329-331) thì dùng nguyên; nếu thiếu, state tự sinh
  một lần và lưu. Builder KHÔNG tái sinh id mỗi build. (finding #11, design §2.1.)

### Bước 2 — Projector pure function (design §3)
`project_root_messages(state, *, window_k) -> list[dict[str,str]]`:
- Pure: không clock, không I/O, không `_read_self`, không mutate state. Idempotent.
- Thứ tự message: (1) system contract; (2) user bootstrap chứa
  `self_ref.content_json` — **byte-khớp `_prime` cũ** (root_session.py:216-231);
  (3) assistant `self_ref.ack_reply_raw`; (4) với mỗi turn trong `turns[-2K:]`
  render `{role, content}` + nhãn status thuần (§3.3); (5) user step_payload hiện
  tại (event/note/tool_results + `self_changes_since_last_step` +
  `runtime_context_delta`).
- Window = **`turns[-2K:]`** (2K turn thô, bất kể role/kind). K=12 danh nghĩa,
  env `ERIS_ROOT_SESSION_WINDOW_PAIRS` default 12. (finding #7.)
- Turn cũ rời window (`len(turns) > 2K`): chèn ĐÚNG MỘT message identity-carry
  **role=system** ngay trước window (tránh gateway merge same-role với turn user
  đầu window — finding #5). Nội dung mặc định: chỉ đếm số lượt bị loại (số nguyên),
  phái sinh thuần, KHÔNG gọi LLM. (design §3.4.)
- Nhãn status (hàm thuần của `TurnRecord.status`, dùng chuỗi hiện có
  prompt_context_builder.py:336-342): pending→"[Đã hiển thị; TTS chưa xác nhận
  phát xong]", cancelled→"[Đã hiển thị; âm thanh bị ngắt giữa chừng]", failed→
  "[Đã hiển thị; phát âm thanh thất bại]", delivered/none→content gốc. Nhãn nối
  SAU content, KHÔNG chèn đầu câu, KHÔNG đổi content gốc. (design §3.3.)

### Bước 3 — Viết lại `ask` dùng state + projector (design §2.3, §3, §3.5)
- Bỏ `self._messages`, `self._self`, `self._last_history`,
  `self._last_delivery_status`, `self._last_context`. Thay bằng `RootSessionState`.
- self-delta: `self_delta = _changed(state.last_self_snapshot, self_now)`; cập
  nhật `state.last_self_snapshot = self_now` SAU khi gửi. KHÔNG dùng
  `self_ref.content_json` làm baseline. Tương tự `runtime_context_delta` với
  `state.last_context`. (finding #1.)
- Giữ `_changed` (root_session.py:63-85) và `_read_self` (33-77) nguyên.
- BỎ `recent_public_history_delta`/`recent_public_history_reconcile` (history nay
  trong window) VÀ `recent_public_delivery_updates` (status một nguồn trong
  window — finding #3).
- Overflow (`not _fits(project(state, K))`): kiểm (a) trước — Self một mình vượt
  cap → trả `None` (caller rơi fallback one-shot agent.py:265-290, như `_prime`
  cũ trả None). Rồi (b) — window quá dài → giảm K tạm `K' = max(2, K//2)`, lặp
  tới khi fit hoặc K'=2; nếu vẫn không fit để `_truncate_to_cap` làm lưới cuối.
  KHÔNG re-prime toàn bộ. (finding #4, design §3.5-overflow.)
- `_fits` (root_session.py:160-178) giữ, nay áp lên output projector.
- `last_reply_raw` cập nhật sau mỗi `ask` (byte-khớp SessionGuard).

### Bước 4 — `_prime` nạp `SelfReference` thay vì set `_messages` (design §5)
- `_prime` dựng `SelfReference` từ `_read_self`; `ack_reply_raw` = reply raw của
  bootstrap ack (kind=no_reply). Giữ hành vi "trả None khi full Self vượt cap"
  (root_session.py:214).

### Bước 5 — Điểm nhập turn vào state
- Khi caller đẩy history (agent.py:705-719 cung cấp `recent_public_history[-32:]`),
  map mỗi entry → `TurnRecord` với `turn_id` từ `history_id`, `content` từ
  `raw_content`, `delivery_id`/`status` từ entry. Flip status: tìm theo
  `delivery_id` trong `state.turns`, gán `status` tại chỗ, KHÔNG đổi turn_id/
  content/vị trí. (design §3.3.)

## 6. Bốn NIT review còn mở (xử lnhẹ, không chặn)

Từ design-review.json (verdict APPROVED). Không bắt buộc nhưng nên làm cho sạch:
1. Mô tả "builder tái sinh id mỗi build" — đảm bảo code thực tế là id ổn định
   trong process (đã chốt ở finding #11, chỉ cần code đúng vậy).
2. §0.2 phát biểu tuyệt đối về cache — giữ ngôn ngữ điều kiện (không ảnh hưởng code).
3. Ngưỡng token 35k-45k là tham khảo, không hard-code vào test; test dùng tiêu chí
   tương đối (±5% sau warm-up, xem §7 verification).
4. Identity-carry mặc định chỉ đếm; tiêu chí nâng mức (carry dòng đầu) để sau khi
   có số đo, không làm sẵn.

## 7. Verification (BẮT BUỘC trước khi báo xong — design §6)

Unit test (file `tests/` tương ứng, dùng framework pytest đang có trong repo):
- `test_projector_idempotent`: project 2 lần cùng (state,K) → list bằng nhau.
- `test_projector_bounded`: 100 turns → `len(messages) == 3 + min(2K,len(turns))
  + 1 (+1 nếu carry)`, độc lập số turn. Đo trên LIST projector (tầng Eris), KHÔNG
  trên block wire.
- `test_status_flip_no_resend`: flip một status pending→cancelled; project lại →
  turn_id/vị trí/content KHÔNG đổi, chỉ nhãn status của đúng turn đổi, số message
  KHÔNG đổi. (Đây là test chứng minh reconcile-resend biến mất.)
- `test_window_drop_carries_identity`: >2K turn → đúng một message carry
  role=system trước window; turn in-window byte-khớp.
- `test_self_invariant`: Self byte-khớp giữa các lần project khi fingerprint
  không đổi.
- `test_self_delta_is_vs_last_turn`: hai lượt đổi field Self khác nhau → self_delta
  lượt 2 chỉ chứa field đổi 1→2, không chứa field từ prime.
- `test_status_single_source`: flip status → step_payload KHÔNG chứa
  `recent_public_delivery_updates`; nhãn xuất hiện trong window.
- `test_window_is_raw_turns`: chuỗi role không xen kẽ + >2K turn → window =
  `turns[-2K:]` chính xác.
- `test_turn_id_stable_on_reload`: nạp turn thiếu history_id hai lần → turn_id
  không đổi.

Integration (fake router ghi lại `conversation_messages`):
- Assert KHÔNG payload nào chứa `recent_public_history_reconcile`; số message mỗi
  lượt ≤ trần §3.2.

Đo token (nếu chạy được localhost DeepSeek Web — nếu không, ghi rõ chưa đo live):
- Phiên ≥20 lượt, ≥3 lần pending→cancelled. Đo `estimated_input_tokens`
  (`[LLM PREFLIGHT]`) + request bytes theo lượt. PASS nếu đường token phẳng (±5%
  sau 2-3 lượt warm-up), không nhảy bậc tại cancelled. FAIL nếu lượt 20 > lượt 5
  quá +10% hoặc nhảy >+15% tại một cancelled.

Chạy test regression hiện có của repo để chắc không vỡ gì (lệnh: xem
`pyproject.toml`/`pytest.ini` trong repo; KHÔNG chạy watch mode, dùng chạy một
lần).

## 8. Worktree & git

- Làm trong worktree riêng, KHÔNG trên cây làm việc chính:
  `git worktree add .worktrees/root-session-redesign -b feature/root-session-redesign <base>`
  với `<base>` = branch đang checkout ở repo chính (hiện `main`). Chạy mọi bước
  trong worktree đó.
- Commit theo bước logic (state → projector → ask rewrite → tests), message rõ.
- KHÔNG commit nếu người giao chưa yêu cầu; nếu được yêu cầu, stage file cụ thể,
  không `git add -A`.
- Kết thúc: rebase branch lên `<base>`, báo cáo. KHÔNG tự merge/push trừ khi được
  yêu cầu.

## 9. Định nghĩa HOÀN THÀNH (Giai đoạn 1)

- [ ] `RootSessionState` + `SelfReference` + `TurnRecord` thay `self._messages`.
- [ ] Projector pure, bounded, window `turns[-2K:]`, K env-tunable.
- [ ] `ask` dùng projector; bỏ reconcile + delivery_updates; self-delta baseline
      lượt-trước; overflow theo §3.5.
- [ ] `_prime` nạp SelfReference; fallback one-shot giữ nguyên.
- [ ] Mọi guard an toàn + schema + API ngoài + lane nền KHÔNG đổi (xác nhận).
- [ ] Toàn bộ test §7 pass; regression repo pass.
- [ ] Đo token (hoặc ghi rõ chưa đo live + lý do).
- [ ] Báo cáo: đổi gì, test gì pass, số đo token, cái gì chưa xác minh.

## 10. Cạm bẫy đã biết (đừng lặp lại)

- Đừng dùng `self_ref` làm baseline self-delta (sẽ phình từ prime — finding #1).
- Đừng để `recent_public_delivery_updates` tồn tại song song với status in-window
  (hai nguồn sự thật — finding #3).
- Đừng dùng role=user cho identity-carry (gateway merge same-role phá nghĩa —
  finding #5).
- Đừng cố ghép cặp (user,assistant) cho window; dùng `turns[-2K:]` thô (autonomous
  turn không có user ghép cặp — finding #7).
- Đừng re-prime toàn bộ khi overflow; giảm K tạm (finding #4).
- Đừng sửa gateway trong Giai đoạn 1. Đừng chạm cây portable mà chưa chốt binary.
- Đừng coi báo cáo cũ (checkout e9cc50e5) là sự thật trên HEAD c3805cc6; nhiều
  lỗi TTS đã được sửa. Reconcile cụ thể trên HEAD cần re-verify bằng trace (design
  §1.2) — nhưng thiết kế state xóa nó về cấu trúc bất kể nguyên nhân cũ.
