# Trạng thái sống/chết các luồng (lane) phụ của Eris — không phải Root/Writer

Ngày điều tra: 2026-10-17. Phạm vi: **điều tra tĩnh, chỉ đọc source** trong
checkout `c:/Users/Gtvkun/Documents/GitHub/eris`. **KHÔNG chạy live**, không đọc
run log phiên mới, không gọi model. Mọi kết luận về "được gọi khi nào / vai trò
/ model" là đọc từ code, **chưa xác nhận bằng trace runtime thật**. Các worktree
dưới `.worktrees/` bị loại khỏi phạm vi; chỉ xét `src/` chính.

Thuật ngữ trạng thái:
- **ALIVE** = có call site production thật trên code path chạy được (per-turn
  hoặc background daemon được khởi động ở bootstrap), và (nếu là feedback/memory)
  có cả đường ghi lẫn đường đọc lại.
- **DORMANT** = code còn, nhưng config mặc định tắt HOẶC không có caller trên
  code path production (chỉ còn import/định nghĩa), có thể bật lại bằng flag.
- **DEAD/ORPHAN** = còn định nghĩa nhưng không caller production nào, chỉ test
  dùng tới.

---

## Tóm tắt trả lời trước (cho câu hỏi của user)

Các luồng phụ KHÔNG đồng loạt "chết" như một báo cáo cũ ngụ ý, nhưng cũng
KHÔNG phải tất cả đều thật sự tham gia lượt nói. Chia làm ba nhóm:

1. **Sống và có tác động thật (ALIVE):**
   - **Observer (post_turn)** — chạy nền sau mỗi public commit, kết quả ghi vào
     StateReducer và ĐƯỢC đọc lại ở lượt sau (context + prompt_summary).
   - **Seed (random chat reservoir)** — daemon nền sinh premise; premise chảy
     vào `mental_material` của WorldState rồi vào context Root/Writer.
   - **Curator / Living User Memory** — pipeline nền (`TurnMemoryPipeline` +
     `BackgroundMemoryDigestKernelService`) ghi memory, và recall quay lại qua
     `memory_kernel.build_public_context` trong context assembler.
   - **Critic/deep** — có call site production, nhưng là background
     maintenance (`MemoryGCService`), KHÔNG phải phản biện per-turn.

2. **Còn chạy nhưng tác động xuống "lời nói" bị cắt / chỉ cấp state (một phần
   DORMANT):**
   - **Inner (private mind / inner diary)** — daemon chạy nền thật, ghi digest
     ra đĩa, đẩy `active_concerns`/`mental_material` vào context. NHƯNG đường
     `private_mind_speech_bias` được "fix" để sync lại **trỏ tới một renderer
     đã bị xóa** (`_render_private_mind_speech_bias_context` không còn tồn tại),
     và export candidate-speech mặc định bị khóa. Nội tâm ảnh hưởng lượt sau chỉ
     còn gián tiếp qua mental_material/concern, không qua bias nói trực tiếp.

3. **Mồ côi / không nằm trên live chat path (DEAD/ORPHAN hoặc DORMANT):**
   - **Companion routing (chọn Flash/Pro per-turn)** — `route_companion_turn`
     chỉ được **import** trong orchestrator, **không có một call site thật nào**
     trong production (chỉ test gọi). Xác nhận lại kết luận đã đính chính trong
     tài liệu tri thức: policy này KHÔNG điều khiển request trên live chat path.
   - **`BackgroundLivingUserObserverService`** (biến thể "curator per-turn")
     — không có constructor production; đường curator thật đi qua pipeline khác.

Lưu ý phương pháp: nhiều lane dùng CHUNG một model/worker (ví dụ `deep_client`
và `critic_client` cùng trỏ `social_critic_client`; `diary_client` thực chất là
worker `inner`). "Có client trong `LlmService`" không chứng minh lane được gọi.

---

## Bản đồ wiring production (điểm neo)

- **Builder host production:** [`src/vision.py`](../../src/vision.py) dựng
  `LlmService` với các client: `inner_client`, `diary_client` (gate bởi
  `inner_diary_model_enabled()` + `inner_diary_deep_reflection_enabled()`, mặc
  định ON), `seed_client`, `curator_client`, `critic_client`
  (`social_critic`), `observer_client` (`social_parser`), `surface_client`,
  `executive_client`. (`src/experiments/v57_simulation/live_runtime.py` cũng
  dựng tương tự nhưng là **simulation harness**, không phải runtime người dùng.)
- **Router production:** `AIRuntimeModelRouter`
  ([`src/runtime/ai_orchestrated/model_router.py`](../../src/runtime/ai_orchestrated/model_router.py)).
  Các property ánh xạ lane → client:
  `observer_client → llm_service.social_parser_client`;
  `deep_client → llm_service.social_critic_client`;
  `critic_client → social_critic_client or fallback`.
  Tức **critic và deep là cùng một worker vật lý** (`social_critic`).
- **Bootstrap Architecture-C:**
  [`src/runtime/ai_orchestrated/bootstrap.py`](../../src/runtime/ai_orchestrated/bootstrap.py)
  khởi tạo `PostTurnObserver`, `RandomChatSeedReservoir` (`.start()`),
  `ExecutiveCortex`.
- **Bootstrap coordinator:**
  [`src/runtime/coordinator_bootstrap.py`](../../src/runtime/coordinator_bootstrap.py)
  khởi tạo `PrivateMindDaemon` (inner), `InnerDiaryPersister`,
  `MemoryGCService`, `TurnMemoryPipeline` (curator).
- Phân biệt `active_worker_role()` ContextVar với attribute `worker_role`:
  router đọc `getattr(client, "worker_role", ...)` để nhận diện DeepSeek web
  worker (model_router.py dòng ~1292), đây là **attribute trên client**, không
  phải ContextVar; cảnh báo trong tài liệu về việc hai thứ này khác nhau vẫn
  áp dụng khi sửa carve-out thinking, không ảnh hưởng tới kết luận call-site ở đây.

---

## Chi tiết từng lane

### 1. Inner (nội tâm / private mind / inner diary) — **ALIVE (state) nhưng DORMANT (speech bias)**

**Tồn tại?** Có. `PrivateMindDaemon` được dựng ở
[`coordinator_bootstrap.py`](../../src/runtime/coordinator_bootstrap.py) (~dòng 633),
`InnerDiaryPersister` (~dòng 708). Daemon model-lane bọc bởi
`legacy_model_lanes_enabled()` (mặc định **False**, xem
[`architecture_flags.py`](../../src/runtime/architecture_flags.py)), nên worker
model riêng của private mind mặc định KHÔNG bật — fallback về deterministic/Gemma
thought-shards. Inner diary deep-reflection (`diary_client` = worker `inner`) thì
mặc định ON.

**Có call site production không?** Có. `_update_private_mind_state` trong
[`observer_private_runtime.py`](../../src/runtime/observer_private_runtime.py)
chạy daemon theo mô hình single-flight trên tick background observer (không chạy
trong lúc `_chat_processing`). Kết quả `digest` được apply, persist ra
`memory_core/inner_diary.json`.

**Output đi đâu, có đọc lại ở lượt sau không?**
- Digest → `self.private_mind_digest` → panel/debug (`panel_adapter.py`,
  `depth_v2_state.py`). Đây là hiển thị, không phải đường nuôi lượt nói.
- `active_concerns` / `mental_material` → qua WorldState
  (`CognitionWorldState`, [`world_state.py`](../../src/runtime/world_state.py))
  → `_private_cognition_context()` trong
  [`context_assembler.py`](../../src/runtime/conversation/context_assembler.py)
  → vào context Root/Writer dưới nhãn "private semantic artifacts". **Đây là
  đường inner ảnh hưởng lượt sau thật sự còn sống.**
- **Đường `private_mind_speech_bias` bị gãy:** `_sync_private_mind_future_bias`
  ([`observer_private_runtime.py`](../../src/runtime/observer_private_runtime.py) ~dòng 455)
  tự nhận là fix cho bug "#3" (nội tâm không chảy vào câu nói), nối
  `digest['future_bias'].speech_bias` → attribute `private_mind_speech_bias`.
  Nhưng comment dẫn renderer `_render_private_mind_speech_bias_context`, và
  **grep toàn `src/` không còn method đó** (chỉ còn trong chính comment). Người
  đọc duy nhất của `private_mind_speech_bias`/`inquiry_plan`/`thought_pressure`
  là `cortex/private_mind/evidence_dossier.py` — tức **chính package private
  mind tự đọc lại**, không phải context writer public. ⇒ speech-bias vẫn KHÔNG
  tới được lời nói công khai; "fix" nối vào một attribute không có consumer
  public. (Đây là đính chính cho kết luận cũ "đã nối nội tâm vào câu nói".)
- Export candidate speech từ private mind/life bị khóa mặc định:
  `_drain_private_mind_surface_impulses` trả `()` khi
  `private_cognition_surface_export_enabled()` = False (mặc định).

**Dấu hiệu chết?** Không mồ côi, nhưng hai nhánh "nói" (speech_bias context +
surface export) mặc định không dẫn tới đâu. Inner hiện là **nguồn state nền
(concern/material) ALIVE**, còn **ảnh hưởng trực tiếp lên wording là DORMANT**.

### 2. Seed (mầm ý / reservoir đề xuất nền) — **ALIVE**

**Tồn tại?** Có. `RandomChatSeedReservoir` + `RandomChatSeedGenerator`
([`random_chat_seed_service.py`](../../src/runtime/ai_orchestrated/random_chat_seed_service.py)),
dùng `llm_service.seed_client` (worker DeepSeek `seed`).

**Call site production?** Có. Dựng và `.start()` ngay trong
[`bootstrap.py`](../../src/runtime/ai_orchestrated/bootstrap.py) (~dòng 342–362),
gắn `mental_event_sink = host.mental_material_runtime.ingest_seed`. Reservoir
chạy nền trên port/worker riêng, không nằm trên critical path của câu nói
(theo chính docstring module). Cơ chế lease: `claim_seed`/`claim` →
`SeedReservoirLease`, commit/release theo kết quả public. Token lease xuất hiện
trong `social_candidate.py` (`seed_lease_token`).

**Output đi đâu, đọc lại không?** Premise validated → `ingest_seed` →
`MentalMaterialRuntime` → `mental_material` của WorldState → context Root
(mục lane Inner ở trên dùng chung đường này). Root CHỈ xem như private material,
có quyền bỏ qua; seed **không tự có quyền phát lời** (đúng nguyên tắc thiết kế).
Caller `claim_seed` trực tiếp không thấy trong `orchestrator.py` theo grep hẹp
(có thể nằm ở executive/initiative hoặc lớp social_candidate); đây là **giới
hạn chưa truy hết** — nhưng reservoir chắc chắn được start và cấp material.

**Dấu hiệu chết?** Không. `ERIS_RANDOM_CHAT_SEED_RESERVOIR_ENABLED` mặc định
True; enabled phụ thuộc `generator.enabled` (cần `seed_client`). Nếu không có
seed worker thì reservoir tự tắt (fail-soft), không giả chạy.

### 3. Critic / deep — **ALIVE (nhưng là maintenance, không phải phản biện per-turn)**

**Tồn tại?** Có. `critic_client`/`social_critic_client` trong `LlmService`;
router expose `deep_client → social_critic_client`. **Critic và deep dùng chung
một worker `critic`** (process_manager `build_social_critic_client` →
`build_deepseek_worker_client("critic")`).

**Call site production?** Có, nhưng không phải "phản biện câu nói mỗi lượt":
- `MemoryGCService` ([`memory_gc_service.py`](../../src/runtime/memory_gc_service.py))
  dùng `_get_critic_client()` để (a) `_run_semantic_review` rà/drop semantic
  memory, (b) `_run_living_user_review` làm reviewer cho curator living-user.
  Daemon này được start ở `coordinator_bootstrap.py` (~dòng 804), mặc định
  `ERIS_MEMORY_GC_ENABLED=True`, interval ~10 phút, có startup delay.
- Trong router có nhánh observer "deep": `observe_completed_turn` dùng
  `deep_client` khi `deep_enabled and ambiguity>=0.58 and importance>=0.55`
  (model_router.py ~dòng 2628) — tức deep critic có thể được gọi như một
  escalation của observer, không phải lane phản biện độc lập mỗi lượt.

**Output đi đâu?** Quyết định drop/giữ memory (GC) và review living-user → ảnh
hưởng kho nhớ dùng lại ở lượt sau. Có cả đường ghi (commit cleanup) lẫn đọc lại
(recall memory). Observer-deep nuôi StateReducer như observer thường.

**Dấu hiệu chết?** Không mồ côi. Nhưng cần phân biệt rõ với kỳ vọng "có một
critic phản biện mỗi câu trả lời công khai" — **không có** lane như vậy trên
chat path; critic hiện phục vụ memory/observer-escalation.

### 4. Observer / post_observer — **ALIVE (ghi VÀ đọc đều có)**

**Tồn tại?** Có. `PostTurnObserver`
([`observer.py`](../../src/runtime/ai_orchestrated/observer.py)), dựng ở
bootstrap, dùng `observer_client` (social_parser) + escalation `deep_client`.

**Call site production (đường GHI)?** Có.
[`observation_bridge.py`](../../src/runtime/conversation/observation_bridge.py)
`observe_assistant_commit` gọi `ai_post_turn_observer.submit(...)`. Bridge này
được gọi từ
[`delivery_adapter.py`](../../src/runtime/conversation/delivery_adapter.py)
(sau khi transport chấp nhận public commit) và từ
[`orchestrator.py`](../../src/runtime/ai_orchestrated/orchestrator.py)
(`observe_user_turn`). Observer là actor nền single-flight, latest-wins, có
deadline/idle budget; chạy sau khi user idle.

**Đường ĐỌC lại ở lượt sau?** Có — đây là điểm mạnh nhất trong các lane:
- `_finalize_success` → `reducer.submit(StateEvent.from_observation(...))`
  (chỉ khi `status==success`, kèm `claim_provenance` observer, không mượn
  origin user).
- StateReducer cập nhật `latest_observation` → đọc lại ở:
  `RuntimeMindState.prompt_summary` (contracts.py, dùng `repair_needed`,
  `confidence>=0.62`), `orchestrator.py` (prime `conversation_handoff` +
  `signal_metadata`), `context_assembler._conversation_status`,
  `expression.py`, `panel_adapter.py`.
- `bootstrap.on_state`: nếu `memory_worthy` + `confidence>=0.68` →
  `_enqueue_background_memory_digest(source="ai_post_turn_observer")` →
  nuôi memory (xem Curator).

**Dấu hiệu chết?** Không. (Đính chính kết luận cũ "observer success nên khỏe;
inner hỏng không ảnh hưởng": observer có đường đọc thật, nhưng chất lượng NỘI
DUNG observation chưa audit ở điều tra tĩnh này — chỉ xác nhận đường đi.)

### 5. Curator (Living User Memory) — **ALIVE** (biến thể per-turn observer là ORPHAN)

**Tồn tại?** Có, nhiều mảnh:
- `LivingUserMemoryService`
  ([`memory/living_user/service.py`](../../src/memory/living_user/service.py))
  với trace journal, authority ledger, admission policy.
- `curator_client` (worker DeepSeek `curator`) trong `LlmService`.
- `MemoryAICurator` ([`memory/memory_ai_curator.py`](../../src/memory/memory_ai_curator.py))
  distillation/concern-bridge trong background maintenance.

**Call site production (GHI / admission)?** Có:
- Hot path: `observation_bridge.observe_user_turn` → `_ingest_user_turn_memory_hot_path`.
- Nền: `TurnMemoryPipeline` + `BackgroundMemoryDigestKernelService`
  ([`background_memory_digest_kernel.py`](../../src/runtime/background_memory_digest_kernel.py),
  [`turn_memory_pipeline.py`](../../src/runtime/turn_memory_pipeline.py)) dựng ở
  `coordinator_bootstrap.py` (~dòng 388–413), `commit_plan(..., observe_living_user,
  sync_living_user_semantic=True)`. Mặc định `ERIS_BACKGROUND_MEMORY_DIGEST=True`.
  Enqueue từ state_commit_service và từ observer (`on_state`).
- Review/GC: `MemoryGCService._run_living_user_review` dùng critic làm reviewer
  (xem lane Critic).

**Đường ĐỌC lại (recall)?** Có.
`memory_kernel.build_public_context(query, session_id=...)`
([`memory/memory_kernel.py`](../../src/memory/memory_kernel.py) ~dòng 555) được
gọi trong `context_assembler._typed_memory_context` → `memory_context` vào
prompt Root/Writer. Ngoài ra `learner_continuity_snapshot` đọc
`memory_kernel.living_user`. Admission/provenance: `MemoryAdmissionPolicy`
(decide_profile_record) + authority ledger giữ provenance/scope.

**Mồ côi?** `BackgroundLivingUserObserverService`
([`background_living_user_observer.py`](../../src/runtime/background_living_user_observer.py))
— "single-owner curator lane per-turn" — **không có constructor production** nào
(chỉ xuất hiện trong module của chính nó + `coordinator_shutdown.py` dưới dạng
`getattr` phòng thủ + tests). ⇒ biến thể observer per-turn này là **ORPHAN**;
curator thật đi qua `TurnMemoryPipeline`. Không suy ra curator chết — nó sống,
chỉ là qua đường khác.

**Dấu hiệu chết?** Không với curator tổng thể. Có với riêng
`BackgroundLivingUserObserverService`.

### 6. Companion routing (policy chọn năng lực/model per-turn) — **DEAD/ORPHAN trên live chat path**

**Tồn tại?** Có.
[`companion_model_routing.py`](../../src/runtime/companion_model_routing.py):
`route_companion_turn`, `CompanionRoutingPolicy` (mặc định enabled=True,
`pro_threshold=0.58`), `CompanionModelRouter`. Decision trả tier Flash/Pro +
`thinking_mode` + `reasoning_effort`.

**Call site production?** **KHÔNG.** `route_companion_turn` được **import** trong
[`orchestrator.py`](../../src/runtime/ai_orchestrated/orchestrator.py) (dòng 26)
nhưng grep toàn file không thấy nó được **gọi** ở bất kỳ đâu; không thấy
`CompanionRouteDecision`, `use_pro`, `tier` được dùng. Mọi call site
`route_companion_turn(...)` / `CompanionModelRouter().route(...)` còn lại đều nằm
trong `src/tests/`. ⇒ Policy này **không điều khiển request** trên live chat
path. Việc chọn model thực tế là **theo vai trò lane cố định** (mỗi lane một
client/worker), và thinking/effort do deepseek adapter + env/carve-out quyết
định — **không** qua companion policy.

Lưu ý: "companion" trong dự án còn có nghĩa khác — `AdaptiveCompanionService`
([`adaptive_companion.py`](../../src/runtime/adaptive_companion.py)) là **delivery
stance policy** (companion/peer/teach), KHÔNG phải model routing. Test
`test_adaptive_companion_integration_v91.py` yêu cầu orchestrator chứa
`ensure_adaptive_companion_service` + `adaptive_companion.prompt_context`, nên
stance policy đó có đường vào prompt. Đây là lane khác với "companion model
routing" ở trên; đừng gộp hai thứ.

**Dấu hiệu chết?** Rõ: import mồ côi + chỉ test gọi + config mặc định bật nhưng
không ai hỏi. Khớp với đính chính trong tài liệu tri thức ("policy không được
gọi trên live chat path").

---

## Bảng tóm tắt trạng thái

| Lane | Trạng thái | Bằng chứng chính | Giới hạn / cảnh báo |
|---|---|---|---|
| Observer / post_observer | **ALIVE** | `observation_bridge → ai_post_turn_observer.submit`; `_finalize_success → reducer.submit`; đọc lại qua `latest_observation`/`prompt_summary`/handoff; enqueue memory digest | Chưa audit chất lượng NỘI DUNG observation (static only) |
| Seed / reservoir | **ALIVE** | `bootstrap.py` dựng + `.start()`; `ingest_seed → mental_material → context` | Caller `claim_seed` cụ thể chưa truy hết; cần trace live để xác nhận lease→public |
| Curator / Living User Memory | **ALIVE** | `TurnMemoryPipeline` + `BackgroundMemoryDigestKernelService` (default on); recall qua `build_public_context`; GC review qua critic | `BackgroundLivingUserObserverService` biến thể per-turn là **ORPHAN** |
| Critic / deep | **ALIVE (maintenance)** | `MemoryGCService` dùng critic cho semantic/living review; observer-deep escalation | Không phải phản biện per-turn; critic = deep = cùng worker `social_critic` |
| Inner / private mind | **ALIVE (state) / DORMANT (speech)** | daemon dựng ở bootstrap; `mental_material`/`concern` vào context; persist diary | `private_mind_speech_bias` sync vào attribute **không có reader public** (renderer đã xóa); surface export mặc định khóa; model-lane legacy mặc định off |
| Companion model routing | **DEAD/ORPHAN** | `route_companion_turn` chỉ import ở orchestrator, **không call site production**; chỉ test gọi | Đừng nhầm với `AdaptiveCompanionService` (stance policy, có đường vào prompt) |

---

## Kết luận & khuyến nghị (không tự ý triển khai)

1. **Trả lời user:** các luồng phụ phần lớn còn "sống" ở dạng **nuôi state/
   memory nền** (observer, seed, curator, inner-concern) và có đường đọc lại
   lượt sau. Nhưng hai kỳ vọng dễ hiểu lầm là KHÔNG đúng: (a) nội tâm **không**
   chảy thẳng vào wording qua speech-bias (đường đó gãy), (b) **không** có
   companion-routing chọn Flash/Pro mỗi lượt trên live path, và **không** có
   critic phản biện mỗi câu public.

2. **Inner speech-bias (ưu tiên nếu muốn nội tâm ảnh hưởng giọng):** cân nhắc
   khôi phục/định nghĩa lại một renderer đọc `private_mind_speech_bias` vào
   context writer, HOẶC bỏ hẳn `_sync_private_mind_future_bias` để tránh ảo
   giác "đã nối". Trước khi sửa, xác nhận bằng trace live rằng
   `digest['future_bias']` thật sự được sinh. (Đây là đính chính cho ghi chú
   "#3 đã fix" trong code.)

3. **Companion routing:** quyết định dứt điểm — hoặc nối `route_companion_turn`
   vào đúng điểm chọn client/thinking trong orchestrator (và đo tác động), hoặc
   xóa import mồ côi + class để khỏi gợi ý sai rằng routing đang chạy. Khớp mục
   "việc còn mở #2" trong tài liệu tri thức.

4. **Dọn ORPHAN:** `BackgroundLivingUserObserverService` nên được nối (nếu muốn
   curator per-turn) hoặc gỡ, vì hiện chỉ còn tham chiếu phòng thủ ở shutdown.

5. **Giới hạn điều tra:** tất cả ở trên là đọc source. Chưa chạy live, chưa đo
   latency, chưa xác nhận worker DeepSeek nào thực sự lên, chưa kiểm chất lượng
   nội dung của observation/diary/seed. Trước khi kết luận "lane X khỏe/hỏng về
   nội dung", cần run log + raw trace của đúng process đang phục vụ (theo đúng
   cảnh báo phương pháp trong `docs/knowledge/2026-10-14-eris-runtime-lessons.md`).

Nội dung từ tài liệu tri thức được diễn giải lại để tuân thủ (rephrased).
