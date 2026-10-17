# Nhiệm vụ 2 — Xóa 5 thought-shards + deep-reflection + observer_comment (phương án a/(1)/(A))

Ngày: 2026-10-17. Workspace chính `c:/Users/Gtvkun/Documents/GitHub/eris`
(không worktree). Chỉ sửa `src/`; bỏ qua `.worktrees/`.

## Quyết định đã chốt (qua các vòng hỏi user)

- **(a)** XÓA HẲN 5 thought-shards (không sửa panel, không giữ store làm state).
- **(1)** phương án an toàn: XÓA thought-shards + deep-reflection + flag thought-shards,
  **GIỮ** residue curator (DiaryResidueStore + client Gemma + flag
  `private_residue_curator_enabled`).
- **(A)** observer_comment ("GEMMA // OBSERVER") bị xóa cùng thought-shards (vì nó
  được sinh trong cùng lượt `write_thought_shards` và lưu trong ThoughtShardStore);
  sửa test adapter; **không** đụng body Godot C#.

## Bằng chứng nền (phân tầng)

- **[ĐÃ ĐỌC SOURCE]** 5 thought-shards + observer_comment + deep-reflection chỉ
  nằm trong digest legacy (`self.private_mind_digest` / `loop.digest()`), KHÔNG vào
  payload production. `public_output_runtime._build_stage_payload` đi đường
  `ai_runtime_enabled=True` lấy `private_mind_digest` từ `build_ai_panel_payload`
  (schema `eris.inner_state.panel.v1`) — schema này không có field
  `thought_shards`/`inner_diary`/`observer_comment`. Nhánh legacy (`depth_v2`,
  dùng `full_private_digest`) mới đọc các field đó và production không đi nhánh này.
- **[ĐÃ ĐỌC SOURCE]** Deep-reflection (DeepSeek qua `InnerDiaryWriter`) chỉ chảy ra
  `digest["inner_diary"]` (renderer panel) + persist `memory_core/inner_diary.json`
  (`InnerDiaryPersister`). `ContextAssembler._private_cognition_context` chỉ đọc
  `active_concerns`, `mental_material`, `current_goal`, `attention` từ WorldState
  cognition — KHÔNG đọc `inner_diary`/`thought_shards`/`deep_reflection`. ⇒ Kết luận
  deep-reflection chỉ ở panel digest, không nuôi context Root/Writer lượt sau.
- **[QUAN SÁT TEST]** Sau khi xóa: 15/15 test trọng tâm (inner_diary_worker,
  v79_residue, identity_panel_v81) pass; import module runtime OK; grep không còn
  tham chiếu gãy (xem dưới).

## Quyết định số phận deep-reflection (theo yêu cầu kiểm riêng)

Deep-reflection **không** nuôi context lượt sau (đã lần ngược: writer output chỉ
vào renderer panel + file đĩa). Vì vậy **xóa** deep-reflection cùng thought-shards.
Tuy nhiên KHÔNG xóa cụm Gemma residue curator vì nó là consumer sống độc lập (xem
mục GIỮ). Flag `inner_diary_deep_reflection_enabled` được GIỮ (xem Ghi chú phạm vi).

## Đã XÓA

Module:
- `src/cortex/private_mind/thought_shards.py` (toàn bộ `SHARD_SLOTS`,
  `ThoughtShardConfig`, `ThoughtShardStore`, kèm observer_comment state).
- `src/cortex/private_mind/inner_diary_writer.py` (toàn bộ `InnerDiaryWriter` —
  lane deep-reflection).

`src/cortex/private_mind/__init__.py`:
- Gỡ import + export `SHARD_SLOTS`, `ThoughtShardConfig`, `ThoughtShardStore`.

`src/runtime/private_mind_loop.py`:
- Gỡ import `InnerDiaryWriter`, `ThoughtShardStore`, `RuntimePrivateMindModelAdapter`,
  và `import hashlib` (không còn dùng sau khi bỏ `_thought_shard_packet`).
- Gỡ khởi tạo `self.thought_shards` và toàn bộ khối dựng `self.diary_writer`
  (diary_adapter/diary_fallback).
- Gỡ background run `"private_thought_shards"` trong tick.
- Xóa method `_maybe_refresh_thought_shards` và `_thought_shard_packet`.
- Xóa method `_diary_voice`.
- Trong `digest()`: bỏ `thought_snapshot`, bỏ field `thought_shards` khỏi `menu`
  và `digest`, bỏ `voice = self._diary_voice(...)` (render với `voice=None`), bỏ
  `micro_thought_owner`/`deep_reflection_owner`/`shard_writer` khỏi
  `inner_diary_contract`.

`src/cortex/private_mind/inner_diary_renderer.py`:
- Gỡ đọc `shard_state`/`shard_slots`/`deep_reflection` và helper `_shard(...)`.
- Các ô now/next/concern/reflection/want/muon_noi quay về chuỗi fallback
  `_voice(...)` + raw-state (judgment/concern/future_bias/fragments/surface_queue/
  retained). GIỮ nguyên emotion board, memory_echo, residue block.
- Bỏ block `thought_shards` trong payload trả về của renderer.

`src/runtime/private_mind_model_adapter.py`:
- Xóa `RuntimePrivateMindModelAdapter`: `write_thought_shards` (+observer_comment),
  `_thought_shard_messages`, `_thought_shard_response_schema`,
  `deep_reflect_inner_diary`, `_deep_reflection_messages`,
  `_deep_reflection_response_schema`, `write_inner_diary`, `diary_fallback_from_env`.
- Xóa config field `max_tokens_diary`, `max_tokens_thought_shards`.
- Xóa `PrivateMindAdapterPool`: dựng `_diary_adapter`, property `diary_adapter`,
  `diary_metadata`, delegate `write_thought_shards`/`deep_reflect_inner_diary`/
  `write_inner_diary`; dọn `debug_status` (bỏ `diary_status`, bỏ key
  `deep_reflection`/`thought_shards`); sửa log `from_env` (bỏ phần deep-reflection,
  đổi "gemma-shards/residue" → "gemma-residue"); `residue_metadata.role`
  `thought_shards_and_residue` → `residue_curator`.

`src/runtime/architecture_flags.py`:
- Xóa hàm `inner_diary_thought_shards_enabled()` và khỏi `__all__`.

`src/vision.py`, `src/experiments/v57_simulation/live_runtime.py`:
- Gỡ import `inner_diary_thought_shards_enabled`; điều kiện dựng
  `residue_curator_client`/`residue_curator` bỏ `OR inner_diary_thought_shards_enabled()`,
  chỉ còn `private_residue_curator_enabled()`.

Test:
- Xóa `src/tests/test_v80_inner_diary_shards_deep_reflection.py` (toàn bộ test
  shard/deep-reflection, gồm cả `test_v82_gemma_identity_observer_comment_*`).
- `src/tests/test_identity_panel_v81_just_enough.py`: bỏ 2 assert adapter chứa
  `observer_comment`/`write_thought_shards` trong
  `test_v83_identity_uses_gemma_observer_without_extra_identity_model_lane`;
  GIỮ assert body C# (`ReadGemmaObserverCommentV82`, `observer_comment`).
- `src/tests/test_inner_diary_worker_v16.py`: viết lại, bỏ test dùng
  `InnerDiaryWriter`/`write_inner_diary`; GIỮ test `build_diary_client`,
  `LlmService.diary_client`, renderer memory_echo.
- `src/tests/test_v79_inner_diary_residue_curator.py`: bỏ import `InnerDiaryWriter`
  và test `test_writer_feeds_retained_entries_back_to_dedicated_diary_writer`;
  GIỮ toàn bộ test residue curator + renderer residue + settings.

`src/llm/process_manager.py`:
- Cập nhật docstring `build_residue_curator_client` (bỏ phần "Thought Shards").
  KHÔNG đổi hành vi.

## Đã GIỮ (lý do: còn nuôi đường cognition, không phải state chết)

- **DiaryResidueStore** (`src/cortex/private_mind/residue_curator.py`): ghi
  `dossier.metadata["residue_continuity"]` (`continuity_for_prompt`) vào evidence
  dossier — có vào đường prompt nội tâm. `private_mind_loop._maybe_consolidate_residue`
  và `_capture_tick_residue` vẫn gọi nó. Đường
  **DiaryResidueStore → residue_continuity → dossier KHÔNG bị gãy** (test
  `test_v79_inner_diary_residue_curator.py` pass, gồm
  `test_unprocessed_stimulus_cannot_be_promoted_to_diary` kiểm `continuity_for_prompt`).
- **residue_curator_client / build_residue_curator_client / flag
  `private_residue_curator_enabled`**: GIỮ vì DiaryResidueStore là consumer sống độc
  lập của client Gemma này.
- **InnerDiaryRenderer**: GIỮ cho emotion board / raw-state / memory_echo / residue.
- **active_concerns / mental_material / AdaptiveCompanionService**: không đụng.

## observer_comment (A) — trạng thái body C# còn lại

- observer_comment được sinh trong `write_thought_shards` và lưu trong
  ThoughtShardStore. Khi xóa thought-shards, observer_comment chết theo (không tách
  được nếu không xây đường lưu+sinh mới — đó là phương án (B) user đã loại).
- Body Godot C# (`src/body/UdpListener.DepthPanel.cs`) **vẫn còn** code đọc
  `thought_shards.observer_comment.text` qua `ReadGemmaObserverCommentV82` và nhãn
  "GEMMA // OBSERVER". Vì payload production không còn sinh `observer_comment`, phía
  body sẽ nhận **chuỗi rỗng** → ô observer hiển thị rỗng (degrade mềm, không crash).
- **File C# KHÔNG bị sửa** (ngoài phạm vi Python). Việc dọn nhãn/ô "GEMMA // OBSERVER"
  phía Godot để lại cho sau nếu user muốn.

## Ghi chú phạm vi / state trơ còn lại (có chủ đích)

- **Flag `inner_diary_deep_reflection_enabled`**: GIỮ. Deletion list của user chỉ
  nêu `inner_diary_thought_shards_enabled`. Sau khi xóa writer, flag này không còn
  gate gì (reader cũ là `_diary_voice`/loop init đã xóa) — là flag trơ. Không xóa
  để giữ phạm vi đúng yêu cầu và tránh phá test migration settings.
- **`diary_client` / `build_diary_client` / `LlmService.diary_client` / wiring
  `vision.py`**: GIỮ. Đây là DeepSeek worker trước chỉ phục vụ deep-reflection; nay
  không còn consumer trong pool. Giữ plumbing để không mở rộng blast radius sang
  LLM service wiring (user không yêu cầu). Client được dựng nhưng không ai tiêu thụ.
- **`runtime_settings_store.py` + `settings/runtime_settings.json`**: GIỮ key
  `inner_diary_thought_shards_enabled` (default + env-map). Đây là default trơ không
  còn reader — cùng tinh thần quyết định Nhiệm vụ 1 (không sửa store để tránh phá
  migration). Có thể dọn ở một thay đổi store riêng sau.
- **`_last_individual_projection`** trong digest: trước được set bên trong
  `_thought_shard_packet` (đã xóa). Nay giữ default `{}`; field `persistent_individual`
  trong digest legacy sẽ rỗng. Production tính `persistent_individual` độc lập
  (`public_output_runtime` projection, `observation_bridge`), nên KHÔNG regression
  đường production — chỉ digest legacy (vốn là nhánh chết) bớt field này.

## Lệnh verify đã chạy + kết quả

Venv: `.venv` (Python 3.12).

1. py_compile các file đã sửa:
```
.\.venv\Scripts\python.exe -m py_compile src/cortex/private_mind/__init__.py \
  src/cortex/private_mind/inner_diary_renderer.py src/runtime/private_mind_loop.py \
  src/runtime/private_mind_model_adapter.py src/runtime/architecture_flags.py \
  src/vision.py src/experiments/v57_simulation/live_runtime.py src/llm/process_manager.py
```
→ EXIT 0.

2. Import thật:
```
import cortex.private_mind; import runtime.private_mind_loop;
import runtime.private_mind_model_adapter; import runtime.architecture_flags;
import cortex.private_mind.inner_diary_renderer; import llm.process_manager; import vision
```
→ `IMPORT_OK`.

3. pytest (private_mind, inner_diary, identity, residue + các test liên quan
   private_mind_loop/adapter):
```
pytest test_inner_diary_worker_v16 test_v79_inner_diary_residue_curator \
  test_identity_panel_v81_just_enough test_identity_panel_contract_v15 \
  test_identity_panel_retired_v90 test_identity_panel_v78_elegant \
  test_identity_panel_v87_composition test_observer_singleflight_private_mind_dirty \
  test_deepseek_provider test_executive_authority_v55 test_v58_initiative_controller \
  test_v59_existential_desire test_v60_telemetry_meaning test_v94_goal_proposal_lifecycle \
  test_v99_object_bound_motivational_focus test_v100_bound_focus_material_authority
```
→ **105 passed, 2 failed**.

### Về 2 test failed — KHÔNG liên quan thay đổi này

- `test_identity_panel_v78_elegant.py::test_identity_panel_v78_main_navigation_does_not_duplicate_other_panels`
- `test_identity_panel_v87_composition.py::test_v87_self_is_one_composition_not_nested_dashboard_cards`

Cả hai chỉ đọc chuỗi/layout trong `src/body/UdpListener.DepthPanel.cs`. File C# này
`git diff --stat HEAD` = rỗng (KHÔNG bị thay đổi bởi nhiệm vụ này). Đây là lệch
pre-existing giữa test panel V78/V87 và body C# hiện tại, không do việc xóa
thought-shards. (confirmed)

## Grep cuối — không còn tham chiếu gãy

Grep `src/**/*.py` cho
`thought_shards|ThoughtShardStore|ThoughtShardConfig|SHARD_SLOTS|inner_diary_thought_shards_enabled|InnerDiaryWriter|deep_reflect_inner_diary|write_thought_shards|write_inner_diary|diary_fallback_from_env|_diary_voice|_maybe_refresh_thought_shards|diary_metadata`:
chỉ còn:
- `runtime_settings_store.py`: default + env-map `inner_diary_thought_shards_enabled`
  (state trơ, GIỮ có chủ đích — xem Ghi chú phạm vi).
- `test_identity_panel_v81_just_enough.py`: một comment giải thích (không phải code).

Không còn import/tham chiếu gãy tới symbol đã xóa trong code chạy.
