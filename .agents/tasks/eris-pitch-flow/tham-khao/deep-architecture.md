# Kiến trúc runtime Eris — phụ lục kỹ thuật cho pitch (đào sâu)

Tài liệu này mô tả **những nguyên lý thiết kế** của runtime Eris ở tầng mà chỉ
dân production mới dựng ra, kèm **bất biến (invariant)** và **bằng chứng code
thật** (file + class + hàm). Mục tiêu: để giám khảo thấy Eris không phải "một
tính năng AI" mà là một **hệ điều hành nhận thức** có ranh giới quyền lực rõ,
có luật chống bịa, và có điểm móc để mở rộng (Tutor) mà không phải viết lại lõi.

Viết theo tinh thần trung tính: mô tả **hệ thống sẽ thực thi gì và vì sao thiết
kế thế**, không phán xét "đã chạy / chưa chạy". Báo cáo luồng cơ bản nằm ở
`flow-description.md` (cùng thư mục); tài liệu này đào sâu 3 trụ cột + lộ trình
Tutor và **không lặp lại** phần mô tả luồng tổng.

---

## Soundbite mở màn (ba câu giám khảo nhớ được)

1. **"Eris tách quyền QUYẾT ĐỊNH khỏi quyền DIỄN ĐẠT khỏi quyền PHÁT — và tách
   VAI TRÒ NHẬN THỨC khỏi MODEL khỏi VRAM."** Không agent AI sinh viên nào tách
   bốn trục này; họ gọi một model, lấy string, đọc lên.
2. **"Eris phân biệt 'định nói' ≠ 'đã nói' ≠ 'đã dạy' bằng receipt có chữ ký,
   không bằng niềm tin của model."** Đây là lớp anti-fabrication cấp hệ thống.
3. **"Eris luôn có TIẾNG kể cả khi LLM chết."** Có một đường fail-soft phát câu
   status cố định, không đi qua model.

---

# TRỤ CỘT 1 — LANE ROUTING NHƯ MỘT HỆ THẦN KINH NHẬN THỨC

> **NGUYÊN LÝ ĐẮT:** Một request suy luận không được định danh bằng "model nào",
> mà bằng **ba trục trực giao**: *nó đang làm vai trò nhận thức gì* (cognitive
> lane), *đi qua đường truyền nào* (backend), *có ngốn VRAM cục bộ không*
> (resource_class). Nhờ tách ba trục, cùng một model DeepSeek có thể vừa là "bộ
> não điều hành bắt buộc" của một lượt chat, vừa là "worker nền có thể bị cắt"
> của một tác vụ khác — mà broker vẫn đối xử đúng với từng vai.

## 1.1 Ba trục trực giao — vì sao elegant

Bằng chứng: `src/runtime/ai_orchestrated/model_router.py`,
`AIRuntimeModelRouter._client_inference_profile()` (docstring tách nghĩa) và
`invoke_structured_worker()` (docstring ví dụ bốn giá trị cùng tồn tại):

- `cognitive_lane`: *request đang làm việc gì* — `turn_executive`,
  `root_conversation`, `tutor:*`, `public_claim_verifier`, `post_observer`…
- `backend`: transport/provider — `ds2api_deepseek_web`,
  `openai_compatible_remote`.
- `resource_class`: có chiếm VRAM cục bộ không — `remote_api`, `local_light`,
  `local_heavy`, `vision_local`, `unknown`.
- `inference_tier`: **chỉ còn là nhãn tương thích cũ** (legacy compatibility
  label) cho telemetry/caller cũ.

Docstring `invoke_structured_worker` nêu thẳng: một DeepSeek worker qua DS2API
đồng thời là `cognitive_lane=turn_executive` + `backend=ds2api_deepseek_web` +
`resource_class=remote_api` + `inference_tier=subconscious_4b`, và **"bốn giá
trị đó không còn bị đánh đồng với nhau"**.

Vì sao đây là trừu tượng mạnh: trong hệ naive, "model = vai trò". Khi muốn một
model vừa chạy nền (có thể bỏ), vừa phục vụ foreground (không được bỏ), bạn
không có cách phân biệt. Eris phân biệt bằng *vai trò*, nên policy ngân sách
(cắt/giữ/deadline) áp đúng theo *ý nghĩa* của request, không theo tên model.

**Bất biến 1.1 — Routing theo VAI TRÒ, không theo tên model.** Nhiều lane có
thể dùng chung một model; quyết định lane/optional/deadline bám `cognitive_lane`
và `reason`, không bám model ID. — Bằng chứng: toàn bộ nhánh if trong
`_run_inference()` phân lane theo `cognitive_key`/`reason_key`; `inference_tier`
chỉ vào `metadata["model_tier"]`.

## 1.2 Bản đồ cognitive lane (đầy đủ) — vai trò, bắt buộc/optional, deadline

Bằng chứng: `_run_inference()` trong `model_router.py` (chuỗi if/elif chọn
`lane`) và tập `optional`.

| cognitive_lane / lane broker | Vai trò nhận thức | Bắt buộc hay optional/preemptible | Deadline |
|---|---|---|---|
| `public_claim_verifier` | Gate kiểm claim BẮT BUỘC trước khi phát công khai | **Bắt buộc** (không nằm trong `optional`) | **timeout_seconds=0.0** (không deadline — chờ DeepSeek suy luận lâu vẫn không bị loại) |
| `chat_tool_required` (nhận `turn_executive`, `root_conversation`, `tutor:*`, `chat_intention`) | Bộ não điều hành + tutor đang phục vụ trực tiếp user turn | **Bắt buộc** | Kế thừa cancel_scope của user turn (không timeout 0) |
| `chat_main` (`public_reply` không autonomous) | Câu trả lời công khai trực tiếp | Bắt buộc | Mặc định |
| `neuro_continuation` | Vòng tiếp nối nền | **Optional/preemptible** | — |
| `neuro_deliberation` | Suy nghĩ tự phát hiếm, có thể ngắt | **Optional/preemptible** | — |
| `capability_deliberation_required` (`capability_planner` + `interactive`) | Lập kế hoạch năng lực one-shot cho user turn | Bắt buộc (biến thể required) | Mặc định |
| `capability_deliberation` (`capability_planner` nền) | Lập kế hoạch năng lực nền | **Optional/preemptible** | — |
| `post_observer` / `post_observer_deep` | Quan sát hậu-lượt nuôi feedback | **Optional/preemptible** | Observer HTTP timeout riêng |
| `autonomous` (`autonomous`/`self_initiated`/`surface`) | Hành vi tự khởi | **Optional/preemptible** | — |
| `tutor_background` (`seed`/`discovery`/`planner`) | Công việc nền của tutor/seed/discovery | **Optional/preemptible** | — |
| `transport` | Fallback mặc định | Bắt buộc (không optional) | Mặc định |

Tập optional chính xác trong code:

```python
optional = lane in {
    "post_observer", "autonomous", "tutor_background",
    "neuro_continuation", "neuro_deliberation",
    "capability_deliberation",
}
```

**Bất biến 1.2 — Lane foreground KHÔNG BAO GIỜ nằm trong tập optional.**
`chat_main`, `chat_tool_required`, `public_claim_verifier`, `transport` đều
nằm ngoài `optional`, nên **không bị cắt** khi tài nguyên eo hẹp. — Bằng chứng:
định nghĩa tập `optional` trong `_run_inference()`.

## 1.3 Câu chuyện HOTFIX (bài học thiết kế thật) — vì sao foreground không được optional

Đây là invariant quan trọng nhất của trụ cột 1, và nó sinh ra từ một lỗi thật.

Trích nguyên văn comment trong `_run_inference()` (nhánh
`cognitive_key in {"turn_executive","root_conversation"} or startswith("tutor:")`):

```python
# Character v1 HOTFIX: claim verifier là gate BẮT BUỘC trước
# public delivery. Trước đây lane này rơi xuống post_observer vì
# inference_tier=subconscious_4b => optional/preemptible. Khi chat
# đang xử lý, broker có thể loại chính bước kiểm bắt buộc, khiến
# writer nhận UNKNOWN, thử lại và Eris im lặng.
# Không đổi model, nội dung lời hay điều kiện receipt PASS.
lane = "chat_tool_required"
```

Diễn giải bài học: trước hotfix, lane của turn_executive/root được suy từ
`inference_tier=subconscious_4b`. Vì tier đó map sang `post_observer` (xem nhánh
cuối `elif ... tier == "subconscious_4b": lane = "post_observer"`), mà
`post_observer` là **optional** → broker được phép **loại bỏ** chính bước điều
hành/kiểm bắt buộc khi quá tải → Writer nhận trạng thái UNKNOWN → thử lại →
**Eris im lặng**. Hotfix chuyển các lane này về `chat_tool_required` (bắt buộc)
*mà không đổi model, không đổi nội dung, không đổi điều kiện PASS của receipt* —
tức sửa đúng tầng ngữ nghĩa (vai trò), không vá triệu chứng.

Tại sao đây là "chỉ dân production mới nghĩ ra": lỗi không nằm ở model hay
prompt, mà ở chỗ **nhãn tài nguyên legacy vô tình quyết định quyền sống của một
bước bắt buộc**. Bài học được đóng băng thành invariant.

**Bất biến 1.3 — Vai trò nhận thức được ưu tiên TRƯỚC tier legacy.** Nhánh
`cognitive_key` được kiểm trước nhánh `tier == "subconscious_4b"`, nên một bước
điều hành không thể bị tier cũ kéo xuống lane optional. — Bằng chứng: thứ tự
if/elif trong `_run_inference()`.

## 1.4 Ngân sách suy luận: inference_context + budget_policy.run_queued

Bằng chứng: `_run_inference()` dùng `with inference_context(lane, optional=...,
timeout_seconds=..., coalesce_key=..., metadata={...})` rồi bên trong gọi
`self.budget_policy.run_queued(tier, func, reason=, priority=, resource_class=,
backend=, cognitive_lane=)` nếu có policy; nếu không thì gọi thẳng `func()`.

Các cơ chế tinh tế:
- **`timeout_seconds=0.0` chỉ cho `public_claim_verifier`**: verifier là bước
  bắt buộc nhưng DeepSeek Web có thể suy luận rất lâu; cho nó context giữ
  cancel_scope của user turn nhưng **không kế thừa deadline tổng đã cạn**.
  Comment: "Timeout 0 chỉ dành cho verifier đã được runtime xác định là bước
  bắt buộc."
- **`coalesce_key = reason_key if optional else ""`**: chỉ request optional mới
  được gộp (coalesce) để tiết kiệm; request bắt buộc không bị gộp nhầm.
- **`optional=optional`** truyền thẳng vào broker: broker biết request nào được
  phép loại khi quá tải.

**Bất biến 1.4 — Chỉ lane optional mới được gộp (coalesce) và mới bị cắt.**
`coalesce_key` rỗng khi không optional. — Bằng chứng: dòng `coalesce_key =
reason_key if optional else ""`.

## 1.5 Client theo vai trò và thứ tự fallback của Root

Bằng chứng: `src/llm/service.py` `LlmService.__init__` khai báo các client
có owner riêng, kèm comment "không fallback ngầm":

- `executive_client` — "Gemma Executive Cortex nằm giữa DeepSeek cognition và
  runtime mechanics; không thay worker role-owned nào."
- `surface_client` — "chỉ viết public wording cho intent đã được governor duyệt;
  không fallback ngầm sang companion."
- `seed_client` — "chỉ tạo premise semantic chạy nền trên port riêng; thiếu
  lane này thì reservoir tắt."
- `tutor_client` — "chỉ phân rã scene thành shared semantic context; không có
  quyền viết câu public."
- `curator_client` — "worker memory/profile riêng; thiếu credential thì
  enrichment ở mức deterministic, không mượn identity hội thoại."
- `research_client`, `observer_client`/`social_parser_client`,
  `critic_client`/`social_critic_client`, `inner_client`, `diary_client`,
  `residue_curator_client`, `coding_client`, `escalation_client`,
  `fallback_client` — mỗi cái một vai; nhiều cái **cố ý không fallback** để
  tránh "một lane sổ sách biến thành cognition owner".

Thứ tự ưu tiên client của Root trong `RuntimeModelRootAgent.decide()`
(`agent.py`):

```python
client = (
    getattr(self.router, "executive_client", None)
    or getattr(self.router, "deep_client", None)
    or getattr(self.router, "seed_client", None)
    or getattr(self.router, "surface_client", None)
    or getattr(getattr(self.router, "llm_service", None), "client", None)
)
```

→ `executive_client → deep_client → seed_client → surface_client →
llm_service.client`. Nếu không có client hoặc router không có
`invoke_structured_worker`, Root rơi xuống `_degraded()` (xem trụ cột 2).

**Bất biến 1.5 — Mỗi worker có owner rõ; fallback ngầm bị cấm ở các lane nhạy
cảm.** — Bằng chứng: các comment "No implicit fallback" trong `service.__init__`.

## 1.6 Sơ đồ ba trục

```
                 ┌─────────────────────── cognitive_lane (VAI TRÒ) ───────────────────────┐
request ────────►│ turn_executive | root_conversation | tutor:* | public_claim_verifier   │
                 │ post_observer | autonomous | tutor_background | capability_* | ...      │
                 └───────────────┬─────────────────────────────────────────────────────────┘
                                 │  _run_inference() chọn lane broker + optional + deadline
                                 ▼
          ┌──────────── backend (TRANSPORT) ────────────┐    ┌──── resource_class (VRAM) ────┐
          │ ds2api_deepseek_web | openai_compatible_remote│    │ remote_api | local_light | ...│
          └──────────────────────────────────────────────┘    └───────────────────────────────┘
                                 │
                                 ▼
          inference_context(lane, optional, timeout) → budget_policy.run_queued(...)
                                 │
          optional? ── yes ─► có thể bị cắt / coalesce / preempt
                    └─ no  ─► ĐƯỢC BẢO VỆ (chat, verifier, transport)
```

---

# TRỤ CỘT 2 — AGENT LOOP NHƯ MỘT VÒNG NHẬN THỨC CÓ KIỂM SOÁT

> **NGUYÊN LÝ ĐẮT:** Root là **bộ não điều hành duy nhất** của một lượt: nó quyết
> *ý định*, không tự viết câu, không tự phát tiếng. Vòng lặp của nó bị chặn bằng
> trần cứng, bị cắt sớm khi quay vòng vô ích, và mọi lời "đã làm / đã dạy" đều
> phải có **receipt** quay về mới được tính — niềm tin của model không phải bằng
> chứng.

## 2.1 Vòng lặp max_root_steps — trần cứng, mỗi bước một action JSON

Bằng chứng: `RuntimeModelRootAgent.__init__` (`agent.py`):

```python
# max_root_steps là trần CỨNG TUYỆT ĐỐI: clamp 2..12, không bao giờ bỏ.
self.max_root_steps = max(2, min(12, int(max_root_steps or 8)))
```

Và docstring class: *"max_root_steps là circuit breaker tài nguyên, không phải
giới hạn văn phong."* Vòng `for step_index in range(self.max_root_steps)` mỗi
bước đọc một action theo `ROOT_STEP_SCHEMA`.

Vì sao có trần cứng: nếu model loop sai (gọi tool mãi, nghĩ mãi), runtime phải
có điểm dừng **cơ học**, không phụ thuộc model tự biết dừng. Đây là biên an toàn
tài nguyên tách khỏi chất lượng nội dung.

**Bất biến 2.1 — Mỗi bước Root là ĐÚNG MỘT action; move/no_reply luôn đứng
riêng, không nằm trong batch.** — Bằng chứng: `ROOT_STEP_SCHEMA` là `oneOf`;
`_NON_FINALIZE_STEP_SCHEMAS` lọc bỏ move/no_reply khỏi `batch.actions`; vòng
`decide()` lọc lại phòng thủ `kind not in {"move","no_reply"}` trước khi chạy
batch.

## 2.2 Bộ move đầy đủ và vì sao tách

Bằng chứng: `ROOT_STEP_SCHEMA` + `ROOT_BATCH_STEP_SCHEMA` + `_run_single_action`.

- **`no_reply`** — finalize im lặng. Với autonomous/continuation, im lặng là
  lựa chọn hợp lệ (system prompt).
- **`move`** — finalize nói, gồm `intent` (mục đích semantic), `say` (điều cần
  truyền đạt, *không phải transcript*), `delivery` (cách thể hiện), `after`
  (`wait_user | may_continue | continue_self`). Finalize **trực tiếp**, không
  chạy vòng self-verify thứ hai (comment: tránh làm phẳng personality;
  anti-fabrication do claim_manifest + grounding gate + enforce ở writer lo).
- **`use_capability`** (`capability ∈ {tutor, work, research, action}`) — gọi
  năng lực chuyên môn data-only; kết quả quay về làm `tool_result`.
- **`recall_memory(query)`** — Root tự yêu cầu truy xuất ký ức (public-safe),
  rồi tự quyết nói hay không.
- **`continue_thinking(focus)`** — vòng Root→Root nội bộ, **không** sinh lời
  public, **không** gọi Writer/TTS. **Giới hạn 2 lần.**
- **`set_note(text)` / `clear_note`** — ghi/xóa working-note giữa các lượt.
- **`batch`** (1..4 action nội bộ độc lập) — chỉ ở nhánh one-shot fallback
  (`ROOT_BATCH_STEP_SCHEMA`), chạy một lượt rồi quan sát chung.

Vì sao tách: mỗi move là một **loại quyền** khác nhau. `continue_thinking` là
quyền *nghĩ* (không được lộ ra ngoài); `use_capability` là quyền *nhờ chuyên
môn* (phải có receipt); `move` là quyền *nói* (đi tiếp xuống Writer). Trộn chúng
thành một "generate text" sẽ xóa mọi ranh giới kiểm soát.

Giới hạn `continue_thinking > 2` (bằng chứng, `_run_single_action`):

```python
if kind == "continue_thinking":
    reflection_state["count"] = reflection_state.get("count", 0) + 1
    if reflection_state["count"] > 2:
        return {"kind": "reflection_result", "status": "limit_reached", "next": "finalize"}
```

Vì sao giới hạn 2: nghĩ thầm không tạo bằng chứng mới cho user; cho model nghĩ
vô hạn là mời gọi loop. Hai lần là đủ để "xét lại tình huống" rồi phải quyết.

**Bất biến 2.2 — Action nội bộ (recall_memory, continue_thinking, note) KHÔNG
phải lời public và KHÔNG tự kích TTS.** — Bằng chứng: system prompt Root nêu
thẳng; chỉ `move`/`no_reply` là finalize đi xuống Writer/Delivery.

## 2.3 Chống loop vô ích — đếm "không tiến triển", cắt khi streak ≥ 2

Bằng chứng: `_NON_PROGRESS_STATUSES` và `_advance_progress_and_maybe_finalize`
(`agent.py`):

```python
_NON_PROGRESS_STATUSES = frozenset(
    {"duplicate", "empty", "failed", "limit_reached", "unavailable", "invalid"})
```

Mỗi bước, nếu toàn bộ `tool_result` sinh ra đều mang status không tiến triển
(hoặc trùng fingerprint result của bước trước), `no_progress_streak` tăng; khi
streak ≥ 2, Root dừng sớm bằng `_no_progress_decision(...)` dù chưa chạm trần
cứng. Dedup gọi tool trùng tham số qua `prior_actions` (fingerprint
`"cap:<name>:<args>"`). Ngoài ra `_background_failure_cooldown` 90s chặn
Root/Writer nền khi hai move nền liên tiếp lỗi (bằng chứng: `kernel.py`
`_handle_event_once` kiểm `event.kind != 'user_turn' and
self._background_failure_cooldown(sid)`).

**Bất biến 2.3 — Vòng lặp có HAI tầng phanh: trần cứng tài nguyên + cắt sớm khi
không tiến triển.** — Bằng chứng: `range(self.max_root_steps)` và streak logic.

## 2.4 "Món đẹp nhất" — phân biệt 'định nói' ≠ 'đã nói' ≠ 'đã dạy'

> **NGUYÊN LÝ ĐẮT:** Một hệ thống trung thực không được phép để model *tuyên bố*
> "mình đã làm/đã dạy". Trạng thái đó phải là **sự kiện vật lý có biên nhận**:
> câu đã thực sự phát ra audio thành công hay chưa.

Chuỗi trạng thái của một delivery (bằng chứng:
`src/runtime/conversation/move_outcomes.py`, `MoveOutcomeLedger.VALID_STATUSES`):

```python
VALID_STATUSES = frozenset({
    'preparing', 'queued_for_audio', 'delivering', 'delivered',
    'failed_before_delivery', 'delivery_failed', 'cancelled',
    'unconfirmed_after_restart', ...})
TERMINAL = frozenset({'delivered', 'failed_before_delivery', 'delivery_failed',
                      'cancelled', 'unconfirmed_after_restart'})
```

Ý nghĩa phân biệt tinh tế (summary text trong `move_outcomes.py`):
- `preparing` → Root đã *định nói*, Kernel cấp `delivery_id` nhưng Writer/TTS
  chưa xong.
- `queued_for_audio` → "đã gửi tới hàng đợi phát; **chưa có audio_start, chưa
  xác nhận user nghe**."
- `delivering` → "đã bắt đầu phát âm thanh; chưa xác nhận phát xong."
- `delivered` → "đã phát xong."
- `cancelled` → "đã bị hủy; **không tự phát lại**."

Ba bằng chứng về sự trung thực:
1. **User chen vào không biến dang dở thành delivered** — `cancel_inflight()`
   chỉ chuyển `preparing/queued_for_audio/delivering → cancelled`.
2. **Restart không giả vờ audio đã xong** — `recover_inflight_on_restart()`:
   *"SQLite biết move từng ở preparing/delivering nhưng không thể chứng minh TTS
   đã đến tai người dùng trước crash. Ghi UNKNOWN thay vì delivered… tuyệt đối
   không phát lại từ ledger."*
3. **Receipt quay về Root** — delivery settle fan-out `DeliveryReceipt` tới
   capability và về `conversation_move_receipts` để Root chỉ được nói "đã thực
   thi" khi có receipt `success` của đúng run/generation.

**Bất biến 2.4 — 'Định nói' không tự trở thành 'đã nói'; 'đã nói' không tự trở
thành 'đã dạy'.** Trạng thái chỉ tiến khi có bằng chứng phát thành công. —
Bằng chứng: `MoveOutcomeLedger` state machine + `TutorExecutive.commit_delivery`
(docstring: *"Eris định nói không đồng nghĩa Eris đã dạy"*) chỉ `advance_kp` sau
receipt `successful`.

## 2.5 Generation-based preemption — concurrency elegant

> **NGUYÊN LÝ ĐẮT:** Khi user nói chen vào, mọi callback TTS cũ phải **chết tức
> thì**, không cần đi lock từng cái. Giải pháp: một con số **generation** tăng
> NGAY; mọi thứ của generation cũ tự động hết hiệu lực.

Bằng chứng: `kernel.py` `_handle_event_once`, nhánh `user_turn`:

```python
# Đổi generation TRƯỚC: callback TTS cũ tới đồng thời sẽ bị loại
# ngay cả khi chưa kịp lấy delivery lock để discard.
state = self.store.mutate(..., lambda prior, now: replace(
    prior, generation=prior.generation + 1, active_run_id=run_id, ...))
self.continuation.cancel_session(sid)
self._discard_session_deliveries(sid)
```

Cổng kiểm cho Root (`root_run_active`), được kernel cấp theo (session,
generation, run_id):

```python
def root_run_active() -> bool:
    current_run = self.store.load(sid)
    return current_run.generation == state.generation and current_run.active_run_id == run_id
agent_context["__root_run_active"] = root_run_active
```

Root gọi `still_active()` **trước mỗi bước** và trước khi finalize; nếu user đã
chen vào thì trả `NoReply(reason="root_turn_preempted")`. Kernel cũng recheck
generation/run_id trước prepare và trước transport (nếu lệch → ghi
`cancelled(reason='stale_after_prepare')`).

Vì sao elegant: thay vì quản lý vòng đời từng task async bằng cancel token lồng
nhau, Eris dùng **một số đơn điệu tăng dần** làm "đồng hồ sự thật". So sánh
bằng-nhau là đủ để loại mọi tàn dư của lượt cũ — không race, không cần dừng
cưỡng bức socket.

**Bất biến 2.5 — Tăng generation là hành động ĐẦU TIÊN của user_turn, trước cả
discard delivery.** — Bằng chứng: thứ tự lệnh trong `_handle_event_once`.

## 2.6 Continuation lease ≠ scheduler nhắc học nhiều ngày

Bằng chứng: `src/runtime/conversation/continuation.py`,
`ContinuationLeaseScheduler`.

- Lease có TTL rất ngắn: `lease_ttl_seconds=30.0`; delay chỉ
  `may_continue_delay=1.2s` / `continue_self_delay=0.15s`.
- Circuit breaker: `max_consecutive_self_wakes=24`, `max_chain_seconds=120.0`.
  Docstring: *"max_consecutive_self_wakes và max_chain_seconds là circuit
  breaker tài nguyên. Đây KHÔNG phải pacing policy: chúng không cắt câu, không
  giới hạn số sentence và không quyết định nội dung nên nói."*
- `after == WAIT_USER` → `cancel_session` (không lập lease).

**Bất biến 2.6 — Continuation lease là cơ chế "nói tiếp trong vài giây", TÁCH
HOÀN TOÀN khỏi lịch ôn tập nhiều ngày (ReviewScheduler SM-2).** Lẫn lộn hai thứ
sẽ hoặc biến một continuation 1.2 giây thành reminder nhiều ngày, hoặc kéo
reminder nhiều ngày vào giới hạn chain 120 giây. — Bằng chứng: continuation TTL
≤ 30s (`continuation.py`) vs `ReviewItem.interval_days` tính bằng **ngày**,
`max_interval_days=180.0` (`learning_core/scheduler.py`). Đây cũng là một hook
point cho lộ trình Tutor (xem phần cuối).

## 2.7 Fail-soft — "Eris luôn có tiếng kể cả khi LLM hỏng"

Bằng chứng: `agent.py` `DeterministicRootAgent` (fail-soft contract) +
`kernel.py` `_deliver_runtime_failure`.

Khi model lỗi/không khả dụng, `RuntimeModelRootAgent.decide()` gọi `_degraded()`
→ `DeterministicRootAgent().decide()` để vẫn trả lời thẳng lượt user. Khi
provider failure nặng (429/401…), kernel đi đường phát status **không qua
Root/Writer/localizer**, với câu cố định (display tiếng Việt, speech tiếng Nhật):

```python
rendered = RenderedConversationMove(surface=SurfaceEnvelope(
    display_text="Ư… tớ đang gặp trục trặc nên chưa trả lời được. Cậu thử lại sau một chút nhé.",
    speech_text="うぅ……今ちょっと調子が悪くて、返事ができないみたい。また少ししてから試してね。",
    language="vi", alignment_safe=False))
# Cố ý không chạy Writer: khi LLM chết đường này vẫn hoạt động.
```

Và nó vẫn kiểm generation/run_id cả trước chuẩn bị lẫn trước transport để không
"nói thay lượt cũ".

**Bất biến 2.7 — Có đúng một đường phát không phụ thuộc LLM; nó vẫn tôn trọng
hợp đồng hai kênh (display VI / speech JA) và preemption.** — Bằng chứng:
`_deliver_runtime_failure` hardcode transcript + kiểm generation hai lần.

## 2.8 Grounding gate + claim_manifest — chống bịa ở Writer

Bằng chứng: `src/runtime/conversation/runtime_writer.py`.

- `__evidence_registry` (`EvidenceRegistry`): chỉ thêm **source refs CÓ SCOPE**
  của đúng run vào grounding context; comment: *"refs không tự biến câu nói
  thành fact"* ở v0.1.
- `claim_manifest` / `_typed_claim_manifest` + `validate_claim_manifest` với
  `allowed_domains` từ `build_writer_evidence_policy(evidence_registry)`:
  manifest sai cấu trúc → `raise RuntimeError("public_writer_manifest_...")`.
  Nhưng cố ý: *"claim_manifest là metadata TÙY CHỌN để nghiên cứu offline, không
  phải hợp đồng phát lời… lỗi manifest không được khiến Eris im lặng"*
  (comment trong `PUBLIC_REPLY_CORE_SCHEMA`, `model_router.py`).
- Lane `public_claim_verifier` (trụ cột 1): gate kiểm claim bắt buộc, không
  deadline.

**Bất biến 2.8 — Grounding là lớp kiểm ĐỘC LẬP với sự tự tin của model; nhưng
nó không được phép làm Eris im lặng.** Ref tồn tại chỉ chứng minh provenance,
không chứng minh nguồn hỗ trợ chính claim. — Bằng chứng: các comment trên +
đối chiếu bài học trong `docs/knowledge/2026-10-14-eris-runtime-lessons.md`
(mục "Bằng chứng phải độc lập với sự tự tin của model").

## 2.9 Sơ đồ agent loop

```
Event ─► Kernel._handle_event_once ─► (user_turn: generation+1, discard cũ)
          │
          ▼
  RuntimeModelRootAgent.decide()  ── for step in range(max_root_steps[2..12]) ──┐
          │  mỗi bước: 1 action JSON (ROOT_STEP_SCHEMA)                          │
          │  still_active()? ── no ─► NoReply(root_turn_preempted)               │
          │  no_reply ───────────────► finalize (im lặng)                        │
          │  move ───────────────────► finalize TRỰC TIẾP (no self-verify) ──────┼─► Writer
          │  use_capability ─► receipt ─► tool_result ──┐                         │
          │  recall_memory ─► public-safe ──────────────┤  no_progress_streak≥2? │
          │  continue_thinking (≤2) ────────────────────┤  ─► cắt sớm            │
          │  set_note/clear_note ───────────────────────┘                        │
          └──────────────────────────────────────────────────────────────────────┘
  (model lỗi) ─► _degraded() = DeterministicRootAgent  |  (provider 429/401) ─► _deliver_runtime_failure (no LLM)
```

---

# TRỤ CỘT 3 — TUTOR NHƯ LEARNING KERNEL DETERMINISTIC + LỘ TRÌNH NÂNG CẤP

> **NGUYÊN LÝ ĐẮT:** Trong Eris, **"LLM đề xuất; deterministic kernel commit."**
> Model chỉ được *gợi ý* hành động sư phạm và *chấm* câu trả lời tự do; nhưng
> ghi nhận mastery/evidence/review là việc của một kernel có luật rõ ràng. Nhờ
> ranh giới này, Tutor không bao giờ trở thành "agent thứ hai" tranh quyền với
> Root.

## 3.1 Nguyên lý cốt lõi: LLM đề xuất; kernel commit

Bằng chứng nguyên văn: `src/runtime/learning_core/service.py` (docstring đầu
module) và `src/runtime/learning_core/BOUNDARY_VI.md`:

```
TutorRole/TutorReasoner -> de xuat pedagogical intent (probe/teach/practice/assess).
ConversationDirector   -> quyet dinh turn nay tiet lo bao nhieu va dung o dau.
LearningService        -> chi commit su that hoc tap deterministic.

Quy tac cot loi: "LLM de xuat; deterministic kernel commit". Nho boundary nay,
DeepTutor-derived logic chi la learning kernel ben trong Eris, khong tro thanh
mot agent thu hai tranh quyen voi root TurnAgentLoop.
```

`BOUNDARY_VI.md` còn liệt kê những gì kernel được quyền sở hữu: MasteryRecord,
LearningEvidence, LearningPath/KnowledgePoint, pending interaction ledger,
**deterministic choice grading**, review scheduler/retrievability, TutorStep
navigation policy.

Vì sao tách `RuntimeTutorReasoner` (model-backed) khỏi `LearningService`
(deterministic) là elegant: nếu để LLM vừa đề xuất vừa commit, một câu "bịa"
của model có thể ghi thẳng vào mastery → hồ sơ người học nhiễm độc. Tách ra, mọi
đề xuất phải qua **gate tin cậy** rồi mới thành sự thật bền vững.

**Bất biến 3.1 — LearningService là CỬA VÀO DUY NHẤT để ghi sự thật học tập; nó
không viết public text, không gọi TTS, không tự bật tutor.** — Bằng chứng:
docstring module + `BOUNDARY_VI.md` ("NHUNG GI MODULE NAY *KHONG* DUOC QUYET").

## 3.2 Graceful degradation: Conservative vs Runtime reasoner

Bằng chứng: `src/runtime/tutor/composition.py` `build_tutor_runtime`:

```python
reasoner = None
if callable(getattr(model_router, "invoke_structured_worker", None)):
    reasoner = RuntimeTutorReasoner(model_router, logger=logger)
```

Và `TutorExecutive.__init__`: `self.reasoner = reasoner or
ConservativeTutorReasoner()`.

- `RuntimeTutorReasoner` (`model_reasoner.py`): bộ não semantic thật, chạy trên
  `router.invoke_structured_worker`. Raise `TypeError` nếu router không có
  transport đó (fail-fast khi dựng, không fail-soft giả).
- `ConservativeTutorReasoner` (`reasoner.py`): fallback deterministic. Docstring:
  *"Fallback này cố ý không chấm câu trả lời tự do. Nó chỉ giúp hệ thống vẫn có
  hành vi hợp lệ, còn semantic evidence phải chờ model assessor thật."* Nó
  `diagnose()` theo `TutorStep.kind` và `choose_move()` theo `envelope`.

Vì sao đẹp: Tutor hoạt động **cả khi có và không có** model reasoner. Không có
model → vẫn chạy theo learning policy deterministic, chỉ là không commit evidence
từ câu tự do. Có model → thêm năng lực chấm semantic. Không có "màn hình trắng"
khi thiếu model.

**Bất biến 3.2 — Thiếu model reasoner KHÔNG làm tutor chết; chỉ làm mất năng lực
chấm câu tự do.** — Bằng chứng: `reasoner or ConservativeTutorReasoner()`.

## 3.3 Năm lớp của learning kernel

Bằng chứng tổng hợp từ `src/runtime/tutor/*` và `src/runtime/learning_core/*`.

1. **TutorState / TutorSessionLedger** (`contracts.py`, `session_store.py`,
   `executive.py`): state session-scoped (path/KP hiện tại, `last_move`,
   `last_delivery_text`, `turn_count`, hypotheses) + persist qua
   `TutorSessionLedger.commit()` (compare-and-swap, SQLite) để resume sau
   restart. Idempotency `committed_move_ids` giới hạn 128 phần tử.

2. **LearnerProfile / MasteryRecord** (`learning_core/contracts.py`):
   pace/style/ngôn ngữ + mastery bền vững theo từng KP; `LearnerHypothesis`
   (`tutor/contracts.py`) là giả thuyết mềm về nguyên nhân vướng.

3. **assess_response → SemanticAssessment** (`executive.py`): chấm semantic câu
   tự do rồi **chỉ commit nếu đủ chắc**:

   ```python
   if assessment.verdict == "uncertain" or assessment.confidence < self.semantic_commit_confidence:
       return False   # không commit evidence
   evidence = self.learning.commit_evidence(...)
   ```

   Ngưỡng `semantic_commit_confidence` được clamp `max(0.50, min(0.95, ...))`,
   default `0.68`. Hypothesis chỉ đổi lifecycle khi assessment cũng đủ chắc để
   thành evidence (comment trong `observe_response`).

4. **GuardrailPolicy → MoveEnvelope** (`policy.py`, `contracts.py`):
   `TutorGuardrailPolicy.envelope(step, diagnosis, learner)` sinh **envelope
   giới hạn**: `allowed_kinds` theo phase (probe/teach/practice/assess/review/
   advance/complete), `max_sentences` (clamp 1..6, điều chỉnh theo pace),
   `requires_user_response`. `enforce(move, envelope, kp_id)` ép proposal của
   model về contract: nếu `move.kind` ngoài `allowed_kinds` thì lấy
   `allowed_kinds[0]`; Socratic question luôn `requires_user_response` kể cả
   khi phase cha là teach (comment: "Không được phát câu hỏi rồi tiếp tục
   autonomous như thể đó chỉ là một câu giải thích").

5. **ReviewScheduler SM-2** (`learning_core/scheduler.py`): `next_review_item`
   theo SM-2 biến thể + forgetting curve `R(t)=e^(-t/(S×half_life))`,
   `_HALF_LIFE_DAYS=14.0`, `ease_delta` theo quality 0..4, reset interval khi
   quality < 2, `max_interval_days` clamp. `grade_choice` (`grading.py`) chấm
   multiple_choice/true_false **deterministic**; short_answer/application cố ý
   `NotImplementedError` trong kernel để ngăn LLM-call lọt vào kernel thuần.

**Bất biến 3.3 — Grading trắc nghiệm là deterministic trong kernel; grading
semantic nằm ở service và phải qua ngưỡng tin cậy.** — Bằng chứng: `grading.py`
docstring ("Only grade_choice is deterministic… Semantic grading stubs raise
NotImplementedError") + `_apply_semantic_assessment` ngưỡng confidence.

## 3.4 Hai invariant "đẹp" của Tutor

**Bất biến 3.4a — Writer KHÔNG BAO GIỜ thấy đáp án.** `TeachingMove.to_writer_dict()`
cố ý bỏ `expected_answer`. — Bằng chứng (`tutor/contracts.py`):

```python
def to_writer_dict(self) -> dict[str, Any]:
    """Projection an toàn cho writer; cố ý không có expected_answer."""
    return { "move_id":..., "instruction_vi":..., "question_goal":..., ... }
```

và `learning_core/contracts.py`: *"The expected_answer is only stored
server-side and never in the public writer output. Grading happens
deterministically against this record."*

Vì sao đẹp: nếu đáp án đi vào Writer, câu hỏi Socratic vô nghĩa (model có thể lộ
đáp án trong lời). Tách đáp án ra khỏi kênh diễn đạt là ranh giới quyền lực:
Writer *diễn đạt câu hỏi*, không *biết câu trả lời*.

**Bất biến 3.4b — Khi user lạc đề, tutor NHẢ quyền chấm (suspend_pending_move)
để không chấm nhầm câu không liên quan.** — Bằng chứng (`executive.py`):

```python
def suspend_pending_move(self, *, reason="user_interrupt", ...):
    # Nếu không clear ở đây, turn sau sẽ nhìn last_move cũ và có thể chấm một
    # câu hoàn toàn không liên quan như câu trả lời bài học.
    # Learning mastery/evidence không bị động tới; chỉ session interaction bị yield.
```

Vì sao đẹp: nó tôn trọng quyền tự do của user. Tutor không "ép" mọi câu user nói
thành câu trả lời bài học; đổi hướng là hợp lệ, và mastery bền vững không bị
nhiễm bởi một câu lạc đề.

## 3.5 Bốn khớp nối Tutor vào hội thoại (điểm móc có thật)

Bằng chứng: `orchestrator.py`, `agent.py`, `capabilities/tutor.py`,
`public_output_runtime.py`.

1. **Đăng ký**: `RootCapabilityRegistry({"tutor": TutorCapability(host.tutor_executive), ...})`.
2. **Schema mở sẵn**: `ROOT_STEP_SCHEMA.use_capability.capability ∈
   {tutor, work, research, action}`.
3. **Entry point data-only**: `TutorCapability.invoke_for_root()` → `advise()`
   → `observe_response()` + `plan_next_move()`; trả `TutorAdvice` không chứa
   expected_answer.
4. **Đóng vòng "đã dạy"**: delivery settle → `observe_delivery_receipt()` →
   `TutorExecutive.commit_delivery(successful=...)` chỉ `note_taught`/`advance_kp`
   khi phát thành công.

## 3.6 ĐIỂM CẦN NỐI (hook point xác nhận bằng code)

`register_path` / `activate_path` **chỉ có call site trong test**
(`src/tests/test_tutor_executive_v1.py`), không có trong luồng chat. — Bằng
chứng: grep toàn repo chỉ ra `learning_core/service.py` (định nghĩa) và test
(gọi), không có call site runtime. Đây là **điểm móc còn mở cho bước "nhập
curriculum"**: ai đó phải gọi `register_path(path)` + `activate_path(path_id)`
từ một nguồn (hội thoại, file curriculum, hoặc một capability khởi tạo). Mô tả
đúng: đây là *khớp nối sẵn sàng*, chưa có call site runtime.

---

# LỘ TRÌNH TUTOR TƯƠNG LAI — "tiềm năng vô hạn", nhưng cắm vào điểm móc THẬT

Mỗi hướng dưới đây chỉ ra **cắm vào điểm móc code nào** và **giữ invariant nào**.
Tất cả đều là mở rộng *trên khung hiện có*, không viết lại lõi.

## H1. Multi-tutor nhiều môn song song
- **Cắm vào**: `RootCapabilityRegistry` (`orchestrator.py`) — thêm nhiều
  capability (`tutor:math`, `tutor:english`…) mỗi cái bọc một `TutorExecutive`
  riêng; lane `cognitive_lane` đã hỗ trợ tiền tố `tutor:*` (model_router nhánh
  `startswith("tutor:")`). `LearningService` theo path/KP riêng từng môn.
- **Giữ invariant**: 1.2 (lane foreground bắt buộc), 3.1 (một cửa commit mỗi
  môn), 3.4a (không lộ đáp án). Root vẫn là bộ não duy nhất chọn gọi môn nào.
- **Vì sao khả thi**: registry là dependency container; thêm key không đổi lõi
  hội thoại. Lane đã nhận `tutor:*`.

## H2. Vision opt-in chấm ảnh bài làm
- **Cắm vào**: `resource_class="vision_local"` đã tồn tại trong
  `_client_inference_profile`; evidence đi qua `EvidenceRegistry` +
  `CapabilityResultReceipt`; commit qua `LearningService.commit_evidence` với
  `LearningEvidence` có provenance.
- **Giữ invariant**: 2.8 (grounding độc lập — ảnh là evidence có scope, không tự
  thành fact), 2.4 (receipt chứng minh đã chấm), 3.3 (semantic grading qua
  ngưỡng confidence).
- **Vì sao khả thi**: vision chỉ là một backend/resource_class mới + một
  evidence contract; receipt pipeline đã sẵn.

## H3. Nhắc học nhiều ngày qua scheduler riêng (KHÔNG kéo continuation lease)
- **Cắm vào**: `ReviewScheduler`/`next_review_item`/`due_items`
  (`learning_core/scheduler.py`) đã tính `due_at` theo ngày; cần một **scheduler
  reminder riêng** phát `reminder_due` event (kernel đã xử lý loại event nền).
- **Giữ invariant**: 2.6 — **tuyệt đối không** dùng `ContinuationLeaseScheduler`
  (TTL ≤ 30s, chain ≤ 120s) cho reminder nhiều ngày. Reminder là event nền
  (optional/preemptible), không chiếm run của user turn.
- **Vì sao khả thi**: dữ liệu due_at theo ngày đã có; chỉ cần một bộ phát event
  riêng, không đụng continuation.

## H4. LearnerModel tiến hóa (dự đoán điểm yếu, forgetting curve nâng cao)
- **Cắm vào**: `MasteryRecord` + `ReviewItem.forgetting_risk` +
  `LearnerHypothesis` (giả thuyết mềm). Nâng cấp hàm retrievability trong
  `scheduler.py` (hiện `R(t)=e^(-t/(S×half_life))`, half_life=14 ngày) thành
  mô hình theo từng KP/learner.
- **Giữ invariant**: 3.1 (kernel commit deterministic — dự đoán vẫn phải qua
  gate để thành evidence), 3.4b (hypothesis là mềm, không phải sự thật).
- **Vì sao khả thi**: forgetting curve đã có tham số; nâng cấp là thay công
  thức, không đổi contract.

## H5. Multi-agent tutor (planner tutor + executor tutor) nhưng vẫn dưới Root
- **Cắm vào**: `RuntimeTutorReasoner` (model_reasoner) có thể tách thành hai vai
  (planner chọn chiến lược, executor soạn move) *bên trong* một capability;
  `TutorGuardrailPolicy.enforce` vẫn là van cuối ép mọi proposal về envelope.
- **Giữ invariant**: 2.1/2.2 (chỉ Root finalize move public), 3.1 (kernel
  commit), 3.4a (không lộ đáp án). Hai tutor chỉ *đề xuất*; không cái nào có
  quyền phát lời — quyền đó thuộc Root → Writer → Delivery.
- **Vì sao khả thi**: reasoner là interface (`TutorReasoner` Protocol); thay
  implementation không đụng executive hay learning kernel.

---

# VÌ SAO KIẾN TRÚC NÀY KHÓ BẮT CHƯỚC (rào cản kỹ thuật cho giám khảo)

1. **Tách bốn trục quyền lực + bốn trục routing**: quyết định / diễn đạt / phát
   / ghi nhớ, và vai trò / backend / VRAM / tier. Một nhóm "gọi API rồi đọc lên"
   không có chỗ để cài luật optional/preemption, anti-fabrication hay
   graceful degradation — vì mọi thứ dính vào một lời gọi model.

2. **Anti-fabrication cấp hệ thống, không cấp prompt**: 'định nói ≠ đã nói ≠ đã
   dạy' được bảo chứng bằng state machine `MoveOutcomeLedger` + `DeliveryReceipt`
   + `CapabilityResultReceipt`, không bằng việc nhắc model "đừng bịa". Receipt
   gắn `event_id/run_id/generation` và không ghi đè — không thể giả.

3. **Concurrency bằng generation đơn điệu**: user chen vào là cả một thế hệ cũ
   chết tức thì bằng so sánh số, không cần hủy từng callback. Restart ghi
   UNKNOWN thay vì giả vờ delivered. Đây là tư duy hệ phân tán, không phải tư duy
   chatbot.

4. **Learning kernel deterministic tách khỏi model**: "LLM đề xuất; kernel
   commit" + envelope guardrail + ngưỡng confidence + SM-2. Tutor không thể
   nhiễm độc hồ sơ người học bằng một câu bịa, và vẫn chạy khi không có model
   reasoner. Đối thủ "một tính năng tutor" thường để model tự chấm và tự ghi.

5. **Fail-soft có thật, giữ hợp đồng downstream**: một đường phát status không
   qua LLM (display VI + speech JA cố định) đảm bảo Eris luôn có tiếng khi
   provider chết — nhưng vẫn kiểm generation để không nói thay lượt cũ. Đây là
   chi tiết chỉ xuất hiện sau khi vận hành thật và vấp lỗi thật (xem HOTFIX ở
   trụ cột 1 và bài học trong `docs/knowledge/2026-10-14-eris-runtime-lessons.md`).

---

## Phụ lục: file/symbol trích dẫn chính (bổ sung cho flow-description.md)

- `src/runtime/ai_orchestrated/model_router.py` — `_client_inference_profile`
  (tách 3 trục), `_run_inference` (chọn lane, tập `optional`, HOTFIX comment,
  `timeout_seconds=0.0` cho verifier, `coalesce_key`), `invoke_structured_worker`,
  `PUBLIC_REPLY_CORE_SCHEMA` (claim_manifest tùy chọn).
- `src/llm/service.py` — `LlmService.__init__` (các client theo vai trò, comment
  "No implicit fallback").
- `src/runtime/conversation/agent.py` — `ROOT_STEP_SCHEMA`,
  `ROOT_BATCH_STEP_SCHEMA`, `_NON_FINALIZE_STEP_SCHEMAS`, `RuntimeModelRootAgent`
  (`max_root_steps` clamp 2..12, thứ tự client fallback, finalize move trực
  tiếp), `_run_single_action` (`continue_thinking > 2`),
  `_NON_PROGRESS_STATUSES`, `_advance_progress_and_maybe_finalize`,
  `DeterministicRootAgent`.
- `src/runtime/conversation/kernel.py` — `_handle_event_once` (generation+1,
  discard, `root_run_active`, `_background_failure_cooldown`),
  `_deliver_runtime_failure` (transcript cố định VI/JA), `KernelTurn`.
- `src/runtime/conversation/move_outcomes.py` — `MoveOutcomeLedger`
  (`VALID_STATUSES`, `TERMINAL`, `cancel_inflight`, `recover_inflight_on_restart`).
- `src/runtime/conversation/continuation.py` — `ContinuationLeaseScheduler`
  (TTL 30s, delay 1.2s/0.15s, breaker 24 wakes/120s).
- `src/runtime/conversation/runtime_writer.py` — grounding gate,
  `__evidence_registry`, `claim_manifest`/`_typed_claim_manifest`,
  `validate_claim_manifest`.
- `src/runtime/tutor/composition.py` — `build_tutor_runtime` (chọn reasoner).
- `src/runtime/tutor/reasoner.py` — `TutorReasoner` Protocol,
  `ConservativeTutorReasoner`.
- `src/runtime/tutor/model_reasoner.py` — `RuntimeTutorReasoner`.
- `src/runtime/tutor/executive.py` — `TutorExecutive` (`semantic_commit_confidence`,
  `observe_response`/`_apply_semantic_assessment`, `commit_delivery`,
  `suspend_pending_move`).
- `src/runtime/tutor/policy.py` — `TutorGuardrailPolicy.envelope`/`enforce`.
- `src/runtime/tutor/contracts.py` — `MoveEnvelope`, `TeachingMove.to_writer_dict`
  (bỏ expected_answer).
- `src/runtime/learning_core/service.py` + `BOUNDARY_VI.md` — "LLM đề xuất;
  kernel commit", `register_path`/`activate_path` (chỉ test gọi).
- `src/runtime/learning_core/scheduler.py` — SM-2 `next_review_item`, forgetting
  curve, `max_interval_days`.
- `src/runtime/learning_core/grading.py` — `grade_choice` deterministic,
  semantic stub `NotImplementedError`.
- `src/runtime/learning_core/contracts.py` — `ReviewItem` (interval_days,
  ease_factor), expected_answer chỉ server-side.

_Nội dung mô tả hệ thống ở dạng thiết kế sẽ thực thi, phục vụ phụ lục kỹ thuật
pitch; mọi trích dẫn bám theo code trong repo. Một số nhận định lịch sử được
đối chiếu với `docs/knowledge/2026-10-14-eris-runtime-lessons.md`._
