# Điều tra kỹ thuật ERIS — Loop, LearnerModel, Evidence, Guardrail

Mục đích: cung cấp **sự thật kỹ thuật có dẫn nguồn** cho bài thuyết trình gia sư AI.
Mọi khẳng định đều kèm đường dẫn file + tên hàm/lớp + trích code ngắn. Chỗ nào code
không nói rõ được đánh dấu ở mục cuối "KHÔNG TÌM THẤY / CHƯA CHẮC".

Phạm vi đã đọc: `docs/knowledge/2026-10-14-eris-runtime-lessons.md`,
`src/runtime/conversation/agent.py`, `src/runtime/tutor/*`,
`src/runtime/learning_core/*`, `src/runtime/capabilities/tutor.py`,
`src/runtime/coordinator.py`, và một file observability thật
`.agents/tasks/eris-20261015-1647-audit/session-observability.jsonl`.

---

## TÓM TẮT NHANH (đọc trước khi viết slide)

1. **Vòng agent loop có thật, nhỏ và có phanh.** Root chọn đúng MỘT action JSON mỗi
   bước trong 7 loại; có trần cứng số bước (`max_root_steps`, clamp 2..12, default 8),
   có cắt sớm khi "không tiến triển" (streak ≥ 2), và giới hạn nghĩ thầm
   (`continue_thinking` tối đa 2 lần). Thiết kế **không** ghi nguồn ReAct/DeepTutor
   trong loop hội thoại — nhóm tự mô tả là "agent loop nhỏ".
2. **Mô hình người học KHÔNG dùng cờ nhị phân "đã hiểu".** Nó là `MasteryRecord`
   với `mastery` và `confidence` liên tục [0,1], cộng `stage`, `attempt/correct_count`,
   `error_codes`, `retrievability` (đường cong quên). Khớp đúng triết lý user yêu cầu:
   "biết nó có bao nhiêu bằng chứng để tin", không phải "biết người học đã hiểu".
3. **Evidence do LLM *đề xuất*, kernel deterministic *chốt*.** Model (reasoner) xuất
   `SemanticAssessment{verdict, confidence,...}`; `TutorExecutive` chỉ commit thành
   `LearningEvidence` khi `verdict != "uncertain"` VÀ `confidence >= 0.68` VÀ delivery
   đã thành công (receipt). Mastery được **tính lại bằng hàm thuần** từ toàn bộ evidence,
   không phải do model tự gán.
4. **Ranh giới "LLM đề xuất / kernel chốt" được viết thành code và docstring.** Writer
   nhận `to_writer_dict()` **cố ý bỏ `expected_answer`**; guardrail ép move về
   `allowed_kinds` theo pha dạy và giới hạn số câu.

**Lưu ý trung thực (bắt buộc để không bịa):** file `session-observability.jsonl` trong
repo là **telemetry** (token, queue, writer metrics) — **KHÔNG chứa** bản ghi
evidence/mastery/verdict. Evidence học tập đi vào **SQLite qua `LearningStore`**, không
phải các JSONL này. Xem mục 3 và mục KHÔNG CHẮC.

---

## CÂU 1 — VÒNG AGENT LOOP (Root loop)

### 1.1 Loop là gì, chọn gì mỗi vòng

Docstring module tự mô tả loop (không viện dẫn ReAct/DeepTutor):
`src/runtime/conversation/agent.py`, đầu file:

```python
"""RootAgent V12: semantic authority duy nhất cho public conversation.
RootAgent hoạt động như một agent loop nhỏ:
    context -> model -> optional capability/note tool -> model -> final decision
...public boundary cuối vẫn luôn là đúng một
``ConversationDecision = NoReply | NextConversationMove``."""
```

Mỗi *iteration* model trả đúng MỘT action theo `ROOT_STEP_SCHEMA` (7 loại, `agent.py`):
- `move` — chốt lời công khai (`intent/say/delivery/after`).
- `no_reply` — im lặng (có `reason`).
- `use_capability` — gọi năng lực domain: `tutor | work | research | action`.
- `recall_memory` — truy hồi ký ức (`query`).
- `continue_thinking` — nghĩ thầm nội bộ (`focus`), KHÔNG phát lời/TTS.
- `set_note` / `clear_note` — ghi/xóa note dùng lại ở lượt sau.

(Nhánh fallback one-shot có thêm `kind="batch"` chạy ≤4 action nội bộ song song —
`ROOT_BATCH_STEP_SCHEMA`; schema chính vẫn giữ 7 oneOf.)

Hai `after` quan trọng cho mạch dạy nhiều lượt: `wait_user`, `may_continue`,
`continue_self` (enum trong `NEXT_MOVE_SCHEMA`).

### 1.2 Điều kiện dừng / phanh

Trần cứng số bước — `RuntimeModelRootAgent.__init__` (`agent.py`):

```python
# max_root_steps là trần CỨNG TUYỆT ĐỐI: clamp 2..12, không bao giờ bỏ.
self.max_root_steps = max(2, min(12, int(max_root_steps or 8)))
```

Docstring class ghi rõ bản chất "circuit breaker tài nguyên, không phải giới hạn văn phong":

```python
"""...``max_root_steps`` là circuit breaker tài nguyên... Nếu model loop sai, runtime
dừng tool loop và dùng degraded root decision; không fallback về planner/social cũ."""
```

Cắt sớm khi KHÔNG tiến triển — `_advance_progress_and_maybe_finalize` (`agent.py`):
đếm streak các bước mà mọi `tool_result` đều vô nghĩa (`duplicate/empty/failed/
limit_reached/unavailable/invalid` hoặc trùng fingerprint bước trước); `stop = streak >= 2`:

```python
stop = streak >= 2
if stop:
    self._log("info", "[root-agent] no_progress streak=%d forcing early finalize", streak)
```

Danh sách status không-tiến-triển: `_NON_PROGRESS_STATUSES = frozenset({"duplicate",
"empty","failed","limit_reached","unavailable","invalid"})`.

Giới hạn nghĩ thầm — `_run_single_action`, nhánh `continue_thinking`:

```python
reflection_state["count"] = reflection_state.get("count", 0) + 1
if reflection_state["count"] > 2:
    return {"kind": "reflection_result", "status": "limit_reached", "next": "finalize"}
```

Phanh preemption (user chen lời) — kiểm `still_active()` đầu mỗi vòng và giữa batch:

```python
if not still_active():
    return NoReply(reason="root_turn_preempted")
```

Dedup: cùng `recall_memory` query hoặc cùng `use_capability` + args trong một event bị
chặn bằng `prior_actions` fingerprint → trả `status="duplicate"`.

### 1.3 Sơ đồ một vòng (từ nhận sự kiện tới chốt)

```
ConversationEvent
   │
   ▼
for step in range(max_root_steps):          # trần cứng 2..12 (default 8)
   │  still_active()? ── no ─► NoReply("root_turn_preempted")
   │  _payload(event, history, note, tool_results)
   │  raw = root_session.ask(ROOT_STEP_SCHEMA)   # hoặc invoke(batch) nếu warm-up
   │  kind?
   │   ├─ no_reply ─────────────► NoReply
   │   ├─ move (hoặc user_turn có intent/say) ─► NextConversationMove  (CHỐT, không self-verify)
   │   ├─ batch  ─► chạy ≤4 action nội bộ ─► cập nhật streak ─► tiếp vòng
   │   └─ recall_memory / use_capability / set_note / clear_note / continue_thinking
   │        └─ _run_single_action → tool_result → cập nhật no_progress_streak
   │             └─ streak ≥ 2 ─► finalize sớm (_no_progress_decision)
   ▼
hết vòng ─► degraded root decision (_degraded)
```

Điểm thiết kế đáng nói cho pitch: sau khi có `move`, Root **finalize trực tiếp, KHÔNG
chạy vòng model thứ hai để tự kiểm** (chú thích trong `agent.py`):

```python
# Finalize TRỰC TIẾP move Root đã chọn — không chạy một vòng model thứ hai (self-verify)
# vốn làm phẳng personality. Anti-fabrication vẫn do claim_manifest + grounding gate +
# enforce_completed_action_claims ở runtime_writer lo, độc lập với self-verify.
```

### 1.4 Nguồn cảm hứng thiết kế

- Loop **hội thoại** (Root): grep `ReAct`/`DeepTutor` trong `agent.py` → **không có**.
  Docstring chỉ tự gọi là "agent loop nhỏ" (xem 1.1). ⇒ không có bằng chứng code rằng
  loop hội thoại trích dẫn ReAct.
- Loop **dạy học** (learning kernel): ghi nguồn rõ. `src/runtime/learning_core/__init__.py`:
  `Nguồn adaptation: HKUDS/DeepTutor @ ef2d9e5c, Apache License 2.0.`
  Các module `contracts.py / mastery.py / grading.py / policy.py` lặp lại "Ported from
  DeepTutor ... (Apache 2.0)". `executive.py` mô tả vòng sư phạm riêng:
  `OBSERVE -> DIAGNOSE -> STRATEGIZE -> TEACHING MOVE -> WAIT -> ASSESS -> LOOP`.

---

## CÂU 2 — MÔ HÌNH HÓA NGƯỜI HỌC (LearnerModel)

Trạng thái người học **không** nằm một chỗ; nó tách làm ba lớp, đúng tinh thần
"evidence → mastery → hypothesis":

### 2.1 `MasteryRecord` — trạng thái nắm vững bền vững (per user, per KP)

`src/runtime/learning_core/contracts.py`, `class MasteryRecord`:

```python
kp_id: str
mastery: float = 0.0            # recency-weighted [0, 1]
confidence: float = 0.0         # confidence cap [0, 1]
stage: str = "unknown"          # unknown|learning|practicing|mastered|retained
attempt_count: int = 0
correct_count: int = 0
last_evidence_at: float = 0.0
next_review_at: float = 0.0
retrievability: float = 1.0     # forgetting curve [0, 1]
error_codes: tuple[str, ...] = ()
```

⇒ **Không có cờ "đã hiểu" nhị phân.** "Nắm vững" là **đại lượng liên tục** `mastery`
cùng `confidence`, `stage`, số lần đúng và các mã lỗi nhận thức.

### 2.2 `LearningEvidence` — một mẩu bằng chứng nguyên tử

Cùng file, `class LearningEvidence`: `evidence_id, kp_id, evidence_type, strength[0..1],
correct, interaction_id, turn_id, recorded_at, error_code, metadata`.
`EVIDENCE_TYPES` gồm: `quiz_correct/incorrect, feynman_pass/fail, application, paraphrase,
self_report, misconception, exposure`.

### 2.3 `LearnerHypothesis` + `TutorDiagnosis` — giả thuyết MỀM (session-scoped)

`src/runtime/tutor/contracts.py`, `class LearnerHypothesis` (docstring):

```python
"""Giả thuyết mềm về nguyên nhân user đang vướng.
Đây KHÔNG phải nhãn lâu dài về con người. Confidence thấp thì tutor phải hỏi
để kiểm tra, không được biến phỏng đoán thành kết luận."""
kind: str          # misconception|missing_prerequisite|fragile_knowledge|...
confidence: float = 0.5
evidence_refs: tuple[str, ...] = ()
status: str = "active"   # active|resolved|rejected
```

`TutorDiagnosis` phân biệt **`understood_points`** và **`uncertain_points`** (hai tuple
riêng) + `confidence` — tức hệ thống mô hình hóa cả "điều đã có bằng chứng hiểu" lẫn
"điều còn mơ hồ", thay vì một phán xét gộp.

### 2.4 Hệ thống suy ra "đã nắm kỹ năng" bằng gì — gate CỨNG

`src/runtime/learning_core/mastery.py`, `gate_passed(...)`:

```python
threshold = MASTERY_THRESHOLDS.get(kp.kp_type, 0.75)
if record.mastery < threshold:
    return False
if kp.kp_type in {"fact", "procedure"}:
    return record.correct_count >= 2          # cần ≥2 lần đúng
return has_feynman_pass                        # concept/design cần giải thích Feynman
```

Ngưỡng theo loại tri thức (`contracts.py`): `fact/procedure = 0.90`, `concept = 0.75`,
`design = 0.70`. ⇒ "đã nắm" = **mastery liên tục vượt ngưỡng VÀ có bằng chứng loại phù hợp**,
không phải model tự tuyên bố.

### 2.5 `LearnerProfile` — sở thích dài hạn

`contracts.py`, `class LearnerProfile`: `preferred_pace, preferred_style,
native_language, goal_description, active_domain`. Docstring ghi "bản sao chính thức nằm
trong living_user"; đây chỉ là snapshot bounded cho policy thuần.

---

## CÂU 3 — ĐƯỜNG ĐI CỦA EVIDENCE (quan trọng nhất)

### 3.1 Evidence sinh ở đâu, do ai đề xuất

Với câu trả lời **tự do** (short answer / Feynman), đánh giá do **LLM reasoner đề xuất**,
KHÔNG tự thành evidence. `src/runtime/tutor/model_reasoner.py`, `assess_response(...)`
gọi structured worker và trả `SemanticAssessment`. System prompt ép dùng `uncertain` khi
thiếu bằng chứng:

```python
"...PASS khi user thể hiện mental model đúng; PARTIAL khi lõi đúng nhưng thiếu một
 dependency quan trọng; FAIL khi có lỗi khái niệm rõ; UNCERTAIN khi evidence không đủ...
 Nếu không chắc, phải dùng uncertain thay vì đoán."
```

`SemanticAssessment` (`tutor/contracts.py`) mang: `verdict ∈ {pass,partial,fail,uncertain}`,
`confidence[0..1]`, `evidence_type`, `strength`, `error_code`, `misconception`.

Với câu **trắc nghiệm/đúng-sai**, evidence sinh **deterministic** (không LLM):
`learning_core/grading.py::grade_choice` so index; `LearningService.resolve_interaction`
dựng thẳng `LearningEvidence(strength=1.0 if correct else 0.0, ...)`.

### 3.2 Confidence gắn ở đâu & ngưỡng chốt

Ngưỡng là `semantic_commit_confidence` — `src/runtime/tutor/executive.py`:

```python
semantic_commit_confidence: float = 0.68,
...
self.semantic_commit_confidence = max(0.50, min(0.95, float(semantic_commit_confidence)))
```

Verdict `uncertain` nằm trong enum `ASSESSMENT_VERDICTS` (`tutor/contracts.py`).

### 3.3 Ai QUYẾT ĐỊNH ghi vào hồ sơ — kernel deterministic, không phải model

Điều kiện commit — `TutorExecutive._apply_semantic_assessment` (`executive.py`):

```python
if assessment.verdict == "uncertain" or assessment.confidence < self.semantic_commit_confidence:
    return False
evidence_type = self._normalized_evidence_type(assessment)
evidence = self.learning.commit_evidence(assessment.kp_id, evidence_type=evidence_type,
    strength=assessment.strength, correct=assessment.correct, ...)
return evidence is not None
```

`_normalized_evidence_type` còn chặn model tạo cặp verdict/evidence mâu thuẫn (vd verdict
`pass` không được map sang `misconception`).

**Điều kiện "đã nói mới được tính là đã dạy"** — `TutorExecutive.commit_delivery`:

```python
"""Commit side-effect chỉ sau khi public delivery thực sự thành công.
Điều này giữ invariant: Eris *định nói* không đồng nghĩa Eris *đã dạy*."""
if not successful:
    return
```

Gọi từ `capabilities/tutor.py::observe_delivery_receipt` với `successful=bool(receipt.successful)`
(một `DeliveryReceipt` thật). Đây chính là cơ chế trả lời phản biện "model tự xác nhận":
side-effect học tập chỉ xảy ra khi có **receipt delivery** + **đủ confidence**, và mastery
được tính lại bằng hàm thuần.

### 3.4 Mastery được tính lại bằng hàm thuần (không do model gán)

`LearningService._commit_evidence_locked` (`service.py`):

```python
if not self._store.append_evidence(evidence):
    return False   # duplicate
all_evidence = self._store.load_evidence(kp_id)
new_record = compute_mastery(kp_id, all_evidence, now=ts, policy=self._mastery_policy)
self._store.save_mastery(new_record, now=ts)
```

`compute_mastery` (`mastery.py`): trọng số theo recency (half-life 1 tuần), cộng dồn theo
`_STRENGTH_MAP`, trừ điểm khi có `misconception`, chặn trần `confidence_cap = 0.95`, rồi gán
`stage`. Docstring class `LearningService` chốt ranh giới:

```python
# NHUNG GI MODULE NAY *KHONG* DUOC QUYET
#  4. Khong tu suy dien user da hieu chi vi Eris vua giai thich xong.
#  5. Khong duoc nhan raw chain-of-thought cua model lam evidence.
# Quy tac cot loi: "LLM de xuat; deterministic kernel commit".
```

### 3.5 Có xuất JSONL evidence không? — CÓ journal, NHƯNG không phải file telemetry này

- grep `.jsonl` trong `src/`: các journal thật là **memory** (`memory_feed_trace.jsonl`,
  `living_user_trace.jsonl` — `src/memory/...`), và các tool đọc `logs/eris_observability*.jsonl`.
- File được brief chỉ tới, `.agents/tasks/eris-20261015-1647-audit/session-observability.jsonl`,
  là **metric telemetry**. Một dòng thật:

```json
{"signal": "gauge", "name": "provider_ready", "timestamp": 1792057650.54,
 "value": 1.0, "tags": {"kind": "action", "provider": "action_executor"},
 "fields": {"event": "bootstrap", "reason": ""},
 "trace_id": "72c896d639a449d08fd7a4da47d52e66", "status": "ok", "_source_line": 494361}
```

Thống kê `name` trong file (top): `rollout_decision_total (54)`, `output_tokens_by_lane (46)`,
`prompt_budget / token_pressure_ratio / prompt_hard_cap (23 mỗi loại)`,
`public_writer_* (6)`, `broker_* (4–8)`, `conversation_run_failed (5)`. Tìm
`evidence|mastery|tutor|verdict` trong file → **0 kết quả**.

⇒ **KHÔNG được nói "evidence học tập nằm trong session-observability.jsonl".** Evidence/mastery
bền vững đi vào **SQLite qua `LearningStore`** (`service.py` gọi `append_evidence/save_mastery`;
`learning_core/store.py` giữ schema). Trường của một evidence record đúng là của
`LearningEvidence.to_dict()` ở mục 2.2.

---

## CÂU 4 — RANH GIỚI "LLM ĐỀ XUẤT / KERNEL CHỐT"

### 4.1 Nguyên tắc viết thành docstring

- `learning_core/service.py` (đã trích ở 3.4): `"LLM de xuat; deterministic kernel commit"`.
- `tutor/contracts.py` đầu file:

```python
"""- Tutor có thể hình thành *giả thuyết* về người học, nhưng giả thuyết không phải sự thật.
   - Mastery/evidence bền vững vẫn thuộc LearningService.
   - Writer chỉ nhận TeachingMove đã được policy giới hạn; không nhận expected_answer.
   - Không lưu chain-of-thought."""
```

- `tutor/model_reasoner.py` đầu file: nếu assessment model fail thì **trả None** —
  "thà không ghi evidence còn hơn chấm bừa".

### 4.2 Guardrail ép đề xuất của model về khung cho phép

`src/runtime/tutor/policy.py`, `class TutorGuardrailPolicy`. Theo pha dạy, `envelope()` trả
`MoveEnvelope(allowed_kinds=..., requires_user_response=..., max_sentences=...)`. Ví dụ pha
`assess`:

```python
if step.kind == "assess":
    return MoveEnvelope(allowed_kinds=("assessment", "guided_practice"),
        requires_user_response=True, max_sentences=2, ...,
        reason="assessment_must_collect_evidence")
```

`enforce()` ép proposal model về contract: kind không hợp lệ bị thay bằng `allowed_kinds[0]`;
câu kiểu Socratic luôn buộc chờ user; số câu bị kẹp `min(move.max_sentences, envelope.max_sentences)`:

```python
kind = move.kind if move.kind in envelope.allowed_kinds else envelope.allowed_kinds[0]
requires_response = envelope.requires_user_response or kind in self._RESPONSE_REQUIRED_KINDS
return replace(move, kind=kind, kp_id=kp_id or move.kp_id,
    interaction_type=envelope.interaction_type, requires_user_response=requires_response,
    max_sentences=min(move.max_sentences, envelope.max_sentences))
```

Phase do **learning policy deterministic** chọn (`learning_core/policy.py::next_step`), reasoner
chỉ được chọn *cách đi trong phase* — prompt `choose_move`: "Không tự ... đổi phase do learning
policy quyết định".

### 4.3 Writer KHÔNG nhận đáp án — bằng chứng code

`src/runtime/tutor/contracts.py`:

- `PendingInteraction` giữ `expected_answer` **chỉ ở server**, và `to_dict()` ghi chú:
  `# expected_answer intentionally omitted from public dict`.
- `TeachingMove.to_writer_dict()`:

```python
def to_writer_dict(self) -> dict[str, Any]:
    """Projection an toàn cho writer; cố ý không có expected_answer."""
    return { "move_id":..., "kind":..., "objective":..., "instruction_vi":...,
             "question_goal":..., "expected_response_shape":..., ... }   # KHÔNG có expected_answer
```

- `TutorDecision.to_writer_context()` chỉ đẩy `move.to_writer_dict()` +
  `delivery_constraints`, không đẩy hypothesis thô hay đáp án ra public.
- Prompt `choose_move` (`model_reasoner.py`): "instruction_vi là chỉ dẫn ngắn cho writer...
  **Không chứa expected answer**."

### 4.4 Tutor chỉ là capability của Root, không phải agent thứ hai

`src/runtime/capabilities/tutor.py` (docstring): adapter "chỉ trả *advice/evidence* cho
RootAgent... **không có API phát public text**... KHÔNG được gọi ở mọi user turn. RootAgent
chỉ invoke nó khi ... cần dạy/đánh giá." Tức đường vào là `use_capability(tutor)` trong
Root loop (Câu 1), giữ Root là "semantic authority duy nhất cho lời public".

---

## KHÔNG TÌM THẤY / CHƯA CHẮC (đừng bịa trong pitch)

1. **Loop hội thoại KHÔNG ghi nguồn ReAct trong code.** grep `ReAct` trong `agent.py` =
   trống. Chỉ learning kernel ghi nguồn DeepTutor (Apache 2.0). Đừng gán "Root loop dựa trên ReAct".
2. **`session-observability.jsonl` KHÔNG chứa evidence/mastery/verdict.** Nó là telemetry.
   Đừng mở file này ra để "chứng minh một dòng evidence". Evidence thật ở SQLite
   (`LearningStore`), schema theo `LearningEvidence.to_dict()`.
3. **Chưa xác minh learning kernel chạy trong phiên chat thật.** `coordinator.py` có build
   `tutor_bundle` và gán `self.learning_service/tutor_executive`, nhưng bọc trong `try/except`
   (fail-soft về None) và chú thích "Chưa giành hot-path delivery của PedagogicalRuntime trong
   bước migration này". Chưa có trace/log nào trong tài liệu điều tra cho thấy một phiên chat
   thực tế đã đi qua `TutorExecutive.observe_response → commit_evidence`. Các run-audit đã đọc
   (mục 8–10 của runtime-lessons) chỉ nói về Root/writer/localization/TTS, **không** nhắc
   mastery/evidence. ⇒ Nói "kiến trúc có cơ chế này" thì ĐÚNG; nói "đã chứng minh chạy trên
   học sinh thật 30 ngày" thì CHƯA có bằng chứng trong repo.
4. **Không có dữ liệu hiệu quả học tập (A/B vs chatbot thường).** Không tìm thấy kết quả
   đo lường learning outcome trong repo. Câu hỏi phản biện của user (30 ngày, so với chatbot)
   hiện **chưa** được repo trả lời bằng số liệu — chỉ có thiết kế cơ chế đo (mastery/review/SRS),
   không có kết quả thực nghiệm.
5. **`correct_count` dùng cho gate `fact/procedure` là tổng tích luỹ, không phải "liên tiếp".**
   `gate_passed` dùng `record.correct_count >= 2` (tích luỹ); còn ngưỡng "liên tiếp" (`consecutive_correct`)
   nằm ở `policy.next_step` bước 7. Đừng trộn hai khái niệm khi vẽ slide.
6. **Giá trị hằng có thể bị caller override.** `semantic_commit_confidence=0.68`,
   `max_root_steps=8`, ngưỡng mastery là *default*; `__init__` cho phép truyền khác (clamp
   0.50–0.95 / 2–12). Nói "ngưỡng mặc định" thay vì "ngưỡng cố định".
7. **Không kiểm runtime live.** Theo AGENTS.md và runtime-lessons: điều tra này là đọc source
   tĩnh; chưa chạy test/live. Không nâng "đọc code" thành "đã chạy".

---

## GỢI Ý CHO NGƯỜI VIẾT PITCH (không phải thay đổi code)

- **Khung kể "triết lý":** bắt đầu từ vòng tuần hoàn ổn định (Câu 1) → cơ chế gác cổng trực
  quan (guardrail envelope + writer không cầm đáp án, Câu 4) → mô hình người học bằng *mức độ
  bằng chứng* chứ không phải cờ hiểu (Câu 2) → đường evidence LLM-đề-xuất / kernel-chốt + ngưỡng
  0.68 + receipt (Câu 3). Đây đúng thứ tự user yêu cầu: "vòng chạy ổn định trước, lỗi là chuyện sau".
- **Trả lời phản biện "model tự khẳng định đúng":** chỉ vào `_apply_semantic_assessment`
  (confidence < 0.68 → bỏ), `compute_mastery` (mastery do hàm thuần tính lại từ evidence),
  `commit_delivery` (chỉ tính là đã dạy khi có receipt). Đó là ba điểm "kernel chốt".
- **Giữ trung thực:** trình bày là **kiến trúc/cơ chế đã có trong code**, và nêu rõ phần
  "chưa có số liệu 30 ngày / chưa xác minh live" như lộ trình cần đo — đúng tinh thần
  "biết mình có bao nhiêu bằng chứng".
