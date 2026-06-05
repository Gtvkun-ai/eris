# ERIS DEBUG SOURCE MAP

Mục tiêu: tài liệu này không dành cho người đọc ngoài. Nó dùng để debug repo ERIS theo kiểu file-to-file: file nào giữ vai trò gì, state nào đọc/ghi, đường gọi nào cần soi khi lỗi.

Nguồn dựng bản này:
- Repo public `Gtvkun-ai/Eris` tại nhánh `main`.
- `Tongquat.txt` bản cũ/legacy nếu còn trong workspace; hiện bản debug chính là `tongquat.md`.
- `Eris Cognitive Pipeline V3 Grand Architecture.pdf` để đối chiếu kiến trúc chuẩn.

Giới hạn trung thực:
- Bản này vẫn chưa phải inventory/audit toàn repo theo kiểu đọc từng dòng tất cả source.
- Tuy vậy, revision hiện tại đã đối chiếu source thật trong workspace cho các điểm nóng đang mở: `src/llm/service.py`, `src/cortex/surface_arbiter.py`, `src/cortex/speech_core.py`, `src/runtime/presence_controller.py`, `src/runtime/autonomous_wake_governor.py`, `src/runtime/coordinator.py`, `src/runtime/no_fallback_policy.py`, `body/MotionController.cs`.
- Những section khác vẫn là source-map debug ưu tiên chính xác theo tài liệu nội bộ + file tree public + mô tả module hiện có.
- Những file được đánh dấu `VERIFY_IN_CODE` cần mở source thật để xác nhận function/class cụ thể.
- Dùng bản này để debug luồng, không dùng làm README public.

---

# 0A. Git delta gần đây

Khoảng thay đổi đã soi trực tiếp: từ `2026-06-04` đến `2026-06-06`, chủ yếu qua các commit `fdfe52c`, `c268eab`, `aa9af6f`, `04bd5f6`, `5f812fc`, `553985e`.

Trạng thái sync với remote lúc rà tài liệu:
- `git fetch origin` chạy sạch.
- `git rev-parse HEAD` = `git rev-parse origin/main` = `553985e189ab44140b8bfe46d7aa025a199c34f7`.
- nghĩa là hiện **không có gì bị thiếu do chưa pull**; phần cần cập nhật là tài liệu và local worktree, không phải thiếu commit upstream.

Trục thay đổi chính theo git:
- low-level surface path được gom về một trục `PresenceController -> SurfaceArbiter -> LowLevelSpeechPolicy -> LlmService.generate_micro_presence_line`, thay cho nhiều nhánh micro-presence rải rác.
- `config/low_level_speech_policy.yaml` + env override được thêm để tune `force_llm_after_silent`, threshold, cooldown, và body-only streak mà không phải sửa code.
- `ModelBudgetPolicy` chuyển trọng tâm sang queue/lease scheduler; `ERIS_RESOURCE_GUARD_ENABLED` hiện mặc định `false`, tức runtime thường là queue-only chứ không chặn vì máy “đang bận”.
- `LlmService` được siết lại ở decision JSON: compact contract, sanitize decision-like JSON, salvage JSON cụt nếu còn `"text"` sạch, và chặn việc wrap metadata/prose thẳng vào `text`.
- tầng nội sinh được đẩy mạnh ở `agent_state_stack.py`, `impulse_arbitration.py`, `speech_core.py`, `surface_arbiter.py`: thêm `vital_pressure`, `metabolic_pressure`, memory/silence/boredom residue, và re-engagement sau im lặng dài.
- `presence_controller.py` tiếp tục được bơm thêm đường `active_memory_resonance -> memory_resonance impulse`, cộng cơ chế tách `body-only presence action` khỏi spoken cooldown.
- `autonomous_wake_governor.py` đã thành gate wake rõ nghĩa hơn: wake level tách hẳn `sleep/observe/think/micro_presence/vision/main`, có degrade theo interrupt cost thay vì chỉ một cờ wake/no-wake.
- `coordinator.py` tiếp tục phình thành nơi hợp mạch runtime thật sự; commit `553985e` còn sửa khá mạnh file này và chính `tongquat.md`, nên các mô tả coordinator nên ưu tiên workspace hiện tại hơn snapshot cũ.
- test coverage mới bám đúng các thay đổi trên: `tests/test_surface_arbiter.py`, `tests/test_model_budget_policy_queue.py`, `tests/test_presence_controller_memory_surface.py`, cùng các ca salvage/repair trong `tests/test_llm_service.py`.

Nhìn theo `git show --stat`, mấy cụm thay đổi đáng chú ý nhất trong chuỗi commit vừa rà là:
- `fdfe52c`: introduce `LowLevelSpeechPolicy`, `SurfaceArbiter`, test `tests/test_surface_arbiter.py`, và dời low-level surface sang một trục thống nhất.
- `c268eab`: xóa `Tongquat.txt`, mở rộng `presence_controller.py`, tăng coverage queue/runtime coordinator, và chuyển `tongquat.md` thành bản chính.
- `aa9af6f`: thêm mạnh vào memory/event ledger + `presence_controller.py` + `autonomous_wake_governor.py`, đẩy hướng presence có residue/memory-resonance.
- `04bd5f6`: tune YAML/policy, tăng `impulse_arbitration.py`, `surface_arbiter.py`, `model_budget_policy.py`, và thêm `tests/test_model_budget_policy_queue.py`.
- `5f812fc`: tăng `micro_repeat_guard.py`, `surface_arbiter.py`, `presence_controller.py`, cùng regression test cho memory-surface.
- `553985e`: tiếp tục sửa `coordinator.py`, `presence_controller.py`, cập nhật `tongquat.md`, và thay đổi runtime state files.

Tình trạng worktree lúc cập nhật tài liệu này:
- `git status --short` hiện có cả drift dữ liệu runtime lẫn source chưa commit:
  - runtime data: `memory_core/active_state_snapshot.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl`.
  - source local: `src/runtime/autonomous_wake_governor.py`, `src/runtime/coordinator.py`.
- nghĩa là repo **không thiếu pull**, nhưng workspace hiện tại **không hoàn toàn sạch**; khi mô tả behavior phải phân biệt đâu là code đã commit ở `HEAD`, đâu là local patch đang nằm ngoài commit.

---

# 0B. Repo snapshot hiện tại

Snapshot thô để khỏi phải đoán “repo giờ to đến đâu”:
- tổng source code đã đếm: khoảng `108,437` dòng trong `247` file code (`.py` + `.cs`).
- riêng Python: `104,703` dòng trong `241` file.
- riêng C#: `3,734` dòng trong `6` file.

Phân theo vùng chính:
- `src/`: `181` file, khoảng `90,044` dòng.
- `tests/`: `49` file, khoảng `10,949` dòng.
- `body/`: `13` file, khoảng `3,888` dòng.
- `scripts/`: `11` file, khoảng `4,408` dòng.
- `memory_core/`: `10` file dữ liệu/state, khoảng `4,270` dòng JSON.
- `config/`: `5` file, khoảng `119` dòng.

Các cụm Python lớn nhất hiện tại:
- `src/cortex/`: `59` file, khoảng `38,582` dòng.
- `src/runtime/`: `36` file, khoảng `27,484` dòng.
- `src/memory/`: `48` file, khoảng `12,500` dòng, chưa tính các tiểu mục `claims/`, `judgement/`, `understanding/`.

Hot files đã soi trực tiếp trong workspace:
- `src/runtime/coordinator.py`: khoảng `6,011` dòng, đúng nghĩa god object/orchestrator.
- `src/runtime/presence_controller.py`: khoảng `2,209` dòng, hiện là trục low-level presence sống nhất.
- `src/cortex/surface_arbiter.py`: khoảng `1,005` dòng, là router low-level surface trọng yếu.
- `src/runtime/autonomous_wake_governor.py`: khoảng `234` dòng, nhỏ hơn nhiều nhưng là gate wake rất nhạy.

---

# 0. Luồng sống chính của ERIS

```text
Godot Body
  body/UdpListener.cs
    ↓ UDP event 4243
Python Runtime
  src/vision.py
    ↓ build services
  src/runtime/coordinator.py
    ↓ mixins/runtime gates
  source_grounding / chat_cycle / frame_builder / speech_pipeline
    ↓
Cortex
  Se -> Evidence -> AttentionSalience -> WorkingMemory -> Meaning -> InternalState -> SpeechCore -> ActionPlanner
    ↓
LLM / Parser / Ti / PostGenerationFilters
    ↓ UDP decision 4242
Godot Body
  UdpDecisionParser -> MotionController / LocalBodyAutonomy / UI bubble
```

Quy tắc debug:
- Nếu ERIS **không nói**: kiểm tra wake gate -> speech_core -> action_utility -> post_generation_filters -> should_speak.
- Nếu ERIS **nói sai nguồn**: kiểm tra source_grounding -> parser_grounding -> Ti -> post_generation_filters.
- Nếu ERIS **lặp hoặc lạnh**: kiểm tra turn_semantics -> conversation_dynamics -> relational_feedback -> FeRenderer -> LlmService chat contract.
- Nếu ERIS **mất câu trả lời do JSON cụt**: kiểm tra LlmService `_complete_decision` max_tokens -> malformed JSON salvage -> parser_grounding strict/lax -> chat_cycle format fallback.
- Nếu ERIS **có nội sinh nhưng không surface**: kiểm tra thought_stream -> spontaneous_life -> impulse_arbitration -> speech_core quiet guard.
- Nếu ERIS **nhớ sai**: kiểm tra memory_commit_policy -> MemoryCognitionCore -> memory_recall_adapter -> SourceGrounding memory_answer_allowed.
- Nếu body **đơ hoặc động tác sai**: kiểm tra Decision.to_payload -> UdpDecisionParser -> MotionController -> LocalBodyAutonomy.

---

# 1. Root / Project files

## `project.godot`
Role: cấu hình Godot project.
Reads/Writes: Godot editor/runtime.
Debug khi: scene không chạy, node path lỗi, C# binding lỗi.
Status: ACTIVE.

## `Eris.csproj`, `Eris.sln`
Role: project .NET/Godot C#.
Debug khi: build Godot C# fail, script không compile, target framework lệch.
Status: ACTIVE.

## `.env.example`
Role: mẫu env. Dùng để chuyển secret/key/config runtime ra khỏi source.
Debug khi: remote/local model không nhận config.
Status: ACTIVE CONFIG.
Note: phải ưu tiên thay hardcoded key bằng env. Nhân loại phát minh ra secret scanning không phải để trang trí.

## `requirements.txt`
Role: dependency Python.
Debug khi: import fail, runtime boot fail, pytest fail do thiếu lib.
Status: ACTIVE.

## `pytest.ini`
Role: cấu hình pytest/import path.
Debug khi: ModuleNotFoundError, test discovery lệch.
Status: ACTIVE.

## `Tongquat.txt`
Role: kiến trúc/tổng quan cũ, đã được thay bằng `tongquat.md`.
Debug khi: chỉ dùng làm tham chiếu legacy nếu file còn tồn tại hoặc cần diff lịch sử.
Status: LEGACY / DELETED IN CURRENT WORKTREE.
Note: không còn coi là nguồn hiện tại. Nếu IDE còn mở tab này thì đó là tab cũ, không phải file source-map chính.

## `commit_notes.md`
Role: ghi chú commit/snapshot.
Status: SUPPORT DOC / VERIFY.

## `pytest-output.txt`, `pytest-report.xml`
Role: kết quả test gần nhất.
Debug khi: cần truy failure cụ thể.
Status: GENERATED DEBUG ARTIFACT.

## `tmp_llama_out.log`, `tmp_llama_err.log`, `tmp_vision_smoke.png`
Role: artifact runtime/test tạm.
Status: GENERATED / SHOULD_NOT_COMMIT nếu public sạch.

## `focus_context_config.json`
Role: override phân loại focus context cho Se/Ni, ví dụ YouTube/nhạc/podcast nền không bị hiểu thành distraction.
Debug khi: ERIS đọc sai active app/activity kind.
Status: ACTIVE CONFIG.

## `config/low_level_speech_policy.yaml`
Role: knobs cho `LowLevelSpeechPolicy` / `SurfaceArbiter`.
Controls:
- force_llm_after_silent.
- high_conf_threshold.
- min_surface_confidence / body_only_min_confidence.
- min_surface_interval_seconds.
- family_cooldown_seconds.
- max_body_only_streak.
- body_only_after_llm_decline.
- always_llm_kinds.
Env override:
- `ERIS_SURFACE_POLICY_CONFIG`.
- `ERIS_SURFACE_FORCE_LLM_AFTER_SILENT`.
- `ERIS_SURFACE_HIGH_CONF_THRESHOLD`.
- `ERIS_SURFACE_MIN_CONFIDENCE`.
- `ERIS_SURFACE_BODY_ONLY_MIN_CONFIDENCE`.
- `ERIS_SURFACE_MIN_INTERVAL_SEC`.
- `ERIS_SURFACE_FAMILY_COOLDOWN_SEC`.
- `ERIS_SURFACE_MAX_BODY_ONLY_STREAK`.
- `ERIS_SURFACE_ALWAYS_LLM_KINDS`.
Debug khi:
- micro-presence/re-engagement không gọi LLM dù cue đủ mạnh.
- surface quá dày do cooldown thấp.
- body-only kéo dài thành giả sống mà không nói.
- thought_stream_surface hoặc inner_whim không bao giờ ra câu.
Status: ACTIVE CONFIG.

## `ni_focus_config.json`, `goal_profiles.json`, `goal_memory.json`, `ni_drift_samples.jsonl`
Role: cấu hình/memory mẫu cho Ni drift, goal tracking.
Debug khi: ERIS nhắc goal sai, coi leisure là lệch goal, hoặc goal không close.
Status: ACTIVE DATA/CONFIG.

---

# 2. Body Godot / C#

## `body/UdpListener.tscn`
Role: scene body gốc.
Owns: CanvasLayer, chat panel, context menu, sprite, bubble.
Calls: `UdpListener.cs`.
Debug khi: body không hiện, UI node path null, context menu lỗi.
Status: ACTIVE.

## `body/UdpListener.cs`
Role: trung tâm body runtime.
Owns:
- UDP receive decision port 4242.
- UDP send event/chat port 4243.
- chat panel, bubble, context menu.
- connect process manager, parser, motion, audio, local autonomy.
Reads:
- payload decision từ Python.
- input user chat / force speak / touch.
Writes:
- event UDP sang Python.
- UI bubble, animation, local body state.
Calls:
- `UdpDecisionParser`
- `ErisProcessManager`
- `MotionController`
- `LocalBodyAutonomy`
- `BodyAudioController`
Debug khi:
- body không nhận text: kiểm tra bind 4242, payload JSON, `should_speak`.
- chat không sang Python: kiểm tra send 4243, event shape.
- body override sai: kiểm tra explicit motion vs body_bias.
Status: ACTIVE GOD OBJECT.
Risk:
- vẫn quá dày: UI + UDP + process + state body.
- nếu còn hardcoded API key thì phải dọn.

## `body/UdpDecisionParser.cs`
Role: parse payload UDP từ Python sang object body.
Reads: raw UDP JSON/plain text.
Outputs: `UdpDecisionPayload`.
Normalizes:
- text, should_speak, parse_mode, debug_trace, parser_trace.
- animation alias: walk/run -> stand_walk, wave -> stand.
- body_bias, emotion_debug, motion fields.
Debug khi:
- payload có text nhưng bubble không hiện.
- animation bị reject.
- motion không chạy dù Python gửi.
Status: ACTIVE.

## `body/ErisProcessManager.cs`
Role: start/stop Python `vision.py` và llama-server.
Reads: Godot export config/env.
Writes: process lifecycle, stdout/stderr log.
Injects env:
- PYTHONUTF8, PYTHONIOENCODING, PYTHONUNBUFFERED.
- LLAMA_SERVER_*, GGUF_MODEL_PATH, ERIS_N_CTX.
- remote API vars, GEMINI_API_KEY.
Debug khi:
- vision.py không boot.
- llama-server không mở.
- stdout/stderr mất traceback.
Status: ACTIVE.
Risk: secret/env handling cần sạch trước public.

## `body/LocalBodyAutonomy.cs`
Role: autonomy cục bộ của thân thể.
Reads:
- BodyBias từ Python: continuity_anxiety, curiosity, overload, solitude, focus_kind, preferred_anchor.
- BodyAutonomyContext: position, screen size, action state, chat visible, top perch.
Writes:
- BodyAutonomyDecision / MotionCommand local.
Behavior:
- ReturnToAnchor, ReadQuietly, ObserveCode, ClimbWall, DropFromCeiling, Withdraw, DormantSit, QuietObserve.
Debug khi:
- body đi lại vô lý.
- body spam climb/drop.
- body không phản ứng body_bias.
Status: ACTIVE.

## `body/MotionController.cs`
Role: physics/movement body.
Reads: MotionCommand.
Owns:
- gravity, velocity X/Y, facing, sprite+bubble flip.
- state machine leo tường: `GoingToWall -> Up -> Top -> TopHold -> Down`.
- `walk`, `walk_to`, `climb_to_top`, `climb_loop`, `drop`, `throw`, `face`, `pose`.
- airborne wall contact + cơ chế `cling:<chance>` để cú ném có thể bám tường rồi leo tiếp.
- busy/perched/thrown state (`IsBusy`, `IsTopPerched`, `IsThrown`) cho body autonomy/UI gate.
Notes:
- `TargetX` là tỷ lệ 0..1 theo bề ngang màn hình, được resolve sang absolute X trong `ResolveAbsoluteTargetX`.
- `NotifyAnimationFinished()` dùng `bounce_action` để tiếp tục walk sau animation va tường.
Debug khi:
- body mắc tường, không rơi, không quay mặt, ném sai impulse.
- leo lên trần nhưng không giữ `TopHold` hoặc xuống tường sai phía.
- payload `throw` có `clingChance` nhưng không bám tường khi va chạm.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

## `body/BodyAudioController.cs`
Role: audio theo animation.
Reads: animation name, sound map.
Writes: AudioStreamPlayer.
Debug khi: âm thanh loop sai, sound không phát.
Status: ACTIVE.

## `asset/Resource/Monika.tscn`
Role: sprite frames/animation map.
Debug khi: animation name hợp lệ nhưng không có frame.
Status: ACTIVE ASSET.

## `asset/Monika/*.png`, `asset/Monika/sound/*.wav`, `asset/icon/*`, `*.import`, `*.uid`
Role: asset body/UI/Godot metadata.
Debug khi: sprite mất frame, import lỗi, sound thiếu.
Status: ASSET.

---

# 3. Entrypoint / Runtime spine

## `src/vision.py`
Role: entrypoint Python cognition.
Boot order:
1. stdout/stderr UTF-8.
2. SingleInstanceLock `.vision.lock`.
3. logging.
4. build LLM clients/process manager.
5. load MemoryCognitionCore.
6. build parser, telemetry, Ni/Ti/Fe.
7. boot ActionExecutor/ActionRouter.
8. create RuntimeCoordinator.
9. run_loop.
Reads:
- env remote/local model.
- memory_core.
- telemetry.
Writes:
- process logs.
- runtime state through coordinator.
Debug khi:
- app boot nhưng cognition không chạy.
- import/config/model path lỗi.
- memory load làm chết boot.
Status: ACTIVE ENTRYPOINT.

## `src/app_logging.py`
Role: logging formatter/grouping.
Debug khi: log quá ồn hoặc mất nhóm traceback.
Status: ACTIVE SUPPORT.

## `src/sender.py`
Role: UDP sender thủ công test body.
Debug khi: muốn test Godot body không cần full Python runtime.
Status: DEBUG TOOL.

## `src/guard_config.py`
Role: cấu hình guard, VERIFY_IN_CODE.
Debug khi: guard quá gắt/quá lỏng.
Status: CONFIG / VERIFY.

## `src/eris_secrets.py`
Role: secrets wrapper, VERIFY_IN_CODE.
Debug khi: env/key không load đúng.
Risk: không commit secret thật.
Status: SECURITY SUPPORT.

---

# 4. Runtime package `src/runtime/*`

## `src/runtime/coordinator.py`
Role: orchestrator trung tâm.
Owns state:
- chat history.
- last response.
- active conversational topic.
- repeated guard.
- vision facts.
- cognitive frames.
- mental process loop.
- session ritual flag.
- public/session turn ledger.
- reply context.
- rapid chat burst queue.
- memory_kernel wrapper + background_memory_digest service.
- presence/reengagement cooldown.
- last_wake_decision / rolling_user_context / rolling_internal_state / daydream result.
- signal buffer / observer snapshot / semantic scene note.
- model_budget_policy + installed queue wrappers cho `llm_service` và `sensory_model_adapter.observe`.
- wake_governor + contextual_autonomy_loop.
- autonomous presence block window, silent cycle counters, reengagement counters.
- ni_meta flags (`ni_meta_chat_enabled`, `ni_meta_auto_enabled`) từ env + `ni_meta_config.json`.
Calls:
- telemetry/Se.
- attention/working memory/meaning/personality.
- internal_state/self_model/social_presence/session_ritual/thought_stream.
- speech_core/action_planner/micro_policy.
- LLM/parser/Ti/Fe.
- memory/action router/executor.
- ModelBudgetPolicy queue wrapper cho các model nặng.
- runtime mixins.
Current code specifics:
- `__init__` bọc `memory_core` thành `MemoryKernel` nếu cần, rồi chỉ bật `background_memory_digest` khi semantic parser khởi tạo được.
- `_install_model_inference_queue()` wrap ở service boundary thay vì từng call-site: `generate_chat_reply -> main_cognition`, `generate_directive -> main_cognition`, `generate_screen_facts -> vision_compressor`, `sensory_model_adapter.observe -> sensory_0_6b`.
- coordinator giữ cả state runtime “có thể nói lại được” lẫn state gate/cooldown: `last_autonomous_spoken_at`, `autonomous_presence_blocked_until`, `presence_maintenance_silent_cycles`, `last_reengagement_at`, `_chat_burst_queue`.
- `contextual_autonomy_loop` nhận chung `agenda_stack`, `daydream`, `budget_policy`, `wake_governor`, nên wake path thực tế không còn là vài if rải rác nữa.
- `_background_memory_digest_idle_probe()` chỉ cho semantic digest chạy khi không đang chat, không còn burst queue pending, và đã đủ yên theo `ERIS_MEMORY_DIGEST_CHAT_IDLE_SEC`.
- coordinator còn giữ nhánh direct-action riêng: `_build_direct_action_decision()` route qua `action_router/action_executor`, còn `_execute_system_action()` hậu xử lý kết quả action vào `Decision` thay vì nhét hết vào LLM path.
- `ni_meta_config.json` hiện được đọc qua `_load_ni_meta_mode_flags()` với default `(chat=True, autonomous=False)` khi file lỗi/mất; `_maybe_apply_ni_meta_critic()` chỉ là lớp làm mềm drift score/confidence, không phải thay luôn base Ni report.
Debug khi:
- lỗi end-to-end không rõ owner.
- autonomous gọi main model dù wake gate không cho.
- background digest commit sai lúc runtime còn bận chat.
- chat burst/lặp/previous public turn sai.
- queue wrap không ăn khiến một đường model nặng chạy chui ngoài scheduler.
- ni meta chat/autonomous bật sai mode làm drift score thay đổi khó hiểu.
- action route trả text đúng mà trace/system_action bị mất hoặc bị double-execute.
Status: ACTIVE GOD OBJECT VERIFIED_IN_WORKSPACE, đã tách bớt bằng mixin nhưng vẫn là nơi hợp mạch.

## `src/runtime/chat_cycle.py`
Role: path xử lý chat user.
Owns:
- user_timestamp.
- rapid burst queue.
- source grounding precheck.
- memory recall deterministic trước LLM.
- direct action route.
- link previous public turn.
- final chat guards.
Reads:
- user text, reply_context, source_grounding, memory_recall_adapter, turn_semantics.
Writes:
- session_turn_ledger user/assistant.
- commit_requests từ user disclosure.
- Decision chat.
Debug khi:
- hỏi trực tiếp mà ERIS trả vòng vo.
- user gửi nhiều tin ngắn bị trả từng mảnh.
- câu “tôi vừa hỏi gì” sai.
Status: ACTIVE.

## `src/runtime/source_grounding.py`
Role: phân loại nguồn trước khi trả lời.
Sources:
- pasted_code, uploaded_file, filename_only, current_screen, live_vision, user_text, memory, web, runtime_state, unknown.
Outputs:
- SourceGroundingReport.
- allowed_sources.
- missing_evidence.
- forbidden_assumptions.
- epistemic_mode: claim/fallback/probe/hypothesis.
- memory_answer_allowed.
Debug khi:
- ERIS nói “tôi thấy màn hình” khi không có screenshot.
- memory giả dạng evidence hiện tại.
- file mention nhưng chưa có file content.
Status: ACTIVE CRITICAL GUARD.

## `src/runtime/post_generation_filters.py`
Role: hàng rào cuối output public.
Guards:
- protocol_surface_guard.
- internal_object_surface_guard.
- memory_haunting_guard.
- chat_grounding_guard.
- micro_line_policy_filter.
- repetition/style drift.
- anti_mindreading_filter.
Side effect:
- ghi feedback user vào PersistentAgentMindStore.
Debug khi:
- output bị rewrite mất hồn.
- output leak `MemoryPacket(...)` hoặc prompt/debug.
- output đang đúng mà bị guard đập thành fallback.
Status: ACTIVE CRITICAL SURFACE GUARD.

## `src/runtime/frame_builder.py`
Role: dựng cognitive frame/disturbance/autonomous frame.
Creates:
- CognitiveDisturbance từ user text, force_speak, autonomous tick, recent event, vision fact.
Calls:
- thought_stream.inject_disturbances.
Handles:
- session ritual fallback.
- surface selector pop/report.
Debug khi:
- nội sinh có pressure nhưng không vào thought_stream.
- force_speak không tạo requested_presence.
Status: ACTIVE.

## `src/runtime/cognitive_frame_recorder.py`
Role: finalize cognitive frame + outcome/self-observation/commit.
Order:
1. execution/action done.
2. OutcomeObserver.observe(frame).
3. SelfObserver.reflect(frame).
4. append repair memory request.
5. build/dedupe StateCommitRequest.
6. StateCommitter.commit(frame).
Debug khi:
- user correction không đi vào repair memory.
- frame không ghi outcome.
- memory_update debug sai.
Status: ACTIVE.

## `src/runtime/state_commit_service.py`
Role: adapter commit/recall/body bias/public ledger.
Owns helpers:
- _send_decision_to_body.
- _record_public_turn.
- _ensure_session_turn_ledger.
- _ensure_memory_commit_policy.
- _ensure_memory_recall_adapter.
- _semantic_memory_lookup.
- _episodic_memory_lookup.
Debug khi:
- decision nói rồi nhưng ledger không ghi.
- body_bias không gửi.
- memory recall deterministic không chạy.
Status: ACTIVE MIDDLE ADAPTER.

## `src/runtime/prompt_context_builder.py`
Role: dựng context prompt cho LLM.
Includes:
- internal state context.
- memory context.
- action plan context.
- Ti context.
- speech evidence/current focus.
- session ritual fallback.
Debug khi:
- prompt bị nhét quá nhiều context.
- LLM thấy memory không nên thấy.
Status: ACTIVE.

## `src/runtime/speech_pipeline.py`
Role: helper path speech/autonomous intent.
Debug khi: speech intent mapping lệch, force_speak/chat path lẫn nhau.
Status: ACTIVE / VERIFY.

## `src/runtime/presence_controller.py`
Role: presence maintenance, reengagement, micro-presence synthesis.
Feeds:
- presence cue cho `SurfaceArbiter`.
- body_action/focus_family/evidence/reason.
Core contracts:
- `MicroPresenceCue`: steering flags cho arbiter, không phải public wording.
- `SocialPresenceEvent`: semantic presence signal + vector/stability/fragmentation/anxiety.
- `MicroPresenceSynthesis`: container cho seed/context/fallback của wording layer.
Current code specifics:
- `PresenceControllerMixin` lazy-init một `SurfaceArbiter` duy nhất; micro presence/re-engagement/spontaneous low-level surface đều đi qua cổng này.
- `_derive_micro_presence_cue()` kết hợp `idle_seconds`, `recent_events`, `vision_facts`, `social_presence_event`, curiosity, và ego gate; idle một mình chưa đủ để nói.
- cue có thể chọn `ObserveCode`, `tilt_head`, hoặc `idle_shift`; `missing_evidence_ids` được set khi không có concrete screen evidence.
- `_build_endogenous_surface_impulses()` hiện có thể nâng `active_memory_resonance` public-safe thành impulse `memory_resonance`; residue private hoặc activation `may_surface=false` phải bị giữ lại.
- `_build_surface_arbiter_result()` là helper mới trả cả `Decision | None` lẫn `SurfaceDecision | None`; wake-gated route dùng nó để giữ reject/body-only/speak status của chính lượt arbitrate hiện tại, thay vì đọc lại `arbiter.last_decision`.
- `_build_surface_arbiter_decision()` giờ chỉ còn là wrapper tương thích ngược trên `_build_surface_arbiter_result()`.
- `_build_surface_arbiter_decision()` chỉ tự chặn bằng `autonomous_presence_blocked_until`; cooldown/spoken-floor/presence gating vẫn nằm ở `_should_allow_presence_maintenance()` và `_should_allow_reengagement()` trước khi vào arbiter.
- body-only presence/re-engagement được convert thành `MotionCommand` thay vì giả vờ có câu nói; body-only không được reset silent cycles như speech thật.
- re-engagement hiện build bằng cue + extra impulse `long_silence` và gọi `SurfaceArbiter` với `force_llm=True`.
- wake-gated telemetry giờ log ngắn cả input/output của arbiter: `surface_kind`, `silent_cycles`, `force_llm`, `cue.should_call_llm`, `cue.missing_evidence_ids`, rồi `kind/generation_mode/should_speak/body_only/reason`.
- `_surface_arbiter_llm_generate()` giờ gắn thêm contract `thin_presence_no_screen` cho presence-like impulse thiếu screen evidence: LLM được phép viết một câu hiện diện rất ngắn dựa vào silence/continuity, nhưng không được claim đang nhìn màn hình, không được hỏi dồn, và không được rơi về status ping.
- sanitizer cho micro-presence/re-engagement hiện cho phép tối đa khoảng 14 từ thay vì cắt cứng ở 8 từ cho mọi route, để contract thin-evidence presence có chỗ thở mà vẫn giữ câu ngắn.
- `_surface_arbiter_llm_generate()` luôn gửi kèm `surface_impulse`, `ego_surface_state`, `micro_presence_flags`, và `surface_contract`; presence-like cue chỉ bị ép `must_return_tiny_text` khi arbiter thật sự force hoặc impulse không-phải-presence đã đủ mạnh/silent lâu.
- local fallback text hiện chỉ còn là lưới an toàn cho non-presence route; presence maintenance không còn giữ “hũ câu mẫu” riêng để spam cho có vẻ sống.
- `_note_autonomous_presence_action()` tách riêng việc ghi nhận presence/re-engagement body-only khỏi `_note_autonomous_spoken()`, để cooldown có tăng nhưng speech debt không bị reset nhầm.
- nếu winner thật của surface khác route gọi ban đầu, planner/final payload giờ có thể gắn `surface_override=...` để debug bớt lú; ví dụ wake-gated presence vào arbiter nhưng winner thật là `thought_stream_surface`.
- env knobs hiện có:
  `ERIS_PRESENCE_MAINTENANCE`,
  `ERIS_PRESENCE_MAINTENANCE_SILENT_LOOPS`,
  `ERIS_PRESENCE_MAINTENANCE_COOLDOWN_SEC`,
  `ERIS_MICRO_PRESENCE_LLM`,
  `ERIS_MICRO_PRESENCE_LLM_PROBABILITY`,
  `ERIS_REENGAGEMENT`,
  `ERIS_REENGAGEMENT_QUIET_LOOPS`,
  `ERIS_REENGAGEMENT_MIN_IDLE_SEC`,
  `ERIS_REENGAGEMENT_COOLDOWN_SEC`.
Should not:
- tự giữ nhiều hũ câu mẫu độc lập.
- biến absence/idle thành guilt-trip.
Debug khi:
- ERIS spam câu hiện diện.
- vừa nói xong lại chen micro-line.
- force speak không có evidence sinh câu rỗng.
- presence cue có `needs_micro_presence=true` nhưng `SurfaceArbiter` reject/rate-limit.
- body-only presence bị tính nhầm là “đã nói”, làm force-LLM không bao giờ tới lượt.
- re-engagement không nổ dù quiet cycles/idleness đủ lớn vì bị `autonomous_presence_blocked_until` hoặc activity gate chặn.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

## `src/runtime/no_fallback_policy.py`
Role: bật/tắt chế độ chặn fallback mềm ở các path chat/autonomous/presence/force_speak.
Provides:
- `no_fallback_mode_enabled()`: đọc env `ERIS_NO_FALLBACK_MODE`.
- `build_no_fallback_payload(...)`: trả payload chuẩn `no_fallback_block` thay vì để từng nơi tự bịa fallback.
Current code specifics:
- chat path có thể trả text giải thích ngắn khi bị block, nhưng `session_ritual`, `directive`, `autonomous`, `force_speak`, `presence` mặc định ưu tiên im hơn là nói bừa.
- payload có `intent=no_fallback_block`, `parse_mode=no_fallback_block`, `debug_trace=no_fallback_mode:<channel>:<reason>`.
Debug khi:
- runtime tưởng “bị câm” nhưng thật ra đang ở no-fallback mode.
- một path lẽ ra phải im lại còn nhả câu fallback kỹ thuật ra public.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

## `src/runtime/public_turn_ledger.py`
Role: sổ các lượt public thật sự visible.
Stores:
- text, timestamp, channel: chat/session_ritual/presence/reengagement/autonomous.
Used by:
- reply_context.previous_public_turn.
Debug khi: user phản ứng câu vừa nói nhưng ERIS không hiểu ngữ cảnh.
Status: ACTIVE.

## `src/runtime/session_turn_ledger.py`
Role: transcript deterministic trong phiên.
Functions:
- nth_user_turn.
- nth_assistant_turn.
- count_user_questions.
- longest_user_question.
- gist_recent_user_topics.
Debug khi: exact recall trong phiên sai.
Status: ACTIVE.

## `src/runtime/memory_recall_adapter.py`
Role: adapter chặn sớm chat memory trước khi rơi vào general LLM path.
Pipeline:
1. bỏ qua nếu user đang self-disclose/update fact.
2. ưu tiên `MemoryKernel.answer(...)` nếu kernel có mặt và query được phép intercept.
3. fallback sang `MemoryQueryCompiler -> TurnGraph -> MemoryQueryExecutor -> MemoryRecallSurfacePolicy -> Decision`.
4. optional `MemoryQueryLLMParser` chỉ dùng để parse IR JSON, không generate answer.
Guards:
- chỉ intercept nếu `intercept_permission=true`, confidence đủ cao, ambiguity đủ thấp.
- scrub internal memory surfaces kiểu `MemoryPacket(...)` trước khi public.
- có `_MemoryCoreProxy` để bridge `memory_core` cũ với semantic/episodic lookup helpers.
Debug khi:
- câu hỏi memory đáng ra deterministic nhưng lại rơi xuống general LLM path.
- câu “tôi tên gì” sai.
- payload memory_recall thiếu `memory_source` / `memory_surface`.
Status: ACTIVE.

## `src/runtime/memory_semantic_parser_adapter.py`
Role: parse user text thành MeaningFrame cho memory intake.
Boundary: không commit, không quyết retention.
Debug khi: user self-disclosure không được parse thành claim.
Status: ACTIVE.

## `src/runtime/body_bias.py`
Role: project internal state / impulse hint thành body_bias.
Fields:
- continuity_anxiety, curiosity, overload, solitude, focus_kind, preferred_anchor.
Debug khi: body không phản ánh nội trạng.
Status: ACTIVE.

## `src/runtime/outcome_observer.py`
Role: đọc hậu quả sau turn.
Detects:
- user accepted/corrected/confused/ignored/intruded.
- action success.
- body match success.
Debug khi: self_observation không có dữ liệu học sửa.
Status: ACTIVE.

## `src/runtime/eris_pathology_policy.py`
Role: deterministic pathology repair/test policy.
Scenarios:
- misread_correction.
- overread_short_ambiguous.
- underacted_fix_request.
- overexplained_short_answer.
- tone_mismatch_technical.
- privacy_intrusion_no_evidence.
- body_mismatch_presence.
- assistant_flattening.
- overhumanization_identity_boundary.
- public_turn_correction.
- memory_not_current_evidence.
Debug khi: muốn regression observable behavior mà không boot full runtime.
Status: ACTIVE TEST/REPAIR POLICY.

## `src/runtime/signal_buffer.py`
Role: rolling signal snapshot/diff trước observer.
Computes:
- novelty, repetition, diff_score.
- window/app/focus/ocr/screen/event/resource/idle transition changes.
Debug khi: observer chạy quá nhiều hoặc không chạy khi nên chạy.
Status: ACTIVE.

## `src/runtime/sensory_model_adapter.py`
Role: adapter 0.6B sensory/observer model.
Reads env:
- ERIS_SENSORY_ENABLED, PROVIDER, MODEL, KEEP_ALIVE, TEMP.
Outputs ObserverFrame JSON schema.
Debug khi: sensory model không trả schema hoặc observer fallback sai.
Status: ACTIVE.

## `src/runtime/contextual_autonomy_loop.py`
Role: backbone 3-tier autonomy.
Tick does:
- update RollingUserContext.
- update RollingInternalState.
- capture ResourceSnapshot.
- call AutonomousWakeGovernor.
- optionally daydream.
Debug khi: wake/sleep cadence sai, daydream không trigger, budget veto bất thường.
Status: ACTIVE.

## `src/runtime/autonomous_wake_governor.py`
Role: quyết định mức thức.
Outputs WakeDecision:
- level, should_speak, should_call_vision, should_wake_main, should_run_daydream.
- reason, confidence, external_pressure, internal_drive, compute_budget, permission, speech_value, interrupt_cost.
Wake levels:
- `sleep`
- `observe_only`
- `think_only`
- `micro_presence`
- `call_vision_compressor`
- `wake_main_cognition`
Current code specifics:
- score chính được pha từ `external_pressure`, `internal_drive`, `permission`, `speech_value`, `agenda_pressure`.
- `speech_value` còn được boost bởi `possible_error`, `user_presence`, và `silence_debt` từ `autonomous_silent_cycles / 12`.
- `recommended_action` trong `RollingUserContext` có thể ép nhánh `call_vision_compressor` hoặc `wake_main_cognition`.
- `should_run_daydream` hiện bật khi `consolidation_pressure >= 0.65` hoặc `insight_pressure >= 0.70`.
- nếu main wake đáng ra được gọi nhưng interrupt cost cao, governor có thể degrade xuống `micro_presence` hoặc thậm chí `think_only/observe_only` thay vì đánh thức main.
- debug payload giữ cả budget decision của `4b`, `main`, `vision`, cùng `silence_debt_micro_ready`.
Debug khi:
- main cognition chạy sai lúc hoặc im sai lúc.
- wake level bị degrade thành `micro_presence`/`think_only` dù external pressure nhìn có vẻ cao.
- silence debt đủ lớn nhưng vẫn không lên `micro_presence`.
Status: ACTIVE CRITICAL GATE VERIFIED_IN_WORKSPACE.

## `src/runtime/model_budget_policy.py`
Role: lightweight inference scheduler cho model nặng; Resource Guard hiện là opt-in.
Capabilities:
- CPU/RAM/GPU/VRAM best-effort telemetry.
- global heavy-model lock qua lease.
- priority queue + timeout + cancel_event.
- `run_queued(...)` / `lease(...)` lifecycle bọc inference thật.
- unload hook sau request xong để tránh load/unload đè VRAM.
- snapshot có active tiers, reserved VRAM, queue depth, `main_cognition_recent`.
- legacy-compatible `mark_started/mark_finished` vẫn còn để giữ cooldown markers.
Current code specifics:
- Mặc định runtime là queue-only: `ERIS_RESOURCE_GUARD_ENABLED` default `false`.
- Khi `resource_guard_enabled=false`, `can_run()` trả `scheduler_allow` dù CPU/RAM/GPU/VRAM/temp/cooldown cao. Guard không còn bóp main/vision/daydream vì máy luôn bận.
- Queue/lease vẫn hoạt động: heavy tiers không chạy chồng nhau vì `_has_incompatible_active_lease_locked()` giữ `main_cognition`, `subconscious_4b`, `vision_compressor` tuần tự.
- Nếu muốn behavior cũ để test/debug, bật `ERIS_RESOURCE_GUARD_ENABLED=1`; lúc đó mới có `gpu_overheat`, `tier_cooldown_active`, `resource_guard:*`, `active_heavy_lease`.
- `vision_force_run` default `true`: trong mode guard-on, `vision_compressor` có priority lane riêng, timeout mặc định `0.0`, bỏ qua queue full mềm, và nếu qua được overheat thì reason thành `vision_force_run`.
- `force_local_gguf_main` vẫn là special path riêng: priority cực cao, timeout riêng, bỏ qua một số giới hạn queue thường.
- heavy tiers thực tế là `main_cognition`, `subconscious_4b`, `vision_compressor`; `sensory_0_6b` dùng soft block riêng.
- queue là in-process priority queue; nếu guard-on, request chỉ bị đo/veto khi đã lên đầu queue.
- resource guard opt-in đáng chú ý: `cpu_busy`, `ram_busy`, `gpu_busy`, `vram_busy`, `heavy_foreground_gpu_owner`, `compile_or_editor_pressure`.
- snapshot phân biệt `eris_reserved_vram_mb` với `external_vram_used_mb`; nghĩa là VRAM của lease đang active không bị tính lẫn hoàn toàn như “ngoài hệ”.
- `queue_state()`, `cancel_queued_request()`, `cancel_all_queued()` là điểm debug khi nghi scheduler kẹt.
Limit:
- không kill được request remote/local đã bay vào provider.
- vẫn là scheduler nhẹ trong-process, chưa phải orchestrator đa worker.
Debug khi: nhiều model chạy chồng, daydream/vision/main đụng queue/lease.
- remote main đang bật `remote_api_enabled` nên behavior heavy/local lock khác với lúc chạy local GGUF.
- Nếu log còn thấy `resource_guard:*` trong runtime thường, kiểm tra env có bật `ERIS_RESOURCE_GUARD_ENABLED=1` không.
- Nếu vision vẫn `model_queue_timeout`, kiểm tra caller có override `timeout_seconds` không và queue head có active heavy lease nào giữ lâu không.
Status: ACTIVE CRITICAL QUEUE SCHEDULER VERIFIED_IN_WORKSPACE.

## `src/runtime/daydream_model_adapter.py`
Role: adapter 4B daydream model.
Providers:
- Ollama.
- llama-server chat/completions JSON.
Debug khi: daydream không parse JSON, provider timeout.
Status: ACTIVE.

---

# 5. Domain / Transport

## `src/domain/decision.py`
Role: contract cuối giữa cognition và Godot.
Fields:
- text, intent, action, animation, should_speak, confidence.
- direction, target_x, bounce_action, next_animation.
- system_action, action_input.
- motion_intent, motion_target_x, motion_facing.
- debug_trace, parser_trace, parse_mode.
- body_bias, emotion_debug.
Resolvers:
- climb + climb_top -> climb_to_top.
- air_swing -> drop.
- target_x -> walk_to.
- stand_walk -> walk.
Debug khi: Python nghĩ có motion nhưng body không chạy.
Status: ACTIVE CRITICAL CONTRACT.

## `src/transport/udp.py`
Role: UDP transport Python.
Ports:
- send decision to Godot 4242.
- receive Godot events 4243.
Debug khi: chat/body mất kết nối.
Status: ACTIVE.

---

# 6. LLM layer `src/llm/*`

## `src/llm/client.py`
Role: clients cho llama-server/OpenAI-compatible/Gemini.
Handles:
- response format fallback.
- grammar unsupported fallback.
- image payload conversion.
- HTTP error body.
Debug khi: provider trả shape lạ, Gemini/OpenAI-compatible không parse được.
Status: ACTIVE.

## `src/llm/ollama_client.py`
Role: client Ollama cho observer/vision/daydream local.
Supports:
- chat_json, generate_json.
- image base64/data URI.
- keep_alive.
- unload/list_models.
Debug khi: Ollama model giữ RAM, JSON bẩn, vision local lỗi.
Status: ACTIVE.

## `src/llm/process_manager.py`
Role: quản lý llama-server và build clients.
Reads:
- env remote/local.
- model/mmproj paths.
Builds:
- main cognition client.
- style client.
- vision client.
Current code specifics:
- remote path hiện ưu tiên `ERIS_REMOTE_API_ENABLED`; mặc định provider là Gemini qua `ERIS_REMOTE_PROVIDER=gemini`.
- remote Gemini mặc định trỏ `https://generativelanguage.googleapis.com/v1beta` và fallback model hiện là `gemma-4-26b-a4b-it` nếu env trống.
- local path sẽ reuse `llama-server` đang chạy chỉ khi server hiện tại có `n_ctx` đủ; nếu phát hiện `n_ctx` thấp hơn nhu cầu, manager cố thay server cũ thay vì cứ tăng port mãi.
- `_detect_running_server_n_ctx()` probe `/props` hoặc `/v1/props` để đọc context size của server đang sống.
- nếu host local đang bị một `llama-server` cũ giữ port, code có best-effort kill theo port nhưng chỉ kill process có tên giống `llama-server`.
- `_resolve_mmproj_path()` cho phép text-only mode khi không tìm thấy mmproj; `build_vision_client()` chỉ bật khi có cả model và mmproj.
- `build_style_client()` và `build_vision_client()` cưỡng bức local mode tạm thời bằng cách hạ `ERIS_REMOTE_API_ENABLED=0` quanh lúc build client.
Debug khi: remote/local path sai, llama-server port conflict, context size error.
Risk: hardcoded default key cần dọn.
Status: ACTIVE.

## `src/llm/contracts.py`
Role: prompt contract/schema/whitelist.
Contains:
- animation whitelist.
- system action whitelist.
- JSON required fields.
- runtime/chat/autonomous rules.
- SelfIdentityProfile.
Debug khi: LLM output hay phá format hoặc role boundary sai.
Status: ACTIVE.

## `src/llm/service.py`
Role: service shape prompt + gọi model + fallback.
Methods:
- generate directive/autonomous.
- generate_chat_reply.
- generate_micro_presence_line.
- generate_screen_facts.
- critic/analysis phụ.
ChatAct:
- direct_question.
- insult_provocation.
- identity_reduction.
- command_style.
- normal_chat.
Guards:
- tone_repair hẹp.
- retry insult boundary nếu uncertainty_dodge.
- strict decision JSON gate trước parser (`response_format=json_object` + `DECISION_GBNF`).
- malformed decision JSON salvage: nếu JSON bị cụt nhưng có `"text"` sạch, rebuild payload an toàn thay vì leak schema hoặc ném format violation ngay.
- protocol failure fallback: dùng payload `protocol_repair`, không wrap raw JSON/prose vào `text`.
- non-empty text rule khi channel yêu cầu phải nói.
- local/style fallback path cho một số lỗi provider như prompt leak/safety block.
Debug khi:
- hỏi thẳng nhưng model vòng vo.
- insult/objectification khiến ERIS quá mềm hoặc quá gắt.
- output JSON lỗi.
- raw API text bắt đầu bằng `{` nhưng thiếu `}` hoặc chết giữa `debug_trace`.
- log có `MAX_TOKENS`, `malformed decision JSON`, hoặc `format_violation_recovered`.
- remote provider trả animation/direction ngoài whitelist như `idle_thoughtful`, `subtle_nod`, `neutral`.
Notes:
- `_complete_decision` hiện dùng output budget: chat `512` tokens, non-chat `384` tokens.
- mọi system prompt cho decision đều được append contract: bắt đầu bằng `{`, kết thúc bằng `}`, đúng 1 compact JSON object, `debug_trace` phải ngắn.
- `debug_trace` phải ngắn: 3-8 words hoặc một marker ngắn. Nếu để model viết trace dài, JSON rất dễ bị cụt.
- Plain prose ngoài JSON vẫn phải bị chặn; chỉ salvage JSON cụt có field `"text"` sạch.
- `generate_micro_presence_line()` và `generate_screen_facts()` cũng ép trả về JSON object riêng, không nhận prose tự do.
Status: ACTIVE CRITICAL VERIFIED_IN_WORKSPACE.

---

# 7. Parser / Grounding

## `src/parser_grounding/service.py`
Role: public DecisionParser API.
Calls: parser_grounding/decision.py mixin.
Debug khi: parse service import/API mismatch.
Status: ACTIVE.

## `src/parser_grounding/decision.py`
Role: parse raw LLM output thành Decision.
Handles:
- JSON strict/lax.
- unwrap structured text.
- salvage prose.
- normalize bool/confidence/action/system_action.
- motion inference.
- capability/perception guard.
Debug khi:
- LLM trả prose nhưng parser không salvage.
- claim screen/action thiếu evidence không bị chặn.
- animation/motion hint lệch.
Status: ACTIVE CRITICAL.

---

# 8. Telemetry / Perception

## `src/telemetry/system.py`
Role: Windows telemetry mixin.
Reads:
- foreground window.
- active app.
- browser/tab via UIAutomation.
- CPU/RAM.
- idle time.
- open windows.
Debug khi: active window/browser title sai.
Status: ACTIVE.

## `src/telemetry/service.py`
Role: telemetry service + screenshot capture.
Outputs:
- dict/snapshot input cho Se.
- JPEG base64 data URI for vision.
Debug khi: screen vision request không có image_data_uri.
Status: ACTIVE.

## `src/cortex/se.py`
Role: SeLens, cảm nhận trực tiếp.
Inputs: telemetry raw.
Outputs:
- TelemetrySnapshot.
- focus context.
- recent events.
- user signals.
- evidence.
- claim_style.
Debug khi:
- ERIS nói quá chắc từ evidence mỏng.
- YouTube/nhạc bị hiểu thành distraction.
- generic window facts tràn prompt.
Status: ACTIVE FRONTLINE EVIDENCE.

---

# 9. Core contracts `src/core/*`

## `src/core/evidence.py`
Role: RawSignal, EvidenceItem, ModuleReport, StateCommitRequest, DebugTrace.
Debug khi: module ghi thẳng memory không qua request, evidence thiếu confidence/source.
Status: ACTIVE CONTRACT.

## `src/core/cognitive_frame.py`
Role: CognitiveFrame contract rộng.
Slots:
- salience, working_memory, workspace, meaning, agency, speech_plan, grounding, etc.
Methods:
- set_slot, add_report, add_commit_request, validate, build_prompt_packet.
Debug khi: frame mutation không audit được.
Status: ACTIVE / PARTIAL MIGRATION.

---

# 10. Cortex cognition `src/cortex/*`

## `src/cortex/contracts.py`
Role: contract runtime cũ/chung.
Contains:
- telemetry snapshot, goal drift, Ti policy, Fe style, percept/social events.
- session ritual, attention broadcast, MeaningLayerResult, PersonalityLensResult.
- appraisal, self state, speech core, speech impulse, thought stream, motivational urge, action plan, cognitive frame, memory update.
Current code specifics:
- `SpeechImpulse` đã có `vital_pressure`, `metabolic_pressure`, `is_vital_pressure` để đưa áp lực nội sinh sang SurfaceArbiter/LLM micro wording.
- `CognitiveActionPlan.to_dict()` hiện serialize `vital_pressure`, `metabolic_pressure`, `is_vital_pressure`.
Status note:
- revision hiện tại đã có ba field này ngay trong dataclass `CognitiveActionPlan`; cảnh báo mismatch cũ không còn là mô tả đúng của `HEAD`.
Debug khi:
- object test double/legacy payload dựng thiếu field contract mới.
- runtime module không hiểu nhau vì caller serialize/deserialize theo schema cũ.
Status: ACTIVE CORE LANGUAGE.

## `src/cortex/attention_salience.py`
Role: chọn evidence đáng chú ý.
Scores:
- novelty, urgency, goal/user/identity/relational relevance.
- affective/risk/unresolved tension.
- recurrence/habituation/false alarm.
Outputs: SalienceFrame.
Debug khi: context flood, signal rác thắng user request, memory echo trồi sai.
Status: ACTIVE.

## `src/cortex/working_memory.py`
Role: bottleneck 3-7 slots.
Inputs:
- frame evidence, salience, memory_packet, goal/relation/affect/constraints.
Outputs:
- WorkingMemoryFrame.
- dominant_thread.
- recall_competition.
- anti_drift_notes.
Debug khi: prompt bị nhồi toàn bộ memory/context.
Status: ACTIVE.

## `src/cortex/background_observer.py`
Role: observer nền không tạo output public.
Inputs: SignalSnapshot + SignalDiff.
Outputs: ObserverFrame.
Modes:
- rule-based.
- optional Ollama text observer.
- sensory adapter route.
Debug khi: wake main quá nhiều hoặc quá ít.
Status: ACTIVE.

## `src/cortex/observer_contracts.py`
Role: SignalSnapshot, SignalDiff, ObserverFrame contract.
Debug khi: observer/signal_buffer/sensory mismatch fields.
Status: ACTIVE CONTRACT.

## `src/cortex/vision_semantic_compressor.py`
Role: nén scene bằng vision model khi salience/diff đủ.
Does not: tự chụp screenshot, tự trả user.
Debug khi: vision compressor chạy khi không cần hoặc OCR-only fallback.
Status: ACTIVE.

## `src/cortex/affect_semantics.py`
Role: phân tích chat user thành pressure nghĩa.
Axes:
- technicality, distress, intimacy, attachment, conflict, correction, objectification, playfulness, directive_pressure, ambiguity, answer_need.
Debug khi: chửi đùa bị hiểu như attack, correction bị bỏ qua, technical request bị emotionalize.
Status: ACTIVE.

## `src/cortex/meaning.py`
Role: biến fact thô thành meaning có thể phản ứng.
Examples:
- code_idle_long -> cognitive_stall.
- tiktok_opened_after_code -> decompression.
- error_visible -> friction_point.
- force_speak -> user_requested_presence.
Outputs:
- MeaningLayerResult.
- semantic_family.
- meaning_shift.
Current code specifics:
- `force_speak`/`channel=force_speak` được map thẳng thành `user_requested_presence`; đây là explicit pull chứ không phải “context rỗng”.
- `_infer_fact()` trộn `snapshot`, `broadcast`, `thought_stream_report`, `user_text`; nó nhìn signal semantic chứ không đọc pixel trực tiếp.
- `ambient_idle` là meaning mềm khi idle/silence/boredom đủ dài; nó không được tự động thăng cấp thành câu chuyện lớn chỉ vì im lâu.
- `_maybe_prolonged_fact()` là semantic bridge mới: nếu cùng semantic family kéo dài đủ lâu thì nảy `prolonged_activity`, mở `meaning_shift_gate` mà vẫn không được bịa chi tiết màn hình.
- `render_prompt_context()` đóng dấu rất rõ: meaning là private pressure layer, không được nói thẳng label kiểu `escape_from_friction`, `cognitive_stall`, `scattered_attention`.
Debug khi:
- autonomous lặp quan sát thô như camera.
- force_speak bị hiểu như thiếu evidence thay vì user gọi hiện diện.
- idle lâu mà `meaning_shift` không bao giờ mở dù activity thực sự bị kéo dài.
Status: ACTIVE CRITICAL.

## `src/cortex/appraisal.py`
Role: sắc thái trước-ngôn-ngữ.
Axes:
- threat, certainty, intimacy, protectiveness, tenderness, amusement, fatigue.
Debug khi: tone quá nóng/lạnh so với context.
Status: ACTIVE.

## `src/cortex/ni.py`
Role: orientation/drift engine.
Uses:
- HybridOrientationInterpreter.
- GoalPersistenceState.
Outputs drift/coherence/intervention pressure.
Debug khi: ERIS nhắc quay lại goal sai, đọc activity lệch.
Status: ACTIVE.

## `src/cortex/orientation_context.py`
Role: lexical fallback + shared orientation contracts.
Handles:
- activity intent.
- goal relation.
- closure detection with negation.
Debug khi: “chưa xong” bị hiểu là xong.
Status: ACTIVE FALLBACK.

## `src/cortex/orientation_semantics.py`
Role: hybrid semantic orientation.
Debug khi: semantic path overread leisure/recovery thành goal conflict.
Status: ACTIVE.

## `src/cortex/semantic_encoder.py`
Role: semantic vector provider/fallback router.
Contains:
- ProviderBacked, Cached, Null, LexicalHashing encoder.
Debug khi: fallback hash bị coi như semantic thật.
Status: ACTIVE INFRA.

## `src/cortex/semantic_hypothesis.py`
Role: compare context with prototypes, produce semantic hypotheses.
Debug khi: dominant label/ambiguity margin sai.
Status: ACTIVE.

## `src/cortex/semantic_prototypes.py`
Role: prototype bank cho activity/goal relation.
Debug khi: muốn tune nhãn semantic mà không sửa engine.
Status: ACTIVE CONFIG-LIKE.

## `src/cortex/ti.py`
Role: TiGovernor, logic/grounding/capability enforce.
Modes:
- observe, chat_code, chat_emotional, resource_guard, goal_drift_alert.
Guards:
- capability violation.
- perception violation.
- screen claim without evidence.
- action claim without execution.
Debug khi: output bịa quyền năng hoặc bị Ti rewrite quá sạch.
Status: ACTIVE CRITICAL GUARD.

## `src/cortex/fe.py`
Role: FeRenderer style/tone.
Tracks:
- FeStyleMemory.
- recent modes/tones/intents/topic tags.
- warmth/sarcasm/brevity bias.
Reads affect/conversation/relationship.
Debug khi: style lạnh, quá formal, quá emotional, type legacy low/mid/high gây crash.
Status: ACTIVE.

## `src/cortex/conversation_dynamics.py`
Role: state hội thoại.
Tracks:
- mode: explore/clarify/repair/relational_repair/execute/compress/defer/settled.
- semantic_tension, correction_severity, frustration_estimate, correction_streak.
Debug khi: user sửa mà ERIS không repair hoặc overrepair.
Status: ACTIVE.

## `src/cortex/relationship_dynamics.py`
Role: state quan hệ lâu hơn một turn.
Tracks:
- familiarity, trust, rupture, repair, ritual_strength.
- attachment_visibility, preferred_distance, dignity_defense, technical_respect.
Debug khi: ERIS bám quá, lạnh quá, không học boundary.
Status: ACTIVE.

## `src/cortex/relationship_event_builder.py`
Role: build RelationshipTurnEvent từ affect/context/evidence.
Debug khi: relationship state update sai vì event classify sai.
Status: ACTIVE.

## `src/cortex/relational_feedback.py`
Role: detect feedback về cách hiện diện.
Detects:
- lạnh, xa cách, robot, máy móc, vô hồn, formal, cứng.
Avoids false positive:
- trời lạnh, máy lạnh.
Debug khi: user chê lạnh mà ERIS phòng thủ/disclaimer.
Status: ACTIVE.

## `src/cortex/personality.py`
Role: PersonalityLens INFJ-ish pressure, không phải roleplay.
Outputs:
- interpretation, stance, coloring, social distance, meaningfulness.
Rules:
- suppression ratio ~70%.
- identity_reduction -> cool_boundary/dry_low_heat.
Debug khi: ERIS quá poetic, quá bám, hoặc thành assistant phẳng.
Status: ACTIVE.

## `src/cortex/internal_state.py`
Role: persistent internal state.
Tracks:
- valence, arousal, curiosity, boredom, social_energy, attachment, fatigue, silence_pressure.
- MentalProcessSystem: curiosity/restraint/tension/continuity/attachment/reflection/social_presence/cognitive_load/background_thought.
Persists:
- goal_persistence, conversation_dynamics, relationship_dynamics, action_memory.
Debug khi: continuity mất sau restart hoặc pressure không decay.
Status: ACTIVE CRITICAL STATE.

## `src/cortex/self_model.py`
Role: SelfModelEngine.
States:
- settled, watchful, engaged, overloaded.
Computes:
- overload, engagement, initiative_bias, brevity_bias, embodiment_bias, continuity_pull.
Debug khi: ERIS tự định nghĩa sai, overhumanize, hoặc objectification không làm lạnh xuống.
Status: ACTIVE.

## `src/cortex/social_presence.py`
Role: nhận biết user hiện diện nền.
Kinds:
- focused_co_presence, passive_companionship, anxious_hovering, fragmented_multitasking, ambient_co_presence, absent/fading.
Debug khi: presence bị hiểu thành lệnh nói.
Status: ACTIVE.

## `src/cortex/event_semantics.py`
Role: semantic tags/clusters cho recent events.
Tags:
- mouse/click/scroll/keyboard/editing/coding/window_switch/restless/build_error/stall/distraction.
Debug khi: event primitive gây embedding spam.
Status: ACTIVE.

## `src/cortex/session_ritual.py`
Role: startup continuity ritual.
Inputs:
- active goal, attractor, unresolved loops, recent direction, self continuity.
Outputs:
- SessionRitualReport.
Debug khi: greeting lạnh hoặc lộ internal label.
Status: ACTIVE.

## `src/cortex/micro_policy.py`
Role: policy cho micro-line.
Rejects:
- generic line.
- no anchor observation.
- blunt emotion declaration.
- no diacritics Vietnamese.
- placeholder/status report.
Debug khi: force_speak/presence line ngu, lặp, hoặc không grounded.
Status: ACTIVE CRITICAL MICRO GUARD.

## `src/cortex/micro_contracts.py`
Role: shared dataclasses/helpers cho micro guard.
Status: ACTIVE CONTRACT.

## `src/cortex/micro_grounding_guard.py`
Role: anchor/grounding validation cho micro line.
Debug khi: micro observation nói lệch evidence.
Status: ACTIVE.

## `src/cortex/micro_repeat_guard.py`
Role: semantic family repeat guard cho micro line.
Status: ACTIVE.

## `src/cortex/micro_surface_lint.py`
Role: lint bề mặt micro line.
Status: ACTIVE.

## `src/cortex/low_level_speech_policy.py`
Role: policy knobs cho utterance thấp tầng.
Does:
- quyết định generation mode: `reject`, `body_only`, `normal_llm`, `force_llm`.
- load config từ `config/low_level_speech_policy.yaml` nếu env không override.
- hỗ trợ parser YAML tối giản nếu PyYAML không có.
- clamp threshold/env để tránh config bẩn phá runtime.
Does not:
- không viết câu public.
- không chọn impulse thắng.
- không bypass grounding/post-generation guard.
Inputs:
- SurfaceImpulse-like object: `should_surface`, `confidence`, `kind`.
- silent_cycles.
Rules:
- dưới `body_only_min_confidence` -> reject.
- silent_cycles >= `force_llm_after_silent` -> force_llm.
- kind trong `always_llm_kinds` và đủ confidence -> force_llm.
- confidence cao -> force_llm.
- confidence vừa -> normal_llm.
- còn lại -> body_only.
Debug khi:
- cue presence đủ mạnh nhưng không gọi LLM.
- silent lâu mà vẫn im.
- env/config YAML không được load.
- body-only nhiều vòng nhưng không leo lên force LLM.
Status: ACTIVE POLICY.

## `src/cortex/surface_arbiter.py`
Role: single source of truth cho low-level surface utterances.
Purpose:
- gom micro presence, re-engagement, spontaneous inner whim, idle curiosity, thought-stream surface.
- chọn có nên surface không và dùng mode sinh nào.
- không hardcode câu thoại public.
Core contracts:
- `SurfaceImpulse`: normalized cue/impulse với kind/source/confidence/pressure/score/topic_seed/evidence/body_action/focus_family.
- `SurfaceDecision`: output cho runtime gồm text/body_only/should_speak/parse_mode/generation_mode/debug_trace/suppressed.
Inputs:
- presence_cue từ `presence_controller`.
- cognitive_frame speech_core `SpeechImpulse`.
- frame/snapshot `surface_impulses`, `low_level_impulses`, `speech_impulses`.
- thought_stream `get_surface_candidates`.
- thought_surface/subconscious seed.
- long silence synthetic impulse.
- extra_impulses.
Pipeline:
1. collect all impulses.
2. normalize/coerce các cue khác nhau thành `SurfaceImpulse`.
3. dedupe theo source/kind/family.
4. loại impulse không `should_surface` hoặc cần external evidence.
5. chọn winner bằng score + priority.
6. áp rate-limit interval/family/body-only streak.
7. hỏi `LowLevelSpeechPolicy` để chọn reject/body_only/normal_llm/force_llm.
8. nếu LLM trả text -> `SurfaceDecision.should_speak=true`.
9. nếu LLM decline và policy cho phép -> body_only.
Current code specifics:
- có synthetic `long_silence_impulse` khi `idle_seconds >= 120` hoặc `silent_cycles >= 3`.
- winner còn đi qua `_ego_gate_reason()` trước rate-limit; mood/rupture/dignity/social_energy/preferred_distance có thể chặn hẳn presence-like impulse dù score đủ.
- `_score_and_select_winner()` cộng nhẹ `vital_pressure` vào score để impulse nội sinh bị nén lâu không thua mãi silence/presence cue yếu.
- `thought_stream_surface` không còn được “leo thang vô cớ” khi thiếu neo: nếu `missing_evidence_ids=true` và `vital_pressure` thấp, confidence/effective score bị cap về vùng khoảng `0.68` thay vì có thể trôi lên `1.00`.
- `thought_stream_surface` giờ phải có payload nội sinh thật (`topic_seed` hoặc `residue_reason`) và ít nhất một anchor nội sinh public-safe như `recent_silence`, `debug_continuity`, `session_ritual_afterglow`, `memory_resonance`, hoặc `unresolved_loop`; thiếu anchor thì bị ép về `forced_body_only:thought_surface_missing_anchor`.
- nếu `silent_cycles` vượt `force_llm_after_silent`, arbiter có thể override `reject` thành `force_llm`.
- `always_llm_kinds` cũng có thể đẩy một kind đủ confidence sang `force_llm` dù policy ban đầu reject.
- `vital_pressure_force_llm_threshold` cũng là đường nâng từ reject lên `force_llm` cho impulse có áp lực nội sinh đủ lớn và vẫn public-safe.
- nếu `body_only_streak` chạm trần, code không rate-limit cứng nữa mà đẩy `silent_cycles` lên ngưỡng force-LLM để tránh kẹt body-only mãi.
- `_mark_attempt()` ghi cả reject/body-only presence-like vào budget thời gian/family cooldown; không đợi đến lúc nói thật mới coi là đã “gõ cửa”.
- `debug_trace` luôn giữ winner + mode + suppressed candidates để soi xung đột impulse.
Debug khi:
- presence/re-engagement bị nhiều module tự nói chồng nhau.
- thought_stream có pressure nhưng không ra surface.
- inner_whim thắng sai micro-presence hoặc ngược lại.
- rate-limit/family cooldown chặn câu tưởng như nên nói.
- LLM trả rỗng rồi body-only streak tăng mãi.
- presence cue đúng score nhưng bị `ego_gate:*` chặn vì mood/distance chứ không phải vì policy threshold.
Important traces:
- `surface_arbiter; kind=...; source=...; mode=...`
- `surface_interval_cooldown`
- `family_cooldown`
- `llm_declined`
- `ego_gate:mood_blocks_presence`
- `ego_gate:dignity_distance`
- `ego_gate:ambient_copresence_no_anchor`
- `suppressed=thought_stream_surface:...`
Status: ACTIVE CRITICAL SURFACE ROUTER VERIFIED_IN_WORKSPACE.

## `src/cortex/goal_persistence.py`
Role: goal nền bền qua turn/session.
Fields:
- summary, source, status, strength, urgency, drift, progress, recurrence, confidence, actionability, intervention_permission, anchors.
Debug khi: active goal bị ghi đè bởi candidate yếu hoặc close sai.
Status: ACTIVE.

## `src/cortex/action_memory.py`
Role: nhớ action gần đây và rhythm.
Tracks:
- social_fatigue, boredom_pressure, exposure_recoil, continuity_pressure, habituation, rhythm_phase.
Debug khi: ERIS lặp cùng kiểu hành động/câu nói.
Status: ACTIVE.

## `src/cortex/thought_stream.py`
Role: substrate suy nghĩ nền.
Owns:
- ThoughtObject.
- association graph.
- prediction tracker.
- tension engine.
- unresolved loop.
- cognitive momentum.
- closure.
- reactivation/reheater.
- surface selector.
Feeds:
- `SurfaceArbiter` qua thought_stream candidates / thought_surface residue.
Debug khi: unresolved loop không giữ, thought pressure không surface, hoặc surface quá nhiều.
Status: ACTIVE CRITICAL SUBSTRATE.

## `src/cortex/agent_mind_persistence.py`
Role: persistent belief/preference/habit cho impulse system.
Stores in: memory_core/agent_mind.json.
Layers:
- persistent belief: `beliefs` với claim/domain/confidence/source/tags/decay/contradiction.
- persistent preference: `preferences` với polarity/strength/stability/source/tags.
- semantic habit: context tags + action pattern + impulse name -> adjustment.
Current seeds đáng chú ý trong `agent_mind.json`:
- `eris.identity.intellectual_detachment`.
- `eris.prefers_pattern_observation`.
- `eris.should_not_sound_like_camera`.
- `presence.status_ping_low_value`.
- `scene.low_risk_casual`.
- `scene.systemic_interest`.
Debug khi:
- feedback “đừng hỏi dồn” không ảnh hưởng hành vi sau.
- ERIS vẫn thích status ping dù đã có belief `presence.status_ping_low_value`.
- habit bias không vào impulse score vì context tags/action/impulse_name không match.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

## `src/cortex/agent_state_stack.py`
Role: contract stack Evidence -> Belief -> Preference -> Need -> Trait -> Habit -> Affordance.
Used by: spontaneous_life / impulse_arbitration / speech/action.
Current code specifics:
- `BeliefSnapshot` thêm INFJ5w4 priors: `silence.ambient_copresence`, `presence.status_ping_low_value`, `eris.prefers_pattern_observation`.
- `PreferenceProfile` tăng trọng số quiet co-presence/pattern observation/cognitive stimulation và giảm companionship thành attendance ping.
- `NeedVector` có đạo hàm tức thời: `silence_pressure`, `boredom_pressure`, `thought_pressure`, `memory_residue_pressure`, `attachment_pressure`, `metabolic_pressure`, `vital_pressure`.
- `metabolic_pressure` là max blend từ silence/boredom/thought/memory/continuity/attachment/social/requested presence.
- `vital_pressure = metabolic_pressure ** 1.45`: áp lực nhỏ bị nén, áp lực lớn được quyền phá im lặng.
- `relation_need` và `social_presence_need` bị mood/social-energy gate; mood xấu hoặc social energy thấp sẽ không biến im lặng thành ping tình cảm.
- `TraitVector` thêm `introverted_observer` và `intellectual_detachment`, làm silence/pattern/inner whim tự nhiên hơn companionship ping.
- `AffordanceMap` bào mòn interrupt cost khi `vital_pressure` cao; code/docs vẫn ma sát cao, nhưng ERIS không hóa đá vĩnh viễn.
Debug khi:
- impulse score thiếu state nền.
- `vital_pressure` nhìn cao nhưng downstream vẫn không surface.
- ERIS biến long silence thành status ping thay vì inner whim/pattern observation.
- force_speak không có screen evidence bị coi như context rỗng thay vì explicit requested presence.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

## `src/cortex/impulse_arbitration.py`
Role: chấm điểm impulse cạnh tranh.
Candidates:
- silence, scene_curiosity, inner_whim, curious_question, micro_story, companionship, random_chatter, memory_resonance, reengagement, technical_help, body_only.
Score terms:
- base, evidence fit, belief support, need pressure, preference fit, trait bias, affordance, habit, risk, repetition, interrupt, resource, metabolic_adjustment.
Current code specifics:
- silence là candidate thật nhưng bị `vital_silence_discount` phạt khi compressed silence/requested presence tăng.
- `scene_curiosity` cần scene affordance/evidence; không được dùng để bịa screen claim.
- `inner_whim`, `random_chatter`, `memory_resonance` là outlet nội sinh/no-screen-claim khi thought/boredom/memory residue tăng.
- `companionship_impulse` bị demote bởi `presence.status_ping_low_value`; co-presence không đồng nghĩa phải nói “tôi còn đây”.
- `reengagement_impulse` là restrained return sau silence dài, không phải attendance ping.
- `technical_help_impulse` chỉ thắng khi competence/task pressure thật.
- `body_only_impulse` vẫn cho presence đi qua motion khi speech quá intrusive.
Debug khi:
- nội sinh có nhưng impulse sai thắng.
- silence thắng dù `metabolic.vital` cao.
- companionship/micro_presence thắng inner_whim vì priors/habit chưa đúng.
- random_chatter chen vào code/docs vì `endogenous_interrupt_cost` hoặc focus tags sai.
Status: ACTIVE CRITICAL VERIFIED_IN_WORKSPACE.

## `src/cortex/inner_thought.py`
Role: biến thought surface/social pressure thành intent nhẹ.
Intents:
- curious_question, inner_whim, random_chatter.
Feeds:
- SpeechImpulse cho `SurfaceArbiter` nếu active và public-safe.
Debug khi: force_speak mỏng không sinh câu hỏi/whim phù hợp.
Status: ACTIVE.

## `src/cortex/spontaneous_life.py`
Role: endogenous speech pressure low-gain.
Reads:
- boredom, silence, thought pressure, memory residue, attachment visibility, fatigue, restraint, cooldown, work-focus penalty.
Outputs:
- SpeechImpulse + arbitration_report + body_bias_hint.
Feeds:
- `SurfaceArbiter` qua speech_core/frame speech impulse.
Debug khi: autonomous im dù có nội sinh, hoặc chen vào lúc user focus code.
Status: ACTIVE.

## `src/cortex/speech_core.py`
Role: chuyển pressure thành quyền public speech.
Inputs:
- snapshot, internal_state, appraisal, ti_report, meaning_layer, thought_surface, self_state, personality_lens, signals, spontaneous_impulse.
Gates:
- meaning_shift_gate.
- quiet_guard.
Outputs:
- AgentSpeechCore with winner/silence state.
Feeds:
- Surface-level `SpeechImpulse` cho `SurfaceArbiter` trong các cue thấp tầng.
Current code specifics:
- các hook fallback cũ (`render_force_speak_repair_text`, `render_safe_fallback_text`) giờ không tự trả public wording nữa; chúng chỉ đóng dấu `requires_dynamic_fallback` + `fallback_intent/context` để wording layer xử lý sau.
- `meaning_shift_gate` chỉ chặn autonomous speech shape cần shift; nếu `spontaneous_impulse` đủ mạnh hoặc silence/internal pressure quá cao thì `_extreme_internal_speech_pressure()` vẫn cho endogenous line đi tiếp vào arbitration.
- `spontaneous_ready` hiện check cả `needs_external_evidence`, `suggested_speech_act`, `surface_pressure`, và `vital_pressure`; force-speak có ngưỡng thấp hơn autonomous.
- `_threshold_for_channel()` không cố định: autonomous threshold tăng theo overload và giảm theo engagement; force_speak gần như mở cổng hoàn toàn.
- `SpeechImpulse` dựng từ `MeaningLayer` vẫn là residue/reactive contract, không phải giấy phép để surface nguyên label nội bộ.
Debug khi: có tension nhưng im, hoặc nói dù không có shift.
- fallback guard vẫn muốn “chữa cháy” bằng câu mẫu cứng dù code hiện tại đã đẩy wording ra downstream layer.
- autonomous bị `meaning_shift_gate` giữ im dù `vital_pressure` hoặc `silence_pressure` nhìn có vẻ đã đủ để cho endogenous leakage.
- `spontaneous_impulse` có act rõ nhưng bị đánh rớt vì `needs_external_evidence=true`.
Status: ACTIVE MOST IMPORTANT SPEECH DEBUG FILE VERIFIED_IN_WORKSPACE.

## `src/cortex/turn_semantics.py`
Role: hiểu nghĩa turn lặp.
Distinguishes:
- low_value_repeat, reask_same_question, repair_reframe, relational_probe, identity_boundary_probe, live_evidence_refresh.
Debug khi: repeat guard chặn nhầm user sửa sai/hỏi lại.
Status: ACTIVE.

## `src/cortex/action_planner.py`
Role: orchestrator chọn action trước LLM.
Calls: ActionUtilityScorer.
Outputs: CognitiveActionPlan.
Debug khi: speech act/animation/style anchor sai.
Status: ACTIVE.

## `src/cortex/action_utility.py`
Role: chấm điểm action space.
Actions:
- no_speech, observe, protect, withdraw, mirror, micro_presence, reengagement, inner_whim, soft_boundary, system_action.
Debug khi: no_speech thắng sai, proactive reengagement quá nhiều.
Status: ACTIVE.

## `src/cortex/daydream_consolidation.py`
Role: 4B consolidation from filtered packets.
Inputs:
- structured memory layers + activation + agenda.
Validator: reject nếu evidence_ids không khớp input.
Debug khi: daydream bịa insight.
Status: ACTIVE.

## `src/cortex/internal_agenda.py`
Role: unresolved agenda stack persist nhẹ.
Stores: memory_core/internal_agenda.json.
Debug khi: agenda mất sau restart.
Status: ACTIVE.

## `src/cortex/self_observation.py`
Role: reflect frame/outcome thành failure class.
Failures:
- misread, overread, overexplained, underacted, tone_mismatch, privacy_intrusion, body_mismatch, assistant_flattening, overhumanization.
Outputs: repair memory request.
Debug khi: lỗi lặp không học sửa.
Status: ACTIVE.

---

# 11. Actions `src/actions/*`

## `src/actions/contracts.py`
Role: whitelist action + ActionExecutionResult.
Actions:
- get_now_playing, focus_window, open_url, set_volume, play_pause_media, copy_text, launch_app, search_web, get_weather.
Debug khi: model/router muốn action ngoài whitelist.
Status: ACTIVE.

## `src/actions/router.py`
Role: regex/router từ chat command sang action.
Debug khi: lệnh rõ vẫn gọi LLM thay vì action.
Status: ACTIVE.

## `src/actions/executor.py`
Role: thực thi action desktop/API.
Debug khi: action nói thành công nhưng OS không làm.
Status: ACTIVE, VERIFY SECURITY.

---

# 12. Memory `src/memory/*`

## `src/memory/memory_cognition.py`
Role: facade commit/recall memory.
Routes StateCommitRequest to:
- event_ledger, active_state, homeostatic_baseline, self_continuity.
- episodic, semantic, relational, affective_residue, procedural, repair.
- memory_candidate / unresolved_memory.
Recall path:
- MemoryCueBuilder -> MemoryRetrievalEngine -> MemoryActivation -> MemoryPacketBuilder.
Also owns: agent_mind store.
Debug khi: commit target sai, recall thiếu layer, memory_candidate không route.
Status: ACTIVE CRITICAL FACADE.

## `src/memory/memory_models.py`
Role: contracts MemoryTarget/Kind/Surface/Decay/CommitDecision/RecallAnswer.
Debug khi: policy -> StateCommitRequest adapter sai.
Status: ACTIVE CONTRACT.

## `src/memory/memory_record.py`
Role: normalize/tokenize/anchor/fingerprint helpers.
Status: ACTIVE INFRA.

## `src/memory/memory_cue.py`
Role: build MemoryCue from query/current context.
Debug khi: recall mode/domain hint sai.
Status: ACTIVE.

## `src/memory/memory_candidate.py`
Role: adapt layer items into common candidate shape.
Status: ACTIVE.

## `src/memory/memory_scoring.py`
Role: relevance/recency/confidence/privacy/layer bias scoring.
Debug khi: procedural/relational recall rỗng dù có data.
Status: ACTIVE.

## `src/memory/memory_activation.py`
Role: select activated candidates/quota/suppression.
Status: ACTIVE.

## `src/memory/memory_retrieval_engine.py`
Role: orchestrator retrieval.
Status: ACTIVE.

## `src/memory/memory_packet_builder.py`
Role: build MemoryPacket final.
Status: ACTIVE.

## `src/memory/event_ledger.py`
Role: append-only raw event ledger.
Debug khi: audit evidence mất.
Status: ACTIVE.

## `src/memory/active_state_snapshot.py`
Role: overwrite current state snapshot.
Debug khi: active goal/session arc/current relation state sai.
Status: ACTIVE.

## `src/memory/episodic_memory.py`
Role: store concrete events.
Status: ACTIVE.

## `src/memory/semantic_memory.py`
Role: stable facts with status/confidence/evidence.
Debug khi: fact mơ hồ thành active truth.
Status: ACTIVE.

## `src/memory/relational_memory.py`
Role: relation patterns.
Status: ACTIVE.

## `src/memory/affective_residue_memory.py`
Role: affective pressure residue, not public claim.
Debug khi: ERIS nói “tôi buồn/cô đơn” từ residue.
Status: ACTIVE.

## `src/memory/procedural_memory.py`
Role: learned handling rules.
Status: ACTIVE.

## `src/memory/repair_memory.py`
Role: failure + correction + future suppression rule.
Status: ACTIVE.

## `src/memory/unresolved_memory.py`
Role: memory_candidate store.
Debug khi: explicit remember but parse unclear.
Status: ACTIVE.

## `src/memory/memory_consolidator.py`
Role: reprocess unresolved candidates during reflection.
Debug khi: candidate never promotes or promotes hallucinated fact.
Status: ACTIVE.

## `src/memory/memory_commit_policy.py`
Role: rule extraction from user turn into MemoryCommitDecision.
Extracts:
- name, birth year/month, observed age, place/current residence, response style, memory test hint, preference, user_convention.
Guards:
- do not commit questions as facts.
Debug khi: “tôi tên X” không nhớ hoặc “tôi tên gì” bị commit thành fact.
Status: ACTIVE CRITICAL.

## `src/memory/memory_recall_policy.py`
Role: surface policy for RawRecallResult.
Decides:
- exact quote/gist/count/explain/admit uncertain.
Status: ACTIVE.

## `src/memory/memory_query_ir.py`
Role: IR/AST memory query.
Status: ACTIVE CONTRACT.

## `src/memory/memory_turn_graph.py`
Role: graph from session_turn_ledger.
Used for exact ordinal/count/relations.
Status: ACTIVE.

## `src/memory/memory_turn_annotator.py`
Role: annotate turn thô thành `TurnNode` có speech_act/tags/fact_mentions rồi dựng edge cho `TurnGraph`.
Does:
- detect fallback kỹ thuật để không coi lỗi service là answer semantic.
- gắn speech act như question/command/correction/fact_disclosure/answer/repair.
- extract một số fact mention tiếng Việt như `user.name`, `user.birth_month`, `user.current_location`, `user.past_location`, `user.response_style`.
- build edges `ANSWERS`, `CORRECTS`, `REPEATS`, `STORES_FACT`.
Boundary:
- không tự trả lời memory query.
- không quyết định user đang hỏi loại IR nào.
Status: ACTIVE.

## `src/memory/memory_query_slot_parser.py`
Role: slot parser Vietnamese memory queries.
Status: ACTIVE.

## `src/memory/memory_query_semantics.py`
Role: semantic hints for ambiguous memory query.
Status: ACTIVE.

## `src/memory/memory_query_llm_parser.py`
Role: optional LLM JSON parser for `MemoryQueryIR`, không phải answer generator.
Debug khi: slot/semantic parser local không đủ để parse query mơ hồ nhưng cũng không được để LLM trả lời thay memory system.
Status: ACTIVE.

## `src/memory/memory_query_compiler.py`
Role: compile query from slot/semantic/repair/LLM parser.
Status: ACTIVE.

## `src/memory/memory_query_executor.py`
Role: execute MemoryQueryIR over TurnGraph/memory_core.
Status: ACTIVE.

## `src/memory/memory_query_repair.py`
Role: prior store for corrected memory query binding.
Status: ACTIVE.

## `src/memory/understanding/*`
Role: parse user text into MeaningFrame.
Files:
- meaning_frame.py.
- entity_linker.py.
- polarity_temporal.py.
- semantic_parser.py.
Debug khi: memory intake parse sai subject/target/time/certainty.
Status: ACTIVE.

## `src/memory/semantic_text.py`, `semantic_claim.py`, `claim_extractor.py`, `claims/*`
Role: convert text/MeaningFrame into SemanticClaim/ExtractedClaim with ontology.
Status: ACTIVE.

## `src/memory/predicate_ontology.py`, `query_intent.py`, `claim_entailment.py`, `semantic_answer_policy.py`
Role: query-answer ontology for memory facts.
Debug khi: overlap text trả lời sai predicate.
Status: ACTIVE.

## `src/memory/memory_worthiness.py`, `memory_retention_policy.py`, `judgement/*`, `claim_consolidator.py`, `memory_pruner.py`
Role: judge keep/promote/prune memory lifecycle.
Debug khi: memory rác được giữ, memory quan trọng bị prune, candidate không promote.
Status: ACTIVE.

---

# 13. memory_core data files

## `memory_core/*.json`
Role: runtime persistent state.
Files đáng chú ý:
- active_state_snapshot.json.
- agent_mind.json.
- episodic_memory.json.
- semantic_memory.json.
- event_ledger.json.
- memory_candidate.json.
- internal_agenda.json.
Debug khi:
- behavior sai nhưng code có vẻ đúng: kiểm tra data/state tích lũy.
Rule:
- phân biệt bug logic với state bẩn. Đây là nơi nhiều người tự bắn vào chân rồi đổ lỗi cho kiến trúc, truyền thống cao quý của nghề code.
Status: RUNTIME DATA.

## `memory_core_backup_*/`
Role: backup memory core.
Debug khi: muốn so sánh state trước/sau.
Status: BACKUP DATA.

---

# 14. Training / Dataset / Scripts

## `src/full_train_dataset.py`, `src/full_train.ipynb`
Role: build dataset train, normalize conversation/context/action.
Debug khi: dataset context sai shape.
Status: TRAINING SUPPORT.

## `src/datasets_clean/*`
Role: cleaned datasets: desktop/persona/fe/se/tools + quarantine.
Status: TRAINING DATA.

## `scripts/clean_split_jsonl.py`
Role: clean/split JSONL.
## `scripts/build_fe_style_supervision.py`
Role: generate FE style supervision.
## `scripts/build_se_supervision.py`
Role: generate Se supervision.
## `scripts/extend_dataset_infj.py`
Role: expand INFJ style data.
## `scripts/prune_dataset_infj.py`
Role: prune weak/redundant INFJ samples.
## `scripts/quarantine_desktop_overinference.py`
Role: quarantine desktop over-inference samples.
## `scripts/rewrite_dataset_infj.py`
Role: rewrite style dataset.
## `scripts/split_training_jsonl.py`
Role: split train/eval/groups.
## `scripts/uniqueify_dataset_assistant.py`
Role: reduce duplicate assistant outputs.
Status: OFFLINE SUPPORT.

---

# 15. Tests

## `tests/test_runtime_coordinator.py`
Role: orchestration regression.
Covers:
- chat/autonomous/force_speak.
- micro_presence/presence/reengagement.
- session ritual.
- action route.
- vision facts.
- repeat guard.
- public turn ledger.
- source grounding.
Debug when: integrated behavior breaks.
Status: CRITICAL TEST.

## `tests/test_llm_service.py`
Role: LLM service fallback/contract/context.
Notable recent coverage:
- `generate_micro_presence_line()` trả tiny text qua JSON API riêng.
- salvage malformed decision JSON mà không leak `intent/debug_trace/action` vào `text`.
- Gemini/OpenAI-compatible metadata không được wrap thành public speech.
- coerce decision-like JSON thiếu field/sai kiểu/sai spacing mà không phải dùng wrapper prose.
Status: CRITICAL TEST.

## `tests/test_llm_client.py`
Role: provider clients/payload fallback/key normalization.
Status: ACTIVE.

## `tests/test_decision_parser.py`, `tests/test_parser_climb.py`
Role: parser/motion/capability regression.
Status: CRITICAL.

## `tests/test_memory_store.py`, `tests/test_memory_commit_protocol.py`, `tests/test_memory_query_system.py`
Role: memory store/commit/query tests.
Status: CRITICAL.

## `tests/test_semantic_claim_entailment.py`
Role: claim-query entailment.
Status: CRITICAL for memory correctness.

## `tests/test_se_lens.py`, `tests/test_attention_salience.py`, `tests/test_background_observer.py`
Role: perception/attention/observer tests.
Status: ACTIVE.

## `tests/test_appraisal_engine.py`, `tests/test_fe_renderer.py`, `tests/test_personality_lens.py`, `tests/test_meaning_layer.py`
Role: cognition/style/meaning regression.
Status: ACTIVE.

## `tests/test_speech_core.py`, `tests/test_micro_policy.py`, `tests/test_inner_thought.py`, `tests/test_subconscious.py`
Role: speech/internal/micro/substrate regression.
Status: CRITICAL for “có hồn nhưng không spam”.

## `tests/test_model_budget_policy_queue.py`
Role: queue/lease regression cho heavy-model scheduler.
Covers:
- queue-only mode với `resource_guard_enabled=false`.
- heavy tiers không overlap.
- cancel queued request trước khi nó chạy.
- `vision_force_run` bỏ qua soft guard/queue timeout nhưng vẫn tôn trọng hard veto như GPU overheat.
- `force_local_gguf_main` có priority lane riêng.
Debug khi:
- log có `model_queue_timeout`, `model_request_cancelled`, `vision_force_run`, `scheduler_allow`.
- main/vision/daydream tưởng đã bỏ guard nhưng vẫn nghẽn vì queue head hoặc timeout lane.
Status: CRITICAL QUEUE TEST.

## `tests/test_surface_arbiter.py`
Role: unit tests độc lập cho low-level surface arbitration.
Covers:
- presence cue force LLM sau silence.
- spontaneous impulse thắng weak presence khi score cao hơn.
- LLM decline chuyển thành body_only và track streak.
- YAML/config loader.
- default repo YAML load khi env thiếu.
Debug khi:
- sửa `SurfaceArbiter` làm micro-presence im.
- config threshold đổi nhưng runtime không ăn.
- body-only streak/rate-limit hành xử lạ.
Status: CRITICAL SURFACE TEST.

## `tests/test_presence_controller_memory_surface.py`
Role: regression test cho đường `active_memory_resonance -> endogenous surface impulse`.
Covers:
- memory resonance public-safe được convert thành `SurfaceImpulse(kind="memory_resonance")`.
- affective/private resonance `may_surface=false` không được surface.
Debug khi:
- memory residue đúng ra chỉ nên thành low-claim muse nhưng lại im hoàn toàn.
- affective residue private bị lộ ra presence/surface path.
Status: ACTIVE TARGETED REGRESSION.

## `tests/test_ti_governor.py`
Role: capability/perception guard regression.
Status: CRITICAL.

## `tests/test_self_model.py`, `tests/test_session_ritual.py`, `tests/test_internal_state.py`, `tests/test_conversation_dynamics.py`, `tests/test_relational_feedback.py`
Role: continuity/self/relation/dialogue state tests.
Status: ACTIVE.

## `tests/test_eris_pathology_scenarios.py`, `tests/eris_test_adapter.py`
Role: observable pathology regression without full runtime.
Status: CRITICAL BEHAVIOR TEST.

## `tests/test_action_router.py`
Role: command-to-action mapping.
Status: ACTIVE.

## `tests/test_full_train_dataset.py`, `tests/test_build_fe_style_supervision.py`
Role: dataset/training scripts.
Status: SUPPORT.

---

# 16. Debug decision table

## Case: user hỏi “lỗi này là gì” nhưng không có screenshot
Check:
1. `chat_cycle.py` calls source grounding.
2. `source_grounding.py` detects deictic/current_screen.
3. If no screen evidence -> missing_evidence.
4. LLM should be preempted or output guarded.
5. `post_generation_filters.py` chat_grounding_guard catches any escaped claim.

## Case: force_speak im hoặc nói rỗng
Check:
1. Godot sends force_speak on 4243.
2. coordinator/frame_builder creates CognitiveDisturbance `requested_presence`.
3. thought_stream receives disturbance.
4. spontaneous_life/inner_thought propose impulse.
5. speech_core force_speak threshold near 0.
6. micro_policy rejects generic/no-anchor bad line.
7. post_generation_filters final force_speak guard.

## Case: autonomous không nói dù có nội sinh
Check:
1. signal_buffer/background_observer diff.
2. contextual_autonomy_loop wake decision.
3. autonomous_wake_governor should_wake_main/should_speak.
4. thought_stream surface selector.
5. spontaneous_life impulse score.
6. speech_core meaning_shift_gate / quiet_guard.
7. action_utility no_speech score.
8. SurfaceArbiter collected the impulse and did not rate-limit it.
9. WakeDecision có bị degrade từ `wake_main_cognition` xuống `micro_presence` hoặc `think_only` vì `interrupt_cost`/`speech_value` không.
10. `model_budget_policy` queue có active heavy lease nào giữ head quá lâu không (`queue_state().active`, `queue_state().queued`).
11. Nếu thấy `resource_guard:*`, `gpu_overheat`, hoặc `tier_cooldown_active`, kiểm tra env `ERIS_RESOURCE_GUARD_ENABLED`; mặc định hiện tại phải là queue-only.
12. Nếu `CognitiveFrame.to_dict()` fail, kiểm tra mismatch `CognitiveActionPlan` field vs `to_dict()` trước khi đổ lỗi cho speech/surface.

## Case: vision/main/daydream vẫn bị nghẽn dù đã bỏ Resource Guard
Symptom:
- log còn báo `model_queue_timeout`.
- wake decision đúng `call_vision_compressor` nhưng facts không update.
- `can_run()` reason là `scheduler_allow`, nhưng request vẫn không vào inference thật.
Check:
1. `ModelBudgetPolicyConfig.resource_guard_enabled` có thật sự false không.
2. `queue_state().active` có heavy lease đang chạy lâu không.
3. caller có truyền `timeout_seconds` ngắn làm request tự timeout dù guard đã tắt không.
4. `vision_force_run_queue_timeout_seconds` có bị env override khỏi `0.0` không.
5. `max_queue_size` chỉ bị bypass cho `force_local_gguf` và `vision_force_run`; các tier khác vẫn có thể `model_queue_full`.
6. Nếu muốn debug guard cũ, bật `ERIS_RESOURCE_GUARD_ENABLED=1` có chủ đích rồi mới đọc `resource_guard:*`.
Fix direction:
- Với máy luôn CPU/GPU/VRAM cao, để `ERIS_RESOURCE_GUARD_ENABLED` trống hoặc `0`.
- Giữ queue để tránh chạy chồng model nặng; đừng disable queue trừ khi đang smoke test rất nhỏ.
- Nếu vision timeout vì active main đang giữ lease, tăng caller timeout hoặc dùng lane priority/timeout riêng.

## Case: low-level surface cue có nhưng ERIS vẫn im/body-only
Symptom:
- presence/re-engagement/thought_stream có cue, nhưng final decision `should_speak=false`.
- debug_trace có `surface_rate_limited`, `surface_reject`, `body_only_by_policy`, `llm_declined`.
Check:
1. `presence_controller.py` cue có `needs_micro_presence=true`, confidence, focus_family, evidence không.
2. `surface_arbiter.py` `_collect_all_impulses` có nhận cue từ presence/frame/thought_stream/extra_impulses không.
3. `_score_and_select_winner` có loại vì `should_surface=false` hoặc `needs_external_evidence=true` không.
4. `_rate_limit_reason` có chặn vì `min_surface_interval_seconds`, `family_cooldown_seconds`, hoặc `max_body_only_streak` không.
5. `low_level_speech_policy.py` threshold có đẩy mode thành reject/body_only thay vì normal_llm/force_llm không.
6. LLM micro generator có trả text rỗng khiến body_only không.
7. `post_generation_filters.py` có chặn micro-line sau khi sinh không.
8. `silent_cycles` đã đủ ngưỡng để `SurfaceArbiter` tự override sang `force_llm` chưa, hay vẫn còn đang dưới `force_llm_after_silent`.
9. Có synthetic `long_silence_impulse` được thêm vào pool nhưng bị impulse khác đè điểm không.
10. Nếu wake-gated log ghi `stage=surface_arbiter`, `rejected_by` giờ phải phản ánh `SurfaceDecision.debug_trace/reason` thật của lượt hiện tại; `reject:not_started` không còn là reject hợp lệ, mà là dấu hiệu status adapter đang đọc sai state cũ/sentinel.
11. Nếu winner là `thought_stream_surface`, kiểm tra nó có payload nội sinh thật và có anchor kiểu `anchor=recent_silence` / `anchor=debug_continuity` / `anchor=session_ritual_afterglow` / `anchor=memory_resonance` / `anchor=unresolved_loop` không; thiếu thì phải body-only chứ không nên thắng slot nói.
12. Nếu presence-like route thiếu evidence mà vẫn muốn nói, kiểm tra `surface_contract` có `thin_presence_no_screen` chưa; nếu chưa có, LLM dễ tự decline hoặc trượt sang status ping vô hồn.
13. Nếu planner/action vẫn ghi `presence_maintenance` nhưng winner thật là route khác, kiểm tra `surface_override` trong `action_plan.notes` hoặc `final_decision` để biết có mismatch route hay không.
Fix direction:
- Tune `config/low_level_speech_policy.yaml` trước, đừng rải thêm câu mẫu trong từng module.
- Nếu cue thiếu evidence, sửa source cue; nếu policy reject đúng thì không ép LLM.
- Nếu body-only streak kẹt, kiểm tra `body_only_after_llm_decline` và `max_body_only_streak`; code hiện tại sẽ cố đẩy sang force-LLM chứ không muốn kẹt body-only vô hạn.

## Case: low-level speech policy config không ăn
Check:
1. `ERIS_SURFACE_POLICY_CONFIG` có trỏ sai path không.
2. Nếu env trống, `_default_policy_config_path()` có thấy `config/low_level_speech_policy.yaml` không.
3. YAML key có đúng tên config dataclass không.
4. Env override có đang đè YAML không.
5. `tests/test_surface_arbiter.py::test_default_repo_yaml_is_loaded_when_env_is_missing`.

## Case: ERIS nói như camera/telemetry logger
Check:
1. Se claim_style.
2. AttentionSalience suppress generic evidence.
3. MeaningLayer converts fact -> meaning.
4. PersonalityLens suppression.
5. LlmService prompt contract.
6. Ti/post_generation_filters remove raw observation claim.

## Case: chat mất câu trả lời vì JSON cụt / malformed decision JSON
Symptom:
- Raw API text có `"text"` sạch nhưng JSON dừng giữa field sau đó, thường là `debug_trace`.
- Log báo malformed JSON, `MAX_TOKENS`, hoặc format violation dù nội dung trả lời nghe ổn.
Check:
1. `src/llm/service.py` `_complete_decision` max_tokens có đủ cho full schema không.
2. Prompt contract có ép compact JSON và `debug_trace` ngắn không.
3. `_strict_decision_candidate_or_raise` có gọi `_coerce_malformed_decision_payload` trước khi raise không.
4. `_coerce_malformed_decision_payload` chỉ lấy field `"text"` sạch, không surface raw JSON/schema.
5. Nếu không có `"text"` sạch hoặc có prompt leak -> `_build_protocol_failure_fallback`.
6. `parser_grounding/decision.py` không được nhận raw malformed JSON như public speech.
7. `chat_cycle.py` format fallback chỉ nên chạy sau khi LlmService không salvage được.
8. Xác nhận `_complete_decision` vẫn còn append compact-JSON contract vào system prompt, nhất là ở các nhánh retry/context shrink/local fallback.
Fix direction:
- Tăng output budget cho decision schema đầy đủ.
- Giữ `debug_trace` cực ngắn.
- Không sửa bằng cách wrap raw malformed JSON vào `text`.
- Remote provider không tuân grammar/schema thì sanitize animation/direction sau parse, nhưng lỗi JSON cụt phải xử lý trước parse.

## Case: memory trả lời sai
Check:
1. memory_commit_policy did it store fact correctly?
2. MemoryCognitionCore target/layer.
3. memory_query_compiler IR.
4. TurnGraph vs memory_core executor.
5. SurfacePolicy exact/gist/count.
6. SourceGrounding memory_answer_allowed.

## Case: body nhận payload nhưng không động
Check:
1. Decision.to_payload motion fields.
2. UDP payload at Godot.
3. UdpDecisionParser HasExplicitMotion.
4. MotionController busy state.
5. LocalBodyAutonomy cooldown/action score.
6. Animation exists in Monika.tscn.

---

# 17. Những gap cần sửa tiếp trong tài liệu/source-map

1. Cần clone repo và chạy script generate inventory thật:
   - list all files.
   - LOC.
   - imports.
   - class/function names.
   - call graph sơ bộ.
   - dead/legacy candidate.

2. Cần thêm bảng ownership:
   ```text
   file | owner layer | reads | writes | called by | calls | debug symptom
   ```

3. Cần thêm state map:
   ```text
   internal_state.json -> read by X -> written by Y
   memory_core/semantic_memory.json -> read by A -> written by B
   ```

4. Cần thêm guard map:
   ```text
   source_grounding -> parser_grounding -> Ti -> post_generation_filters -> micro_policy
   ```

5. Cần thêm test coverage map:
   ```text
   file -> covered by tests -> missing tests
   ```

6. Cần phân loại rõ:
   - ACTIVE.
   - ACTIVE BUT GOD OBJECT.
   - FACADE.
   - LEGACY.
   - GENERATED.
   - CONFIG.
   - SHOULD_NOT_COMMIT.

7. Với các section đã đọc source thật trong revision này, nên gắn marker `VERIFIED_IN_WORKSPACE` để tách khỏi phần còn đang dựa trên source-map/tài liệu.

---

# 18. Kết luận debug

`tongquat.md` hiện tại mô tả kiến trúc theo hướng debug tốt hơn bản `Tongquat.txt` cũ, nhưng vẫn chưa đủ chuẩn audit tuyệt đối vì còn thiếu:
- bảng dependency.
- bảng state read/write.
- bảng symptom -> file.
- trạng thái active/legacy/generated.
- test coverage map.

Bản `tongquat.md` này là bước chuyển từ “tổng quan kiến trúc” sang “bản đồ debug”. Ở revision hiện tại, nó đã bám đúng việc `HEAD` đang sync với `origin/main` và workspace còn vài local patch chưa commit; nhưng nó vẫn cần một lần audit bằng source thật để thành file-to-file hoàn chỉnh tuyệt đối.
