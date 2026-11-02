# Kế hoạch: cắt context bloat khối Self trong request Root (ưu tiên 1, rẻ & an toàn)

Repo: `c:\Users\Gtvkun\Documents\GitHub\eris` (Windows, PowerShell, Python).
Phạm vi: CHỈ sửa đường projection đưa Self vào **prompt Root warm-up**. KHÔNG đụng
persistence (`to_dict()` của model), KHÔNG đổi nhánh one-shot (`render_prompt_context`),
KHÔNG đổi worktree. Làm trực tiếp trên branch hiện tại.

## 0. Quyết định thiết kế (chốt, kèm lý do ngắn)

- **Điểm sửa = `src/runtime/conversation/self_prompt_view.py`** (projection vận chuyển thuần,
  đã là nơi `compact_profile`/`project_self_view` làm việc này). Không sửa `models.py:to_dict()`
  vì `store.save()`/`apply()`/`from_dict()` dùng chung `to_dict()` cho lưu đĩa; đổi nó sẽ hỏng
  file persistence và round-trip `from_dict`. Đã xác nhận `store.py:113` (`snapshot`) và
  `store.py` `apply()` (`before = [r.to_dict() ...]`) đều dùng chung `to_dict()`.
- **Profile records:** mở rộng `compact_profile` để CẮT `evidence_ids` và các mốc timestamp
  epoch thô, thay vì chỉ rút field trùng. Giữ `path`/`value`/`explicitness`/`scope` (và các
  qualifier hiện có). Lý do: đây đã là hàm projection profile duy nhất trên đường warm-up;
  gom thay đổi vào một chỗ giữ tính idempotent dễ kiểm.
- **Episodes:** thêm hàm mới `compact_episode(...)` và gọi trong `project_self_view` cho từng
  phần tử `recent_episodes`. Lý do: episode `to_dict()` KHÔNG đi qua `compact_profile`
  (đã xác nhận `project_self_view` chỉ pop `metadata.source_turns`); cần một bước projection
  riêng, giữ nguyên các trần cắt độ dài do `UserEpisode.__post_init__` áp.
- **Delta tự đúng, không cần code thêm:** `_read_self` trả `project_self_view(result)`, và CẢ
  `bootstrap_self_snapshot` LẪN `self_now` (trong `ask`) đều lấy từ `_read_self`
  (`root_session.py` `_prime` dùng `_read_self`, `ask` gọi `self_now = _read_self(self._host)`).
  Vì vậy `_changed(bootstrap, now)` đã tính trên CÙNG hình dạng đã-chiếu-gọn → delta không
  trộn gọn với nặng. Ràng buộc bắt buộc giữ: projection phải **deterministic + idempotent**
  (`project_self_view(view) == view`, `compact_profile(projected) == projected`,
  `compact_episode(x) == compact_episode(compact_episode(x))`) để `state_difference` không
  báo delta giả giữa lượt. Guard idempotent hiện có: `compact_profile` trả sớm khi
  `projection_schema == "eris.root_profile.v1"`; sẽ thêm guard tương tự cho episode.
- **mind_state giữ nguyên tuyệt đối:** KHÔNG chạm nhánh `mind_state`/`persisted_mind_variants`
  trong `project_self_view` (yêu cầu sản phẩm `SELF_BOOTSTRAP_INSTRUCTION`: giữ cả belief yếu/
  trái chiều, không top-k, không tóm tắt).

## 1. Danh sách field CẮT / GIỮ

### Profile record (mỗi record trong `living_user.profile.records`)
- CẮT: `evidence_ids` (toàn bộ); `created_at`, `updated_at`, `last_confirmed_at`,
  `valid_from`, `valid_until`, `expires_at` (6 mốc epoch thô); `metadata` dict (mặc định cắt).
- GIỮ: `path`, `value`, `explicitness`, `scope` (dạng ngắn), `value_type`, `status`,
  `sensitivity`, `tier`, `cardinality`, `recurrence`, `source`, `confidence`, `id`.
  (Các field này nhẹ và `compact_profile` đã rút field trùng của chúng; không bắt buộc cắt
  thêm trong phạm vi "rẻ & an toàn". `id` giữ để ổn định delta theo record.)
- Lưu ý `defaults`/`aliases`: sau khi cắt 6 timestamp + `evidence_ids` khỏi record, KHÔNG đưa
  chúng vào vòng gom `defaults`; bỏ luôn 2 alias `updated_at→last_confirmed_at`,
  `created_at→valid_from` (vì nguồn/đích đều đã bị cắt). Danh sách gom `defaults` còn lại:
  `scope/status/sensitivity/cardinality/recurrence/tier/source/value_type`.

### Episode (mỗi phần tử `living_user.recent_episodes`)
- CẮT: `evidence_ids` (≤128/episode); `metadata` dict (mặc định cắt — đã sẵn pop
  `metadata.source_turns`, nay cắt cả dict); `started_at`, `ended_at` (epoch thô);
  `session_id` (id nội bộ, model không cần để cá nhân hóa); `source`.
- GIỮ: `title`, `summary`, `outcome`, `topics`, `entities`, `decisions`, `open_loops`,
  `user_signals` (giữ nguyên trần độ dài do `__post_init__`), `importance`, `scope`, `id`.

### mind_state / actions / subject_self
- GIỮ NGUYÊN hoàn toàn. `actions` (goals/commitments/workflows từ `action_store.snapshot()`)
  không bị chạm. `mind_state` không bị chạm. `subject_self` không bị chạm (chỉ `_read_self`
  đang loại `generated_at` như cũ).

## 2. Các bước thực thi (theo thứ tự phụ thuộc)

- [ ] 1. Mở rộng `compact_profile` trong `src/runtime/conversation/self_prompt_view.py:38-73`
      để cắt `evidence_ids` + 6 timestamp + `metadata` khỏi mỗi record SAU bước gom `defaults`,
      và bỏ 2 alias timestamp (nguồn/đích đã cắt). Giữ `projection_schema="eris.root_profile.v1"`
      làm guard early-return (idempotent). Cập nhật docstring: không còn "lossless"; nêu rõ
      cắt audit metadata, giữ path/value/qualifier.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q`
      — chạy sau khi đã cập nhật assertion ở bước 4; kỳ vọng pass.

- [ ] 2. Thêm hàm `compact_episode(episode: Mapping) -> dict` trong cùng file: trả bản copy đã
      cắt `evidence_ids`/`metadata`/`started_at`/`ended_at`/`session_id`/`source`, giữ
      `title/summary/outcome/topics/entities/decisions/open_loops/user_signals/importance/scope/id`.
      Thêm marker idempotent (ví dụ `"projection_schema": "eris.root_episode.v1"`) để
      `compact_episode(compact_episode(x)) == compact_episode(x)` và early-return nếu đã có marker.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: cùng lệnh pytest ở bước 5.

- [ ] 3. Trong `project_self_view` (`self_prompt_view.py:75-104`), thay vòng pop
      `metadata.source_turns` của episode bằng gọi `compact_episode` cho từng phần tử
      `living["recent_episodes"]` (gán lại list đã chiếu). Giữ nguyên nhánh `profile` gọi
      `compact_profile`, nhánh `mind_state`/`persisted_mind_variants`/`active_state` KHÔNG đổi.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: cùng lệnh pytest ở bước 5.

- [ ] 4. Cập nhật test `src/tests/conversation/test_root_prompt_cleanup.py`:
      `test_compact_profile_roundtrips_qualifiers_exceptions_and_timestamps` hiện assert
      round-trip LOSSLESS (`decoded == rows`) — mâu thuẫn chủ đích mới. Đổi nó (hoặc tách test
      mới) thành: assert `evidence_ids`/6 timestamp/`metadata` ĐÃ BỊ CẮT khỏi mỗi record, và
      `path`/`value`/`explicitness`/`scope` được GIỮ; vẫn assert không mutate `source` đầu vào
      và idempotent `compact_profile(projected) == projected`. Trong
      `test_self_view_removes_debug_and_clones_without_changing_owner`, assert
      `view["memory_state"]["living_user"]["recent_episodes"]` giờ là bản đã `compact_episode`
      (giữ `summary`, không có `evidence_ids`/`metadata`/`session_id`/timestamp), thay vì bằng
      `{"recent_episodes": [{"summary": "real memory"}]}` nguyên như cũ.
      Files: `src/tests/conversation/test_root_prompt_cleanup.py`
      Verify: `.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` pass.

- [ ] 5. Cập nhật test `src/tests/test_memory_interpretation_context.py`:
      `test_episode_sources_survive_reconsolidation_but_stay_out_of_root` hiện chỉ assert
      `"source_turns" not in ...["metadata"]`. Sau thay đổi, `metadata` episode bị cắt hẳn trong
      projection — sửa assertion thành: episode đã chiếu KHÔNG còn `evidence_ids`/`metadata`/
      `started_at`/`ended_at`/`session_id`, nhưng CÒN `summary`/`title`. Giữ nguyên các assert
      không-liên-quan (snapshot không mutate; `scrub_evidence` trên store gốc vẫn chạy — store
      gốc dùng `to_dict()` đầy đủ, KHÔNG bị projection đụng, nên scrub vẫn thấy `source_turns`).
      Files: `src/tests/test_memory_interpretation_context.py`
      Verify: `.\.venv\Scripts\python.exe -m pytest src/tests/test_memory_interpretation_context.py -q` pass.

- [ ] 6. Chạy nhóm regression đụng Root session/projector/self-view để xác nhận delta,
      idempotency và bounded prompt không hồi quy.
      Files: (không sửa) — chỉ chạy.
      Verify: `.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py src/tests/conversation/test_root_session_projector_v1.py src/tests/conversation/test_root_session_bootstrap_v12.py src/tests/test_memory_interpretation_context.py src/tests/test_companion_memory_authority_consolidation.py -q`
      — tất cả pass. Đặc biệt kiểm `test_every_request_can_reconstruct_current_self_and_context`
      (delta reconstruct) và `test_self_invariant` (Self bất biến) vẫn xanh.

## 3. Giữ delta đúng (chi tiết ràng buộc)

- KHÔNG tính delta trên bản nặng rồi mới gọn, và ngược lại. Cả bootstrap lẫn per-turn đều qua
  `_read_self` → `project_self_view` nên đã đồng hình dạng. Không thêm đường đọc Self nào khác.
- Projection phải idempotent & deterministic: cùng input → cùng output byte, và chiếu lần 2
  không đổi. Nếu không, `_changed(bootstrap, now)` sẽ sinh patch giả mỗi lượt (phình delta,
  sai ngữ nghĩa overlay). Guard marker `projection_schema` ở cả profile và episode đảm bảo điều này.
- Không thêm timestamp/clock vào projection (ví dụ không chèn "now" vào episode) — sẽ phá
  determinism và làm delta khác nhau mỗi lượt.

## 4. Đo trước/sau (bắt buộc ghi số)

Dùng log sẵn có, KHÔNG thêm grep:
- `root_session.py:_prime` ghi `self_component_chars=<JSON breakdown>` với prefix
  `self.*`, `memory.*`, `living_user.*` (gồm `living_user.profile`, `living_user.recent_episodes`).
- `root_session.py:_call` ghi `request_size messages=... message_chars=[...] estimated_tokens=...`.

Cách đo không cần bản chạy live: viết một đoạn đo tạm (hoặc test tạm) dựng `host.memory_state`
từ một `living_user.summary()` thực (hoặc fixture đại diện ~38 record + 8 episode), rồi so
`len(json.dumps(project_self_view(_read_self(host))))` TRƯỚC và SAU thay đổi, log breakdown
`living_user.profile` và `living_user.recent_episodes`. Kỳ vọng (ước lượng từ báo cáo điều tra):
`living_user.profile` giảm mạnh do mất `evidence_ids`(≤96/record)+6 timestamp+`metadata`;
`recent_episodes` giảm do mất `evidence_ids`(≤128)+`metadata`+timestamp. Mục tiêu định tính:
tổng khối `living_user` giảm đáng kể, `mind_state`/`actions` KHÔNG đổi kích thước. Xóa file đo
tạm sau khi ghi số vào báo cáo.

## 5. Danh sách file test liên quan cần chạy (đã grep src/tests)

- `src/tests/conversation/test_root_prompt_cleanup.py` — `compact_profile`, `project_self_view`,
  `project_runtime_context`, `_read_self`, delta reconstruct (CẦN SỬA assertion: bước 4).
- `src/tests/test_memory_interpretation_context.py` — `project_self_view` trên episode thực
  (CẦN SỬA assertion: bước 5).
- `src/tests/conversation/test_root_session_projector_v1.py` — `project_root_messages`, bounded
  prompt, Self invariant (không sửa; phải vẫn xanh).
- `src/tests/conversation/test_root_session_bootstrap_v12.py` — nạp full Self + delta
  (`_read_self`, `_changed`) (không sửa; phải vẫn xanh).
- `src/tests/test_companion_memory_authority_consolidation.py` — `render_prompt_context` nhánh
  one-shot (không sửa; đảm bảo KHÔNG bị ảnh hưởng — xác nhận nhánh gọn tách biệt).
- Tham khảo loại trừ: `test_dialogue_contract_recovery.py`, `test_user_input_batch.py`,
  `test_root_parallel_tools_v12.py` set `ERIS_ROOT_SESSION_BOOTSTRAP=0` (nhánh one-shot),
  không đụng projection — chạy để chắc không hồi quy nếu còn thời gian.

Lệnh verify tổng (từ repo root, pytest.ini đã set `pythonpath = src .`):
`.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py src/tests/conversation/test_root_session_projector_v1.py src/tests/conversation/test_root_session_bootstrap_v12.py src/tests/test_memory_interpretation_context.py src/tests/test_companion_memory_authority_consolidation.py -q`

## 6. Giới hạn & kiểm tra ngược

- Không chứng minh được bản portable đang chạy có `ERIS_ROOT_SESSION_BOOTSTRAP=1`; thay đổi chỉ
  có hiệu lực trên đường warm-up. Nhánh one-shot (`render_prompt_context`) vốn đã gọn, không đổi.
- `from_dict` của model KHÔNG đổi; file persistence không bị ảnh hưởng vì ta không chạm
  `to_dict()`. Xác nhận lại bằng grep call site `to_dict` trước khi kết luận an toàn nếu cần.
- Theo AGENTS.md: trạng thái "warm-up đang chạy live" là suy đoán từ default env, chưa có trace
  live; plan này không nâng suy đoán đó thành fact.

---
Đường dẫn plan: `c:\Users\Gtvkun\Documents\GitHub\eris\.agents\tasks\eris-token-growth\cheap-cut-plan.md`
