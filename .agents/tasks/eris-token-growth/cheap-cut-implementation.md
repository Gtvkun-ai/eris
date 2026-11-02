# Triển khai: cắt context bloat khối Self trong request Root (vòng đầu)

Repo: `c:\Users\Gtvkun\Documents\GitHub\eris`. Branch hiện tại (`main`), không worktree.
`review.json` KHÔNG tồn tại tại thời điểm chạy → đây là vòng implement đầu tiên theo
`cheap-cut-plan.md`, không phải vòng sửa finding.

## (a) Điểm sửa + lý do (file:dòng)

Tất cả thay đổi nằm trong **đường projection warm-up thuần vận chuyển**, không chạm
persistence và không chạm nhánh one-shot `render_prompt_context`.

1. `src/runtime/conversation/self_prompt_view.py` — `compact_profile(...)`
   (nay ~dòng 38–96). Mở rộng hàm projection profile duy nhất trên đường warm-up:
   thêm bước pop `_PROFILE_AUDIT_FIELDS` khỏi mỗi record TRƯỚC bước gom `defaults`.
   Lý do chọn đây: đây đã là nơi `project_self_view` nén profile; gom thay đổi vào một
   chỗ giữ tính idempotent (guard `projection_schema="eris.root_profile.v1"` giữ nguyên).
   Bỏ hẳn hai alias timestamp (`updated_at→last_confirmed_at`, `created_at→valid_from`)
   vì cả hai alias source và target `valid_from` đều đã bị cắt — không alias nào còn
   hình thành được; `aliases` nay luôn `{}`.

2. `src/runtime/conversation/self_prompt_view.py` — hàm mới `compact_episode(...)`
   (nay ~dòng 99–126). Episode `to_dict()` KHÔNG đi qua `compact_profile`; trước đây
   `project_self_view` chỉ pop `metadata.source_turns`. Hàm mới pop toàn bộ
   `_EPISODE_AUDIT_FIELDS`, giữ nội dung lời kể, và gắn marker
   `projection_schema="eris.root_episode.v1"` để idempotent (early-return nếu đã có).

3. `src/runtime/conversation/self_prompt_view.py` — `project_self_view(...)`
   (nay ~dòng 142–151). Thay vòng pop `metadata.source_turns` bằng gọi
   `compact_episode` cho từng phần tử `living["recent_episodes"]` (gán lại list đã chiếu).
   Nhánh `mind_state`/`persisted_mind_variants`/`active_state`/`subject_self` KHÔNG đổi.

## (b) Field đã CẮT / đã GIỮ

### Profile record (`_PROFILE_AUDIT_FIELDS`)
- CẮT: `evidence_ids` (phần nặng nhất, ≤96 id/record, thuần audit); `metadata` (dict
  mặc định cắt — không có consumer Root prompt đọc); 4 mốc epoch thô `created_at`,
  `updated_at`, `last_confirmed_at`, `valid_from`.
- GIỮ: `path`, `value`, `explicitness`, `scope`, `status`, `sensitivity`, `tier`,
  `cardinality`, `recurrence`, `source`, `value_type`, `confidence`, `id`.
- Lưu ý `valid_until`/`expires_at`: KHÔNG cắt thẳng; chúng là qualifier hạn dùng
  (không phải id audit) và vẫn đi qua bước gom `defaults` như cũ (phần lớn `None` nên
  bị gom vào `defaults`, gần như không tốn ký tự/record). Đây là lý do giữ 2 field này
  trong danh sách `defaults` thay vì cắt hẳn như 4 timestamp kia.

### Episode (`_EPISODE_AUDIT_FIELDS`)
- CẮT: `evidence_ids` (≤128/episode); `metadata` (chứa `source_turns`); `started_at`,
  `ended_at` (epoch thô); `session_id` (id nội bộ); `source`.
- GIỮ: `title`, `summary`, `outcome`, `topics`, `entities`, `decisions`, `open_loops`,
  `user_signals` (trần độ dài do `UserEpisode.__post_init__` áp, không đụng), `importance`,
  `scope`, `id`.

### mind_state / actions / subject_self
- GIỮ NGUYÊN hoàn toàn — không chạm nhánh nào. Belief yếu/mâu thuẫn trong `mind_state`
  và `persisted_mind_variants` còn nguyên (yêu cầu sản phẩm `SELF_BOOTSTRAP_INSTRUCTION`).

## (c) Con số ký tự trước/sau (phép đo thật)

Đo bằng script tạm `_measure_cut.py` (đã xóa sau khi ghi số): dựng khối `living_user`
đại diện **38 profile record + 8 episode**, mỗi record đầy `evidence_ids`(12)+metadata+
6 timestamp, mỗi episode đầy `evidence_ids`(40)+`source_turns`(8)+timestamp. Chạy qua
projection CŨ (tái dựng pre-change: giữ audit, chỉ pop `metadata.source_turns`) và MỚI,
đếm `len(json.dumps(..., ensure_ascii=False, separators=(",",":")))`:

| Khối | CŨ (ký tự) | MỚI (ký tự) | Cắt | % |
|---|---:|---:|---:|---:|
| `living_user.profile` | 20.802 | 7.426 | 13.376 | **64,3%** |
| `living_user.recent_episodes` | 12.841 | 8.929 | 3.912 | **30,5%** |
| `living_user` tổng | 33.674 | 16.386 | 17.288 | **51,3%** |

Phần `profile` giảm mạnh nhất vì mất `evidence_ids` + 4 timestamp + `metadata` + key JSON
lặp. Episode giảm vừa phải vì nội dung lời kể (summary/topics/entities/…​) được giữ.
`mind_state`/`actions`/`subject_self` KHÔNG nằm trong phép đo vì không bị chạm → kích thước
không đổi.

> Giới hạn phép đo: đây là fixture đại diện theo trần code, KHÔNG phải số byte request live
> trên bản portable. Mức % trên dữ liệu thật của user sẽ dao động theo số `evidence_ids`/
> độ dài `metadata` thực tế mỗi record. Hướng và độ lớn (hàng chục %) là chắc chắn; con số
> tuyệt đối là ước lượng từ fixture.

## (d) Kết quả chạy test

Lệnh (qua `_run_cut_tests.ps1`, Python 3.12.10 trong `.venv`):

```
python -m pytest \
  src/tests/conversation/test_root_prompt_cleanup.py \
  src/tests/conversation/test_root_session_projector_v1.py \
  src/tests/conversation/test_root_session_bootstrap_v12.py \
  src/tests/test_memory_interpretation_context.py \
  src/tests/test_companion_memory_authority_consolidation.py \
  --tb=short -q
```

Kết quả: **50 passed, 1 failed**.

- Baseline TRƯỚC khi sửa (chỉ 2 file bị ảnh hưởng, đo trước khi edit):
  `test_root_prompt_cleanup.py` + `test_memory_interpretation_context.py` → **17 passed**.
- Sau khi sửa: hai file đó + nhóm regression → 50 passed.
- **1 failed là ĐỎ SẴN CÓ TRÊN BASE, không phải regression.**
  `test_companion_memory_authority_consolidation.py::test_living_user_competence_claim_is_context_only_not_teaching_authority`
  fail với `assert 'technical.experience_level' in ''` — `render_prompt_context()` trả rỗng.
  Đã xác nhận bằng cách `git stash` 3 file tôi sửa rồi chạy riêng test này trên base:
  **vẫn fail y hệt** (`1 failed in 1.51s`), rồi `git stash pop` khôi phục.
  Test này đi qua nhánh one-shot `compile_context().render_prompt_context()` — nhánh tôi
  KHÔNG chạm — nên lỗi độc lập với thay đổi này.
- `test_every_request_can_reconstruct_current_self_and_context` (delta reconstruct) và
  `test_self_invariant`/bootstrap v12 (Self bất biến) đều PASS → delta tính trên cùng hình
  dạng đã-chiếu-gọn, không trộn gọn với nặng; idempotency giữ nguyên.

Test đã cập nhật assertion (vì chủ đích đổi từ "lossless" sang "cắt audit, giữ telling"):
- `test_root_prompt_cleanup.py`: đổi `test_compact_profile_roundtrips_...` →
  `test_compact_profile_cuts_audit_keeps_telling_and_qualifiers` (assert audit bị cắt,
  path/value/explicitness/scope được giữ, không mutate input, idempotent). Cập nhật
  `test_self_view_removes_debug_...` để assert episode đã qua `compact_episode`.
- `test_memory_interpretation_context.py`: `test_episode_sources_survive_reconsolidation_but_stay_out_of_root`
  nay assert episode đã chiếu KHÔNG còn `evidence_ids`/`metadata`/`started_at`/`ended_at`/
  `session_id` nhưng CÒN `title`/`summary`; vẫn assert `scrub_evidence` chạy trên store gốc.

## (e) Xác nhận KHÔNG đụng persistence

- `ProfileRecord.to_dict()` (`src/memory/living_user/models.py:193`) và
  `UserEpisode.to_dict()` (`:354`) KHÔNG bị sửa — vẫn serialize đủ 22/18 field gồm
  `evidence_ids`/`metadata`/timestamp. `store.save()`/`snapshot()` dùng chung `to_dict()`
  này để lưu đĩa và round-trip `from_dict` → không đổi hành vi.
- Thay đổi chỉ nằm trong `self_prompt_view.py`, chỉ được gọi trên nhánh
  `root_session.py:_read_self → project_self_view` (đường đưa Self vào PROMPT). `compact_profile`/
  `compact_episode` nhận `Mapping` (dict đã `to_dict`) và trả bản `deepcopy` đã cắt — KHÔNG
  mutate đối tượng gốc (test `assert snapshot == before` / `assert source == before` xác nhận).
- Bằng chứng runtime: `test_episode_sources_survive_reconsolidation_but_stay_out_of_root`
  PASS cả hai assert — episode đã chiếu mất `source_turns`, NHƯNG `store.scrub_evidence(["u1"])`
  trên store gốc vẫn trả `1` và xóa được (store gốc dùng `to_dict()` đầy đủ, projection không
  đụng tới).

## (f) Điều CHƯA xác minh (trung thực về bằng chứng)

- Chưa chạy live trên bản portable; không có số byte request thực. Con số ở (c) là từ fixture
  đại diện, không phải trace live. Theo AGENTS.md, trạng thái "warm-up đang chạy live với
  `ERIS_ROOT_SESSION_BOOTSTRAP=1`" vẫn là suy đoán từ default env, không nâng thành fact.
- Không chạy toàn bộ test suite; chỉ chạy nhóm regression liên quan đến Root session/projector/
  self-view/memory-interpretation + file one-shot để chứng minh tách biệt. 1 lỗi đỏ-sẵn-có ở
  `render_prompt_context` chưa được điều tra nguyên nhân gốc (ngoài phạm vi task này — nhánh
  one-shot không bị đụng).
- `valid_until`/`expires_at` giữ trong `defaults` thay vì cắt hẳn: quyết định theo plan (chúng
  là qualifier hạn dùng, không phải audit id). Nếu sau này xác nhận không consumer nào đọc,
  có thể cắt thêm — chưa làm trong vòng này.
