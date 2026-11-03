# Ba phần nặng nhất của Root request — đánh giá "thừa vô tác dụng"

Điều tra READ-ONLY. Không sửa code, không build, không restart. Mọi kết luận kèm
file:dòng. Phân biệt rõ: **đọc được từ source** vs **suy đoán/chưa xác minh**.
Repo: `c:\Users\Gtvkun\Documents\GitHub\eris` (checkout chính, không dùng worktree).

Đã đọc trước (theo AGENTS.md):
- `docs/knowledge/2026-10-14-eris-runtime-lessons.md` — áp quy tắc "field có trong
  to_dict KHÔNG chứng minh Root đọc field đó; phải tìm consumer thực".
- `.agents/tasks/eris-token-growth/live-self-log-readout.md` — số đo live.

---

## (0) TÓM TẮT CÂU TRẢ LỜI

| Phần | Kích thước LIVE | Cốt lõi CẦN | Khối THỪA vô tác dụng (ước cắt) | Phân loại chính |
|---|---:|---|---|---|
| **mind_state** | 7.182 → 10.732 | personality.core/temperament/mood, identity.values/beliefs/motives/defenses, relationship, appraisal, latest_intention, open_loops/goal_records | **trajectory[-96], consolidation_ledger[-24], corroboration_records[-16], streaks, day_usage, corroboration, identity.ledger, mọi `*_at` timestamp + `version`/`schema`** → **~3.500–6.000 ký tự** và là NGUỒN PHÌNH theo phiên | THỪA (telemetry/history tích lũy) |
| **message cuối ~37k** | ~37.438 | event (user turn), runtime_context (grounding/status), self_changes_since_bootstrap | **KHÔNG lặp lại Self prefix** (đã xác minh). Thừa chỉ là phần trùng đã được dedup một phần; dư địa nhỏ hơn nhiều so với kỳ vọng | CẦN phần lớn; dedup thêm nhỏ |
| **living_user.profile** | 9.568 | path + value + explicitness + status + confidence | **id, value_type, cardinality, recurrence, tier, source** (các qualifier kỹ thuật không lái câu) → ước **~1.500–2.500 ký tự** | CHƯA XÁC MINH mạnh cho vài field (xem dưới) |

**Kết luận dứt khoát về "thừa vô tác dụng thật sự":**
1. **Thừa lớn nhất + rủi ro thấp nhất = nhóm telemetry/history trong `mind_state`**
   (`trajectory`, `consolidation_ledger`, `corroboration_records`, `streaks`,
   `day_usage`, `corroboration`, `identity.ledger`, các timestamp). Đây CHÍNH là
   nguyên nhân mind_state tăng 7182→10732 theo phiên, và **không có consumer nào
   đọc chúng ở đường Root sinh move**.
2. **message cuối ~37k KHÔNG phải khối trùng Self** như giả thuyết trong brief —
   đó là nội dung current-turn thật (user text + grounding + delta). Giả thuyết
   "lặp lại gần toàn bộ Self 38k mỗi lượt" bị **đính chính**: nó không tái gửi Self.
3. **living_user.profile** đã qua compact nên phần thừa còn lại nhỏ và là các
   qualifier kỹ thuật; cắt được nhưng lợi ích/rủi ro thấp hơn (1).

---

## (1) mind_state (~10,7k, đang phình)

### (a) Nó gồm field gì

`mind_state = host.ai_state_reducer.snapshot().to_dict()`
— `src/runtime/conversation/root_session.py:48-56` (`_read_self`).

`snapshot()` trả `RuntimeMindState`
— `src/runtime/ai_orchestrated/state_reducer.py:98-101`.

`RuntimeMindState.to_dict()` — `src/runtime/ai_orchestrated/contracts.py:552-568`.
Field top-level:

| Field | Nguồn | Bản chất |
|---|---|---|
| `schema`, `version`, `last_applied_turn_seq`, `updated_at` | contracts.py:553-555,567 | **telemetry/định danh** |
| `relationship` | `RelationshipState.to_dict()` contracts.py:103-104 | **nhận thức** (trust/closeness/rupture…) — nhỏ, phẳng |
| `appraisal` | `AppraisalState.to_dict()` contracts.py:147-148 | **nhận thức** (pleasantness/curiosity/pressure…) — nhỏ, phẳng |
| `personality` | `PersonalityProfile.to_dict()` personality.py:621-648 | **hỗn hợp**: core/temperament/mood (CẦN) + history (THỪA) |
| `identity` | `IdentityProfile.to_dict()` identity.py:611-632 | **hỗn hợp**: values/beliefs/motives/defenses (CẦN) + ledger/corroboration (THỪA) |
| `identity_learning_enabled` | contracts.py:557 | flag — nhỏ |
| `latest_observation` | contracts.py:558 | 1 record observer (lớn nhưng KHÔNG tích lũy, bị thay mỗi lượt) |
| `latest_intention` | contracts.py:559 | 1 record plan — bị thay mỗi lượt |
| `open_loops` | contracts.py:560, cap `[-8:]` (contracts.py:509) | CẦN, có trần |
| `goal_records` | contracts.py:561, cap `[-8:]` (contracts.py:513-517) | CẦN, có trần — **đây là "goal" user hỏi ở message #5** |
| `memory_candidates` | contracts.py:562, cap `[-12:]` (contracts.py:519) | CHƯA XÁC MINH |

**Nguồn phình (tích lũy) nằm trong `personality` và `identity`:**

`PersonalityProfile.to_dict()` (personality.py:621-648) xuất:
- `trajectory`: list, nạp cap `[-96:]` (personality.py:548-552) — **96 record/phiên**.
- `consolidation_ledger`: list cap `[-24:]` (personality.py:579-583).
- `corroboration_records`: dict of list cap `[-16:]` mỗi key (personality.py:570-577).
- `streaks`, `day_usage`, `corroboration`: dict tích theo lượt (personality.py:633-634).
- `last_consolidated_at`, `last_decay_at`, `last_updated_at`: timestamp (personality.py:645-647).

`IdentityProfile.to_dict()` (identity.py:611-632) xuất:
- `ledger`: list `[dict(value) for value in self.ledger]` (identity.py:629) — tích lũy.
- `corroboration`: dict (identity.py:630).
- `pending_strategies`, `imprints`, `active_motives`, `active_defenses`: list.
- `last_updated_at`: timestamp.

### (b) Consumer thực khi Root sinh move

Đường Root: `agent.py` → `self._root_session.ask(...)`
(`src/runtime/conversation/agent.py:295-301`). Trong `ask`:
- Self prefix (full `mind_state`) nằm ở `bootstrap_content(...)`
  — root_session.py:360-362 + root_session_projector.py:83-88.
- Hướng dẫn đọc Self: `SELF_BOOTSTRAP_INSTRUCTION`
  — root_session_projector.py:19-40. Nó yêu cầu đọc **belief trái chiều / giá trị
  yếu / stance**; KHÔNG nhắc đến trajectory/ledger/streaks/day_usage/timestamp.
- System prompt `ROOT_SYSTEM_CORE` — root_prompt_contract.py:5 dòng 76-95: yêu cầu
  "Personality context, relationship state và live affect PHẢI ảnh hưởng…",
  "Belief, giá trị và self-model… là các lập trường CÓ THỂ SAI". → consumer thực
  của **personality / relationship / affect / belief / value / self-model**.

**Quan trọng:** ở đường Root session, các bản tóm tắt digest
(`personality_context`, `personality_summary`, `relationship_context`) bị **POP bỏ**
khỏi runtime_context — root_session.py:383-385. Nghĩa là Root KHÔNG nhận bản digest
`prompt_summary()`; nó chỉ nhận `mind_state` thô. Vì vậy personality/identity/
relationship/appraisal thô trong mind_state THỰC SỰ là surface consumer của Root.

Nhưng **không có instruction/consumer nào trỏ tới** `trajectory`,
`consolidation_ledger`, `corroboration_records`, `streaks`, `day_usage`,
`corroboration`, `identity.ledger`, `*_at`, `version`, `schema`. `prompt_context()`/
`prompt_summary()` (contracts.py:571-595; identity.py:637+; personality.py:666+)
chứng minh bản digest KHÔNG bao giờ dùng các field này — chúng chỉ phục vụ
reducer/panel/debug/persistence.

### (c) Phân loại từng khối

| Khối | Phân loại | Lý do (consumer) |
|---|---|---|
| personality.core / temperament / mood / *_anchor / *_baseline | **CẦN** | ROOT_SYSTEM_CORE yêu cầu personality/affect lái intent |
| identity.values / beliefs / motives / defenses / emergent_values / relationships / active_conflict / latest_value_choice | **CẦN** | ROOT_SYSTEM_CORE + SELF_BOOTSTRAP_INSTRUCTION yêu cầu đọc belief/value |
| relationship, appraisal | **CẦN** | ROOT_SYSTEM_CORE "relationship state PHẢI ảnh hưởng" |
| latest_intention, open_loops, goal_records | **CẦN** | continuity; goal_records là goal user hỏi (message #5) |
| **personality.trajectory** | **THỪA** | không instruction/digest nào đọc; cap 96 record → phình chính |
| **personality.consolidation_ledger** | **THỪA** | audit consolidation; digest không đọc |
| **personality.corroboration_records / corroboration / streaks / day_usage** | **THỪA** | counter/book-keeping; digest không đọc |
| **identity.ledger / identity.corroboration** | **THỪA** | audit ghi state; không có consumer prompt |
| **version / schema / last_applied_turn_seq / updated_at / last_*_at** | **THỪA** | định danh/telemetry; không lái câu |
| personality.pending_strategies / imprints; memory_candidates | **CHƯA XÁC MINH** | chưa truy được consumer prompt rõ ràng; không khẳng định thừa |

### (d) Vì sao mind_state TĂNG 7182→10732, có trần không

- Tăng do `trajectory` (nạp tới 96 record — personality.py:548-552),
  `corroboration_records` (16/ key), `consolidation_ledger` (24),
  `streaks`/`day_usage`/`corroboration` lớn dần theo lượt. **Có trần** (cap `[-N:]`),
  nhưng trần cao: trajectory 96 record đủ thêm vài KB. Phiên 9 phút chưa chạm trần
  trajectory → **chưa đo được đỉnh thật trên phiên dài** (CHƯA XÁC MINH mức bão hòa).
- `internal_state` (5828) ở snapshot đầu rồi biến mất: **đã xác minh** —
  `project_self_view` xóa `memory.internal_state` khi nó TRÙNG
  `active_state.metadata.internal_state` (self_prompt_view.py:302-304), và riêng
  `ai_orchestrated_state` được rút gọn thành `persisted_mind_variants` = phần KHÁC
  so với mind_state (self_prompt_view.py:316-324). Vậy internal_state biến mất là do
  **dedup trùng**, không phải gộp vào mind_state. Nó KHÔNG giải thích mind_state tăng;
  mind_state tăng là do trajectory/ledger/counter tích lũy như trên.
- internal_state ↔ mind_state trùng affect/mood: đã có cơ chế dedup (pop khi trùng)
  → không còn trùng lặp lớn trên prefix hiện tại.

### (e) Ước cắt

Cắt toàn bộ nhóm THỪA (trajectory, consolidation_ledger, corroboration_records,
corroboration, streaks, day_usage, identity.ledger/corroboration, các timestamp,
version/schema) khỏi **projection Root** (giữ nguyên store): ước **~3.500–6.000 ký tự**
và quan trọng hơn là **chặn phình theo phiên** (trajectory là biến tăng chính).
Cách làm an toàn: thêm một compact view cho mind_state giống mẫu
`compact_agent_mind`/`compact_active_state` đã có (self_prompt_view.py:118-205),
chỉ cắt ở transport, store vẫn giữ. (Chỉ khuyến nghị — KHÔNG triển khai.)

---

## (2) message history projection cuối (~37k)

### (a) Nó gồm gì — chính xác

`message_chars[-1]` = phần tử cuối của `project_root_messages`
(root_session_projector.py:93-128). Phần tử cuối (dòng 123-126) =
`json.dumps(state.current_step_payload)`.

`current_step_payload` được dựng trong `ask` — root_session.py:386-394:
```
state.current_step_payload = { ... payload trừ các key history/runtime_context ... }
current_step_payload["runtime_context"] = current_ctx            # đã xử lý
current_step_payload["self_changes_since_bootstrap"] = self_delta
current_step_payload["self_base_fingerprint"] = fingerprint
```
`payload` gốc từ `agent._payload` (agent.py:664-690): gồm `step_index`, `event`
(**user turn text, cap 32.000 ký tự** — agent.py:669), `conversation_note`,
`runtime_context` (_bounded_context), `tool_results`.

Nhưng trong `ask` các key sau bị **loại khỏi** current_step_payload
(root_session.py:388-392): `recent_public_history`,
`recent_public_history_delta`, `recent_public_history_reconcile`,
`recent_public_delivery_updates`, và `runtime_context` gốc (được thay bằng bản xử lý).
Lịch sử hội thoại đi qua **message window** (các message role user/assistant ở giữa),
KHÔNG nằm trong message cuối.

`runtime_context` (current_ctx) chứa gì: whitelist `_bounded_context`
(agent.py:748-776) — `grounding_context`, `conversation_status`,
`private_cognition_context`, `discourse_context`, `background_proposals`,
`affective_voice_state`, `open_loop_hints`, v.v. Trong `ask` còn **pop bỏ**
`personality_context/personality_summary/relationship_context/previous_public_excerpt/memory_context`
(root_session.py:383-385).

### (b) Nó CÓ lặp lại Self prefix không? — ĐÃ XÁC MINH: KHÔNG

- Self prefix (`message_chars[1]` ~38k) = `bootstrap_content(self_ref.content_json)`
  (root_session_projector.py:100-102) = full Self, **cố định trong phiên**.
- Message cuối gửi **delta** `self_changes_since_bootstrap`
  (`_changed(bootstrap_snapshot, self_now)` — root_session.py:378), KHÔNG phải full Self.
  `state_difference` (self_prompt_view.py:22-35) chỉ trả phần KHÁC so với bootstrap.

→ **Giả thuyết trong brief ("~37k lặp lại gần toàn bộ Self 38k mỗi lượt") bị
đính chính.** Message cuối KHÔNG tái gửi Self. ~37k đó là nội dung current-turn
THẬT: chủ yếu `event.text` (user turn tới 32k) + `grounding_context` +
`runtime_context` còn lại + `self_delta`.

Vì sao nó xấp xỉ 38k: trong phiên đo, `event.text`/grounding lớn (user dán/âm thanh,
grounding vision) là phần chi phối, cộng self_delta tăng dần theo phiên (delta lớn lên
đúng vì trajectory/ledger của mind_state tích lũy — liên đới phần (1)).

### (c) History window có dồn tích không, có trần không

`ERIS_ROOT_SESSION_WINDOW_PAIRS=12` → `project_root_messages` giữ tối đa `2*K=24`
turn thô gần nhất (root_session_projector.py:107,117-121). Turn cũ hơn bị bỏ, chỉ còn
1 dòng system "<đã có N lượt trước>" (dòng 108-113). → **CÓ trần cứng 24 turn**, không
dồn tích vô hạn. Turn giữ nguyên văn `turn.content` (dòng 118), nhưng số lượng có trần,
nên history window KHÔNG phình theo số lượt.

### (d) Phân loại

| Khối trong message cuối | Phân loại | Lý do |
|---|---|---|
| `event` (user turn text) | **CẦN** | là input hiện tại Root phải trả lời |
| `runtime_context.grounding_context` | **CẦN** | grounding step 5 cố ý giữ (self_prompt_view.py:283) |
| `conversation_status` (đã dedup latest_observation) | **CẦN** | dedup với mind_state đã làm (self_prompt_view.py:327-331) |
| `self_changes_since_bootstrap` | **CẦN** (nhưng sẽ NHỎ lại nếu cắt telemetry ở (1)) | overlay cập nhật Self |
| `self_base_fingerprint`, `step_index` | **CẦN** (nhỏ) | contract overlay |
| phần self_delta sinh từ trajectory/ledger | **THỪA GIÁN TIẾP** | nếu (1) cắt telemetry, delta cũng co lại |

### (e) Ước cắt

Trực tiếp ở message cuối: **nhỏ** (phần lớn là content current-turn cần thiết).
Gián tiếp: nếu cắt telemetry ở phần (1), `self_changes_since_bootstrap` co lại theo
(delta hiện phản ánh trajectory/counter thay đổi mỗi lượt). Đây là lý do nên ưu tiên (1).

---

## (3) living_user.profile (9.568)

### (a) Gồm field gì sau compact_profile

`compact_profile` — `src/runtime/conversation/self_prompt_view.py:58-98`. Nó:
- **Giữ** mỗi record: `path`, `value`, và các qualifier nhẹ:
  `explicitness`, `scope`, `status`, `sensitivity`, `cardinality`, `recurrence`,
  `tier`, `source`, `value_type`, `confidence`, `valid_until`, `expires_at`, `id`
  (self_prompt_view.py:76-89 liệt kê các key được factor thành `defaults`; các field
  khác giữ nguyên trên record).
- **Factor** các qualifier trùng nhau ra `defaults` (dòng 76-90) — tiết kiệm khi nhiều
  record cùng giá trị.
- **Cắt** (`_PROFILE_AUDIT_FIELDS`, dòng 49-52): `evidence_ids`, `metadata`,
  `created_at`, `updated_at`, `last_confirmed_at`, `valid_from`.

→ 9.568 ký tự còn lại = ~11 record × (path + value dài + loạt qualifier kỹ thuật).
Value tự do (ví dụ mô tả dài) + các qualifier `id`/`value_type`/`cardinality`/
`recurrence`/`tier`/`source` là phần còn chiếm chỗ.

### (b) Consumer thực

SELF_BOOTSTRAP_INSTRUCTION nói về profile: "Profile projection dùng defaults cho field
vắng… provenance nặng có thể chỉ nằm ở store, không coi thiếu evidence trong prompt là
xác nhận fact" (root_session_projector.py:35-37). ROOT_SYSTEM_CORE không liệt kê field
profile cụ thể nào. → Consumer thực đọc **path + value** (Eris biết gì về user) và
`status`/`confidence`/`explicitness` (độ chắc/để không coi là fact). Không có instruction
nào trỏ tới `id`, `value_type`, `cardinality`, `recurrence`, `tier`, `source`.

### (c) Phân loại từng field còn giữ

| Field | Phân loại | Lý do |
|---|---|---|
| `path`, `value` | **CẦN** | nội dung Eris biết về user |
| `status`, `confidence`, `explicitness` | **CẦN** | để Root không nâng guess thành fact (đúng tinh thần instruction) |
| `scope` | **CHƯA XÁC MINH** | có thể phân biệt project/global; chưa thấy consumer prompt đọc |
| `sensitivity` | **CHƯA XÁC MINH** | có thể liên quan redaction downstream, không chắc Root dùng |
| `id` | **THỪA** | định danh kỹ thuật; không lái câu |
| `value_type` | **THỪA** | kiểu dữ liệu nội bộ; không lái câu |
| `cardinality` | **THỪA** | single/multi — book-keeping; không lái câu |
| `recurrence` | **THỪA** | lịch lặp nội bộ; không lái câu |
| `tier` | **THỪA** (nhiều khả năng) | phân hạng lưu trữ; chưa thấy consumer prompt |
| `source` | **THỪA** | provenance; instruction đã nói provenance có thể chỉ ở store |

### (d) Ước cắt

Cắt `id`, `value_type`, `cardinality`, `recurrence`, `tier`, `source` khỏi projection
(đa số đã được factor thành defaults nên tiết kiệm phần lặp): ước **~1.500–2.500 ký tự**.
Rủi ro: thấp cho id/value_type/cardinality/recurrence; `scope`/`sensitivity` nên GIỮ cho
đến khi truy được chúng không ảnh hưởng redaction/scope downstream (CHƯA XÁC MINH).

---

## (4) Xếp hạng: thừa cắt được nhiều nhất, rủi ro thấp nhất

1. **mind_state telemetry/history** — cắt ~3,5k–6k, **rủi ro thấp nhất**, và là thứ
   DUY NHẤT trong ba phần đang **phình theo phiên**. Không consumer prompt nào đọc
   trajectory/ledger/counter/timestamp. **Ưu tiên cao nhất.**
2. **living_user.profile qualifier kỹ thuật** (id/value_type/cardinality/recurrence/
   tier/source) — cắt ~1,5k–2,5k, rủi ro thấp cho phần lớn field, giữ scope/sensitivity.
3. **message cuối ~37k** — KHÔNG phải khối trùng Self; dư địa trực tiếp nhỏ. Lợi ích
   gián tiếp đến từ (1) làm self_delta co lại. **Không phải nơi cắt lớn như brief nghĩ.**

---

## (5) Những điểm CHƯA XÁC MINH (ghi rõ theo AGENTS.md)

1. **Đỉnh thật của mind_state trên phiên dài**: trajectory cap 96 record chưa chạm trần
   trong phiên 9 phút; chưa đo mức bão hòa.
2. **memory_candidates, personality.pending_strategies, identity.imprints**: chưa truy
   được consumer prompt rõ → để "chưa xác minh", không khẳng định thừa.
3. **profile.scope / profile.sensitivity**: chưa truy được có lái redaction/scope hay
   không ở đường Root → giữ, chưa kết luận.
4. **Số record profile chính xác (ước 11)**: đọc từ report cũ, chưa đếm trực tiếp trên
   store live trong lần này.
5. Đây là đối chiếu SOURCE checkout chính; chưa chứng minh bản portable
   `Documents/eris/Eris.exe` đã nhận đúng các projection này (các compact_* khác thì
   report live cho thấy đã khớp — xem live-self-log-readout.md mục (e)).

## Khuyến nghị (KHÔNG triển khai)

- Thêm `compact_mind_state(...)` trong `self_prompt_view.py` theo đúng mẫu
  `compact_agent_mind`/`compact_active_state` (cùng file, dòng 118-205): cắt
  trajectory/consolidation_ledger/corroboration_records/corroboration/streaks/day_usage/
  identity.ledger/các `*_at`/version ở TRANSPORT; store giữ qua to_dict(). Idempotent
  qua projection marker để `state_difference` không thấy phantom delta.
- Mở rộng `_PROFILE_AUDIT_FIELDS` để cắt thêm `id`/`value_type`/`cardinality`/
  `recurrence`/`tier`/`source` (giữ scope/sensitivity cho tới khi xác minh downstream).
- Giữ nguyên message cuối; ưu tiên (1) để gián tiếp giảm self_delta.
