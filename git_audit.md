# ERIS Git Audit Log

File này chứa lịch sử git delta, audit drift, và worktree status được tách ra từ `tongquat.md` để giữ debug source-map gọn hơn.

Snapshot tại `HEAD d287f57` (2026-06-08). Nếu cần tra cứu commit hash cụ thể hoặc drift notes theo từng file, xem tại đây.

---

# 0A. Git delta gần đây

Khoảng thay đổi đã soi trực tiếp hiện tại: từ `2026-06-04` đến `2026-06-08`, chuỗi commit nóng kéo từ `fdfe52c`, `c268eab`, `aa9af6f`, `04bd5f6`, `5f812fc`, `553985e`, `eff0420`, `e8d3511`, `104c45b`, `9bbdcd2`, `637e7fc`, `f8555c6`, `86d3fcf`, `3782f41`, `8e915de`, `aa1d303`, `0ac74ec` lên tới `d287f57`.

Trạng thái sync với remote lúc rà tài liệu:
- `git rev-parse HEAD` = `git rev-parse origin/main` = `d287f576069578f728e7b856847f9c0ec7e2d3b6`.
- `git rev-list --left-right --count HEAD...origin/main` trả `0  0`.
- `git status --short` ở lượt recheck cuối hiện có dirty/untracked mới: `memory_core/active_state_snapshot.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl`, `src/memory/embedding_index.py`, `src/memory/memory_models.py`, `tongquat.md`, và untracked `src/paraphrase-multilingual-MiniLM-L12-v2/`.
- nghĩa là hiện **không có commit nào bị thiếu do chưa pull**, nhưng worktree ở thời điểm bàn giao không còn sạch.
- **CẬP NHẬT 2026-06-08 audit**: các dòng cũ nói `aa1d303` là HEAD mới nhất, hoặc mô tả dirty state còn xoay quanh private-mind/private-life, đều đã lạc hậu. `0ac74ec` đã commit hẳn cụm `claim-epistemic-awareness`, `src/cortex/private_mind/epistemic.py`, `tests/test_epistemic.py`, `tests/test_private_mind_contracts.py`, `tests/test_surface_valve.py`, cùng đợt mở rộng lớn cho `body/UdpListener.cs`/Inner Diary UI. `d287f57` tiếp tục commit hẳn các thay đổi memory như `src/memory/memory_ai_curator.py`, `src/memory/embedding_index.py`, mở rộng `memory_maintenance.py`, `memory_commit_policy.py`, `memory_semantic_parser_adapter.py`, `claim_builder.py`, và thêm một vòng cập nhật `UdpListener`/`chat_cycle`/`concern_store`. Dirty state hiện tại lại lệch sang cụm memory runtime + embedding model/cache.

Lịch sử `git pull` còn thấy trực tiếp trong reflog gần đây:
- tổng cộng `6` entry có chữ `pull`.
- mốc rõ nhất: `2026-06-04 21:24:32 +0700` (merge), `2026-05-30 19:33:35 +0700` (fast-forward), `2026-05-30 18:52:07 +0700` (merge), `2026-05-27 15:55:50 +0700` (merge), `2026-05-26 22:30:42 +0700` (merge).
- còn một mốc `pull --rebase (start)` tại `2026-05-02 16:02:07 +0700`.

Trục thay đổi chính theo git:
- low-level surface path đã được khóa thành một trục rõ ràng `PresenceController -> SurfaceArbiter -> LowLevelSpeechPolicy -> LlmService.generate_micro_presence_line`, với thêm các nhánh guard mới cho `blind_frustration`, continuity tension, và thought-surface có anchor.
- `config/low_level_speech_policy.yaml` tiếp tục được tune; file này giờ quan trọng hơn snapshot cũ vì các threshold/reasoning path đã đổi thêm sau `553985e`, không chỉ còn mỗi force-LLM sau im lặng.
- `LlmService` vẫn giữ strict decision JSON, nhưng phần mô tả tài liệu cũ đã lạc nhịp với việc service gọn bớt fallback cứng và đẩy nhiều logic route/repair sang các layer quanh nó.
- `sensor_visibility.py` được thêm hẳn thành contract factual cho trạng thái “mù màn hình”; plain missing evidence thì im, còn timeout / budget block / context shift chưa refresh mới có quyền mở cửa cho `blind_frustration`.
- `telemetry/system.py` không còn chỉ đọc active window/browser title; nó đã lazy-init `ContentMetadataCollector` để nhặt metadata foreground có source ladder L0-L5 rồi nhét vào telemetry snapshot.
- `telemetry/content_metadata.py` là mảng mới đáng chú ý: DOM/accessibility/media-session/browser title được gom theo thang nguồn, có privacy guard, stale guard, conflict notes, và cap confidence trước khi Se dùng.
- `SeLens` đã bớt kiểu router keyword tuyệt đối; hiện nó chấm điểm context cạnh tranh, giữ `confidence`, `ambiguity`, `confidence_cap`, và hấp thụ `content_metadata` vào evidence/claim style/prompt facts.
- `MeaningLayer` được đẩy thêm nhánh `prolonged_activity`: cùng semantic family kéo dài đủ lâu giờ có thể trở thành meaning shift riêng, thay vì mọi thứ mắc kẹt mãi ở `ambient_idle`.
- `continuity_threat.py` là module mới tách riêng “im lâu” khỏi “đứt gãy hiện diện”; continuity anxiety giờ được tính như prediction error theo ngữ cảnh, không phải đồng hồ im lặng cosplay cảm xúc.
- `contracts.py` giờ đã mang `content_metadata` ngay trong `TelemetrySnapshot`, nên các downstream layer không cần tự đoán metadata foreground qua title thô nữa.
- `sensory_model_adapter.py` được khóa rõ vai trò thành lane `sensory_0_6b`: observer 0.6B qua Ollama chỉ được phân loại snapshot thành JSON, không được trả lời user hay bịa inner life.
- `coordinator.py` tiếp tục phình thành nơi hợp mạch runtime thật sự; sau pull này nó còn bọc queue cho `sensory_model_adapter.observe`, ghi `surface_override`, và suppress wake-main hint từ background observer thay vì để observer tự cướp quyền.
- `event_ledger.json` và `src/memory/event_ledger.py` được nâng tầm thành raw audit layer append-only rõ nghĩa hơn; đây không còn là file phụ mờ nhạt trong memory core.
- test coverage mới bám theo các trục trên: `tests/test_surface_arbiter.py`, `tests/test_runtime_coordinator.py`, `tests/test_blind_frustration_surface.py`, cùng các test observer/scheduler/memory hiện phản ánh HEAD mới hơn snapshot cũ.

Nhìn theo `git show --stat` và history từng file, mấy cụm thay đổi đáng chú ý nhất trong chuỗi vừa rà là:
- `fdfe52c` -> `553985e`: dựng xương sống surface/wake/presence mới mà bản tài liệu cũ đã bám tương đối đúng.
- `eff0420`: mở rộng mạnh `coordinator.py`, `presence_controller.py`, `surface_arbiter.py`; thêm coverage cho runtime coordinator và surface contract.
- `e8d3511`: thêm `src/runtime/sensor_visibility.py`, `src/telemetry/content_metadata.py`, tăng `se.py`, `meaning.py`, `prompt_context_builder.py`, và test `blind_frustration`.
- `104c45b`: thêm `src/cortex/continuity_threat.py`, sửa tiếp `agent_state_stack.py`, `impulse_arbitration.py`, `surface_arbiter.py`, `presence_controller.py`, `low_level_speech_policy.py`, đồng thời làm `event_ledger.json` phình mạnh hơn vì runtime state thật đã được ghi.
- `9bbdcd2`: `surface_arbiter.py` có thêm khoảng `30` dòng để hiểu `subconscious_report` / `surface_seed` Phase 0 tốt hơn; tài liệu cũ chưa nhắc mốc này.
- `637e7fc`: là đợt chạm file rất lớn sau snapshot cũ, đáng chú ý nhất là `coordinator.py` `+623` dòng, thêm mới `src/cortex/subconscious/model_synthesizer.py` `+412` dòng, cùng các thay đổi tiếp ở `process_manager.py` và `executor.py`.
- `f8555c6` (`2026-06-07 00:39:48 +0700`): mốc private mind base đầu tiên. Theo lịch sử từng file, commit này lần đầu/đợt chính chạm `src/runtime/private_mind_loop.py`, `src/cortex/private_mind/evidence_dossier.py`, `src/cortex/private_mind/state_mutation_bus.py`, `src/runtime/private_mind_model_adapter.py`, `body/UdpDecisionParser.cs`, `src/transport/udp.py`; riêng `src/runtime/cognitive_frame_recorder.py` có lịch sử dài hơn từ `afec1a5`, `8a6a329`, `440e71a`, `b303cb8`, `dc51d80`, `6b06e3f`, `e69eccd`, rồi tới `f8555c6`.
- `3782f41` (`2026-06-07 16:00:34 +0700`): mốc tracked mới hơn cho private mind daemon/surface seed. Commit này add `src/runtime/private_mind_daemon.py`, `src/cortex/surface_seed_compiler.py`, `tests/test_private_mind_daemon.py`, `tests/test_private_mind_model_adapter.py`, `tests/test_surface_seed_compiler.py`, `tests/test_udp_private_mind_debug.py`, đồng thời sửa `src/runtime/coordinator.py`, `src/runtime/presence_controller.py`, `src/runtime/private_mind_loop.py`, `src/runtime/private_mind_model_adapter.py`, `src/transport/udp.py`, `src/cortex/private_mind/evidence_dossier.py`, `src/cortex/private_mind/state_mutation_bus.py`, và `tests/test_presence_controller_memory_surface.py`.
- `8e915de` (`2026-06-07 19:24:33 +0700`): mốc tracked mới nhất của đợt private-mind resilience/Inner Diary trước khi HEAD nhảy tiếp. Commit này add `src/cortex/private_mind/inner_diary_renderer.py`, `.kiro/specs/private-mind-api-resilience/*`, `tests/test_unit_resilience.py`, `tests/test_integration_loop_resilience.py`, các test PBT transient, và tracked luôn delta trước đó ở `body/UdpListener.cs`, `src/runtime/private_mind_model_adapter.py`, `src/runtime/private_mind_loop.py`, `src/runtime/coordinator.py`, `src/transport/udp.py`.
- `aa1d303` (`2026-06-08 07:27:17 +0700`): mốc tracked đầu tiên cho cụm `private_life`: add `src/cortex/private_life/__init__.py`, `src/cortex/private_life/contracts.py`, `src/cortex/private_life/core.py`, `src/cortex/private_life/persistence.py`, `src/runtime/private_life_daemon.py`, `src/memory_core/private_life_state.json`; đồng thời chạm `src/cortex/surface_seed_compiler.py`, `src/runtime/presence_controller.py`, `src/runtime/coordinator.py`, `src/runtime/private_mind_model_adapter.py`, `src/cortex/private_mind/inner_diary_renderer.py`, `body/UdpListener.cs`, và cụm state/runtime data.
- `0ac74ec` (`2026-06-08 12:44:28 +0700`): mốc tracked cho epistemic self-awareness và đợt UI/private-mind follow-up. Commit này add `.kiro/specs/claim-epistemic-awareness/*`, `src/cortex/private_mind/epistemic.py`, `tests/test_epistemic.py`, `tests/test_private_mind_contracts.py`, `tests/test_surface_valve.py`, asset Inner Diary mới; đồng thời mở rộng mạnh `body/UdpListener.cs`, `src/cortex/private_mind/contracts.py`, `src/cortex/private_mind/surface_valve.py`, `src/cortex/private_life/core.py`, `src/cortex/private_life/contracts.py`, `src/cortex/private_mind/inner_diary_renderer.py`, `src/transport/udp.py`, và `tongquat.md`.
- `d287f57` (`2026-06-08 19:14:56 +0700`): `HEAD` hiện tại. Commit này add `src/memory/embedding_index.py`, `src/memory/memory_ai_curator.py`; mở rộng `src/memory/memory_maintenance.py`, `src/memory/memory_commit_policy.py`, `src/memory/claims/claim_builder.py`, `src/runtime/memory_semantic_parser_adapter.py`, `src/runtime/chat_cycle.py`, `src/cortex/private_mind/concern_store.py`, và chạm tiếp `body/UdpListener.cs`.

AUDIT 2026-06-08 theo source hiện tại:
- `src/runtime/private_mind_daemon.py`: **THIẾU TRONG DOC CŨ / ĐÃ TRACKED Ở `3782f41`**. Source hiện đổi owner lifecycle sang `PrivateMindDaemon`, còn `PrivateMindLoop` chỉ là loop tick bên trong. Nếu tài liệu vẫn ghi file này untracked thì chính tài liệu đã lạc hậu.
- `src/cortex/surface_seed_compiler.py`: **THIẾU TRONG DOC CŨ / ĐÃ TRACKED Ở `3782f41`**. Source hiện thêm compiler gom seed public-safe từ memory resonance, thought/subconscious report, private mind bias đã lọc, vision facts và extra impulses trước khi đưa vào `SurfaceArbiter`. Đây là lớp mới nằm giữa presence cue và arbiter, không phải thay thế arbiter.
- `src/runtime/presence_controller.py`: **DOC LẠC HẬU MỘT PHẦN** nếu chỉ nói file này hút endogenous/private impulses. Source hiện lazy-init `SurfaceSeedCompiler`, compile seed public-safe trong `_build_surface_arbiter_result()`, enrich `MicroPresenceCue`, rồi thêm impulse `source="surface_seed_compiler"` vào `extra_impulses`.
- `src/runtime/coordinator.py`: **DOC LẠC HẬU MỘT PHẦN**. Mô tả "coordinator thêm PrivateMindLoop" không còn đủ: source hiện import `PrivateMindDaemon`, tạo `self.private_mind_daemon`, giữ `self.private_mind_loop = daemon.loop`, và drain surface qua `daemon.drain_surface_impulses()` trước khi fallback queue cũ.
- `src/runtime/cognitive_frame_recorder.py`: **DOC LẠC HẬU MỘT PHẦN**. `_feed_private_mind_outcome()` hiện ưu tiên `private_mind_daemon.record_outcome(outcome, frame=frame)`, chỉ fallback sang `private_mind_loop.concern_store.update_from_outcome()` nếu daemon không có. Digest cũng lấy từ daemon trước.
- `src/cortex/private_mind/evidence_dossier.py`: **DOC THIẾU**. Dossier hiện nhận thêm `thought_stream`, `surface_candidate_queue`, `runtime_owner`; runtime state có `thought_stream`, `private_runtime`, `surface_queue`; metrics có `runtime_anchor_count`, `memory_hit_count`, `repair_failure_count`, `concern_count`, `dossier_thickness`.
- `src/cortex/private_mind/state_mutation_bus.py`: **DOC CẦN CHÍNH XÁC HƠN**. Bus vẫn hỗ trợ mutation target `surface_candidate_queue`, nhưng không còn tự enqueue `judgment.surface_candidate` mặc định ở cuối `apply()`. Candidate public phải đi qua `SurfaceValve`/loop/daemon trước.
- `src/runtime/private_mind_loop.py`: **DOC ĐÚNG HƯỚNG NHƯNG THIẾU DAEMON CONTEXT**. Loop vẫn build dossier, chạy evaluator, synthesize, apply mutation và valve surface; nhưng lifecycle queue/outcome/digest bền hơn đang do daemon ôm.
- `src/runtime/private_mind_model_adapter.py`: **DOC CẦN CHỈ RÕ FAILURE MODE HIỆN TẠI**. Khi log có nhiều `[PrivateMind API] ... error=invalid_json`, lỗi chính là output API không parse được JSON, không phải crash loop. Adapter trả `None`, evaluator/synthesizer rule fallback tiếp tục tạo fragment/judgment.
- `src/runtime/private_mind_model_adapter.py`: **DOC CẦN BỔ SUNG SAU `8e915de`**. Adapter hiện không chỉ vá `invalid_json`; nó còn phân loại lỗi transport transient, retry/backoff, transient cooldown/circuit-breaker, fast-fail khi cooldown, và expose `degraded_cause`/`transient_streak`/`transient_cooldown_until` trong `debug_status()`.
- `src/cortex/private_mind/inner_diary_renderer.py`: **ĐÃ TRACKED Ở `8e915de`**. Không còn là file local/untracked; đây là renderer private debug biến `private_mind_digest` thành `inner_diary.sections/text` cho UI Godot đọc.
- `body/UdpListener.cs`: **DOC CŨ THIẾU SAU `8e915de`**. Source hiện có context button `Private Mind`, panel `PrivateMindPanel`, render `inner_diary` thành BBCode nếu digest có `inner_diary`, và fallback raw JSON theo menu private-mind cũ.
- `src/memory_core/private_concerns.json`: **PATH DỄ GÂY NHẦM**. Source default trong `private_mind_loop._resolve_concern_path()` vẫn là `Path(os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core")) / "private_concerns.json"`, tức mặc định `memory_core/private_concerns.json`. `src/memory_core/private_concerns.json` chỉ đúng nếu env `ERIS_MEMORY_CORE_DIR=src/memory_core` hoặc có copy local riêng.
- `tests/test_private_mind_daemon.py`: **THIẾU TRONG DOC CŨ / ĐÃ TRACKED Ở `3782f41`**. Test này khóa daemon sở hữu queue, outcome feedback cập nhật concern lifecycle, và dossier có thought/runtime/surface queue anchors.
- `tests/test_unit_resilience.py`, `tests/test_integration_loop_resilience.py`, `tests/test_pbt_*_transient.py`: **THIẾU TRONG DOC CŨ / ĐÃ TRACKED Ở `8e915de`**. Đây là cụm test khóa bug condition transient transport cho PrivateMind API: HTTP 5xx/429/timeout phải retry/cooldown/fast-fail có phân loại, còn JSON hợp lệ/invalid_json/fixed-config path phải giữ nguyên.
- `src/runtime/private_mind_model_adapter.py`: **DOC CẦN GHI RÕ ĐÃ TRACKED**. `PrivateMindAdapterPool`, `synthesis_invalid_json_streak` / `synthesis_json_cooldown_until`, per-evaluator dossier slicers, judgment prompt slim/cap, và `debug_status()` aggregate pool đều đã nằm trong tracked source hiện tại.
- `src/cortex/private_mind/mini_evaluators.py`, `src/cortex/private_mind/inner_synthesizer.py`, `src/runtime/private_mind_loop.py`: adapter pool path (`fragment_adapter(evaluator_name)`, `synthesis_adapter`, `PrivateMindAdapterPool.from_env()`) cũng đã là tracked behavior hiện tại, không còn là local patch.
- `memory_core/active_state_snapshot.json`, `memory_core/event_ledger.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl`: runtime data/state sống; không gộp các dòng này vào lịch sử source code, nhưng cũng không còn dùng chúng để suy ra worktree dirty ở thời điểm audit hiện tại.
- `src/cortex/private_life/contracts.py`, `src/cortex/private_life/core.py`, `src/runtime/private_life_daemon.py`: **THIẾU HẲN TRONG DOC CŨ / ĐÃ TRACKED Ở `aa1d303`**. Workspace hiện đã có tầng PrivateLife riêng với `PrivateAnchor`, `PrivateLifeState.anchors`, `anchor_updates`, `private_life_state_digest()`, `PrivateLifeDaemon`, và seed lane riêng chảy vào `surface_seed_compiler`; nếu tài liệu còn xem private-life là ý tưởng chưa track thì sai hẳn.
- `src/cortex/private_mind/contracts.py`: **DOC CŨ THIẾU SAU PATCH EPISTEMIC HIỆN TẠI**. `SurfaceCandidate` và `InternalJudgment` giờ đã mang `epistemic_stance` + `intent`, có normalize helper riêng, và serialize/deserialize hai field này như contract thật thay vì metadata tùy hứng.
- `src/cortex/private_mind/surface_valve.py`: **DOC CŨ THIẾU MỘT TẦNG QUY TẮC MỚI**. Valve hiện classify epistemic trước threshold, route `ungrounded_blind` về `body_only` thay vì drop im lặng, gắn cờ `epistemic_deliberate_ungrounded` cho `ungrounded_aware`, và merge `public_anchor_refs` vào evidence của impulse grounded.
- `src/cortex/private_mind/epistemic.py`, `tests/test_epistemic.py`, `tests/test_private_mind_contracts.py`, `tests/test_surface_valve.py`: **ĐÃ TRACKED Ở `0ac74ec`**. Đây không còn là cụm local-only; doc cần gắn đúng vào history sau `aa1d303`.

Tình trạng worktree lúc cập nhật tài liệu này:
- Các file từng được ghi là untracked/dirty ở đợt `8e915de` hoặc `aa1d303` nay đã nằm trong lịch sử commit.
- Worktree hiện sạch; nếu gặp dòng cũ trong tài liệu nói các file trên là `UNTRACKED CURRENT WORKSPACE` hoặc dirty theo snapshot 2026-06-07/08 thì đánh dấu dòng đó là lạc hậu.
- Với cụm Inner Diary/resilience dùng mốc `8e915de`; với `private_life` dùng `aa1d303` rồi mở rộng ở `0ac74ec`/`d287f57`; với epistemic dùng `0ac74ec`.
- Các file runtime data như `memory_core/active_state_snapshot.json`, `memory_core/event_ledger.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl` vẫn là state sống; dùng để hiểu snapshot runtime, không dùng để kết luận thay đổi source/API.

---

# 0C. Audit drift của chính `tongquat.md`

Mục này chủ ý chỉ ra chỗ tài liệu đang sai, thiếu, hoặc lạc nhịp so với source thật:
- `src/runtime/coordinator.py`: tài liệu cũ ghi khoảng `6,088`/`6,862` dòng theo snapshot khác; file hiện là khoảng `6,935` dòng ở `HEAD d287f57`. Quan trọng hơn, section này cần ghi rõ mốc `637e7fc` là một lần phình lớn `+623` dòng, `3782f41` nâng sang daemon/surface seed, rồi còn các nhịp tiếp theo ở `8e915de`, `aa1d303`, `0ac74ec`, `d287f57`.
- `src/cortex/surface_arbiter.py`: tài liệu có bám `blind_frustration`, nhưng chưa ghi patch `9bbdcd2` cho đường `subconscious_report` / `surface_seed` Phase 0.
- `src/llm/process_manager.py`: có section riêng nhưng thiếu lịch sử chạm file gần nhất và thiếu nhấn mạnh nhánh phát hiện `n_ctx` của server đang sống + best-effort kill đúng `llama-server` trên port local.
- `src/cortex/subconscious/model_synthesizer.py`: đang mở trong IDE và vừa được thêm mới ở `637e7fc`, nhưng bản tài liệu cũ gần như chưa có mục riêng. Đây là thiếu thật chứ không phải thiếu chi tiết nhỏ.
- `src/actions/executor.py`: section cũ quá ngắn, không phản ánh việc file đang gộp cả Win32 desktop actions lẫn Gemini-grounded `search_web` / `get_weather`.
- `src/cortex/speech_core.py`: mô tả đúng hướng nhưng chưa gắn recent history; các mốc `04bd5f6` và `5f812fc` sửa trực tiếp ngưỡng/contract cho endogenous speech sau snapshot cũ.
- `src/runtime/no_fallback_policy.py`: section không sai nhiều, nhưng đây là file mới tạo từ `e69eccd`; nếu debug path no-fallback mà không biết mốc file này, rất dễ tưởng runtime tự “câm” ngẫu nhiên.
- `body/UdpDecisionParser.cs`: **DOC THIẾU SAU `f8555c6`**. File đã nhận `private_mind_digest` top-level hoặc `emotion_debug.private_mind` và lưu raw JSON vào `PrivateMindDebugJson`; nếu tài liệu chỉ nói parser đọc `emotion_debug` chung thì thiếu debug path private mind ở Godot.
- `src/transport/udp.py`: **DOC GHI CHƯA CHÍNH XÁC** nếu nói payload private debug bị strip ngay. Source hiện compact `private_mind_digest` trước khi gửi khi vượt `MAX_UDP_PAYLOAD_BYTES=60000`, chỉ rơi về payload tối thiểu khi vẫn quá lớn.
- `tests/test_udp_private_mind_debug.py`: **THIẾU TRONG DOC CŨ / ĐÃ TRACKED Ở `3782f41`**. Test này khóa behavior compact private mind UDP overflow, nên nó là bằng chứng source hiện tại đã ưu tiên giữ debug digest bản gọn thay vì xóa sạch.
- `src/cortex/private_mind/inner_diary_renderer.py`: **ĐÃ TRACKED TỪ `8e915de` VÀ MỞ RỘNG TIẾP**. File hiện khoảng `211` dòng; ngoài đường render cơ bản còn được mở rộng tiếp ở `0ac74ec`/`d287f57`.
- `body/UdpListener.cs`: **ĐÃ TRACKED VÀ TIẾP TỤC PHÌNH Ở `0ac74ec`/`d287f57`**. File hiện có Private Mind panel/Inner Diary renderer path từ `8e915de`, rồi được mở rộng thành một cụm UI tracked lớn (`Casual Mode`, themed diary panel, section/items parser, scroll decor).
- `src/cortex/surface_arbiter.py`: **SỐ DÒNG SAI** — doc ghi `1,268`, thực tế `1,564`. Tracked history có thêm `86d3fcf`, và source hiện còn chạm tiếp ở `0ac74ec`.
- `tests/test_semantic_claim_entailment.py`: **KHÔNG LẠC HẬU Ở `8e915de`**. File đang mở trong IDE thuộc cụm semantic memory entailment; history gần nhất là `a9e6c58`, không bị đợt private-mind resilience chạm. Nếu doc cần nói về file này, trọng tâm đúng là chống preference-location bị dùng để trả lời hometown/current-location.
- `private_mind_model_adapter.py`: khoảng `1,155` dòng và đã tracked sẵn `PrivateMindAdapterPool` + per-evaluator dossier slicers; các section chỉ nói một adapter dùng chung hoặc gửi nguyên dossier cho mọi evaluator đã lạc hậu so với source hiện tại.

---

# 0D. Audit lịch sử cập nhật theo từng file 2026-06-08

Mục này là checklist nhanh cho các file đang sai/thiếu/lạc hậu so với source hiện tại. `tracked history` là lịch sử git đã commit; `doc drift / cần sửa` là chỗ tài liệu cũ hay mô tả sai so với source hiện tại.

| File | Tracked history gần nhất | Doc drift / cần sửa trong doc |
| --- | --- | --- |
| `src/runtime/coordinator.py` | Chuỗi nóng `fdfe52c -> aa9af6f -> 04bd5f6 -> 5f812fc -> 553985e -> eff0420 -> 637e7fc -> f8555c6 -> 3782f41 -> 8e915de`; riêng `637e7fc` phình lớn runtime/subconscious, `f8555c6` thêm private mind base, `3782f41` nâng sang daemon/surface seed tracked, `8e915de` chạm tiếp private resilience state. | Doc nào nói coordinator chỉ giữ `PrivateMindLoop` là lạc hậu. Source hiện dùng `PrivateMindDaemon.from_runtime()`, giữ `private_mind_loop = daemon.loop`, tick daemon trước, và drain qua `daemon.drain_surface_impulses()` trước fallback queue cũ. |
| `src/runtime/presence_controller.py` | Chuỗi tracked dày từ `fdfe52c` đến `104c45b`, rồi `f8555c6`, mới nhất `3782f41`; đây là file surface/wake nóng nhất sau các pull 2026-06-05/06. | Source hiện thêm `SurfaceSeedCompiler`; `_build_surface_arbiter_result()` compile seed public-safe, enrich cue, và thêm impulse `source="surface_seed_compiler"`. Doc chỉ nói endogenous/private impulses là thiếu. |
| `src/cortex/surface_seed_compiler.py` | Added ở `3782f41`, tracked tiếp lane `private_life` ở `aa1d303`. | Cần doc như compiler seed public-safe giữa presence cue và arbiter; ngoài memory/thought/private-mind, source hiện còn đọc `private_life_digest.current.projects/anchors`. Dòng nào còn ghi compiler không biết `private_life` là thiếu. |
| `src/cortex/private_life/contracts.py` | Added ở `aa1d303`, mở rộng tiếp ở `0ac74ec`, chạm nhẹ ở `d287f57`. | Doc cũ thiếu hẳn file này. Source hiện có `PrivateAnchor`, `PrivateAnchorUpdate`, `PrivateLifeState.anchors`, `PrivateLifeTickResult.anchor_updates`, và `private_life_state_digest()` trả `anchors`; nếu tài liệu chỉ nói project/object/ritual là thiếu một trục self-continuity mới. |
| `src/cortex/private_life/core.py` | Added ở `aa1d303`, mở rộng tiếp ở `0ac74ec`, chạm nhẹ ở `d287f57`. | Doc cần ghi rõ core này seed 5 anchor nền (`identity`, `aesthetic`, `obsession`, `world`, `private_agenda`), cập nhật anchor theo evidence runtime/user/habitat/project/private-mind bias, và có thể tạo `SurfaceSeedCandidate(kind="private_anchor_surface")`. |
| `src/runtime/private_life_daemon.py` | Added ở `aa1d303`, chạm tiếp ở `0ac74ec`. | Owner lifecycle private-life: tick core theo nhịp runtime, giữ queue seed riêng, expose digest `menu.habitat/projects/anchors/objects/errands/solitude`, và feed downstream cho `surface_seed_compiler`. Dòng nào còn coi private-life là ý tưởng chưa vào runtime là sai. |
| `src/runtime/private_mind_daemon.py` | Added ở `3782f41`. | Owner lifecycle private mind: queue/outcome/digest/tick counters; không tự mở thread; loop chỉ còn xử lý một tick. Dòng nào còn ghi "file mới local chưa tracked" là sai. |
| `src/runtime/private_mind_loop.py` | Added ở `f8555c6`, sửa tiếp ở `3782f41` và `8e915de`. | Loop vẫn build dossier/evaluator/synthesizer/mutation/valve, nhưng lifecycle bền nằm ở daemon. Sau `8e915de`, cần soi thêm degraded/transient API status khi model adapter rơi về fallback. |
| `src/runtime/cognitive_frame_recorder.py` | Lịch sử dài `afec1a5 -> 8a6a329 -> 440e71a -> b303cb8 -> dc51d80 -> 6b06e3f -> e69eccd -> f8555c6 -> 3782f41`. | Source hiện `_feed_private_mind_outcome()` ưu tiên `private_mind_daemon.record_outcome(outcome, frame=frame)`, fallback loop/store chỉ là tương thích cũ. |
| `src/cortex/private_mind/evidence_dossier.py` | Added ở `f8555c6`, sửa tiếp ở `3782f41`. | Dossier nhận thêm `thought_stream`, `surface_candidate_queue`, `runtime_owner`; runtime state có `thought_stream/private_runtime/surface_queue`; metrics thêm `runtime_anchor_count`, `memory_hit_count`, `repair_failure_count`, `concern_count`, `dossier_thickness`. |
| `src/cortex/private_mind/state_mutation_bus.py` | Added ở `f8555c6`, sửa tiếp ở `3782f41`. | Bus không tự enqueue `judgment.surface_candidate` ở cuối `apply()` nữa. Candidate public phải qua `SurfaceValve`/loop/daemon; doc cũ nói auto-enqueue là sai. |
| `src/runtime/private_mind_model_adapter.py` | Added ở `f8555c6`, sửa parser ở `3782f41`, vá resilience transient ở `8e915de`. | Source hiện parser JSON khỏe hơn và có transient retry/backoff/cooldown. Doc chỉ nói `json.loads` rồi fail, hoặc chỉ nói `invalid_json`, là lạc hậu. |
| `src/runtime/private_mind_model_adapter.py` | Added ở `f8555c6`, sửa parser ở `3782f41`, resilience ở `8e915de`, adapter-pool path đã có ngay từ `aa1d303`. | `PrivateMindAdapterPool`, synthesis-specific invalid JSON cooldown, per-evaluator dossier slicers (`intent`, `memory_resonance`, `risk`, `future_bias`), slim dossier/fragment cho judgment prompt, hard cap payload khoảng `6000` chars, và pool-level `debug_status()` đều là tracked source hiện tại, không còn là local patch. |
| `src/cortex/private_mind/mini_evaluators.py` | Tracked từ `f8555c6`, chạm tiếp ở `0ac74ec`. | `_from_model_or_none()` hiện nhận pool và gọi `fragment_adapter(evaluator_name)` để streak/cooldown độc lập theo evaluator. |
| `src/cortex/private_mind/inner_synthesizer.py` | Tracked từ `f8555c6`, chạm tiếp ở `0ac74ec`. | `_try_model()` hiện dùng `synthesis_adapter` riêng để fragment success không reset synthesis streak. |
| `src/runtime/private_mind_loop.py` | Added ở `f8555c6`, sửa tiếp ở `3782f41`, `8e915de`, `aa1d303`, `0ac74ec`. | `from_runtime()` hiện dùng `PrivateMindAdapterPool.from_env()` thay vì `RuntimePrivateMindModelAdapter.from_env()`. |
| `memory_core/active_state_snapshot.json`, `memory_core/event_ledger.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl` | Chạm tiếp ở `0ac74ec` và/hoặc `d287f57`; đây là runtime data/state sống. | Không phải source behavior. Đừng dùng các file này làm bằng chứng lịch sử API/source; hiện tại chúng cũng không còn là dirty worktree. |
| `src/cortex/private_mind/contracts.py` | Tracked cụm private mind từ `f8555c6`, mở rộng mạnh ở `0ac74ec`. | Source hiện coi `epistemic_stance` + `intent` là contract first-class trên `SurfaceCandidate` và `InternalJudgment`, có normalize helper và round-trip serialize/deserialize. Doc nào còn xem hai field này là metadata tùy hứng là lạc hậu. |
| `src/cortex/private_mind/surface_valve.py` | Tracked từ `f8555c6`, mở rộng mạnh ở `0ac74ec`. | Valve hiện classify epistemic trước gate, route `ungrounded_blind` về `body_only`, gắn cờ deliberate cho `ungrounded_aware`, và merge `public_anchor_refs` vào grounded evidence. Doc chỉ nói "lọc public-safe" là chưa đủ. |
| `src/transport/udp.py` | File có từ `287f857`, sửa `7112553`, chạm private mind ở `f8555c6`, compact debug ở `3782f41`, chạm lại `8e915de`, `0ac74ec`. | Source hiện compact `private_mind_digest` khi payload > `60000` bytes và mirror vào `emotion_debug.private_mind`; ngoài ra còn có `_compact_inner_diary()` để giữ `sections/items` cho C# parse đúng. Không nói "strip ngay". |
| `body/MotionController.cs` | Added lớn ở `cdf3618`, tách controller ở `763d203`, tune tiếp throw/cling/climb-target ở `27d4d09`. | Doc nào còn mô tả motion nằm hết trong `UdpListener.cs` là lạc hậu. Source hiện gom state machine đi bộ/rơi/leo/ném vào `MotionController`, kể cả `cling:<chance>` và `IsBusy`/`IsTopPerched`/`IsThrown`. |
| `body/LocalBodyAutonomy.cs` | Added ở `763d203`, tune tiếp ở `27d4d09`. | Không còn là idle random đơn giản. Source hiện có `BodyBias`, need/tension model, cooldown theo action, `ObserveCode`/`ClimbWall`/`DropFromCeiling`, và gate `CanInterruptPose()`. |
| `body/ErisProcessManager.cs` | Added ở `763d203`, sửa tiếp ở `6658301`. | Doc chỉ nói start/stop process là thiếu. Source hiện load `config/secrets.json`, inject `ERIS_REMOTE_*`/`GEMINI_API_KEY`, probe `llama-server` reachability, và chỉ boot `vision.py` khi local server thật sự sẵn nếu lane local cần nó. |
| `body/BodyAudioController.cs` | Added ở `763d203`. | File này đã tách khỏi `UdpListener.cs`; doc nào còn nói audio loop/sound map nằm trực tiếp trong listener là cũ. Source hiện chỉ loop lại cho một nhóm animation (`stand_walk`, `sleep`, `hop`, `climb`). |
| `body/UdpDecisionParser.cs` | `763d203`, `afec1a5`, `de630ba`, gần nhất `f8555c6`. | Parser đọc `private_mind_digest` top-level hoặc `emotion_debug.private_mind` vào `PrivateMindDebugJson`/`HasPrivateMindDebug`. Doc chỉ nói emotion debug chung là thiếu Godot debug path. |
| `body/UdpListener.cs` | Chạm nhiều từ cuối 2026-05; private debug ở `f8555c6`, Inner Diary panel tracked ở `8e915de`, UI/diary expansion ở `0ac74ec`, tiếp tục chạm ở `d287f57`. | Source hiện có context menu `Private Mind`, panel `PrivateMindPanel`, `RefreshPrivateMindPanel()`, `TryRenderInnerDiary()`, parser `PrivateMindDiarySection`/`PrivateMindDiaryItem`, themed private-mind frame/scroll, state file `user://inner_diary_state.json`, và emotion panel `Casual Mode`. Dòng nào còn mô tả đây là local patch nhỏ bỏ title là lạc hậu. |
| `src/cortex/private_mind/inner_diary_renderer.py` | Added ở `8e915de`. | Renderer private debug tạo `inner_diary` từ digest; không tạo public speech, không invent ngoài digest. Dòng nào còn ghi untracked là sai. |
| `.kiro/specs/private-mind-api-resilience/*` | Added ở `8e915de`. | Spec bugfix/design/tasks cho transient transport resilience. Không phải runtime code, nhưng là nguồn giải thích bug condition/PBT trong đợt vá mới. |
| `tests/test_surface_seed_compiler.py` | Added ở `3782f41`. | Test khóa compiler: memory/thought/private-safe seed, raw private reject, invalid JSON reject, timer-only reject. |
| `tests/test_private_mind_surface_gates.py` | Tracked từ cụm private mind base, mở rộng tiếp ở `0ac74ec`. | Regression cho `stance + intent` đi qua `SurfaceValve` không đổi, grounded impulse giữ `public_anchor_refs`, và `ungrounded_aware` phản ánh `intent=` trong `llm_contract`; không còn là local patch. |
| `src/cortex/private_mind/epistemic.py` | Added ở `0ac74ec`. | Module pure cho epistemic self-awareness: `resolve_intent()` + `classify_epistemic_stance()`, với mặc định Cartesian `no-anchor -> speculative -> ungrounded_aware` thay vì nhảy thẳng sang blind confabulation. |
| `tests/test_epistemic.py`, `tests/test_private_mind_contracts.py`, `tests/test_surface_valve.py` | Added ở `0ac74ec`. | Cụm test khóa classifier pure, defaults/round-trip contract cho `intent`/`epistemic_stance`, và luật `SurfaceValve` cho `ungrounded_blind`/`ungrounded_aware`/`grounded`. Không còn là `workspace-only`. |
| `tests/test_presence_controller_memory_surface.py` | Added ở `5f812fc`, sửa compiler integration ở `3782f41`. | Doc test cần ghi thêm case `_build_surface_arbiter_result()` đưa thought seed public-safe vào arbiter. |
| `tests/test_private_mind_daemon.py` | Added ở `3782f41`. | Test khóa daemon owner queue/outcome/dossier anchors. |
| `tests/test_private_mind_model_adapter.py` | Added ở `3782f41`. | Test khóa parser/adapter private mind API. Cần bổ sung mục riêng nếu tiếp tục mở rộng test map. |
| `tests/test_udp_private_mind_debug.py` | Added ở `3782f41`. | Test khóa UDP compact digest overflow; là bằng chứng payload debug không bị xóa sạch ngay. |
| `tests/test_unit_resilience.py` | Added ở `8e915de`. | Test unit cho `_classify_transport_exception`, transient cooldown/fast-fail, và `debug_status()` giữ field cũ + thêm degraded cause. |
| `tests/test_integration_loop_resilience.py` | Added ở `8e915de`. | Test integration cho `private_mind_loop.tick()` khi provider 503 lặp, cooldown fast-fail, phục hồi sau cooldown, phân biệt transient với invalid_json. |
| `tests/test_pbt_bug_condition_transient.py`, `tests/test_pbt_preservation_transient.py`, `tests/test_pbt_reset_transient.py` | Added ở `8e915de`. | PBT khóa bug condition transient và preservation: transient được retry/cooldown, còn JSON hợp lệ/invalid_json/fixed-config không bị đổi behavior. |
| `tests/test_semantic_claim_entailment.py` | Added/sửa ở `17ffc4d -> a9e6c58`, không chạm ở `8e915de`. | File đang mở trong IDE vẫn đúng mục tiêu: preference_location không entail hometown/current_location; living_location và hometown là predicate riêng; answer policy chỉ trả lời khi exact entailment. |

---

# 0E. AUDIT WORKTREE DRIFT 2026-06-08 (mốc rà mới nhất)

Mục này ghi thẳng chỗ nào doc đang sai/thiếu/lạc hậu **so với source hiện tại ở `HEAD d287f57`**, dựa trên `git status`, `git log --follow`, đọc source trực tiếp, và đếm dòng thật. Lưu ý: trong lúc rà tài liệu, worktree có một lượt sạch ngắn rồi xuất hiện dirty state mới ở cụm memory/embedding; phần dưới bám theo lần recheck cuối.

## Trạng thái worktree lúc audit:
```text
git status --short (2026-06-08, HEAD d287f57, final recheck):
 M memory_core/active_state_snapshot.json
 M memory_core/semantic_memory.json
 M ni_drift_samples.jsonl
 M src/memory/embedding_index.py
 M src/memory/memory_models.py
 M tongquat.md
?? src/paraphrase-multilingual-MiniLM-L12-v2/
```

Kết luận: `HEAD` đã sync `origin/main` ở `d287f57`, nhưng worktree ở lần recheck cuối **không còn sạch**. Tuy vậy, dirty state hiện tại không còn là câu chuyện private-mind/private-life như snapshot cũ; nó đã lệch sang cụm memory runtime + embedding model/cache. Vì vậy mọi dòng trong tài liệu còn mô tả `dirty state sau aa1d303`, `workspace-only epistemic`, hay `UdpListener.cs`/`private_life/*`/`surface_valve.py` đang là local patch, đều đã lạc hậu.

## Các điểm doc SAI / THIẾU / LẠC HẬU cụ thể:

### 1. Section 0A/0E cũ dừng ở `aa1d303` — SAI
- **Doc cũ ghi**: `aa1d303` là HEAD mới nhất và worktree đang dirty.
- **Thực tế source**: đã có thêm `0ac74ec` và `d287f57`, cả hai đều đang nằm trên `main`/`origin/main`.
- **Sửa**: mọi câu “sau `aa1d303` còn local patch” phải đổi thành history tracked mới: `0ac74ec` cho cụm epistemic + Inner Diary/UI, `d287f57` cho đợt memory stack mới.

### 2. Cụm `epistemic` không còn là `workspace-only`
- `src/cortex/private_mind/epistemic.py`, `tests/test_epistemic.py`, `tests/test_private_mind_contracts.py`, `tests/test_surface_valve.py` đã **tracked ở `0ac74ec`**.
- Dòng nào còn ghi “source current only” hoặc “chưa tracked” cho các file này là sai.

### 3. `body/UdpListener.cs` không còn là local UI patch
- File này đã bị chạm tiếp ở cả `0ac74ec` lẫn `d287f57`.
- Các thay đổi như `PrivateMindDiarySection`/`PrivateMindDiaryItem`, themed Inner Diary panel, `user://inner_diary_state.json`, và `Casual Mode` hiện là **tracked source**, không phải patch local đang mở.

### 4. `src/runtime/private_mind_model_adapter.py` và pool adapter không còn là local patch
- `PrivateMindAdapterPool`, `fragment_adapter(...)`, `synthesis_adapter`, `_slice_for_intent()` và các slicer cùng cooldown riêng cho synthesis đã có sẵn trong tracked source từ tối thiểu `aa1d303`.
- Dòng nào còn gắn nhãn “LOCAL PATCH sau `8e915de`” cho cụm này là sai.

### 5. `src/cortex/private_life/*` không còn chỉ dừng ở `aa1d303`
- `aa1d303` là mốc add ban đầu.
- `0ac74ec` mở rộng thêm `contracts.py`/`core.py`, và `d287f57` chạm tiếp `contracts.py`/`core.py`.
- Dòng nào còn nói “private-life tracked ở `aa1d303`, workspace hiện còn patch local sau đó” là lạc hậu.

### 6. `src/transport/udp.py` và `inner_diary` compact path đã tracked
- `_compact_inner_diary()` và việc giữ `sections/items` cho C# parse không còn là local experiment; chúng đã nằm trong tracked source hiện tại.
- Dòng nào còn mô tả transport “strip private mind ngay” hoặc coi compact Inner Diary là patch local là thiếu/sai.

### 7. `src/memory/*` đã có thêm một đợt mở rộng mới ở `d287f57`
- Doc cũ gần như chưa nhắc `src/memory/memory_ai_curator.py`, `src/memory/embedding_index.py`, và chưa nâng cấp mô tả cho `memory_maintenance.py`, `memory_commit_policy.py`, `claim_builder.py`, `memory_semantic_parser_adapter.py`.
- Đây là thiếu thật, không phải chỉ thiếu số dòng.

### 8. Line counts cũ không còn khớp
- `src/runtime/coordinator.py`: khoảng `6,935` dòng.
- `src/runtime/presence_controller.py`: khoảng `2,693` dòng.
- `src/cortex/surface_arbiter.py`: khoảng `1,564` dòng.
- `src/runtime/private_mind_model_adapter.py`: khoảng `1,155` dòng.
- `src/cortex/private_mind/inner_diary_renderer.py`: khoảng `211` dòng.
- `body/UdpListener.cs`: khoảng `3,972` dòng.

### 9. Runtime data không còn là bằng chứng “dirty state”
- `memory_core/active_state_snapshot.json`, `memory_core/event_ledger.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl` là state/data sống và hiện đã được commit tiếp.
- Dòng nào dùng chúng để chứng minh worktree đang dirty hoặc xem đó là API/source drift thì sai trọng tâm.

### 10. Dirty state mới ở lượt recheck cuối nằm ở cụm memory/embedding
- Source file đang dirty thật: `src/memory/embedding_index.py`, `src/memory/memory_models.py`.
- Runtime data đang dirty thật: `memory_core/active_state_snapshot.json`, `memory_core/semantic_memory.json`, `ni_drift_samples.jsonl`.
- Có thêm untracked local model/cache directory `src/paraphrase-multilingual-MiniLM-L12-v2/`; doc nên coi đây là artifact/runtime asset cục bộ, không gộp vào tracked architecture.

### 11. `tests/test_semantic_claim_entailment.py` vẫn là file “đúng hướng, không bị đợt private-mind kéo đi”
- History gần nhất vẫn bám `17ffc4d -> a9e6c58`.
- Nếu cần nhắc file này, trọng tâm đúng vẫn là chống việc dùng `preference_location` để trả lời `hometown/current_location`.

---

