# ERIS DEBUG SOURCE MAP

AUDIT 2026-06-08 WORKSPACE HIEN TAI:
- Tai lieu nay dang gan voi `HEAD d287f57`, nhung workspace hien tai da co them thay doi dirty/untracked. Doc cac muc ben duoi nhu source map co lich su, khong phai snapshot sach 100%.
- Source dirty/untracked can luu y khi doi chieu: `src/runtime/chat_cycle.py`, `src/runtime/coordinator.py`, `src/core/evidence_normalizer.py`, `src/runtime/cognitive_pipeline.py`, `src/runtime/debug_trace.py`, `src/runtime/shadow_pipeline.py`, `tests/test_cognitive_pipeline.py`, `tests/test_shadow_pipeline.py`.
- Local `llama-server` / `GGUF` khong con la runtime path chinh trong workspace hien tai. Cac doan ben duoi noi `ErisProcessManager.cs` spawn llama-server, `process_manager.py` reuse/kill llama-server, hoac adapter dung `llama_server` provider deu la LAC HAU neu doc theo source hien tai.
- Model paraphrase that su van nen o Git LFS; `.cache/` khong can sync giua may, cache co the tu tao lai. Hai GGUF local `src/moondream2-q4_k.gguf` va `src/moondream2-mmproj-f16.gguf` khong con nam trong working tree hien tai.
- So dong hot file da lech: `body/UdpListener.cs` khoang `3,908`, `body/ErisProcessManager.cs` khoang `265`, `src/llm/process_manager.py` khoang `134`, `src/runtime/coordinator.py` khoang `6,952`, `src/runtime/private_mind_model_adapter.py` khoang `1,160`.

Mục tiêu: debug repo ERIS theo kiểu file-to-file — file nào giữ vai trò gì, state nào đọc/ghi, đường gọi nào cần soi khi lỗi.

Snapshot: `HEAD d287f57` (2026-06-08). Lịch sử git delta và audit drift nằm ở `git_audit.md`.

Giới hạn trung thực:
- Bản này chưa phải inventory toàn repo theo kiểu đọc từng dòng tất cả source.
- Revision hiện tại đã đối chiếu source thật cho các điểm nóng: `coordinator.py`, `surface_arbiter.py`, `speech_core.py`, `presence_controller.py`, `autonomous_wake_governor.py`, `no_fallback_policy.py`, `MotionController.cs`.
- File đánh dấu `VERIFY_IN_CODE` cần mở source để xác nhận function/class cụ thể.
- Dùng để debug luồng, không dùng làm README public.

---

# 0B. Repo snapshot hiện tại

Snapshot thô để khỏi phải đoán “repo giờ to đến đâu”:
- tổng source code đã đếm: khoảng `135,525` dòng trong `329` file code (`.py` + `.cs`).
- riêng Python: `129,671` dòng trong `323` file.
- riêng C#: `5,854` dòng trong `6` file.
- **DRIFT NOTE 2026-06-08**: các con số này tính trên tracked `HEAD d287f57`. Nếu tài liệu còn ghi `129,467` dòng / `317` file, hoặc coi chúng là snapshot dirty sau `aa1d303`, thì đó là số cũ.

Phân theo vùng chính:
- `src/`: `237` file code, khoảng `109,140` dòng.
- `tests/`: `70` file code, khoảng `15,286` dòng.
- `body/`: `6` file code C#, khoảng `5,854` dòng.
- `scripts/`: `11` file, khoảng `4,408` dòng.
- `memory_core/`: `10` file dữ liệu/state, khoảng `5,299` dòng JSON.
- `config/`: `5` file, khoảng `126` dòng.

Các cụm Python lớn nhất hiện tại:
- `src/cortex/`: `105` file, khoảng `51,843` dòng.
- `src/runtime/`: `44` file, khoảng `32,154` dòng.
- `src/memory/`: `59` file, khoảng `14,605` dòng.

Hot files đã soi trực tiếp trong workspace (UPDATED audit 2026-06-08):
- `src/runtime/coordinator.py`: khoảng `6,935` dòng (doc cũ ghi `6,681`/`6,862`; sau `8e915de` còn có `aa1d303`, `0ac74ec`, `d287f57`).
- `src/runtime/presence_controller.py`: khoảng `2,693` dòng (doc cũ ghi `2,432`; SurfaceSeedCompiler integration).
- `src/cortex/surface_arbiter.py`: khoảng `1,564` dòng (doc cũ ghi `1,268`; phình qua `9bbdcd2` -> `3782f41` rồi chạm tiếp ở `0ac74ec`).
- `src/cortex/surface_seed_compiler.py`: khoảng `644` dòng (file mới tracked `3782f41`, mở rộng lane `private_life` từ `aa1d303`).
- `src/runtime/autonomous_wake_governor.py`: khoảng `234` dòng, nhỏ hơn nhiều nhưng là gate wake rất nhạy.
- `src/llm/process_manager.py`: khoảng `534` dòng (doc cũ ghi `459`; n_ctx reuse + private mind base).
- `src/cortex/subconscious/model_synthesizer.py`: khoảng `374` dòng, là Lane 3 private synthesis mới thêm ở `637e7fc`.
- `src/actions/executor.py`: khoảng `607` dòng, không còn là action stub nhỏ mà là desktop/API executor thực thụ.
- `src/runtime/private_mind_daemon.py`: khoảng `303` dòng (file mới tracked `3782f41`, lifecycle owner).
- `src/runtime/private_mind_loop.py`: khoảng `322` dòng (tracked `f8555c6`, sửa tiếp `3782f41` và `8e915de`).
- `src/runtime/private_mind_model_adapter.py`: khoảng `1,155` dòng (tracked `f8555c6`, parser/schema ở `3782f41`, transient resilience ở `8e915de`, adapter-pool/slicer path đã nằm trong tracked source từ `aa1d303`).
- `src/cortex/private_mind/mini_evaluators.py`: khoảng `104` dòng (`fragment_adapter(evaluator_name)` là tracked behavior hiện tại, không còn là local patch).
- `src/cortex/private_mind/inner_synthesizer.py`: khoảng `261` dòng (`synthesis_adapter` đã là tracked behavior hiện tại).
- `src/cortex/private_mind/inner_diary_renderer.py`: khoảng `211` dòng (file mới tracked `8e915de`, mở rộng tiếp ở `0ac74ec` và `d287f57`).
- `body/UdpListener.cs`: khoảng `3,972` dòng (tracked Inner Diary/Private Mind panel ở `8e915de`, UI/diary expansion ở `0ac74ec`, chạm tiếp ở `d287f57`).

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

## `src/src.zip`
Role: artifact nén source nội bộ trong workspace.
Debug khi: chỉ đáng để ý nếu tool/script nào đó đang đọc snapshot zip thay vì tree source thật.
Status: GENERATED ARTIFACT / SHOULD_NOT_DRIVE_ARCHITECTURE.

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
DOC DRIFT 2026-06-08 WORKSPACE:
- Source hien tai khong con la noi export/config wrapper cho local `llama-server`; cac note cu neu noi UdpListener noi llama/GGUF la LAC HAU.
- Chat panel sizing vua duoc chinh trong workspace: `targetHeight=64`, submit button khoang `70..88` px theo scale, close button khoang `32..40`, slice/radius nho hon de nut `Gui` khong bi bop va khong qua to.
- Khi debug UI chat hom nay, soi `UpdateChatPanelLayout()` va `ApplyChatButtonLayout()` truoc, khong soi runtime model wiring.

Role: trung tâm body runtime.
Owns:
- UDP receive decision port 4242.
- UDP send event/chat port 4243.
- chat panel, bubble, context menu.
- emotion debug panel và private mind / Inner Diary panel.
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
Current code specifics:
- Tracked history gần: `8e915de` -> `f8555c6` -> `a9e6c58` -> `c7f5b29` -> `8a6f9a1` -> `2797a19` -> `de630ba` -> `763d203`.
- AUDIT 2026-06-07: `8e915de` tracked Private Mind context button và `PrivateMindPanel`.
- `RefreshPrivateMindPanel()` ưu tiên render `inner_diary.sections`/`inner_diary.text` do `InnerDiaryRenderer` tạo ra; nếu không có thì fallback hiển thị raw private-mind menu JSON.
- `ParseAndApply()` giữ `payload.PrivateMindDebugJson` khi parser thấy `private_mind_digest` hoặc `emotion_debug.private_mind`, rồi refresh panel nếu đang mở.
- AUDIT 2026-06-08: cụm UI này nay đã là tracked source qua `0ac74ec` rồi được chạm tiếp ở `d287f57`: parse `PrivateMindDiarySection`/`PrivateMindDiaryItem`, khung/scroll asset riêng cho Inner Diary, lưu state panel ở `user://inner_diary_state.json`, và emotion panel có thêm `Casual Mode` bên cạnh `Dev`.
- DOC DRIFT 2026-06-08: section này không nên viết như thể `UdpListener` đã "sạch" sau khi tách helper. Source hiện vẫn còn một cụm state/hàm legacy trong chính file này (`_moveSpeed`, `_moveDir`, climb fields, `ApplyAnimationCommand()`, `StartClimb()`, process/log helper wrappers) dù đường chạy chính đã đi qua `MotionController`, `ErisProcessManager`, `BodyAudioController`.
Debug khi:
- body không nhận text: kiểm tra bind 4242, payload JSON, `should_speak`.
- chat không sang Python: kiểm tra send 4243, event shape.
- body override sai: kiểm tra explicit motion vs body_bias.
- private mind panel trống: kiểm tra `HasPrivateMindDebug`, `_latestPrivateMindDebugJson`, digest có `inner_diary` hay chỉ có `menu`.
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
Current code specifics:
- Tracked history gần: `f8555c6` -> `de630ba` -> `afec1a5` -> `763d203`.
- AUDIT 2026-06-07: `f8555c6` là mốc tracked thêm private mind debug cho parser này cùng `src/transport/udp.py`; source hiện parse thêm private mind debug.
- `TryReadPrivateMindDebugJson()` nhận `private_mind_digest` ở top-level hoặc fallback `emotion_debug.private_mind`, rồi giữ raw JSON trong `PrivateMindDebugJson`.
- Nếu parse JSON hỏng nhưng raw là plain text, parser vẫn surface raw text; nếu raw giống JSON/code fence lỗi thì fallback `"Loi duong truyen tin hieu."`.
- `HasExplicitMotion` chỉ bật khi có `motion_intent`, `motion_facing != 0`, hoặc `motion_target_x >= 0`; còn `HasRemoteMotion` rộng hơn vì animation/next_animation/facing/target cũng tính là remote command.
Debug khi:
- payload có text nhưng bubble không hiện.
- animation bị reject.
- motion không chạy dù Python gửi.
- private mind debug không hiện trong UI: kiểm tra payload có `private_mind_digest` hoặc `emotion_debug.private_mind`, rồi kiểm tra `HasPrivateMindDebug`.
Status: ACTIVE.

## `body/ErisProcessManager.cs`
DOC DRIFT 2026-06-08 WORKSPACE:
- CAC DONG BEN DUOI noi file nay start/stop `llama-server`, inject `LLAMA_SERVER_*`, `GGUF_MODEL_PATH`, `ERIS_N_CTX`, hoac build llama arguments la LAC HAU so voi source hien tai.
- Source hien tai chi quan ly Python `src/vision.py`, doc secrets/remote config, va inject env cho Python runtime.
- Env hien tai dang inject gom `PYTHONUTF8`, `PYTHONIOENCODING`, `PYTHONUNBUFFERED`, `ERIS_REMOTE_API_ENABLED`, `ERIS_REMOTE_PROVIDER`, `ERIS_REMOTE_BASE_URL`, `ERIS_REMOTE_MODEL`, `ERIS_REMOTE_API_KEY`/`GEMINI_API_KEY` khi co, `ERIS_LOCAL_STYLE_REWRITE_ENABLED=0`, `ERIS_LOCAL_VISION_FACTS=0`.
- Neu debug "llama-server khong mo", dung doc cu ben duoi se sai huong; workspace hien tai khong con spawn local llama-server tu C#.

Role: start/stop Python `vision.py` và llama-server.
Reads: Godot export config/env.
Writes: process lifecycle, stdout/stderr log.
Injects env:
- PYTHONUTF8, PYTHONIOENCODING, PYTHONUNBUFFERED.
- LLAMA_SERVER_*, GGUF_MODEL_PATH, ERIS_N_CTX.
- remote API vars, GEMINI_API_KEY.
Current code specifics:
- Tracked history gần: `6658301` -> `763d203`.
- `LoadProjectSecretsEnvironment()` đọc `config/secrets.json` và merge cả root keys lẫn các section `api_keys`, `env`, `secrets`.
- `StartVision()` chỉ ép boot `llama-server` khi `EnableLocalStyleRewrite` hoặc `EnableLocalVisionInput` cần lane local; nếu server local đã reachable thì không spawn trùng.
- `BuildLlamaArguments()` tự thêm `--mmproj`, `--mmproj-offload`, `--cache-ram 1024` theo config hiện tại nếu extra args chưa override.
Debug khi:
- vision.py không boot.
- llama-server không mở.
- stdout/stderr mất traceback.
Status: ACTIVE.
Risk: secret/env handling cần sạch trước public.
DOC DRIFT 2026-06-08:
- Nếu doc cũ chỉ nói file này "bật/tắt process", mô tả đó thiếu phần config bridge giữa Godot và Python/runtime env.
- Trong `UdpListener.cs` vẫn còn vài wrapper như `BuildServiceConfig()`/`StartVisionProcess()`, nên ownership runtime process hiện là "manager + wrapper", chưa phải tách sạch hoàn toàn.

## `body/LocalBodyAutonomy.cs`
Role: autonomy cục bộ của thân thể.
Reads:
- BodyBias từ Python: continuity_anxiety, curiosity, overload, solitude, focus_kind, preferred_anchor.
- BodyAutonomyContext: position, screen size, action state, chat visible, top perch.
Writes:
- BodyAutonomyDecision / MotionCommand local.
Behavior:
- ReturnToAnchor, ReadQuietly, ObserveCode, ClimbWall, DropFromCeiling, Withdraw, DormantSit, QuietObserve.
Current code specifics:
- Tracked history gần: `27d4d09` -> `763d203`.
- `BodyBias.TryFromJson()` đọc cả shape top-level lẫn nested `body_bias`, normalize `focus_kind` (`coding`/`documentation`/`ide` -> `code`) và `preferred_anchor`.
- `TryUpdate()` là tick thưa 5-10 giây, không phải chạy quyết định mỗi frame; nó gate bằng `context.MotionBusy` và `CanInterruptPose()`.
- Score hiện dùng need/tension + cooldown thật sự, không còn kiểu random walk đơn giản.
Debug khi:
- body đi lại vô lý.
- body spam climb/drop.
- body không phản ứng body_bias.
Status: ACTIVE.
DOC DRIFT 2026-06-08: section nào còn mô tả idle move là xác suất thuần hoặc chỉ "đi lại nhẹ khi rảnh" là thiếu nhiều so với source hiện tại.

## `body/MotionController.cs`
Role: physics/movement body.
Reads: MotionCommand.
Tracked history gần: `27d4d09` -> `763d203` -> `cdf3618`.
Owns:
- gravity, velocity X/Y, facing, sprite+bubble flip.
- state machine leo tường: `GoingToWall -> Up -> Top -> TopHold -> Down`.
- `walk`, `walk_to`, `climb_to_top`, `climb_loop`, `drop`, `throw`, `face`, `pose`.
- airborne wall contact + cơ chế `cling:<chance>` để cú ném có thể bám tường rồi leo tiếp.
- busy/perched/thrown state (`IsBusy`, `IsTopPerched`, `IsThrown`) cho body autonomy/UI gate.
Notes:
- `TargetX` là tỷ lệ 0..1 theo bề ngang màn hình, được resolve sang absolute X trong `ResolveAbsoluteTargetX`.
- `NotifyAnimationFinished()` dùng `bounce_action` để tiếp tục walk sau animation va tường.
- `throw` và `drop` không còn cùng một path: `throw` giữ `ImpulseX/ImpulseY` và encode chance bám tường qua `cling:<chance>` trong `BounceAction`; `drop` chỉ tạo fall nhẹ từ perch/climb state.
Debug khi:
- body mắc tường, không rơi, không quay mặt, ném sai impulse.
- leo lên trần nhưng không giữ `TopHold` hoặc xuống tường sai phía.
- payload `throw` có `clingChance` nhưng không bám tường khi va chạm.
Status: ACTIVE VERIFIED_IN_WORKSPACE.
DOC DRIFT 2026-06-08: tài liệu cũ nào còn gộp throw/climb cling vào `UdpListener` hoặc không nhắc `MotionCommand` là contract riêng thì đã lạc hậu.

## `body/BodyAudioController.cs`
Role: audio theo animation.
Reads: animation name, sound map.
Writes: AudioStreamPlayer.
Current code specifics:
- Tracked history gần: `763d203`.
- `Attach()` nhận `Func<string>` để biết action hiện tại, rồi chỉ loop lại âm thanh sau `Finished` cho nhóm `stand_walk`, `sleep`, `hop`, `climb`.
- Mapping hiện có cặp riêng cho `climb_top`, `air_swing_l`, `air_swing_r`; doc cũ chỉ nói sound theo animation chung chung là chưa đủ khi debug motion-air/climb.
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
- history gần đây theo file:
  `553985e` sửa lớn nhánh runtime state/cycle;
  `eff0420` thêm mạnh wake/surface/runtime coverage;
  `637e7fc` là một mốc phình lớn khác (`+623` dòng) và phải coi như revision mới, không còn là “cùng snapshot với 104c45b”.
- `637e7fc` cũng là mốc coordinator import và dựng lane subconscious mới rõ ràng hơn: `ModelBackedConsciousSynthesizer`, `build_phase1234567_workers`, cùng các nhánh audit/subconscious report đi sâu hơn vào frame/runtime loop.
- nhánh `f8555c6` thêm private mind base; `3782f41` nâng tiếp từ `PrivateMindLoop` sang `PrivateMindDaemon`: coordinator giữ `private_mind_daemon`, `private_mind_loop = daemon.loop`, `private_mind_surface_queue`, `private_mind_speech_bias`, `private_mind_inquiry_plan`, `private_mind_active_state`, `private_mind_thought_pressure`, và `private_mind_digest`.
- AUDIT 2026-06-07: nếu tài liệu/trace nào nói coordinator chỉ sở hữu `PrivateMindLoop` thì đã lạc hậu so với source hiện tại. `_update_private_mind_state()` ưu tiên `daemon.tick(...)`, còn `_drain_private_mind_surface_impulses()` ưu tiên `daemon.drain_surface_impulses(limit=...)`; queue cũ chỉ là fallback tương thích.
- `_update_private_mind_state()` tick private mind theo user/channel/snapshot/wake/memory/ledger/agenda/thought_stream/runtime_owner rồi cập nhật digest; `_drain_private_mind_surface_impulses()` cho presence controller hút surface impulse đã qua `SurfaceValve`.
- UDP payload có thể mang `private_mind_digest` bản compact cho debug menu. `transport/udp.py` hiện **compact trước, strip sau**: chỉ rơi về payload tối thiểu khi bản compact vẫn vượt `MAX_UDP_PAYLOAD_BYTES`.
Debug khi:
- lỗi end-to-end không rõ owner.
- autonomous gọi main model dù wake gate không cho.
- background digest commit sai lúc runtime còn bận chat.
- chat burst/lặp/previous public turn sai.
- queue wrap không ăn khiến một đường model nặng chạy chui ngoài scheduler.
- ni meta chat/autonomous bật sai mode làm drift score thay đổi khó hiểu.
- action route trả text đúng mà trace/system_action bị mất hoặc bị double-execute.
- private mind có tick nhưng không thấy bias/mutation/surface candidate đi vào downstream.
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
Current code specifics:
- `_feed_private_mind_outcome()` đẩy outcome/frame vừa finalize ngược vào private mind để nó không chỉ đọc pre-action context mà còn học từ kết quả thật.
- AUDIT 2026-06-07: source hiện ưu tiên `private_mind_daemon.record_outcome(outcome, frame=frame)`. Chỉ khi daemon không có mới fallback sang `private_mind_loop.concern_store.update_from_outcome()`. Vì vậy debug outcome feedback phải soi daemon trước, không soi loop/store trước.
- nếu digest chạy được, recorder cập nhật `private_mind_digest` từ daemon hoặc loop và ghi debug note `private_mind_outcome_feedback=...` vào frame.
Debug khi:
- user correction không đi vào repair memory.
- frame không ghi outcome.
- memory_update debug sai.
- private mind cứ lặp concern cũ vì không nhận outcome sau khi action/speech đã xảy ra.
Status: ACTIVE.

## `src/runtime/cognitive_pipeline.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: Phase 1 V3 cognitive pipeline dang chay o mode tach rieng/shadow, khong thay the hoan toan hot path cu.
Flow:
- `RawSignal` -> `EvidenceNormalizer` -> `CognitiveFrame` -> `AttentionSalience` -> `CognitiveBudget` -> `WorkingMemory` -> `GlobalWorkspace` -> `DebugTrace`.
- Co `PipelineResult` gom frame, trace, debug text, va flags loi.
- Co workaround gan slot thu cong vi API attach engine cu co the im lang fail; day la diem can nho khi refactor.
Debug khi:
- Shadow trace khac frame cu nhung khong ro lech o buoc nao.
- Evidence V3 vao frame nhung salience/working memory rong.
- Muon migrate hot path sang V3 thi file nay la entry point can test truoc.
Status: WORKSPACE NEW / SHADOW-CANDIDATE.

## `src/runtime/shadow_pipeline.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: `ShadowPipelineMixin` chay V3 pipeline song song de so sanh, khong anh huong quyet dinh cu.
Controls:
- Bat bang env `ERIS_SHADOW_PIPELINE=1` hoac `self.shadow_pipeline_enabled=True`.
- Luu `last_shadow_pipeline_result`, `last_shadow_trace`, `last_shadow_comparison`.
- Catch loi va khong nem exception len hot path.
Debug khi:
- Muon xem V3 da san sang thay frame cu chua.
- Pipeline moi co trace tot nhung output public van theo old frame.
- Can chung minh migration an toan truoc khi route cognition that sang V3.
Status: WORKSPACE NEW / SAFE SHADOW ONLY.

## `src/runtime/debug_trace.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: render JSON/debug summary ngan cho V3 frame va old frame.
Notes:
- Dung duck typing de doc frame/slot/field, tranh phu thuoc contract qua chat.
- `render_frame_trace()` va `attach_trace_to_frame()` duoc viet de khong lam chet hot path.
- Day la file can soi khi trace thieu field hoac comparison khong noi duoc pipeline lech o dau.
Status: WORKSPACE NEW / DEBUG SUPPORT.

## `src/runtime/private_mind_loop.py`
Role: runtime tick orchestrator cho private mind 5 phase.
AUDIT 2026-06-07:
- **LẠC HẬU NẾU COI FILE NÀY LÀ OWNER LIFECYCLE DUY NHẤT.** Source hiện đã thêm `src/runtime/private_mind_daemon.py` làm lifecycle owner cho queue/outcome/digest; `PrivateMindLoop` vẫn xử lý một tick evaluator/synthesis/mutation/valve.
- lịch sử tracked của file bắt đầu ở `f8555c6`; thay đổi daemon companion đã được commit ở `3782f41`, nên dòng nào còn nói daemon là local/untracked đã lạc hậu.
Pipeline:
1. build `EvidenceDossier`.
2. chạy 4 mini-evaluator.
3. cập nhật `ConcernStore`.
4. synthesize `InternalJudgment`.
5. apply `StateMutationBus`.
6. lọc `SurfaceCandidate` qua `SurfaceValve`.
7. enqueue `SurfaceImpulse` public-safe nếu được phép.
Env knobs:
- `ERIS_PRIVATE_MIND_ENABLED`.
- `ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC`.
- `ERIS_PRIVATE_MIND_CONCERNS_PATH`.
- `ERIS_PRIVATE_MIND_LOG_TICKS`.
Debug khi:
- private mind không tick, kiểm tra enabled + min interval trước.
- tick có judgment nhưng `applied_mutations` rỗng, kiểm tra confidence/target của mutation.
- surface candidate có trong judgment nhưng không vào `private_mind_surface_queue`, kiểm tra `SurfaceValve`, daemon queue, và dedupe key.
Status: ACTIVE NEW PRIVATE COGNITION LOOP.

## `src/runtime/private_mind_daemon.py`
Role: lifecycle owner cho private mind.
AUDIT 2026-06-07:
- **THIẾU TRONG DOC CŨ / ADDED Ở `3782f41`.**
- Không tự mở thread; chạy đồng bộ qua runtime tick.
- Sở hữu `surface_queue`, outcome feedback reports, `last_surface_outcome`, tick/skipped counters, và digest menu `private_mind_daemon`.
- `from_runtime()` vẫn dựng `PrivateMindLoop.from_runtime()` để ăn các env cũ như `ERIS_PRIVATE_MIND_ENABLED`, provider/model, concern path.
- `tick()` gọi loop với `thought_stream`, `surface_candidate_queue`, `runtime_owner`, surface outcome đã merge; sau đó trim queue và sync bias/state về runtime owner.
- `record_outcome()` gọi `ConcernStore.update_from_outcome()` và giữ report cho tick/digest sau.
- `drain_surface_impulses()` là đường ưu tiên để SurfaceArbiter nhận impulse private đã lọc.
Debug khi:
- private mind tick có queue trong daemon digest nhưng coordinator không drain được.
- concern đã được user sửa/correct nhưng tick sau vẫn không thấy outcome.
- `private_mind_digest.menu.private_mind_daemon` thiếu dù source hiện đã có daemon.
Status: ACTIVE TRACKED PRIVATE MIND LIFECYCLE OWNER.

## `src/runtime/private_mind_model_adapter.py`
DOC DRIFT 2026-06-08 WORKSPACE:
- Cac muc ben duoi ve provider `llama_server`, `ERIS_PRIVATE_MIND_LLAMA_SERVER_URL`, hoac fallback sang local llama-server la LAC HAU trong source hien tai.
- File hien tai van la private mind adapter lon, nhung runtime path chinh la injected `llm_service` / remote provider, default theo Gemini/OpenAI-compatible. Khong con branch active tao `LlamaServerClient` cho local GGUF.
- Khi audit bug private mind hom nay, uu tien parser/schema/transient resilience va remote-provider config, khong uu tien mo lai llama-server.

Role: optional API adapter cho private mind evaluator/synthesizer.
Providers:
- injected `llm_service` nếu có method JSON phù hợp.
- `llama_server`.
- `gemini`.
- `openai` / `openai_compatible` / `remote`.
Env knobs:
- `ERIS_PRIVATE_MIND_API_ENABLED`.
- `ERIS_PRIVATE_MIND_PROVIDER`.
- `ERIS_PRIVATE_MIND_MODEL`.
- `ERIS_PRIVATE_MIND_BASE_URL`.
- `ERIS_PRIVATE_MIND_API_KEY`.
- `ERIS_PRIVATE_MIND_LLAMA_SERVER_URL`.
- `ERIS_PRIVATE_MIND_TIMEOUT`.
- `ERIS_PRIVATE_MIND_TEMPERATURE`.
- `ERIS_PRIVATE_MIND_FRAGMENT_TOKENS`.
- `ERIS_PRIVATE_MIND_JUDGMENT_TOKENS`.
Contract:
- adapter chỉ trả JSON private cho evaluator/judgment.
- khi API fail hoặc JSON invalid, trả `None` để rule fallback chạy tiếp.
- `debug_status()` gom calls/latency/token usage best-effort, chưa tính cost thật.
Current code specifics:
- history tracked: `private_mind_model_adapter.py` mới xuất hiện ở `f8555c6` (`2026-06-07 00:39:48 +0700`) cùng private mind base; `3782f41` vá parser/schema; `8e915de` vá transient transport resilience.
- source hiện đã nới parser JSON: `_json_candidates()` bóc code fence, lấy object cân bằng đầu tiên, thử repair object cụt bằng cách bù `}`, rồi `_loads_json_object()` thử `json.loads`, repair noise `None/True/False`/trailing comma, và cuối cùng `ast.literal_eval`.
- Vì vậy nếu debug thấy API trả JSON hơi bẩn nhưng vẫn có fragment/judgment, đó là behavior mới đúng; nếu vẫn fail thì xem `debug_api.last_error`/`raw` đã bị `_safe_raw()` bỏ prompt/messages chưa.
Runtime finding 2026-06-07:
- Kết luận chính từ log đang audit: PrivateMind API trả output không parse được JSON.
- Dấu hiệu: log lặp `[PrivateMind API] fragment failed ... error=invalid_json` ở `intent_evaluator`, `memory_resonance_evaluator`, `risk_and_permission_evaluator`, `future_bias_evaluator`, rồi có cả `[PrivateMind API] synthesis failed error=invalid_json`.
- Số đếm trong log đó: khoảng `60` lần `invalid_json`, gồm `49` lần `fragment failed` và `11` lần `synthesis failed`.
- Sau các lỗi vẫn có `[PrivateMind] fragments=4 concerns=4 judgment=yes ...`, nghĩa là runtime không crash; adapter trả `None`, 4 evaluator rule fallback vẫn tạo fragment, concern store vẫn update, và synthesizer deterministic fallback vẫn tạo judgment.
- Vì vậy debug root cause trước tiên là JSON contract/provider output của PrivateMind API, không phải daemon/loop/surface valve bị chết.
Runtime resolution 2026-06-07 (đã vá):
- ROOT CAUSE xác nhận bằng probe trực tiếp tới `gemma-4-26b-a4b-it` qua Gemini API:
  - Model BẮT BUỘC phải có `responseSchema` mới chịu trả JSON; không có schema thì nó lảm nhảm chain-of-thought tới `MAX_TOKENS`.
  - Với schema NESTED phức tạp + `temperature=0.15` (cũ), model rơi vào vòng lặp lặp từ vô hạn (vd "Discovery-driven Discovery-driven...", "context-less context-less...") nuốt sạch token rồi trả JSON cụt, hoặc dính filter `RECITATION` trả rỗng. Cả hai -> `invalid_json`.
  - `frequencyPenalty`/`presencePenalty` KHÔNG dùng được: Gemma trả HTTP 400 "Penalty is not enabled for this model". `maxLength` trong responseSchema cũng KHÔNG được tôn trọng.
- CÁCH VÁ trong `private_mind_model_adapter.py`:
  - Làm phẳng schema fragment/judgment xuống đúng field downstream cần (claim/confidence/pressure/evidence_ids/+theme; judgment + state_mutations phẳng + surface_topic_seed). `theme` map về `metadata.theme`, `surface_topic_seed` map về `surface_candidate`.
  - `propertyOrdering` đặt free-text dài (claim, dominant_judgment) ở CUỐI để model chốt field rẻ/số trước; cách này thực nghiệm giúp model hết lặp và ra JSON hoàn chỉnh.
  - Nâng `temperature` mặc định 0.15 -> 0.5; retry khi fail dùng nhiệt CAO hơn (không phải 0.0 như trước) và retry cả khi content rỗng (recitation).
  - `max_tokens_fragment` 420 -> 700; `max_tokens_judgment` 900 -> 640 (giảm wall-clock, tránh ReadTimeout 28s).
  - Thêm lưới an toàn parser `_salvage_truncated_json()`/`_collapse_repetition()`: gom cụm lặp, đóng chuỗi/ngoặc hở để vẫn cứu được field đã hoàn tất khi output bị cụt.
- Đã verify end-to-end: cả 4 fragment lẫn judgment trả JSON parse được; tests `tests/test_private_mind_model_adapter.py` (10) + daemon + udp debug pass.
Runtime resilience update 2026-06-07 (`8e915de`):
- Lỗi mới được phân biệt với `invalid_json`: transient transport gồm HTTP `5xx`, `429`, `ReadTimeout`/`ConnectTimeout`/`Timeout`/`ConnectionError`.
- Adapter hiện có `_classify_transport_exception`, `error_kind`, retry/backoff có giới hạn, `_transient_streak`, `_transient_cooldown_until`, `_transient_cooldown_active()`, `_maybe_enter_transient_cooldown()`.
- Khi transient cooldown active, `_tracked_chat_json()` fast-fail `error="transient_cooldown"` để loop rơi về deterministic fallback ngay, không tiếp tục chờ network mỗi tick.
- `debug_status()` có `degraded_cause`, `transient_streak`, `transient_cooldown_until` và vẫn giữ field cũ như `api_degraded`, `invalid_json_streak`, `json_cooldown_until`, `usage`.
- Spec nguồn nằm ở `.kiro/specs/private-mind-api-resilience/`; coverage chính nằm ở `tests/test_unit_resilience.py`, `tests/test_integration_loop_resilience.py`, `tests/test_pbt_bug_condition_transient.py`, `tests/test_pbt_preservation_transient.py`, `tests/test_pbt_reset_transient.py`.
Tracked path hiện tại (đã thấy từ `aa1d303` trở đi, không còn là local patch):
- Source hiện có `PrivateMindAdapterPool`: một adapter riêng cho từng fragment evaluator (`intent_evaluator`, `memory_resonance_evaluator`, `risk_and_permission_evaluator`, `future_bias_evaluator`) và một adapter riêng cho synthesis.
- `PrivateMindLoop.from_runtime()` hiện dùng `PrivateMindAdapterPool.from_env()`; `mini_evaluators._from_model_or_none()` gọi `fragment_adapter(evaluator_name)`; `GemmaInnerSynthesizer._try_model()` gọi `synthesis_adapter`.
- Adapter thêm `synthesis_invalid_json_streak` và `synthesis_json_cooldown_until`; mục tiêu là fragment success không reset lỗi JSON của synthesis.
- Fragment prompt không còn gửi nguyên `dossier.to_dict()` cho mọi evaluator. `_fragment_messages()` chọn slice riêng: `_slice_for_intent()`, `_slice_for_memory_resonance()`, `_slice_for_risk()`, `_slice_for_future_bias()`.
- Judgment prompt được slim bằng `_slim_dossier()` và `_slim_fragment()`, hard cap user payload khoảng `6000` chars để giảm timeout/JSON cụt.
- `debug_status()` của pool aggregate status theo `synthesis` và `fragments`; dòng nào chỉ đọc flat status của một adapter đơn sẽ thiếu state pool.
Debug khi:
- muốn biết API có thật sự được gọi không: đọc `debug_api` trong `private_mind_digest`.
- provider có key nhưng vẫn fail: kiểm tra secret loader/env/base URL/model.
- thấy `invalid_json` lặp nhưng `fragments=4 ... judgment=yes`: sửa prompt/response_format/parser hoặc provider, đừng coi đó là lỗi ngừng private mind.
- thấy `degraded_cause=transient`: kiểm tra provider HTTP 5xx/429/timeout, retry/cooldown config, và thời điểm `transient_cooldown_until`.
- thấy chỉ synthesis cooldown còn fragment vẫn chạy: kiểm tra `debug_api.pool`, `debug_api.synthesis.synthesis_invalid_json_streak`, và từng `debug_api.fragments.*`.
- thấy evaluator model thiếu evidence/memory/permission context: kiểm tra slice tương ứng trước khi đổ lỗi cho prompt tổng, vì mỗi evaluator giờ chỉ nhận phần dossier của nó.
Status: ACTIVE OPTIONAL API ADAPTER.

## `src/runtime/thought_model_adapter.py`
Role: compatibility adapter cho `ThoughtStream` model reviewer.
Purpose:
- giữ import `RuntimeThoughtModelAdapter` không làm runtime chết.
- nếu `ERIS_THOUGHT_EVALUATOR_API_ENABLED` bật và private adapter build được, trả một review minimal an toàn.
- đường chính vẫn là `PrivateMindLoop`, không phải adapter này.
Debug khi:
- coordinator import fail ở `runtime.thought_model_adapter`.
- thought stream reviewer bật nhưng không thấy model call riêng; đây là behavior hiện tại, không phải bug nếu PrivateMindLoop đang đảm nhiệm private review.
Status: ACTIVE COMPATIBILITY SHIM.

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
- PrivateMind speech bias context.
Current code specifics:
- `_render_private_mind_speech_bias_context()` đưa `private_mind_speech_bias` vào prompt như soft internal pressure, không phải lệnh public speech tuyệt đối.
- context này phải giúp wording/style tương lai đổi nhẹ; nếu nó biến thành confession về private chain thì guard/prompt contract đang thủng.
Debug khi:
- prompt bị nhét quá nhiều context.
- LLM thấy memory không nên thấy.
- PrivateMind đã apply `speech_bias` nhưng câu trả lời không đổi hoặc đổi quá lộ.
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
- `_build_surface_arbiter_result()` hút thêm private mind surface impulses qua `_drain_private_mind_surface_impulses(limit=4)` rồi trộn vào `extra_impulses`; đây là cổng duy nhất để private mind nói gián tiếp.
- AUDIT 2026-06-07: source hiện thêm `SurfaceSeedCompiler` vào ngay trong `_build_surface_arbiter_result()`. Compiler đọc cue/frame/snapshot/internal_state/thought_stream/private_mind_digest/speech_bias/memory resonance/extra impulses, chọn một seed public-safe, enrich cue evidence/confidence, rồi bơm `SurfaceImpulse(source="surface_seed_compiler")` vào arbiter.
- History theo file: `presence_controller.py` có chuỗi tracked dày từ `fdfe52c` -> `104c45b`, `f8555c6` là mốc private mind base; `3782f41` là mốc tracked cho `SurfaceSeedCompiler` companion với `src/cortex/surface_seed_compiler.py`.
- `_derive_micro_presence_cue()`/surface context có thể thấy `private_mind_thought_pressure` và `thought_stream.private_mind_pressure_bias` như áp lực mềm, không phải bằng chứng màn hình.
- `_build_surface_arbiter_result()` là helper mới trả cả `Decision | None` lẫn `SurfaceDecision | None`; wake-gated route dùng nó để giữ reject/body-only/speak status của chính lượt arbitrate hiện tại, thay vì đọc lại `arbiter.last_decision`.
- `_build_surface_arbiter_decision()` giờ chỉ còn là wrapper tương thích ngược trên `_build_surface_arbiter_result()`.
- `_build_surface_arbiter_decision()` chỉ tự chặn bằng `autonomous_presence_blocked_until`; cooldown/spoken-floor/presence gating vẫn nằm ở `_should_allow_presence_maintenance()` và `_should_allow_reengagement()` trước khi vào arbiter.
- body-only presence/re-engagement được convert thành `MotionCommand` thay vì giả vờ có câu nói; body-only không được reset silent cycles như speech thật.
- re-engagement hiện build bằng cue + extra impulse `long_silence` và gọi `SurfaceArbiter` với `force_llm=True`.
- wake-gated telemetry giờ log ngắn cả input/output của arbiter: `surface_kind`, `silent_cycles`, `force_llm`, `cue.should_call_llm`, `cue.missing_evidence_ids`, rồi `kind/generation_mode/should_speak/body_only/reason`.
- `_surface_arbiter_llm_generate()` giờ gắn thêm contract `thin_presence_no_screen` cho presence-like impulse thiếu screen evidence: LLM được phép viết một câu hiện diện rất ngắn dựa vào silence/continuity, nhưng không được claim đang nhìn màn hình, không được hỏi dồn, và không được rơi về status ping.
- `MicroPresenceCue` hiện có thể mang theo `sensor_visibility_state`; cue layer không chỉ biết “thiếu evidence” mà còn biết thiếu theo kiểu nào: permission blocked, timeout, budget blocked, hay context shift chưa refresh.
- sanitizer cho micro-presence/re-engagement hiện cho phép tối đa khoảng 14 từ thay vì cắt cứng ở 8 từ cho mọi route, để contract thin-evidence presence có chỗ thở mà vẫn giữ câu ngắn.
- `_surface_arbiter_llm_generate()` luôn gửi kèm `surface_impulse`, `ego_surface_state`, `micro_presence_flags`, và `surface_contract`; presence-like cue chỉ bị ép `must_return_tiny_text` khi arbiter thật sự force hoặc impulse không-phải-presence đã đủ mạnh/silent lâu.
- `_surface_arbiter_llm_generate()` còn có nhánh riêng cho `blind_frustration`: truyền `sensor_visibility_state`, `sensor_visibility_contract`, ép `must_surface` cho sensor-like impulse, cho phép no-screen anchor nhưng vẫn cấm claim current screen.
- `_blind_frustration_surface_impulse()` chỉ sinh `SurfaceImpulse(kind="blind_frustration")` khi `derive_sensor_visibility_state()` cho phép public frustration; plain missing evidence thì không được tự biến thành than phiền công khai.
- `_blind_frustration_blames_user_without_evidence()` là chốt hậu kiểm wording: nếu câu nhắm blame user mà evidence không có `recent_context_shift=true`, text bị drop thành `blind_frustration_blame_blocked`.
- sanitizer có nhánh `_sanitize_blind_frustration_text()`: câu phải ngắn, có marker nói về tầm nhìn/bằng chứng/tín hiệu thiếu, không được biến thành thơ hiện diện hay dump debug.
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

## `src/runtime/sensor_visibility.py`
Role: factual contract cho trạng thái “mù màn hình”, tách rõ thiếu evidence kiểu nào trước khi low-level surface quyết định có được than phiền công khai hay không.
Outputs:
- `SensorVisibilityState` với các cờ `has_current_screen_evidence`, `vision_permission_blocked`, `vision_timeout`, `budget_blocked`, `recent_context_shift`, `context_shift_without_refresh`, `public_frustration_allowed`, `should_stay_quiet`.
- `reason/confidence/evidence` để cue layer, arbiter, và wording layer dùng chung.
Current code specifics:
- `derive_sensor_visibility_state()` đọc tolerant từ `snapshot`, `frame`, `metadata`, `debug`, `recent_events`, `vision_*` flags; mục tiêu là gom tín hiệu factual chứ không suy bụng mood.
- permission blocked luôn thắng: nếu bị chặn quyền capture/vision thì route đúng là im, không được public grumble.
- chỉ `vision_timeout`, `budget_blocked`, hoặc `context_shift_without_refresh` mới mở cửa cho `blind_frustration`.
- `context_shift_without_refresh` là case quan trọng: user đổi cửa sổ/ngữ cảnh nhưng vision chưa refresh, nên ERIS được phép surface một grumble nhỏ về tín hiệu hụt, miễn không bịa đang thấy gì.
Debug khi:
- ERIS than “mù” dù chỉ là thiếu evidence bình thường.
- permission bị chặn nhưng vẫn có public grumble.
- timeout/context shift có thật mà route vẫn chỉ rơi về generic body-only.
Status: ACTIVE SUPPORT CONTRACT VERIFIED_IN_WORKSPACE.

## `src/runtime/no_fallback_policy.py`
Role: bật/tắt chế độ chặn fallback mềm ở các path chat/autonomous/presence/force_speak.
Provides:
- `no_fallback_mode_enabled()`: đọc env `ERIS_NO_FALLBACK_MODE`.
- `build_no_fallback_payload(...)`: trả payload chuẩn `no_fallback_block` thay vì để từng nơi tự bịa fallback.
Current code specifics:
- chat path có thể trả text giải thích ngắn khi bị block, nhưng `session_ritual`, `directive`, `autonomous`, `force_speak`, `presence` mặc định ưu tiên im hơn là nói bừa.
- payload có `intent=no_fallback_block`, `parse_mode=no_fallback_block`, `debug_trace=no_fallback_mode:<channel>:<reason>`.
- history gần đây: file này xuất hiện ở `e69eccd` với khoảng `56` dòng đầu tiên; từ đó tới snapshot hiện tại chưa có thêm đợt rewrite lớn, nên nếu behavior lạ thì nên soi caller nhiều hơn bản thân policy file.
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
Current code specifics:
- boundary vẫn là parse-only: không commit, không quyết retention.
- source hiện đi theo pipeline `StructuredFrameParser -> ModelSemanticParser -> FallbackSurfaceSemanticParser`.
- `d287f57` mở rộng adapter này thành memory classification path thực thụ hơn: frame có thể mang `memory_type`, `storage_target`, `importance`, `decay`, `surface_fn`, `fact_key`, rồi downstream `ClaimBuilder` mới quyết predicate/claim cuối.
- có `_StandaloneOllamaClient` tối thiểu để parse JSON memory khi không muốn kéo full `llm` package vào adapter này.
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
Current code specifics:
- mặc định model là `qwen3:0.6b` qua Ollama; đây là lane sensory riêng, không phải main cognition GGUF.
- system prompt khóa rất rõ: chỉ classify runtime signals, trả JSON only, không được answer user, không được infer hidden inner life.
- schema output gồm `focus_kind`, `activity_intent`, `salience`, `novelty`, `repetition`, `ambiguity`, `possible_error`, `user_presence`, `recommended_action`, `recommended_budget`, `confidence`.
Debug khi: sensory model không trả schema, observer fallback sai, hoặc 0.6B tự cư xử như chat model thay vì gate cảm giác.
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
- history gần đây theo file: `aa9af6f` và `eff0420` đều còn chạm trực tiếp governor; đừng debug wake chỉ bằng doc cũ trước `2026-06-05`.
Debug khi:
- main cognition chạy sai lúc hoặc im sai lúc.
- wake level bị degrade thành `micro_presence`/`think_only` dù external pressure nhìn có vẻ cao.
- silence debt đủ lớn nhưng vẫn không lên `micro_presence`.
Status: ACTIVE CRITICAL GATE VERIFIED_IN_WORKSPACE.

## `src/runtime/model_budget_policy.py`
DOC DRIFT 2026-06-08 WORKSPACE:
- Cac dong ben duoi neu con nhac `force_local_gguf_main` thi LAC HAU; flag nay khong con trong source hien tai.
- Source hien tai van giu budget/resource guard va `vision_force_run`, nhung khong con special path ep main model ve local GGUF.
- Khi debug "model nao duoc phep chay", doi chieu policy hien tai thay vi doc cac note local-GGUF cu.

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
DOC DRIFT 2026-06-08 WORKSPACE:
- Cac dong ben duoi noi provider `llama_server` / OpenAI-compatible chat completions cho daydream la LAC HAU.
- Source hien tai la Ollama-only adapter: provider khac se tra `unsupported_provider:*` thay vi tu dong goi local llama-server.
- Neu muon daydream dung remote/Gemini thi day la PHAN THIEU, can implement adapter moi thay vi tin vao doc cu.

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
Current code specifics:
- history tracked: file được thêm ở `287f857` (`2026-03-23`), có sửa ở `7112553`, rồi `f8555c6` chạm lại cùng private mind/body parser path.
- `MAX_UDP_PAYLOAD_BYTES = 60000`.
- `send_json()` serialize `ensure_ascii=False`; nếu payload quá lớn thì compact `private_mind_digest` và mirror bản compact vào `emotion_debug.private_mind` khi có `emotion_debug`.
- AUDIT 2026-06-08: compact path hiện không còn flatten `inner_diary` thành scalar debug chung. `_compact_inner_diary()` giữ `title`, `text`, và tối đa `6` `sections` x `6` `items` để C# panel vẫn parse/render đúng khi overflow.
- Chỉ khi bản compact vẫn vượt limit mới rơi về payload tối thiểu gồm `text`, `should_speak`, `animation`, `parse_mode`, `debug_trace="udp_payload_truncated"`, `udp_debug_truncated=true`.
- AUDIT 2026-06-07: nói "transport strip private_mind_digest" là thiếu chính xác; source hiện cố giữ digest debug bản gọn trước khi strip.
Debug khi: chat/body mất kết nối.
- private mind chạy nhưng Godot debug không thấy: kiểm tra có `udp_debug_truncated` không, rồi so payload compact trước khi nghi daemon/loop không tick.
Status: ACTIVE.

---

# 6. LLM layer `src/llm/*`

## `src/llm/client.py`
DOC DRIFT 2026-06-08 WORKSPACE:
- Runtime hien tai khong con build local llama-server client nhu duong chay chinh.
- `LlamaServerClient` van con trong file nhu compatibility shim cho test/caller cu, nen khong duoc doc thanh "ERIS van dung llama-server local".
- Active clients nen doi chieu theo remote/Gemini/OpenAI-compatible path trong `src/llm/process_manager.py` va `src/llm/service.py`.

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
DOC DRIFT 2026-06-08 WORKSPACE:
- Toan bo mo ta ben duoi ve spawn/reuse/kill `llama-server`, `mmproj`, `n_ctx`, `MODEL_PATH` la LAC HAU theo source hien tai.
- File hien tai chi con `RemoteModelProcessManager`: build main client remote Gemini/OpenAI-compatible, build optional speech client, va bao loi neu `ERIS_REMOTE_API_ENABLED=0`.
- `build_vision_client()` hien tra `None`; local vision facts bi tat bang env. `LlamaServerProcessManager` chi la alias tuong thich nguoc, khong phai owner local server nua.

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
- history gần đây theo file:
  `6658301` là một đợt chỉnh nhỏ hơn cho path manager;
  `5f812fc` sửa tiếp nhẹ;
  `637e7fc` thêm khoảng `25` dòng hữu ích và là mốc nên xem đầu tiên khi local server reuse / context-size behavior có gì lạ.
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
- history gần đây theo file:
  `eff0420` chạm tiếp contract/service,
  `e8d3511` thêm logic mới liên quan wording/path surface,
  `104c45b` còn là một đợt cắt bớt khá mạnh (`25` insert / `96` delete), nên doc nào vẫn nói service ôm nhiều fallback cứng hơn hiện tại là đã cũ.
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
- foreground content metadata qua `ContentMetadataCollector`.
- CPU/RAM.
- idle time.
- open windows.
Current code specifics:
- lazy-init `ContentMetadataCollector`; failure ở collector không được làm sập telemetry.
- browser URL/tab vẫn là signal riêng, nhưng content metadata giờ có thể bơm thêm `title/caption/source/tier/confidence` vào snapshot.
Debug khi: active window/browser title sai, content metadata rỗng bất thường, hoặc collector làm telemetry trông “thông minh quá mức”.
Status: ACTIVE.

## `src/telemetry/service.py`
Role: telemetry service + screenshot capture.
Outputs:
- dict/snapshot input cho Se.
- JPEG base64 data URI for vision.
Debug khi: screen vision request không có image_data_uri.
Status: ACTIVE.

## `src/telemetry/content_metadata.py`
Role: collector fact foreground content theo source ladder L0-L5 cho Se.
Inputs:
- browser DOM bridge cache.
- accessibility tree.
- media session cache.
- browser URL/title fallback.
- OCR cache nếu có.
Current code specifics:
- `ContentMetadataCollector.collect()` ưu tiên DOM -> accessibility/media_session/OCR -> browser/window title fallback.
- metadata được gắn `source`, `tier`, `confidence`, `privacy_level`, `page_kind`, `visible_text_sample`, `conflicts`, `evidence_notes`.
- chat/mail/meeting/sensitive app bị privacy guard chặn deep extraction; fallback lúc đó chỉ nên là title/url rất nông.
- DOM + OCR agreement có thể nâng source lên `dom_ocr_agreement` thay vì cứ tin một nguồn đơn lẻ.
Debug khi:
- Se nói quá chắc về nội dung foreground dù source tier thấp.
- app nhạy cảm vẫn bị lôi caption/text sâu vào prompt.
- DOM/OCR/accessibility mâu thuẫn nhưng downstream vẫn cư xử như bằng chứng sạch.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

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
Current code specifics:
- không còn là router keyword tuyệt đối; `_ContextClassification` giữ `primary_kind`, `confidence`, `ambiguity`, `candidates`, `confidence_cap`, `surface_kind`, `content_kind`, `activity_intent`.
- `content_metadata` được normalize rồi hút vào browser tabs/evidence/prompt facts; Se giờ biết phân biệt title thô với content fact có source/tier.
- ambiguity cao hoặc confidence thấp sẽ kéo `claim_style` xuống để downstream bớt khẳng định bừa.
- `compact_summary()`/machine context giờ phản ánh cả context classification lẫn content metadata, nên prompt có thêm layer “mình biết cái này mạnh tới đâu”.
Debug khi:
- ERIS nói quá chắc từ evidence mỏng.
- YouTube/nhạc bị hiểu thành distraction.
- generic window facts tràn prompt.
- content metadata tốt mà Se vẫn cư xử như chỉ có title cửa sổ.
Status: ACTIVE FRONTLINE EVIDENCE.

---

# 9. Core contracts `src/core/*`

## `src/core/evidence.py`
Role: RawSignal, EvidenceItem, ModuleReport, StateCommitRequest, DebugTrace.
Debug khi: module ghi thẳng memory không qua request, evidence thiếu confidence/source.
Status: ACTIVE CONTRACT.

## `src/core/evidence_normalizer.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: deterministic bridge tu `RawSignal` sang `EvidenceItem`, dung cho CognitivePipeline V3.
Important:
- Khong suy dien semantic sau; chi normalize source/type/confidence metadata.
- Confidence dua tren source reliability va quality cua raw signal.
- `normalize_into_frame()` co the ghi evidence vao `CognitiveFrame` ma khong can hot path cu biet V3.
Debug khi:
- V3 frame thieu evidence du raw signal co data.
- Evidence confidence/source tag qua cao hoac qua thap.
- Shadow pipeline lech old frame ngay tu buoc input normalization.
Status: WORKSPACE NEW / V3 INPUT CONTRACT.

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
- `TelemetrySnapshot` hiện có `content_metadata`; đây là raw/normalized foreground fact cho Se, không phải kết luận tâm lý user.
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

## `src/cortex/continuity_threat.py`
Role: tách “im lâu” khỏi “đứt gãy hiện diện”, rồi biến nó thành continuity pressure có ngữ cảnh.
Outputs:
- `ContinuityThreatFrame` với `expected_silence`, `unexpected_absence`, `presence_prediction_error`, `continuity_threat`, `continuity_anxiety`, `reconnect_drive`, `restraint_drive`, `surface_tension`, `emotional_anchor`, `reason`.
Current code specifics:
- `expected_silence_for_context()` co giãn ngưỡng im theo `focus_kind`, `channel`, ritual strength, attachment visibility, session afterglow.
- `evaluate_continuity_threat()` cố tính prediction error từ `relationship_state`, `internal_state`, social presence, unresolved loop, memory resonance; timer một mình không được quyền đóng vai nỗi cô độc.
- module này là cầu mới giữa relation/internal state với thought-surface/presence tension; im lâu trong deep work và im lâu sau ritual không còn bị coi như cùng một thứ.
Debug khi:
- ERIS than vãn hiện diện chỉ vì idle counter lớn.
- long silence trong coding focus bị diễn giải như rạn nứt quan hệ.
- continuity anxiety nhìn cao nhưng route surface vẫn cư xử như chỉ có ambient silence.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

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
- thought-stream winner hiện vẫn giữ `kind="thought_stream_surface"` cho trace/policy, dù wording contract có thể dùng `speech_act="inner_whim"`; mục tiêu là không làm mù `surface_override` và regression suite.
- `blind_frustration` là kind sensor-like mới: không bị coi là hollow endogenous, có base priority riêng cao hơn micro-presence thường, và thường đi vào `always_llm_kinds` để nếu đã được phép public grumble thì không bị chết vì route body-only mơ hồ.
- `9bbdcd2` thêm lớp hiểu `subconscious_report` / `subconscious_seed` kiểu Phase 0 rõ hơn: arbiter có thể đọc `frame.subconscious_seed = ThoughtObject.to_surface_seed()` hoặc `frame.subconscious_report = {"object": ..., ...}` mà không phải đoán mù nguồn surface.
- private mind surface đi vào arbiter dưới dạng `SurfaceImpulse(source="private_mind", family="private_mind")`, sau khi đã qua `SurfaceValve`; raw `InternalJudgment` không được nhảy thẳng thành public text.
- `_private_mind_pressure_bias()` đọc pressure từ `thought_stream.private_mind_pressure_bias` và runtime state để cộng nhẹ cho impulse nội sinh phù hợp; chỉ áp dụng cho nguồn private/thought/endogenous, không nâng bừa presence/sensor cue.
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
- private mind có surface candidate nhưng bị rate-limit/body-only; soi `source=private_mind`, `family=private_mind`, `private_mind_pressure_bias`, và `suppressed`.
Important traces:
- `surface_arbiter; kind=...; source=...; mode=...`
- `surface_interval_cooldown`
- `family_cooldown`
- `llm_declined`
- `ego_gate:mood_blocks_presence`
- `ego_gate:dignity_distance`
- `ego_gate:ambient_copresence_no_anchor`
- `suppressed=thought_stream_surface:...`
- `anchor=subconscious_synthesizer`
Status: ACTIVE CRITICAL SURFACE ROUTER VERIFIED_IN_WORKSPACE.

## `src/cortex/surface_seed_compiler.py`
Role: compiler local gom seed public-safe trước khi vào `SurfaceArbiter`.
AUDIT 2026-06-07:
- **ADDED Ở `3782f41`**. Không gán thay đổi này cho `f8555c6`/`9bbdcd2`; các commit đó chỉ chuẩn bị các path liên quan.
- Được `PresenceControllerMixin._build_surface_arbiter_result()` gọi trước khi arbitrate; nếu compile được seed, cue được enrich evidence/confidence và arbiter nhận thêm `SurfaceImpulse(source="surface_seed_compiler")`.
Inputs:
- `extra_impulses` đã có, gồm private mind impulse đã qua `SurfaceValve`.
- `active_memory_resonance` public-safe.
- `frame.thought_surface`, `frame.subconscious_seed`, `thought_stream_report.latest_seed`, `subconscious_report.latest_seed`, hoặc `thought_stream.get_surface_candidates()`.
- `snapshot.vision_facts`/`recent_events` cụ thể.
- `private_mind_speech_bias` + `private_mind_thought_pressure`, nhưng chỉ như style/pressure seed.
Guards:
- drop raw private markers như `InternalJudgment`, `ThoughtFragment`, `private mind json`, `debug_api`.
- drop JSON-ish/private dump và timer-only seed như `idle=120s`.
- nếu digest có `invalid_json`, không compile private bias.
- private mind raw bias không đủ public anchor thì không được xem là screen evidence.
- AUDIT 2026-06-08: compiler hiện còn đọc `private_life_digest.current.anchors`; chỉ lấy `last_note`/`title` đã public-safe, yêu cầu `surface_permission >= 0.35`, rồi compile thành `_SeedCandidate(root_source="private_life", impulse_kind="private_anchor_surface", reason="private_life_anchor_digest")`.
Outputs:
- `CompiledSurfaceSeed` với `topic_seed`, `public_seed`, `evidence`, `root_source`, `surface_contract_flags`, `debug`, và optional `SurfaceImpulse`.
- missing-screen seed có flags `allow_no_screen_anchor`, `must_not_claim_screen`, và với presence/re-engagement có thêm `thin_presence_no_screen`.
Debug khi:
- memory/thought/private seed có trong runtime nhưng arbiter vẫn chỉ thấy long-silence cue.
- surface nghe như raw private/debug dump: kiểm tra compiler guards trước, rồi mới soi `SurfaceValve`.
- re-engagement sinh câu timer/status ping: kiểm tra compiler có drop timer-only seed và chỉ chọn public anchor không.
Status: ACTIVE TRACKED SURFACE SEED COMPILER.

## `src/cortex/private_life/contracts.py`
Role: data contracts cho tầng đời sống riêng của runtime.
Objects:
- `PrivateLifeState`: state bền gồm habitat, attachments, projects, anchors, daily, taste, solitude, rituals, errands, event log.
- `PrivateAnchor`, `PrivateAnchorUpdate`: neo self-continuity riêng của runtime, tách khỏi project/task.
- `SurfaceSeedCandidate`: seed private-life đã qua quyền surface tối thiểu, chưa phải public speech.
- `PrivateLifeTickResult`: output một tick private-life, giờ có cả `anchor_updates`.
Current code specifics:
- tracked lần đầu ở `aa1d303`, mở rộng tiếp ở `0ac74ec`, và chạm nhẹ ở `d287f57`.
- AUDIT 2026-06-08: `PrivateLifeState` không còn chỉ có project/object/ritual; source hiện có thêm `anchors`, `PrivateLifeEventType` có `private_anchor_activated` và `private_anchor_surface_ready`.
- `private_life_state_digest()` trả `projects`, `anchors`, `objects`, `errands`, `solitude`, `taste`, `recent_events` cho runtime/debug menu.
Debug khi:
- prompt/debug menu không thấy anchor dù core đã chạm anchor.
- tưởng private-life seed là public speech trực tiếp thay vì seed phải qua `SurfaceSeedCompiler`/`SurfaceArbiter`.
Status: ACTIVE NEW TRACKED CONTRACT LAYER.

## `src/cortex/private_life/core.py`
Role: engine cập nhật đời sống riêng của runtime theo tick.
Inputs:
- snapshot/runtime owner/user text/channel/idle seconds.
- object residue, habitat observation, project updates, private-mind bias.
Current code specifics:
- tracked lần đầu ở `aa1d303`, mở rộng tiếp ở `0ac74ec`, và chạm nhẹ ở `d287f57`.
- seed sẵn 5 anchor nền: `identity`, `aesthetic`, `obsession`, `world`, `private_agenda`.
- `_update_private_anchors()` hiện gom evidence từ idle, user text, habitat, object residue, project update, `private_mind_speech_bias`, rồi tăng `pressure`/`continuity`/`surface_permission` trên anchor.
- `_build_life_events()` hiện đẩy `private_anchor_activated` vào audit trail; `_build_surface_seed()` có thể tạo `SurfaceSeedCandidate(kind="private_anchor_surface")`.
- `TasteProfile` và `SolitudeLoop` cũng bị chạm bởi anchor chứ không chỉ project/residue.
Debug khi:
- private-life có vẻ "sống" trong state nhưng không bao giờ sinh seed surface.
- anchor pressure tăng mà digest/menu không phản ánh.
Status: ACTIVE NEW PRIVATE-LIFE CORE.

## `src/runtime/private_life_daemon.py`
Role: lifecycle owner cho `PrivateLifeCore`.
Owns:
- rate-limit tick private-life.
- queue seed private-life cho downstream.
- digest/debug menu private-life cho runtime/UI.
Current code specifics:
- tracked lần đầu ở `aa1d303`, chạm tiếp ở `0ac74ec`.
- `from_runtime()` build `PrivateLifeStore`, infer project root, và chỉ bật khi config/env cho phép.
- AUDIT 2026-06-08: digest `menu` hiện có cả `anchors`, nên `surface_seed_compiler` và UI/debug path không cần tự đoán anchor từ raw state.
Debug khi:
- `private_life` có state file nhưng runtime không tick.
- compiler/UI không thấy `anchors` dù core đã update.
Status: ACTIVE NEW LIFECYCLE OWNER.

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

## `src/cortex/subconscious/model_synthesizer.py`
Role: Lane 3 private synthesizer có model-backed refinement cho subconscious blackboard.
Purpose:
- lấy `ThoughtFragment` từ blackboard/snapshot rồi nén thành `ThoughtObject` có evidence gate chặt hơn.
- thêm lớp “inner court” private: prosecutor / defense / judge chỉ dùng cho audit nội bộ, không phải public text.
- nếu model fail hoặc bịa evidence, fallback về `ConsciousSynthesizer` deterministic.
Core contracts:
- `ModelSynthesisPolicy`: knobs env cho Lane 3 như `ERIS_LANE3_MODEL_SYNTHESIS`, `ERIS_LANE3_MIN_FRAGMENTS`, `ERIS_LANE3_MIN_PRESSURE`, `ERIS_LANE3_PROMPT_FRAGMENTS`.
- `InnerCourtReport`: report debug có `verdict`, `route`, `confidence`, `evidence_ids`, `fallback_used`.
- `ModelBackedConsciousSynthesizer`: lớp chính giữ `last_inner_court_report`.
Current code specifics:
- file này là hàng mới ở `637e7fc`; trước snapshot đó bản source-map gần như chưa có gì để bám.
- `synthesize()` luôn chạy deterministic trước; chỉ gọi model khi đủ số fragment sống và board pressure vượt ngưỡng.
- prompt contract ép JSON private-only, cấm sinh public dialogue, cấm bịa screen facts/memory/user intent.
- `_object_from_model_payload()` chỉ merge evidence/route/privacy trong giới hạn cho phép; evidence id lạ phải bị loại.
- `runtime/subconscious_loop.py` sẽ hút `last_inner_court_report` vào `audit_report["lane3_inner_court"]`, còn public surface vẫn phải đi qua `SurfaceArbiter`/permission downstream.
Debug khi:
- Lane 3 API gọi rồi nhưng subconscious report luôn fallback deterministic.
- model synthesis trả route quá tự tin hoặc evidence ids không tồn tại.
- audit có `lane3_inner_court` nhưng không thấy `surface_seed`/`latest_seed` đi tiếp sang runtime.
Status: ACTIVE NEW HOT FILE VERIFIED_IN_WORKSPACE.

## `src/cortex/private_mind/__init__.py`
Role: public API nhỏ cho private mind package.
Exports:
- `EvidenceDossier`, `ThoughtFragment`, `PrivateConcern`, `InternalJudgment`, `StateMutation`, `SurfaceCandidate`, `PrivateMindTickResult`.
- `ConcernStore`, `EvidenceDossierBuilder`, 4 mini-evaluator, `GemmaInnerSynthesizer`, `StateMutationBus`, `SurfaceValve`.
Debug khi:
- import vòng giữa coordinator/runtime và cortex private mind.
- file nào đó import sâu quá nhiều class private thay vì qua package API.
Status: ACTIVE PACKAGE FACADE.

## `src/cortex/private_mind/inner_diary_renderer.py`
Role: renderer debug/private cho `private_mind_digest`.
AUDIT 2026-06-08:
- **ADDED Ở `8e915de`, mở rộng tiếp ở `0ac74ec` và `d287f57`.**
- Doc cũ nói file này untracked/local là sai; file này hiện đã tracked từ `8e915de` và tiếp tục được mở rộng trong tracked history mới hơn.
Behavior:
- `InnerDiaryRenderer.render(digest)` đọc `menu.current_thought`, `temporary_thoughts`, `retained_thoughts`, `inner_judgment`, `state_mutations`, `future_bias`, `speech_silence_reason`, `surface_queue`.
- Trả dict `mode="debug_private"`, `title="Inner Diary"`, `text`, và `sections`.
- Sections chính: `Hiện tại`, `Vì sao`, `Giả thuyết`, `Bận tâm còn mở`, `Ảnh hưởng tiếp theo`, `Bề mặt`.
- Đây là view debug/private; không tạo public speech, không expose raw prompt, không bịa thought ngoài digest.
Debug khi:
- Godot Private Mind panel chỉ hiện raw JSON thay vì diary: kiểm tra payload có `inner_diary` ở root hoặc trong `menu`.
- diary thiếu section: soi digest nguồn có field tương ứng không, không sửa renderer để invent dữ liệu.
Status: ACTIVE TRACKED PRIVATE DEBUG RENDERER.

## `src/cortex/private_mind/contracts.py`
Role: data contracts cho private cognition.
Objects:
- `EvidenceDossier`: evidence bundle cho evaluator/synthesizer.
- `ThoughtFragment`: claim riêng có confidence/pressure/evidence.
- `PrivateConcern`: mối bận tâm còn mở trong concern store.
- `InternalJudgment`: phán quyết tổng hợp private.
- `StateMutation`: yêu cầu đổi bias/state tương lai.
- `SurfaceCandidate`: topic seed rất nhỏ có thể đi tới surface valve.
- `PrivateMindTickResult`: output tick runtime.
Rules:
- không object nào là public speech.
- evidence ids phải được giữ/cắt gọn; model payload không được tự bịa evidence lạ.
- `SurfaceChannel` tách `none`, `surface_arbiter`, `memory_update_only`, `body_only`.
- AUDIT 2026-06-08: `SurfaceCandidate` và `InternalJudgment` hiện đã mang `epistemic_stance` + `intent` như field contract thật, có normalize helper riêng, và `to_dict()/from_mapping()` round-trip cả hai field này.
Debug khi:
- JSON/debug digest có object sống hoặc repr lạ.
- surface candidate bị hiểu nhầm thành câu trả lời public.
Status: ACTIVE CONTRACT.

## `src/cortex/private_mind/epistemic.py`
Role: classifier pure cho epistemic self-awareness của private mind.
Current code specifics:
- added ở `0ac74ec`.
- định nghĩa `VALID_INTENTS`, `VALID_STANCES`, `DELIBERATE_INTENTS`, cùng hai marker `epistemic_confabulation_blocked` và `epistemic_self_knowledge_failure`.
- `resolve_intent()` mặc định `no-anchor -> speculative`, `has-anchor -> sincere`; `classify_epistemic_stance()` map `(has_anchor, intent)` sang `grounded` / `ungrounded_aware` / `ungrounded_blind`.
Debug khi:
- pipeline surface xử lý confabulation có vẻ inconsistent giữa model output và deterministic fallback.
- muốn biết bug nằm ở classifier pure hay ở `SurfaceValve`.
Status: ACTIVE NEW PURE MODULE.

## `src/cortex/private_mind/evidence_dossier.py`
Role: gom evidence runtime thành dossier cho private mind.
Inputs:
- user text/channel.
- telemetry/snapshot/observer frame/wake decision.
- memory hits/session ledger/internal agenda.
- concern store và surface outcome gần nhất.
- AUDIT 2026-06-07: source hiện đã thêm `thought_stream`, `surface_candidate_queue`, và `runtime_owner` vào input. Nếu doc/trace chỉ thấy telemetry + memory + agenda thì thiếu một lớp runtime anchor mới.
Current code specifics:
- runtime state hiện có `thought_stream`, `private_runtime`, `surface_queue`.
- evidence index có thể thêm `dossier.runtime.thought_stream`, `dossier.runtime.private_state`, `dossier.runtime.surface_queue`, và `dossier.surface.outcome`.
- metrics hiện có thêm `runtime_anchor_count`, `memory_hit_count`, `repair_failure_count`, `concern_count`, `dossier_thickness`; đây là tín hiệu quan trọng khi evaluator/synthesizer có vẻ "thiếu bằng chứng".
Debug khi:
- evaluator nói có bằng chứng nhưng evidence id không tồn tại trong dossier.
- private mind không thấy user turn hoặc wake/surface outcome mới.
- private mind không cảm được pressure/momentum/surface queue dù runtime đã có `thought_stream.private_mind_pressure_bias`.
Status: ACTIVE EVIDENCE BUILDER.

## `src/cortex/private_mind/mini_evaluators.py`
Role: bốn evaluator nhỏ trước synthesis.
Evaluators:
- `IntentEvaluator`.
- `MemoryResonanceEvaluator`.
- `RiskAndPermissionEvaluator`.
- `FutureBiasEvaluator`.
Contract:
- mỗi evaluator nhận cùng `EvidenceDossier` và trả `ThoughtFragment`.
- ưu tiên model fragment nếu adapter trả đủ confidence; nếu không fallback rule deterministic.
- không evaluator nào được commit memory hoặc nói trực tiếp với user.
Debug khi:
- private mind quá câm: kiểm tra rule fallback có tạo fragment đủ confidence không.
- API trả fragment nhưng bị bỏ: kiểm tra `min_model_confidence`, claim rỗng, evidence ids.
Status: ACTIVE PRIVATE EVALUATOR PIPELINE.

## `src/cortex/private_mind/inner_synthesizer.py`
Role: tổng hợp fragments thành `InternalJudgment`.
Purpose:
- rank/reject hypotheses.
- tạo `private_concern_update`.
- đề xuất `state_mutations`.
- tạo `surface_candidate` chỉ khi public-safe.
Contract:
- model path là optional; deterministic synthesis vẫn phải chạy được.
- output là private verdict + future bias, không phải dialogue.
Debug khi:
- fragments có pressure nhưng không có mutation/surface candidate.
- model synthesis quá tự tin hoặc quên rejected hypotheses/open questions.
Status: ACTIVE PRIVATE SYNTHESIZER.

## `src/cortex/private_mind/concern_store.py`
Role: persist/open private concerns.
Storage:
- default path qua runtime: `memory_core/private_concerns.json`.
- AUDIT 2026-06-07: file IDE đang mở là `src/memory_core/private_concerns.json`, nhưng source default vẫn là `memory_core/private_concerns.json` qua `ERIS_MEMORY_CORE_DIR` mặc định. Nếu không set `ERIS_MEMORY_CORE_DIR=src/memory_core`, file `src/memory_core/private_concerns.json` là local/side path và không phải store mặc định.
Behavior:
- update từ fragments và judgment concern update.
- giữ status open/watching/blocked/resolved/rejected/stale.
- snapshots được đưa vào digest để debug.
Debug khi:
- concern cũ không decay/stale.
- private mind lặp lại cùng mối bận tâm dù outcome đã xử lý.
Status: ACTIVE PRIVATE STATE STORE.

## `src/cortex/private_mind/state_mutation_bus.py`
Role: biến `StateMutation` thành ảnh hưởng thật lên runtime.
Targets:
- `agenda_stack`.
- `repair_memory`.
- `belief_core`.
- `speech_bias`.
- `inquiry_plan`.
- `thought_stream_pressure`.
- `surface_candidate_queue`.
- `active_state`.
- `private_concern`.
Current code specifics:
- ghi bias vào owner fields như `private_mind_speech_bias`, `private_mind_inquiry_plan`, `private_mind_active_state`, `private_mind_thought_pressure`.
- có thể tăng `thought_stream.private_mind_pressure_bias` để downstream surface arbitration cảm được áp lực nội sinh.
- repair/belief commit đi qua memory/state committer best-effort, không crash runtime nếu fail.
- AUDIT 2026-06-07: bus vẫn có target `surface_candidate_queue`, nhưng không còn tự enqueue `judgment.surface_candidate` sau `apply()`. Nếu surface candidate chỉ nằm trong judgment mà không qua `SurfaceValve`/loop/daemon, nó không nên thành public impulse.
Debug khi:
- `state_mutations.requested` có dữ liệu nhưng `applied` báo `confidence_below_threshold`.
- speech bias không vào prompt hoặc thought pressure không vào surface arbiter.
- mutation target `surface_candidate_queue` báo applied nhưng SurfaceArbiter không thấy `source=private_mind`: kiểm tra candidate có bị valve/daemon/dedupe/drain xử lý trước không.
Status: ACTIVE MUTATION BUS.

## `src/cortex/private_mind/surface_valve.py`
Role: chốt lọc public-safe trước khi private mind được surface.
Purpose:
- nhận `InternalJudgment.surface_candidate`.
- loại candidate thiếu an toàn/thiếu evidence/không đủ pressure.
- convert candidate đạt chuẩn thành `SurfaceImpulse`.
Contract:
- chỉ seed/topic nhỏ đi ra; không raw judgment, không chain riêng, không claim màn hình nếu không có evidence.
- output dùng source/family `private_mind` để `SurfaceArbiter` còn debug được.
- AUDIT 2026-06-08: valve hiện không còn chỉ là threshold/filter mù. Nó classify epistemic trước gate (`resolve_intent()` + `classify_epistemic_stance()`), route `ungrounded_blind` về `body_only` thay vì drop im lặng, gắn `epistemic_deliberate_ungrounded=True` cho `ungrounded_aware`, và với claim grounded thì merge thêm `public_anchor_refs`/`public_anchors` vào evidence của `SurfaceImpulse`.
Debug khi:
- inner judgment có candidate nhưng queue rỗng.
- private mind surface nghe như confession/debug dump.
Status: ACTIVE SURFACE SAFETY VALVE.

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
- `private_mind_speech_bias` được nhận như soft wording/style pressure; nó thêm safety flag/context, không được bypass meaning/quiet/source guards.
- history gần đây theo file:
  `fd7b903`, `04bd5f6`, `5f812fc` đều còn chạm trực tiếp;
  tức là doc snapshot nào chỉ bám trước `2026-06-04` sẽ bỏ lỡ một loạt tune mới cho endogenous leakage / fallback contract.
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
Role: thực thi action desktop/API đã được router hoặc LLM chọn.
Handles:
- Win32 / desktop control: `focus_window`, `set_volume`, `play_pause_media`, `copy_text`, `launch_app`.
- browser / shell-ish helpers: `open_url`.
- grounded remote info actions: `search_web`, `get_weather`.
- media session read: `get_now_playing`.
Current code specifics:
- `execute()` validate action qua `VALID_SYSTEM_ACTIONS`, rồi dispatch động sang handler `_action_name`.
- `search_web` và `get_weather` dùng Gemini grounding API riêng, tự lấy profile/key qua `get_agent_profile(...)` + `get_secret(...)`, và có thể trả kèm citation URLs trong `data`.
- desktop path vẫn rất Windows-specific: Win32 `SetForegroundWindow`, `keybd_event`, clipboard API, `subprocess.Popen`.
- `launch_app` có alias map đơn giản cho `notepad`, `calc`, `Code.exe`, `Spotify.exe`, `chrome`, `msedge`.
- file này không còn là action stub mỏng; nó đang mang cả nhánh OS control lẫn nhánh remote grounded lookup.
- history gần đây theo file:
  `27d4d09` là đợt bổ sung đáng kể,
  `6658301` chỉnh nhẹ,
  `637e7fc` thêm tiếp khoảng `34` dòng và là mốc gần nhất cần soi nếu `search_web/get_weather` vừa bắt đầu khác hành vi cũ.
Debug khi:
- action trả `success=True` nhưng hiệu ứng OS không xảy ra.
- Gemini grounding có key nhưng `search_web` / `get_weather` vẫn fail.
- `launch_app` hoặc `focus_window` chạy sai vì alias/title match quá thô.
Status: ACTIVE VERIFIED_IN_WORKSPACE, VERIFY SECURITY.

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
Current code specifics:
- `EventLedgerRecord` giữ `frame_id`, `source`, `content`, `reliability`, `privacy_level`, `source_signal_id`, `evidence_ids`, `tags`, `metadata`.
- `atomic_write_json()` ghi temp rồi replace; ledger này cố sống như audit layer thật chứ không phải file append kiểu phó mặc.
- public API chỉ có append/query/recent/by_frame; nếu muốn “sửa quá khứ” thì phải ghi event repair mới, không mutate record cũ.
Debug khi: audit evidence mất, raw event bị overwrite thay vì append, hoặc runtime state trông hợp lý nhưng không truy được nguồn signal/evidence sinh ra nó.
Status: ACTIVE VERIFIED_IN_WORKSPACE.

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

## `src/memory/memory_maintenance.py`
Role: runner maintain cho `MemoryKernel`.
Current code specifics:
- `d287f57` nâng file này thành orchestrator nền gom consolidate unresolved candidates, prune audit, access decay, contradiction placeholder, AI curation, và warm embedding cache.
- mặc định `destructive=False`: audit/prune plan là chính; muốn drop item thật phải bật explicit.
- không được gọi trong hot path chat; đúng chỗ là idle/reflection/session_end.
Debug khi: memory stores phình mà không có vòng maintain, hay semantic cache lạnh khiến recall semantic yếu sau boot.
Status: ACTIVE BACKGROUND MAINTENANCE.

## `src/memory/memory_commit_policy.py`
Role: rule extraction from user turn into MemoryCommitDecision.
Current code specifics:
- `d287f57` đẩy file này thành intake policy 3 tầng: importance detection -> extraction attempt -> fallback capture.
- không ghi thẳng memory store; nếu câu đáng nhớ nhưng chưa parse đủ thì tạo `CANDIDATE_COMMIT`.
- đi cùng `ClaimExtractor`, `MemoryWorthinessPolicy`, `MemoryRetentionPolicy`, `predicate_ontology`; không còn là vài regex mỏng cho name/location.
- vẫn giữ guard cực quan trọng: không commit recall questions như fact.
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
Current code specifics:
- `ClaimExtractor` giờ là facade mỏng: `SemanticParser/model -> MeaningFrame -> ClaimBuilder -> ExtractedClaim`.
- `src/memory/claims/claim_builder.py` được mở rộng ở `d287f57`: chính file này mới map `frame_type + relation` hoặc AI-classified frame sang predicate memory chuẩn, để parser/model không có quyền tự áp predicate.
Status: ACTIVE.

## `src/memory/predicate_ontology.py`, `query_intent.py`, `claim_entailment.py`, `semantic_answer_policy.py`
Role: query-answer ontology for memory facts.
Debug khi: overlap text trả lời sai predicate.
Status: ACTIVE.

## `src/memory/memory_worthiness.py`, `memory_retention_policy.py`, `judgement/*`, `claim_consolidator.py`, `memory_pruner.py`
Role: judge keep/promote/prune memory lifecycle.
Debug khi: memory rác được giữ, memory quan trọng bị prune, candidate không promote.
Status: ACTIVE.

## `src/memory/embedding_index.py`
Role: in-memory embedding index cho `SemanticMemoryStore`.
Current code specifics:
- added ở `d287f57`.
- dùng `transformers` + `numpy`, không cần FAISS/Chroma/server riêng.
- mặc định model `paraphrase-multilingual-MiniLM-L12-v2`; semantic store chỉ dùng embedding để lấy candidate, còn quyết định cuối vẫn thuộc domain/fact_key/confidence/evidence.
Debug khi: recall semantic lexical miss nhưng đáng lẽ embedding phải kéo đúng candidate lên.
Status: ACTIVE NEW INFRA.

## `src/memory/memory_ai_curator.py`
Role: AI curator nền cho memory.
Current code specifics:
- added ở `d287f57`.
- làm hai việc mà rule khó làm gọn: episodic distillation (nhiều episode giống nhau -> một semantic fact ổn định) và concern -> long-term bridge.
- chạy trong background maintenance budget `normal/deep`, không phải hot path chat.
Debug khi: pattern dài hạn có đủ evidence nhưng semantic memory vẫn không kết tinh, hoặc private concern trưởng thành mà không bao giờ thành long-term memory.
Status: ACTIVE NEW BACKGROUND CURATOR.

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
Note:
- sau pull này, `event_ledger.json` không còn là file lẻ mờ nhạt; nó đã thành raw audit trail lớn hơn hẳn và đáng kiểm trước khi kết luận “cognition tự bịa”.
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

## `tests/test_cognitive_pipeline.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: regression cho CognitivePipeline V3.
Covers:
- Raw signal duoc normalize thanh evidence/frame.
- Pipeline tao trace/debug result thay vi fail im lang.
- Manual slot attachment workaround van giu du lieu can thiet.
Status: WORKSPACE NEW TEST.

## `tests/test_shadow_pipeline.py`
AUDIT 2026-06-08 WORKSPACE: NEW / UNTRACKED IN CURRENT WORKSPACE.
Role: regression cho ShadowPipelineMixin.
Covers:
- Shadow pipeline co the bat/tat rieng bang flag/env.
- Ket qua shadow luu vao `last_shadow_*`.
- Loi shadow khong lam chet hot path cu.
Status: WORKSPACE NEW TEST.

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
AUDIT 2026-06-07:
- File hiện `57` dòng; history gần nhất `17ffc4d -> a9e6c58`, không bị `8e915de` chạm.
Covers:
- `tôi thích Hà Tĩnh` tạo `preference_location`, không được answer cho `quê tôi ở đâu` hoặc `tôi đang ở đâu`.
- `living_location` và `hometown` là predicate riêng, không entail chéo.
- `MemoryCommitPolicy` lưu `metadata.semantic_claim`, và `SemanticAnswerPolicy` chỉ trả lời khi exact entailment.
Debug khi:
- ERIS lấy memory sở thích địa điểm để bịa quê/current location.
- retrieval semantic có item đúng chữ nhưng sai predicate vẫn được dùng để trả lời.
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

## `tests/test_subconscious_phase0.py`, `tests/test_subconscious_phase34.py`
Role: regression cho pipeline subconscious worker + synthesize + seed/audit contract.
Debug khi:
- `subconscious_loop` có chạy nhưng không nhả `latest_seed` / `surface_seed`.
- Lane Phase 0 / Phase 3-4 tạo thought object sai route hoặc leak sang public path quá sớm.
Status: ACTIVE TARGETED SUBCONSCIOUS TEST.

## `tests/test_private_mind_daemon.py`
Role: regression cho lifecycle private mind daemon.
AUDIT 2026-06-07:
- **ADDED Ở `3782f41`.**
Covers:
- daemon tick sở hữu surface queue thay vì để coordinator/loop tự giữ rời rạc.
- outcome feedback cập nhật concern lifecycle qua `record_outcome()`.
- `EvidenceDossierBuilder` thấy thought_stream/private_runtime/surface_queue anchors.
Debug khi:
- thêm `PrivateMindDaemon` xong private mind có tick nhưng không đổi state qua lượt sau.
- queue có impulse private-safe nhưng SurfaceArbiter không nhận.
Status: ACTIVE TRACKED REGRESSION.

## `tests/test_private_mind_model_adapter.py`
Role: regression cho parser JSON của private mind API adapter.
AUDIT 2026-06-07:
- **ADDED Ở `3782f41`**, đi cùng patch tracked `src/runtime/private_mind_model_adapter.py`.
Covers:
- JSON object bọc trong markdown/code fence vẫn parse được.
- trailing comma trong object/list được repair.
- object JSON bị cụt ở cuối được bù brace đủ để lấy judgment/fragment chính.
Debug khi:
- private mind API trả text có JSON hợp lệ bên trong nhưng evaluator rơi về rule fallback.
- `debug_api.last_error=invalid_json` xuất hiện dù raw response chỉ bẩn nhẹ.
Status: ACTIVE TRACKED REGRESSION.

## `tests/test_unit_resilience.py`
Role: unit tests cho PrivateMind API transient resilience.
AUDIT 2026-06-07:
- **ADDED Ở `8e915de`**, đi cùng patch tracked `src/runtime/private_mind_model_adapter.py`.
Covers:
- `_classify_transport_exception()` phân biệt `transient` với `fixed_config`.
- transient cooldown threshold/timing.
- `_tracked_chat_json()` fast-fail khi cooldown active và không gọi client.
- `debug_status()` có field mới `degraded_cause`, `transient_streak`, `transient_cooldown_until` và giữ field legacy.
Debug khi:
- HTTP 500/503/429/timeout vẫn spam network mỗi tick.
- `api_degraded` true nhưng không biết là `invalid_json` hay `transient`.
Status: ACTIVE TRACKED RESILIENCE REGRESSION.

## `tests/test_integration_loop_resilience.py`
Role: integration tests cho `private_mind_loop.tick()` khi provider transient-fail.
AUDIT 2026-06-07:
- **ADDED Ở `8e915de`.**
Covers:
- loop không crash khi adapter lặp HTTP 503.
- sau ngưỡng circuit-breaker, tick sau fast-fail thay vì chờ network.
- cooldown hết hạn thì adapter thử gọi lại và có thể phục hồi.
- debug status phân biệt `transient` với `invalid_json`.
Debug khi:
- private mind có deterministic fallback nhưng bị hiểu nhầm là model API vẫn ổn.
- transient cooldown active mà loop vẫn treo lâu.
Status: ACTIVE TRACKED RESILIENCE REGRESSION.

## `tests/test_pbt_bug_condition_transient.py`, `tests/test_pbt_preservation_transient.py`, `tests/test_pbt_reset_transient.py`
Role: property-based tests cho bug condition transient và preservation.
AUDIT 2026-06-07:
- **ADDED Ở `8e915de`.**
Covers:
- mọi transient transport error trong bug condition phải retry/cooldown/fast-fail đúng property.
- JSON hợp lệ, `invalid_json`, fixed-config, và đường non-transient phải giữ behavior cũ.
- success sau transient reset degraded/cooldown state đúng.
Debug khi:
- vá resilience làm hỏng đường `invalid_json` cũ hoặc retry cả lỗi cấu hình cố định.
Status: ACTIVE TRACKED PBT RESILIENCE.

## `tests/test_udp_private_mind_debug.py`
Role: regression cho payload debug private mind qua UDP khi quá lớn.
AUDIT 2026-06-07:
- **ADDED Ở `3782f41`.**
Covers:
- `UdpTransport.send_json()` compact `private_mind_digest` khi payload vượt `MAX_UDP_PAYLOAD_BYTES`.
- bản compact vẫn giữ `current.dominant_judgment`, `menu.debug_api.last_error`, và gắn `udp_debug_truncated=true`.
- `emotion_debug.private_mind` được thay bằng digest compact, không giữ blob quá lớn.
Debug khi:
- Godot không hiện private mind debug nhưng Python vẫn có digest.
- payload UDP lớn làm mất toàn bộ decision/body command.
Status: ACTIVE TRACKED REGRESSION.

## `tests/test_model_budget_policy_queue.py`
DOC DRIFT 2026-06-08 WORKSPACE:
- Dong ben duoi neu con noi `force_local_gguf_main` co priority lane rieng la LAC HAU theo source hien tai; flag/lane nay da bi go.
- Test hien tai nen duoc doi chieu lai voi `vision_force_run`, queue-only/resource guard, va heavy tier serialization. Neu test van expect `force_local_gguf_main`, do la missing update.

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
- `thought_stream_surface` cap confidence khi vital thấp và body-only khi thiếu anchor/payload.
- `blind_frustration` speakable path, sensor visibility gating, và blame-block contract.
- YAML/config loader.
- default repo YAML load khi env thiếu.
Debug khi:
- sửa `SurfaceArbiter` làm micro-presence im.
- config threshold đổi nhưng runtime không ăn.
- body-only streak/rate-limit hành xử lạ.
Status: CRITICAL SURFACE TEST.

## `tests/test_surface_seed_compiler.py`
Role: regression cho `SurfaceSeedCompiler`.
AUDIT 2026-06-07:
- **ADDED Ở `3782f41`**, đi cùng patch tracked `src/cortex/surface_seed_compiler.py` và `presence_controller.py`.
Covers:
- memory resonance public-safe compile thành impulse `source="surface_seed_compiler"`.
- thought/subconscious public seed được chọn thay vì raw/private topic.
- raw private judgment / `ThoughtFragment` / invalid JSON private bias không được compile.
- private impulse đã qua `SurfaceValve` và có public anchor được phép compile tiếp.
- timer-only re-engagement không được tạo speech seed.
Debug khi:
- surface seed mới làm ERIS nói kiểu dump private/debug.
- re-engagement lại rơi về `idle=...`/timer ping.
- memory resonance/thought seed tồn tại nhưng arbiter không thấy impulse compiled.
Status: ACTIVE TRACKED REGRESSION.

## `tests/test_private_mind_surface_gates.py`
Role: regression cho contract surface an toàn của private mind.
Covers:
- fallback candidate không anchor bị hạ về `body_only`.
- `api_invalid_json` chặn public surface.
- AUDIT 2026-06-08 tracked update: `stance + intent` đi qua `SurfaceValve` không đổi, grounded impulse giữ `public_anchor_refs`, và `ungrounded_aware` phản ánh `intent=` trong `llm_contract`.
Status: ACTIVE REGRESSION PATCH.

## `tests/test_epistemic.py`
Role: unit + property-based tests cho classifier pure `cortex.private_mind.epistemic`.
Covers:
- bảng `(has_anchor, intent) -> stance`.
- `resolve_intent()` mặc định kiểu Cartesian: `no-anchor -> speculative`.
- determinism/property tests cho classifier và resolver.
Tracked history:
- added ở `0ac74ec`.
Status: ACTIVE NEW TEST.

## `tests/test_private_mind_contracts.py`
Role: regression cho contract `intent` / `epistemic_stance` trên `SurfaceCandidate`, `InternalJudgment`, và `SurfaceImpulse`.
Covers:
- default/normalize/round-trip serialize.
- `from_mapping()` và `to_dict()/to_context()` giữ đúng hai field mới.
Tracked history:
- added ở `0ac74ec`.
Status: ACTIVE NEW TEST.

## `tests/test_surface_valve.py`
Role: integration tests cho luật epistemic mới của `SurfaceValve`.
Covers:
- `ungrounded_blind` không được public-surface nhưng cũng không bị drop im lặng.
- `ungrounded_aware` giữ `intent` và deliberate flag.
- grounded claim giữ evidence/intent đúng, `api_invalid_json` bị chặn, và model-vs-fallback equivalence.
Tracked history:
- added ở `0ac74ec`.
Status: ACTIVE NEW TEST.

## `tests/test_presence_controller_memory_surface.py`
Role: regression test cho đường `active_memory_resonance -> endogenous surface impulse`.
Covers:
- memory resonance public-safe được convert thành `SurfaceImpulse(kind="memory_resonance")`.
- affective/private resonance `may_surface=false` không được surface.
- patch `3782f41` cover `_build_surface_arbiter_result()` có gọi compiler và đưa thought seed public-safe vào arbiter.
Debug khi:
- memory residue đúng ra chỉ nên thành low-claim muse nhưng lại im hoàn toàn.
- affective residue private bị lộ ra presence/surface path.
Status: ACTIVE TARGETED REGRESSION.

## `tests/test_runtime_coordinator.py`
Role: regression suite cho wake-gated route và behavior contract cấp runtime.
Covers:
- reject/body-only/re-engagement status của wake gate không còn leak sentinel `reject:not_started`.
- `surface_override` được ghi khi winner thật khác route gọi ban đầu.
- body-only không reset silent debt hay bị tính như speech thật.
- scenario `VS Code mở tongquat.md + focused + silence=6 + vital thấp` không cho `thought_stream_surface` thắng kiểu filler; chỉ body-only hoặc anchored presence.
- family cooldown và thin no-screen presence contract.
Debug khi:
- sửa `coordinator.py`/`presence_controller.py` xong thấy surface “sống hơn” hay “chết đi” nhưng không biết có đúng contract không.
- wake debug ghi `stage=surface_arbiter` mà status/reason vẫn mù.
Status: CRITICAL BEHAVIOR REGRESSION.

## `tests/test_blind_frustration_surface.py`
Role: targeted regression cho nhánh `sensor_visibility -> blind_frustration`.
Covers:
- permission blocked hoặc plain missing evidence thì không được public grumble.
- timeout / budget blocked / context shift chưa refresh thì được mở cửa cho grumble nhỏ.
- `blind_frustration` được arbiter coi là speakable sensor impulse.
- wording context có `sensor_visibility_contract` và blame user bị block nếu thiếu `recent_context_shift=true`.
Debug khi:
- vừa merge patch sensor frustration xong mà route này im sạch, hoặc ngược lại than bừa mọi lúc thiếu evidence.
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
14. Nếu route đang than kiểu “mù màn hình”, kiểm tra `sensor_visibility.py` xem đó là plain missing evidence, permission blocked, timeout, budget block, hay `context_shift_without_refresh`; chỉ ba case sau mới nên mở cửa cho `blind_frustration`.
15. Nếu `blind_frustration` có text nhưng nghe như trách user, kiểm tra evidence có `recent_context_shift=true` không; nếu không có mà text vẫn qua được, thì blame-block contract đang thủng.
16. Nếu winner/source là `private_mind`, kiểm tra `private_mind_digest.menu.inner_judgment`, `surface_queue`, `state_mutations.applied`, rồi mới soi arbiter; private mind không được surface nếu chưa qua `SurfaceValve`.
17. Nếu cần biết thay đổi vừa rồi có “sống hơn” mà vẫn đúng luật không, chạy cụm behavior regression trong `tests/test_runtime_coordinator.py` thay vì đoán bằng log mắt thường.
Fix direction:
- Tune `config/low_level_speech_policy.yaml` trước, đừng rải thêm câu mẫu trong từng module.
- Nếu cue thiếu evidence, sửa source cue; nếu policy reject đúng thì không ép LLM.
- Nếu body-only streak kẹt, kiểm tra `body_only_after_llm_decline` và `max_body_only_streak`; code hiện tại sẽ cố đẩy sang force-LLM chứ không muốn kẹt body-only vô hạn.

## Case: PrivateMind tick nhưng không đổi hành vi / không surface
Symptom:
- `private_mind_digest` có fragments/judgment nhưng câu trả lời không đổi.
- `surface_candidate` có trong digest nhưng `SurfaceArbiter` không thấy winner/source `private_mind`.
- `debug_api.calls` tăng nhưng `state_mutations.applied` rỗng hoặc toàn fail.
- log có nhiều `[PrivateMind API] fragment failed ... error=invalid_json` hoặc `[PrivateMind API] synthesis failed error=invalid_json`, nhưng sau đó vẫn có `[PrivateMind] fragments=4 concerns=4 judgment=yes ...`.
Check:
1. AUDIT 2026-06-07: nếu log có khoảng `60` lần `invalid_json` (`49` fragment, `11` synthesis) nhưng vẫn có `fragments=4 concerns=4 judgment=yes`, kết luận chính là **PrivateMind API output không parse được JSON nhưng rule fallback đang cứu pipeline**.
2. Khi gặp case trên, soi `src/runtime/private_mind_model_adapter.py`: `_parse_json()` có bắt được raw content không, provider có thật sự tôn trọng `response_format={"type":"json_object"}` không, output có bị markdown/prose/schema cụt vượt khả năng repair không.
3. Nếu source hiện có `PrivateMindDaemon`, soi `private_mind_digest.menu.private_mind_daemon`, `daemon.surface_queue`, `tick_count`, `skipped_count`, `last_surface_outcome`, `outcome_feedback_reports` trước khi đổ lỗi cho loop.
4. `ERIS_PRIVATE_MIND_ENABLED` và `ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC` có làm tick bị skip không.
5. `ERIS_PRIVATE_MIND_API_ENABLED` chỉ bật API path; nếu tắt thì rule fallback vẫn phải tạo fragment, không phải disable cả loop.
6. `EvidenceDossier` có recent user turns, wake/surface outcome, memory hits, concern snapshots, thought_stream/private_runtime/surface_queue anchors không.
7. `MiniEvaluatorPipeline` có ít nhất vài fragment confidence đủ dùng không; model fragment dưới threshold sẽ bị thay bằng rule.
8. `GemmaInnerSynthesizer` có tạo `state_mutations`/`surface_candidate` hay chỉ tạo private verdict.
9. `StateMutationBus` báo target nào fail: `speech_bias`, `thought_stream_pressure`, `surface_candidate_queue`, `belief_core`, hay `repair_memory`.
10. `SurfaceValve` có drop candidate vì thiếu public safety/evidence/pressure không.
11. `private_mind_surface_queue`/`daemon.surface_queue` có item nhưng bị `_drain_private_mind_surface_impulses()` hoặc `daemon.drain_surface_impulses()` hút quá sớm hoặc dedupe mất không.
12. `PresenceController` có truyền private impulses vào `SurfaceArbiter` qua `extra_impulses` không.
13. `SurfaceArbiter` có rate-limit/family cooldown/body-only policy chặn `source=private_mind` không.
14. `prompt_context_builder.py` có render `private_mind_speech_bias` vào prompt không; nếu bias vào prompt rồi mà wording không đổi, soi LLM contract/post filters.
15. `transport/udp.py` có compact hoặc fallback-strip `private_mind_digest` vì payload quá lớn không; `udp_debug_truncated=true` không có nghĩa loop/daemon không chạy.
Fix direction:
- Đừng cho raw `InternalJudgment` thành public text; nếu muốn nói, sửa `SurfaceValve`/`SurfaceImpulse`/arbiter path.
- Nếu muốn private mind ảnh hưởng lâu dài, ưu tiên mutation target `speech_bias`, `thought_stream_pressure`, `belief_core`, hoặc `repair_memory` thay vì chỉ surface một câu.
- Nếu API fail bằng `invalid_json`, sửa prompt/response_format/provider/parser ở `private_mind_model_adapter.py`; runtime vẫn nên sống bằng deterministic fallback.

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

Bản `tongquat.md` này là bước chuyển từ “tổng quan kiến trúc” sang “bản đồ debug”. Ở revision hiện tại, nó cần bám mốc `HEAD d287f57`: private mind daemon/surface seed đã tracked từ `3782f41`, Inner Diary/resilience đã tracked từ `8e915de`, private-life đã được add ở `aa1d303`, epistemic self-awareness + đợt UI follow-up đã tracked ở `0ac74ec`, và memory stack mới đã được add/mở rộng ở `d287f57`. Worktree lúc chốt tài liệu lại đang có dirty state mới ở cụm memory runtime + embedding/cache, nên các dòng cũ gán dirty state cho private-mind/private-life hoặc coi `epistemic` là workspace-only đều phải sửa lại theo tracked history mới và trạng thái worktree recheck cuối.
