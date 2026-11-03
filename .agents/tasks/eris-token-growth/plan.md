# Implementation Plan — Audit-cut telemetry/history khỏi Self prefix của Root

Mục tiêu (verbatim từ task): Dọn "thừa vô tác dụng" cuối cùng trong khối Self prefix của
request Root. (A) cắt nhóm TELEMETRY/HISTORY trong `mind_state` — thứ KHÔNG consumer prompt
nào đọc và là nguồn phình theo phiên; (B) cắt các qualifier kỹ thuật thừa trong
`living_user.profile`. CHỈ cắt ở ĐƯỜNG PROJECTION đưa Self vào PROMPT
(`self_prompt_view.py`), KHÔNG đụng dữ liệu lưu đĩa (`to_dict()` persistence), GIỮ NGUYÊN
nội dung nhận thức và GIỮ belief trái chiều.

## Quyết định thiết kế (đã chốt, grounded theo code đã đọc)

- **Nơi sửa duy nhất:** `src/runtime/conversation/self_prompt_view.py`. Thêm một helper
  `compact_mind_state(...)` (gọi hai helper con `compact_personality(...)` +
  `compact_identity(...)`) theo đúng mẫu `compact_agent_mind`/`compact_active_state` đã merge
  (deepcopy input, marker `projection_schema` để idempotent, chỉ pop field, không mutate input).
  Lý do: đây là pattern tiền lệ duy nhất đã được review/merge cho đúng bài toán này; lặp lại
  nó giữ tính nhất quán và idempotency mà `state_difference` cần.

- **Chỗ gọi:** trong `project_self_view(...)`, thêm nhánh xử lý `result["mind_state"]`
  (key TOP-LEVEL của snapshot `_read_self`, KHÔNG nằm trong `memory_state`). Xác nhận bằng
  code: `_read_self` đặt `result["mind_state"] = _jsonable(raw)` (root_session.py:48-56) và
  `project_self_view` nhận chính `result` đó; nhánh `persisted_mind_variants` hiện có đọc
  `result.get("mind_state")` làm `primary` (self_prompt_view.py:316-318) → đúng là top-level.

- **Idempotency & delta:** cả bootstrap snapshot lẫn self-now đều đi qua `_read_self` →
  `project_self_view`. Xác nhận bằng code: `_prime` gọi `project_bootstrap_self(_read_self(host))`
  (root_session.py: `self_context = project_bootstrap_self(_read_self(self._host))`) và `ask`
  gọi `self_now = _read_self(self._host)` rồi `_changed(state.bootstrap_self_snapshot, self_now)`.
  Vì `compact_mind_state` chạy BÊN TRONG `project_self_view`, cả hai nhánh đều đã-chiếu-gọn
  trước khi tính delta → không có phantom delta, không lệch bootstrap-vs-now.
  `project_bootstrap_self` KHÔNG đụng `mind_state` (chỉ pop `memory_state.living_user` episodes)
  → không double-process, không desync. Marker `projection_schema="eris.mind_state.v1"` làm
  helper idempotent khi `project_self_view(view)` chạy lại.

- **Phần B:** mở rộng `_PROFILE_AUDIT_FIELDS` (self_prompt_view.py:49-52) để pop thêm
  `id, value_type, cardinality, recurrence, tier, source`. ĐỒNG THỜI phải xóa đúng các key này
  khỏi danh sách ứng viên `defaults` trong `compact_profile` (self_prompt_view.py:77-78) để
  chúng không bị re-promote thành `defaults` (nếu để lại, pop-ở-record nhưng vẫn promote →
  không giảm được gì). GIỮ `path, value, status, confidence, explicitness, scope, sensitivity`.

- **Danh sách cắt mind_state (chốt theo field thật trong to_dict đã đọc):**
  - Top-level `RuntimeMindState.to_dict` (contracts.py:552-568): cắt `schema`, `version`,
    `last_applied_turn_seq`, `updated_at`. GIỮ `relationship, appraisal, personality (compacted),
    identity (compacted), identity_learning_enabled, latest_observation, latest_intention,
    open_loops, goal_records, memory_candidates`.
  - `PersonalityProfile.to_dict` (personality.py:621-648): cắt `trajectory`,
    `consolidation_ledger`, `corroboration_records`, `corroboration`, `streaks`, `day_usage`,
    `last_consolidated_at`, `last_decay_at`, `last_updated_at`, `schema`, `version`. GIỮ `core,
    temperament, mood, core_anchor, temperament_attractor, mood_baseline, strategy_reinforcement,
    narrative, relationship_profiles` (nội dung nhận thức/anchor/baseline).
  - `IdentityProfile.to_dict` (identity.py:611-632): cắt `ledger`, `corroboration`,
    `last_updated_at`, `schema`, `version`. GIỮ `values, motives, defenses, beliefs,
    emergent_values, relationships, strategies, pending_strategies, imprints, active_motives,
    active_defenses, active_conflict, latest_value_choice` (gồm belief trái chiều).
  - KHÔNG cắt (quy tắc "không chắc thì giữ"): `memory_candidates`, `personality.pending_strategies`
    [lưu ý: pending_strategies nằm trong IDENTITY, không phải personality — xem to_dict], và
    `identity.imprints`. → KHÔNG đưa các key này vào bất kỳ danh sách pop nào.

- **Phạm vi cấm đụng:** KHÔNG sửa `to_dict()` của `RuntimeMindState`/`PersonalityProfile`/
  `IdentityProfile`/`ProfileRecord`. KHÔNG đụng nhánh one-shot `render_prompt_context`. KHÔNG
  đụng message cuối/history projection (`project_root_messages`). KHÔNG cắt belief/value/stance/
  personality-core/relationship/appraisal/goal; KHÔNG làm mất belief trái chiều.

---

- [ ] 1. Thêm helper `compact_personality`, `compact_identity`, `compact_mind_state` vào
      `src/runtime/conversation/self_prompt_view.py` (đặt ngay sau `compact_semantic_item`,
      trước `project_self_view`). Mỗi helper: `deepcopy(dict(input))`; early-return nếu marker
      đã có; pop đúng danh sách field THỪA ở trên; đặt marker. `compact_mind_state` set marker
      `"eris.mind_state.v1"`, gọi `compact_personality` trên `result["personality"]` (nếu là
      Mapping) và `compact_identity` trên `result["identity"]` (nếu là Mapping), rồi pop top-level
      `schema/version/last_applied_turn_seq/updated_at`. Thêm 3 hằng tuple field-list
      (`_MIND_TOP_AUDIT_FIELDS`, `_PERSONALITY_AUDIT_FIELDS`, `_IDENTITY_AUDIT_FIELDS`) kèm comment
      giải thích "không consumer prompt nào đọc" giống các khối audit hiện có. TUYỆT ĐỐI không
      đưa `memory_candidates`, `imprints`, `pending_strategies`, hay bất kỳ key nhận thức nào vào
      các tuple này.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `.\.venv\Scripts\python.exe -c "import ast,sys; ast.parse(open(r'src/runtime/conversation/self_prompt_view.py',encoding='utf-8').read())"` chạy không lỗi (ghi stdout/stderr ra file `..\_verify1.txt` rồi đọc file). Bước test thật ở item 5.

- [ ] 2. Gọi `compact_mind_state` trong `project_self_view(...)`
      (`src/runtime/conversation/self_prompt_view.py`). Thêm — sau khối xử lý `memory`/`active`,
      trước khối `persisted_mind_variants` — đoạn: `if isinstance(result.get("mind_state"), Mapping):
      result["mind_state"] = compact_mind_state(result["mind_state"])`. Phải đặt TRƯỚC khối
      `persisted_mind_variants` để `primary = result.get("mind_state")` so sánh với
      `ai_orchestrated_state` trên cùng hình dạng (persisted là raw to_dict nên `state_difference`
      sẽ coi các field đã-cắt là "khác" → xuất hiện trong `persisted_mind_variants`; đó là hành vi
      ĐÚNG và vô hại: persisted_mind_variants hiện chỉ ~123 ký tự và là "phần khác của persistence",
      không phải nội dung nhận thức). Ghi 1-2 dòng comment nêu lý do thứ tự.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: cùng item 5 (test suite). Về mặt logic: không có consumer nào khác đọc
      `mind_state` trong file này ngoài nhánh persisted.

- [ ] 3. Mở rộng `_PROFILE_AUDIT_FIELDS` và danh sách `defaults` trong `compact_profile`
      (`src/runtime/conversation/self_prompt_view.py:49-52` và `:77-78`). Thêm vào
      `_PROFILE_AUDIT_FIELDS`: `"id", "value_type", "cardinality", "recurrence", "tier", "source"`.
      Trong vòng lặp `defaults`, XÓA các key `"cardinality", "recurrence", "tier", "source",
      "value_type"` khỏi tuple ứng viên (chỉ còn lại `"scope", "status", "sensitivity",
      "valid_until", "expires_at"`), vì các field đó giờ bị pop ở record nên không còn để promote.
      Cập nhật docstring/comment của `compact_profile` và `_PROFILE_AUDIT_FIELDS` cho khớp (nêu rõ
      GIỮ `scope`/`sensitivity`). KHÔNG đụng `scope, status, sensitivity, confidence, explicitness,
      path, value, valid_until, expires_at`.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: cùng item 5 (test suite).

- [ ] 4. Thêm/ cập nhật regression test trong
      `src/tests/conversation/test_root_prompt_cleanup.py`. (a) Thêm
      `test_compact_mind_state_cuts_telemetry_keeps_cognition`: dựng fixture `mind_state` giống
      shape `RuntimeMindState.to_dict()` với `personality` (core/temperament/mood + trajectory/
      consolidation_ledger/corroboration_records/corroboration/streaks/day_usage/last_*_at),
      `identity` (values/beliefs gồm 1 belief trái chiều/active_conflict/emergent_values + ledger/
      corroboration/last_updated_at), `relationship`, `appraisal`, `latest_observation`,
      `goal_records`, `memory_candidates`, `schema/version/last_applied_turn_seq/updated_at`.
      Assert: các field THỪA bị cắt ở cả 3 cấp; `core/temperament/mood`, `identity.values/beliefs/
      active_conflict/emergent_values`, `relationship`, `appraisal`, `goal_records`,
      `memory_candidates`, `identity.imprints`, `identity.pending_strategies` còn nguyên; input
      không bị mutate (`source == before`); idempotent (`compact_mind_state(projected)==projected`).
      (b) Mở rộng `test_compact_profile_cuts_audit_keeps_telling_and_qualifiers`: thêm assert
      `id/value_type/cardinality/recurrence/tier/source` KHÔNG còn ở record lẫn `defaults`, và
      `scope/sensitivity/status/confidence/explicitness` CÒN. (c) Cập nhật
      `test_self_view_removes_debug_and_clones_without_changing_owner`: fixture `mind` hiện chỉ có
      `identity/relationship/latest_observation` (không chứa field bị cắt) nên sau projection sẽ
      THÊM marker `projection_schema="eris.mind_state.v1"` + compact lồng vào identity → đổi assert
      `view["mind_state"] == mind` thành so sánh có tính tới marker (và `persisted_mind_variants`
      có thể đổi do persisted raw vs mind_state compacted — cập nhật expected cho khớp hành vi mới).
      Files: `src/tests/conversation/test_root_prompt_cleanup.py`
      Verify: cùng item 5.

- [ ] 5. Chạy regression suite cho nhánh projection và root session. Chạy từ repo root với venv:
      `.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py
      src/tests/conversation/test_root_session_bootstrap_v12.py
      src/tests/conversation/test_root_session_projector_v1.py
      src/tests/test_memory_interpretation_context.py -q 2>&1 | Tee-Object -FilePath ..\_pytest_cleanup.txt`
      rồi `read` file `..\_pytest_cleanup.txt` (PowerShell exit code không tin được → đọc file).
      Expected: tất cả PASS, gồm test mới ở item 4 và test cũ `test_every_request_can_reconstruct_
      current_self_and_context` (chứng minh overlay/delta vẫn reconstruct đúng self sau compact).
      Files: (không sửa; chỉ chạy)
      Verify: dòng cuối file có `passed` và không có `failed`/`error`.

- [ ] 6. Xác nhận bằng code rằng persistence `to_dict()` KHÔNG bị đụng. `grep` diff của task
      không được chạm 4 file persistence; đọc lại để chắc chữ ký và thân `to_dict` nguyên vẹn:
      `src/runtime/ai_orchestrated/contracts.py` (RuntimeMindState.to_dict:552-568),
      `src/runtime/ai_orchestrated/personality.py` (PersonalityProfile.to_dict:621-648),
      `src/runtime/ai_orchestrated/identity.py` (IdentityProfile.to_dict:611-632),
      `src/memory/living_user/models.py` (ProfileRecord.to_dict:193-215). Chạy
      `git diff --stat 2>&1 | Tee-Object -FilePath ..\_gitstat.txt` và đọc file; expected: chỉ
      `src/runtime/conversation/self_prompt_view.py`, `src/tests/conversation/test_root_prompt_cleanup.py`
      (và các file đo/README dưới `.agents/`) thay đổi — KHÔNG có 4 file persistence trên.
      Files: (không sửa)
      Verify: `..\_gitstat.txt` không liệt kê contracts.py/personality.py/identity.py/models.py.

- [ ] 7. Viết script đo tiết kiệm token trên dữ liệu thật (profile) + fixture mind_state. Tạo
      `.agents/tasks/eris-token-growth/measure_self_cut.py` (ngoài src, không phải test). Script:
      (1) Copy READ-ONLY `C:\Users\Gtvkun\Documents\ErisLive\memory\core\living_user_profile.json`
      sang một thư mục temp (shutil.copy2 vào `tempfile.mkdtemp()`), KHÔNG đọc/sửa bản gốc tại chỗ.
      (2) `sys.path` thêm `src`; `from memory.living_user.store import UserProfileStore`; dựng
      `store = UserProfileStore(path=<temp copy>)`; lấy `snapshot = store.snapshot(include_sensitive=True)`
      (shape `{records:[...]}` mà `compact_profile` nhận). (3) `from runtime.conversation.self_prompt_view
      import compact_profile, compact_mind_state`; đo `len(json.dumps(snapshot))` trước vs
      `len(json.dumps(compact_profile(snapshot)))` sau. (4) Dựng fixture `mind_state` đại diện (có
      trajectory 96 record giả, consolidation_ledger 24, corroboration_records, streaks, day_usage,
      timestamp + core/temperament/mood + 1 belief trái chiều/value/personality) và đo
      `compact_mind_state` trước/sau. (5) In bảng ký tự trước/sau/tiết kiệm cho cả hai, và assert
      bằng tay rằng path/value/belief trái chiều còn trong output. Script chỉ ĐỌC store (không gọi
      `.apply`/`.save`), chạy trên bản copy → không chạm dữ liệu live.
      Files: `.agents/tasks/eris-token-growth/measure_self_cut.py`
      Verify: `.\.venv\Scripts\python.exe .agents/tasks/eris-token-growth/measure_self_cut.py 2>&1
      | Tee-Object -FilePath ..\_measure.txt` rồi đọc file; expected: in được số "trước > sau" cho
      cả profile lẫn mind_state, và dòng khẳng định belief trái chiều/path/value còn giữ. Nếu file
      profile live không tồn tại khi chạy, script in cảnh báo và chỉ đo fixture (không fail cứng).

- [ ] 8. Dọn file tạm và cập nhật ghi chú kết quả. Xóa các file đo tạm ngoài repo
      (`..\_verify1.txt`, `..\_pytest_cleanup.txt`, `..\_gitstat.txt`, `..\_measure.txt`,
      `..\_eriscore_ls.txt`) sau khi đã đọc. Ghi tóm tắt số đo (ký tự profile trước/sau, mind_state
      trước/sau) vào cuối `three-heavy-waste-assessment.md` hoặc một ghi chú ngắn trong
      `.agents/tasks/eris-token-growth/` nêu rõ: đã cắt telemetry/history mind_state + qualifier
      profile ở TRANSPORT, persistence nguyên vẹn, belief trái chiều còn, delta reconstruct pass.
      Files: `.agents/tasks/eris-token-growth/*.md`
      Verify: `git status --short 2>&1 | Tee-Object -FilePath ..\_final_status.txt` rồi đọc; chỉ còn
      các file chủ đích (self_prompt_view.py, test, measure script, ghi chú), không còn file `_*.txt` tạm.

## Điểm rủi ro đã lường trước (cho coder)

- `persisted_mind_variants` sẽ to lên chút sau khi compact mind_state (vì persisted là raw
  to_dict còn mind_state đã gọn → `state_difference` thấy nhiều field "chỉ có ở persisted").
  Đây KHÔNG phải nội dung nhận thức mới; nếu muốn triệt để, có thể cho persisted đi qua cùng
  `compact_mind_state` TRƯỚC khi `state_difference` — nhưng việc này NẰM NGOÀI phạm vi task
  (task chỉ yêu cầu cắt telemetry/profile). Mặc định: GIỮ hành vi hiện tại của nhánh persisted,
  chỉ thêm comment. Nếu test `test_self_view_removes_debug_and_clones_without_changing_owner`
  đòi persisted_mind_variants cụ thể, cập nhật expected cho khớp, KHÔNG nới phạm vi cắt.
- `pending_strategies` nằm trong `IdentityProfile.to_dict` (identity.py:627), KHÔNG phải
  personality — phải tránh nhầm khi viết `compact_identity` (giữ nó).
- Fixture mind_state trong test và trong measure script phải khác nhau: test khẳng định
  hành vi cắt từng field; measure script chỉ ước lượng tiết kiệm.
