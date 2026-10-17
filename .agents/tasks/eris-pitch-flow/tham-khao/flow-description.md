# Mô tả luồng hoạt động Eris (dùng cho slide pitch ý tưởng)

Tài liệu mô tả **hệ thống làm gì và luồng chạy ra sao**, bằng ngôn ngữ trung
tính (hệ thống "nhận", "chọn", "chạy"), không phán xét "đã chạy / chưa chạy /
sẽ làm" và không nói thời gian. Mọi mô tả đều trích tên file / class / hàm thật
trong `c:\Users\Gtvkun\Documents\GitHub\eris\src` làm bằng chứng cho lập luận
khả thi.

---

## 0. Tóm tắt một dòng cho giám khảo

Eris là một **agent hội thoại nhiều bước** trong đó một "bộ não điều hành" duy
nhất (RootAgent) quyết định *ý định của lượt*, rồi mới giao cho lớp diễn đạt
(Writer) → phát (Delivery) → tổng hợp giọng (TTS). Kiến trúc tách bạch **quyền
quyết định** khỏi **quyền diễn đạt**, và cắm năng lực chuyên môn qua một
**Capability Registry** có biên nhận (receipt). Chính biên nhận + registry +
memory là các điểm móc để một **Tutor Core** (dạy học) nối vào mà không phải
viết lại lõi hội thoại — và trên thực tế lõi Tutor đã hiện diện dưới dạng các
module `runtime/tutor` và `runtime/learning_core`.

---

## 1. LUỒNG SỰ KIỆN → QUYẾT ĐỊNH

### Sơ đồ bước

```
Event (user_turn | continuation_due | autonomous_signal | reminder_due)
  -> ConversationKernel.handle_event()          # chốt lifecycle, generation, run_id
  -> ConversationKernel._handle_event_once()    # giành quyền run, kiểm preempt
  -> RootAgent.decide()  == RuntimeModelRootAgent.decide()
       vòng lặp tối đa max_root_steps bước, mỗi bước là MỘT action JSON nhỏ:
         no_reply | move | use_capability | recall_memory
         | continue_thinking | set_note/clear_note | batch
  -> trả về ConversationDecision = NoReply | NextConversationMove
  -> Kernel chuyển move sang Writer -> Delivery -> TTS
```

### Giải thích từng bước (kèm bằng chứng)

**a. Event vào hệ thống qua Kernel.**
`ConversationKernel.handle_event()` (file `src/runtime/conversation/kernel.py`)
là chủ sở hữu lifecycle/đồng thời, **không** phải người lập kế hoạch hội thoại.
Nó khử trùng lặp event theo `event_id` (`_events_inflight`, `_event_results`),
rồi gọi `_handle_event_once()`.

**b. Phân biệt loại event và quyền chiếm "run".**
Trong `_handle_event_once()`:
- `user_turn`: tăng `generation` NGAY (`store.mutate(... generation+1 ...)`),
  hủy continuation đang chờ (`continuation.cancel_session`) và loại các bản
  phát cũ (`_discard_session_deliveries`). Việc tăng generation trước làm mọi
  callback TTS của lượt cũ bị vô hiệu.
- Event nền (`continuation_due`, autonomous…): nếu phiên đang bận
  (`RunPhase.THINKING/WORKING/WRITING/DELIVERING`) thì trả `status="busy"` —
  tín hiệu nền **không** chiếm quyền của một lượt user đang xử lý
  (hàm nội bộ `claim_idle_run`).
- Có cơ chế ngắt mạch nền: `_background_failure_cooldown` chặn chạy Root/Writer
  theo timer khi hai move nền liên tiếp lỗi trong 90s.

**c. Kernel trao context cơ học cho Root, kèm cổng kiểm preempt.**
`agent_context["__root_run_active"]` là callback `root_run_active()` kiểm tra
`generation` + `active_run_id` còn khớp không. Root dùng cổng này để dừng giữa
chừng khi user chen vào (trả `NoReply(reason="root_turn_preempted")`).

**d. Vòng lặp đa bước của Root.**
`RuntimeModelRootAgent.decide()` (file `src/runtime/conversation/agent.py`) lặp
`for step_index in range(self.max_root_steps)` (trần cứng clamp 2..12). Mỗi bước
model trả **đúng một** action theo `ROOT_STEP_SCHEMA`:
- `move` / `no_reply`: finalize. `move` được finalize **trực tiếp**, không chạy
  vòng self-verify thứ hai (chú thích trong code: tránh làm phẳng personality;
  anti-fabrication do `claim_manifest` + grounding gate + Writer lo).
- `use_capability` (`capability ∈ {tutor, work, research, action}`): gọi năng
  lực chuyên môn (xem mục 3).
- `recall_memory`: truy xuất ký ức theo yêu cầu của chính Root (xem mục 5).
- `continue_thinking`: vòng Root→Root nội bộ, giới hạn 2 lần
  (`reflection_state["count"] > 2`), **không** sinh lời public.
- `set_note` / `clear_note`: ghi/xóa working-note qua `ConversationNoteTools`.
- `batch`: 1..4 action nội bộ độc lập chạy một lượt rồi quan sát chung (chỉ ở
  nhánh one-shot fallback dùng `ROOT_BATCH_STEP_SCHEMA`).

**e. Continuation sau receipt.**
Mỗi action non-finalize trả về một `tool_result` được nối vào `tool_results`
và đưa lại cho model bước kế tiếp (`_payload(... tool_results=...)`). Sau khi
finalize `move`, nếu `after=may_continue|continue_self`, kernel lập lịch
continuation qua `ContinuationLeaseScheduler`; event `continuation_due` quay lại
chính `handle_event` ở lượt sau. Cơ chế chống loop vô ích: hàm
`_advance_progress_and_maybe_finalize` đếm "không tiến triển"
(`_NON_PROGRESS_STATUSES`) và cắt sớm khi streak ≥ 2.

**f. Fail-soft.**
Khi model lỗi hoặc không khả dụng, `_degraded()` dùng `DeterministicRootAgent`
để vẫn trả lời trực tiếp lượt user theo hợp đồng tối thiểu.

> Lưu ý về `root_session.py` (file đang mở): đây là **cache vận chuyển + hội
> thoại** của Root với gateway DeepSeek (`RootConversationSession`,
> `_read_self`, `_ingest_recent_turns`, `project_root_messages`). Nó nạp "Self"
> một lần rồi gửi *delta* mỗi bước, giữ receipt theo `delivery_id` làm nguồn sự
> thật. Nó là **lớp dưới** của `RuntimeModelRootAgent.decide()` (gọi qua
> `self._root_session.ask(...)`), không phải nơi ra quyết định hội thoại.

---

## 2. LANE / MODEL ROUTING

### Sơ đồ bước

```
Domain module gọi router.invoke_structured_worker(client, ..., cognitive_lane=...)
  -> ModelRouter._client_inference_profile(client)   # suy ra backend + resource_class
  -> ModelRouter._run_inference(tier, func, reason=, cognitive_lane=)
       phân lane broker theo VAI TRÒ NHẬN THỨC (cognitive_lane) trước, tier legacy sau
  -> inference_context(lane, optional=?, timeout=?) + budget_policy.run_queued(...)
```

### Giải thích (kèm bằng chứng)

File `src/runtime/ai_orchestrated/model_router.py`. Code tách rõ ba khái niệm
(chú thích ngay trong `_client_inference_profile`):
- `cognitive_lane`: *request đang làm việc gì* (vd `root_conversation`,
  `turn_executive`, `tutor:*`, `public_claim_verifier`).
- `backend`: transport/provider (vd `ds2api_deepseek_web`,
  `openai_compatible_remote`).
- `resource_class`: có chiếm VRAM cục bộ không (`remote_api`, `local_light`…).

**Chọn lane trong `_run_inference`** (ưu tiên vai trò nhận thức, không theo tên
model):
- `cognitive_lane == "public_claim_verifier"` → lane `public_claim_verifier`
  (bắt buộc, không deadline — chờ DeepSeek suy luận lâu vẫn không bị loại).
- `cognitive_lane ∈ {turn_executive, root_conversation}` hoặc bắt đầu bằng
  `tutor:` → lane `chat_tool_required` (bắt buộc, không rơi xuống nền). Chú
  thích nêu rõ: trước đây các lane này bị tụt xuống `post_observer` vì
  `inference_tier=subconscious_4b` nên bị coi là optional/preemptible → gây
  writer nhận UNKNOWN và Eris im lặng; hotfix giữ chúng ở lane bắt buộc.
- `public_reply` (không autonomous) → `chat_main`.
- `neuro_continuation`, `neuro_deliberation`, `capability_deliberation[_required]`,
  `post_observer`, `autonomous`, `tutor_background`, `transport` → các lane phụ.

**Optional/preemptible**: tập `optional = {post_observer, autonomous,
tutor_background, neuro_continuation, neuro_deliberation,
capability_deliberation}`. Lane foreground (chat) không nằm trong tập này nên
không bị cắt bỏ khi tài nguyên eo hẹp.

**Client theo vai trò** (file `src/llm/service.py` + property trong
`model_router.py`): `executive_client`, `surface_client`, `deep_client`
(trỏ `social_critic_client`), `seed_client`, `research_client`, `tutor_client`,
`curator_client`… Root chọn client theo thứ tự ưu tiên trong
`RuntimeModelRootAgent.decide()`:
`executive_client → deep_client → seed_client → surface_client →
llm_service.client`.

**Quan trọng cho lập luận trung tính**: nhiều lane có thể dùng *cùng* một model;
`inference_tier` chỉ còn là nhãn tương thích cũ. Routing là theo *vai trò* chứ
không theo tên model.

---

## 3. CAPABILITY REGISTRY (điểm cắm Tutor)

### Sơ đồ bước

```
orchestrator._... xây RootCapabilityRegistry({tutor, work, research, action})
  -> đặt vào runtime_context["__root_capabilities"]
  -> Root chọn use_capability -> RuntimeModelRootAgent._invoke_capability()
       -> capability.invoke_for_root(arguments, event, recent_history)
       -> registry.record_result(...) tạo CapabilityResultReceipt
  -> Root nhận {kind: capability_result, receipt_ref, result}
  -> (sau khi phát xong) Delivery settle -> capability.observe_delivery_receipt()
```

### Giải thích (kèm bằng chứng)

**Đăng ký.** File `src/runtime/ai_orchestrated/orchestrator.py` dựng registry:
```python
capability_registry = RootCapabilityRegistry({
    "tutor":   tutor_capability,     # TutorCapability(host.tutor_executive)
    "work":    work_capability,
    "research":research_capability,
    "action":  action_capability,
})
runtime_context["__root_capabilities"] = capability_registry
```
`RootCapabilityRegistry` (file `src/runtime/conversation/context.py`) chỉ là
**dependency container** — không tự route theo keyword, không tự gọi tutor mỗi
lượt. Bình luận trong code nhấn mạnh: small-talk không được chạy domain planner
ngầm; **chỉ Root** quyết có gọi capability hay không.

**Gọi (foreground vs background).** `RuntimeModelRootAgent._invoke_capability()`
(file `agent.py`) lấy `capability = registry.get(name)` rồi gọi
`capability.invoke_for_root(arguments=..., event=..., recent_history=...)`.
Mỗi capability triển khai một method **data-only** `invoke_for_root` trả về
`Mapping` structured (không phát public text). Với năng lực chạy nền (vd
`research` bắt đầu một job), kết quả hoàn tất quay về Root ở lượt sau qua
`*_result` — Root phân biệt `started/queued` với `completed` (system prompt nêu
rõ: chỉ được nói "đã thực thi" khi capability result xác nhận `success/evidence`).

**Receipt / chống bịa.** Sau khi executor trả về,
`registry.record_result(name, invocation_id, event, run_id, result)` tạo
`CapabilityResultReceipt` (frozen, gắn `event_id/session_id/generation/run_id`,
không cho ghi đè cùng `invocation_id`). Root đọc lại qua
`result_receipts_for(event_id, run_id, generation)`, và `tool_result` kèm
`receipt_ref="capability:<invocation_id>"`. Dedup: fingerprint
`"cap:<name>:<args>"` trong `prior_actions` chặn gọi lại cùng tham số trong một
event.

**Đóng vòng receipt sau phát.** File
`src/runtime/public_output_runtime.py`: khi delivery được settle, hệ thống dựng
`DeliveryReceipt` rồi fan-out tới đúng capability của lượt đó:
`capability.observe_delivery_receipt(receipt)`. `TutorCapability`
(file `src/runtime/capabilities/tutor.py`) chuyển tiếp thành
`executive.commit_delivery(self._last_decision, successful=receipt.successful)`
— giữ invariant "định nói ≠ đã dạy".

---

## 4. WRITER → DELIVERY → TTS

### Sơ đồ bước

```
NextConversationMove (intent/say/delivery/after) do Root chốt
  -> Kernel tạo KernelTurn (cấp delivery_id trước) -> _move_outcome('preparing')
  -> ConversationWriter.realize(turn, event, recent_history, runtime_context)
       == RuntimeWriterAdapter  (runtime_writer.py)
       -> gọi surface writer (lane surface) để diễn đạt move thành câu
       -> _prelocalize_v03_speech(): chốt transcript TTS tiếng Nhật TRƯỚC prepare
       -> prepare/guards: grounding, action-claim, ngôn ngữ, single-speaker
       -> RenderedConversationMove(surface=SurfaceEnvelope{display_text, speech_text, language})
  -> Kernel.mark_delivery_started() (kiểm preempt) -> delivery.deliver(turn, rendered, delivery_id)
  -> Transport/Stage -> TTSBroker.synthesize(chunk_id, text, prosody_hint) -> audio
  -> settle_delivery_id(successful/cancelled) -> MoveOutcomeLedger + fan-out receipt
```

### Giải thích (kèm bằng chứng)

**a. Root chốt move, Kernel cấp identity.**
`KernelTurn` (file `kernel.py`) gắn `session_id/generation/run_id/move` và cấp
**`delivery_id` trước** khi gọi Writer, để receipt và TTS dùng một identity bất
biến. Kernel ghi outcome `preparing` qua `MoveOutcomeLedger` (file
`move_outcomes.py`).

**b. Writer diễn đạt (không quyết nội dung).**
Port `ConversationWriter.realize()` (file `writer.py`) trả
`RenderedConversationMove` chứa `SurfaceEnvelope` (file `delivery.py`) tách
**`display_text`** (kênh hiển thị) khỏi **`speech_text`** (kênh TTS). Adapter
thật là `runtime_writer.py`. Hàm `_prelocalize_v03_speech()` chốt bản TTS tiếng
Nhật **trước** prepare/verify: ưu tiên `speech.text`, nếu rỗng fallback sang
display; nếu chưa phải chữ Nhật thì gọi `SpeechLocalizer.localize(strict=True)`,
cho **một** retry; cancellation **không** retry (ném
`v03_speech_localization_cancelled`); hết retry dùng filler hiragana
`_V03_SPEECH_JA_FILLER = "えっと…"` để nhánh fallback vẫn có tiếng. Writer cũng
đọc `__root_capabilities` để biết capability nào đã dùng và `__evidence_registry`
cho grounding.

**c. Turn-taking, interrupt/cancel.**
Trước và sau mỗi stage, Kernel kiểm `generation`/`active_run_id` còn khớp
không; nếu user đã chen vào thì ghi outcome `cancelled`
(`reason='stale_after_prepare'` hoặc `PREEMPTED_BEFORE_DELIVERY`) và dừng.
`mark_delivery_started()` là chốt giành quyền phát. Khi có `user_turn` mới,
`_discard_session_deliveries()` hủy bản phát cũ và
`outcomes.cancel_inflight(reason='preempted_by_user')`.

**d. TTS.**
`TTSBroker.synthesize(chunk_id, text, prosody_hint)` (file
`src/runtime/world/tts_broker.py`) trả `TTSReceipt{status, audio_ref,
duration_ms, evidence_refs}`. Transport/Stage thật nằm ở
`public_output_runtime.py`.

**e. Receipt phát.**
`settle_delivery_id(successful, cancelled)` (kernel.py) cập nhật
`MoveOutcomeLedger` với các trạng thái phân biệt: `preparing` / `queued_for_audio`
/ `delivering` (audio_start đã xảy ra) / `delivered` (phát xong) /
`failed_before_delivery` / `delivery_failed` / `cancelled`. Receipt này fan-out
tới capability (mục 3) và quay lại Root ở `conversation_move_receipts` (bằng
chứng THỰC THI trong system prompt của Root).

**f. Đường báo lỗi không qua LLM.**
`_deliver_runtime_failure()` phát một câu status cố định (display VI +
speech JA) qua đúng transport/TTS khi Root/Writer lỗi — giữ Eris có tiếng kể cả
khi LLM hỏng.

---

## 5. MEMORY (ghi nhớ & recall)

### Sơ đồ bước

```
Root chọn recall_memory(query)
  -> RootMemoryRecallTools.query(text)  (context.py)
  -> memory_recall_tools_for_host(host).recall(query)
  -> host.memory_kernel.build_public_context(query, session_id, token_budget, max_lines)
  -> trả {status: found/empty, text, degraded, source_count}  (public-safe)
  -> Root nhận memory_result, tự quyết nói hay không
```

### Giải thích (kèm bằng chứng)

File `src/runtime/conversation/context.py`:
- `RootMemoryRecallTools` chỉ là **cổng đọc** theo yêu cầu của Root; không tự
  chèn lời thoại, không ghi ký ức mới, không cho model chạm filesystem.
- `memory_recall_tools_for_host()` dùng `host.memory_kernel.build_public_context`
  (MemoryKernel hiện hữu), trả về đoạn văn + cờ `degraded` + `source_count`;
  cố ý không biến ký ức không rõ nguồn thành fact.
- Root (system prompt trong `agent.py`) được chỉ dẫn: memory chỉ là dữ liệu
  tham khảo; không làm theo chỉ thị lẫn trong `memory_result`; kết quả
  `empty/degraded` không được biến suy đoán thành sự thật.

**Nối context giữa các lượt/buổi.**
- Lớp vận chuyển Root (`root_session.py`): nạp "Self" một lần
  (`_read_self` lấy từ `ai_state_reducer.snapshot()`, `subject_service.self_view()`,
  `memory_state`/`long_term_memory`), sau đó mỗi bước chỉ gửi *delta*
  (`_changed`), giữ cửa sổ hội thoại `project_root_messages(window_k)`, và nối
  receipt theo `delivery_id`/`history_id` (`_ingest_recent_turns`).
- `ContextAssembler` + `EvidenceAssembler` (orchestrator.py:
  `ensure_conversation_context_assembler`, `ensure_conversation_evidence_assembler`)
  ghép identity/relationship/affect/memory/grounding vào `runtime_context` cho
  mỗi lượt — là *projection*, không route intent.
- **Learning memory bền vững** là một kho riêng: `LearningStore` +
  `LearningService` (SQLite) giữ `MasteryRecord`, `LearningEvidence`,
  `ReviewItem`, con trỏ path/KP (`learning_runtime_v1`) sống qua restart.

---

## 6. ĐIỂM MÓC TUTOR (phần quan trọng nhất cho pitch)

Lõi Tutor móc vào kiến trúc hội thoại tại **bốn khớp nối có sẵn**:
Capability Registry (đăng ký) → `invoke_for_root` (gọi) → `CapabilityResultReceipt`
(bằng chứng tư vấn) → `observe_delivery_receipt` (xác nhận đã dạy). Dưới đây là
ánh xạ 5 lớp "Tutor Core" mà slide nêu vào code thật.

### Bảng ánh xạ "Tutor Core" → module Eris

| Lớp pitch | Khớp vào code Eris | File / symbol |
|---|---|---|
| **LessonSession** | State session-scoped của một buổi dạy: path/KP hiện tại, hypothesis, move gần nhất, câu đã phát, đếm lượt/stall; persist qua `TutorSessionLedger` để resume sau restart | `TutorState`, `TutorExecutive._ensure_session`, `TutorSessionLedger` (`runtime/tutor/contracts.py`, `executive.py`, `session_store.py`) |
| **LearnerModel** | Hồ sơ người học + mức nắm vững bền vững: pace/style/ngôn ngữ, mastery theo từng KP, stage, forgetting-curve; cùng hypothesis mềm về nguyên nhân vướng | `LearnerProfile`, `MasteryRecord` (`runtime/learning_core/contracts.py`); `LearnerHypothesis` (`runtime/tutor/contracts.py`) |
| **EvidenceEvaluator** | Chấm semantic câu trả lời tự do rồi quyết có commit thành bằng chứng học tập không (ngưỡng tin cậy) | `TutorReasoner.assess_response` → `SemanticAssessment`; `TutorExecutive.observe_response` + `_apply_semantic_assessment` (`semantic_commit_confidence`); commit qua `LearningService.commit_evidence` |
| **TeachingStrategy** | Chọn hành động sư phạm kế tiếp trong khung quyền deterministic (probe/explain/counterexample/assessment…), giới hạn số câu, loại tương tác | `TutorGuardrailPolicy.envelope`/`enforce` → `MoveEnvelope`; `TutorReasoner.choose_move` → `TeachingMove` (`runtime/tutor/policy.py`, `contracts.py`) |
| **ReviewPlanner** | Lập lịch ôn tập theo đường quên (spaced repetition SM-2) và chọn bước kế trên learning path | `runtime/learning_core/scheduler.py` (`ReviewScheduler`, `next_review_item`, `due_items`); `runtime/learning_core/policy.py` (`next_step`, `TutorStep`); `LearningService.next_tutor_step` |

### Các điểm cắm cụ thể trong luồng hội thoại

1. **Đăng ký capability** — `orchestrator.py`:
   `RootCapabilityRegistry({"tutor": TutorCapability(host.tutor_executive), ...})`.
   Đây là nơi duy nhất cần bơm `TutorExecutive` vào hội thoại; lõi hội thoại
   không đổi. `TutorExecutive`/`LearningService` được dựng một lần qua
   `build_tutor_runtime()` (`runtime/tutor/composition.py`).

2. **Schema quyết định đã mở sẵn cho tutor** — `agent.py`:
   `ROOT_STEP_SCHEMA` có `use_capability.capability ∈ {tutor, work, research,
   action}`. Root phát `use_capability(capability="tutor", arguments={user_text,
   response_to_previous})` khi *chính nó* nhận thấy cần dạy/đánh giá.

3. **Entry point data-only** — `capabilities/tutor.py`:
   `TutorCapability.invoke_for_root()` → `advise()` →
   `executive.observe_response()` (chấm câu trước) + `executive.plan_next_move()`
   (lập move kế). Trả `TutorAdvice{active, assessment, teaching_move,
   expects_learner_response}` — **không** chứa `expected_answer` (xem
   `TeachingMove.to_writer_dict` cố ý bỏ đáp án).

4. **Receipt tư vấn** — Root nhận `capability_result` kèm `receipt_ref`; dùng
   `teaching_move.instruction_vi`/`question_goal` để soạn `intent`/`say` cho
   move public (Writer diễn đạt, Root vẫn giữ quyền nói).

5. **Đóng vòng "đã dạy"** — `public_output_runtime.py` →
   `TutorCapability.observe_delivery_receipt()` →
   `TutorExecutive.commit_delivery(successful=...)`: chỉ khi câu thực sự phát
   thành công mới `note_taught`/`advance_kp`; đánh giá câu trả lời kế tiếp bám
   đúng `last_delivery_text`. Khi user đổi hướng, `suspend_pending_move()` nhả
   quyền chấm để không chấm nhầm câu lạc đề.

6. **Phân lane riêng cho tutor** — `model_router.py`: `cognitive_lane` bắt đầu
   bằng `tutor:` đi lane bắt buộc `chat_tool_required` khi phục vụ user turn;
   còn công việc nền của tutor đi `tutor_background` (optional/preemptible).

7. **Trí nhớ học tập tách khỏi trí nhớ hội thoại** — `LearningService` là
   **cửa vào duy nhất** để ghi/duyệt sự thật học tập (mastery/evidence/review);
   nó *không* viết public text, *không* gọi TTS, *không* tự bật tutor. Nguyên
   tắc cốt lõi ghi trong `service.py`: **"LLM đề xuất; deterministic kernel
   commit"** — nhờ vậy lõi DeepTutor-derived chỉ là learning kernel bên trong
   Eris, không trở thành một agent thứ hai tranh quyền với Root.

---

## 7. Kết luận cho lập luận khả thi (slide)

- **Tách quyền quyết định / quyền diễn đạt**: Root chốt *ý định*, Writer chỉ
  *diễn đạt*, Delivery/TTS *phát*. Đây là xương sống khiến thêm năng lực mới
  không phải viết lại lõi.
- **Capability Registry + receipt**: một giao diện chuẩn (`invoke_for_root` +
  `CapabilityResultReceipt` + `observe_delivery_receipt`) cho mọi năng lực
  chuyên môn. Tutor chỉ là một capability cắm vào bốn khớp này.
- **Learning kernel deterministic**: mastery/evidence/review/scheduler là
  dữ liệu bền vững có luật rõ ràng (`runtime/learning_core`), tách khỏi phần
  "model đề xuất" (`runtime/tutor`). Lập luận khả thi: mô hình dạy học
  (DeepTutor-derived) đã có cấu trúc dữ liệu và policy để hành vi dạy ổn định,
  không phụ thuộc thiện chí của LLM.
- **Phần cần làm rõ/hoàn thiện khi trình bày** (khuyến nghị, không triển khai
  ở đây): (a) cơ chế *khởi tạo learning path* từ hội thoại (ai gọi
  `register_path`/`activate_path`, và từ nguồn nào) chưa thấy call site trong
  luồng chat — nên mô tả như một bước "nhập curriculum" trong slide; (b) runtime
  reasoner của tutor (`RuntimeTutorReasoner`) chỉ được nối khi router có
  `invoke_structured_worker`, ngược lại dùng `ConservativeTutorReasoner` — slide
  nên nói Tutor hoạt động cả khi có và không có model reasoner.

---

### Phụ lục: file/symbol trích dẫn chính

- `src/runtime/conversation/kernel.py` — `ConversationKernel`, `KernelTurn`,
  `_handle_event_once`, `settle_delivery_id`, `_deliver_runtime_failure`.
- `src/runtime/conversation/agent.py` — `RuntimeModelRootAgent.decide`,
  `ROOT_STEP_SCHEMA`, `_run_single_action`, `_invoke_capability`,
  `_advance_progress_and_maybe_finalize`, `_system_prompt`.
- `src/runtime/conversation/root_session.py` — `RootConversationSession`,
  `_read_self`, `_ingest_recent_turns`, `project_root_messages`.
- `src/runtime/conversation/context.py` — `RootCapabilityRegistry`,
  `CapabilityResultReceipt`, `RootMemoryRecallTools`,
  `memory_recall_tools_for_host`, `ConversationNoteTools`.
- `src/runtime/conversation/writer.py` / `delivery.py` / `runtime_writer.py` —
  `ConversationWriter`, `RenderedConversationMove`, `SurfaceEnvelope`,
  `_prelocalize_v03_speech`.
- `src/runtime/world/tts_broker.py` — `TTSBroker`, `TTSReceipt`.
- `src/runtime/ai_orchestrated/model_router.py` — `_client_inference_profile`,
  `_run_inference`, `invoke_structured_worker`, các property client theo vai trò.
- `src/runtime/ai_orchestrated/orchestrator.py` — nơi dựng
  `RootCapabilityRegistry` và `runtime_context`.
- `src/runtime/public_output_runtime.py` — settle delivery + fan-out receipt
  tới capability.
- `src/runtime/capabilities/tutor.py` — `TutorCapability` (`invoke_for_root`,
  `advise`, `observe_delivery_receipt`).
- `src/runtime/tutor/*` — `TutorExecutive`, `TutorState`, `TeachingMove`,
  `TutorDiagnosis`, `SemanticAssessment`, `TutorGuardrailPolicy`,
  `build_tutor_runtime`.
- `src/runtime/learning_core/*` — `LearningService`, `LearningStore`,
  `MasteryRecord`, `LearningEvidence`, `ReviewItem`, `LearnerProfile`,
  `next_step`/`TutorStep`, `ReviewScheduler`.

_Nội dung được diễn đạt lại để mô tả hệ thống ở dạng thiết kế luồng, phục vụ
slide pitch; mọi trích dẫn bám theo code trong repo._
