# Cắt telemetry/history của mind_state + qualifier kỹ thuật của profile ở Self prefix Root

Chỉ sửa ĐƯỜNG PROJECTION đưa Self vào prompt (`self_prompt_view.py`). KHÔNG đụng
`to_dict()` persistence. GIỮ nguyên nội dung nhận thức và belief trái chiều.

## (a) Điểm sửa + lý do (file:dòng)

Một file duy nhất: `src/runtime/conversation/self_prompt_view.py`.

1. **Thêm `compact_personality` / `compact_identity` / `compact_mind_state`** (đặt
   ngay sau `compact_semantic_item`, trước `project_self_view`). Theo đúng mẫu
   `compact_agent_mind`/`compact_active_state`/`compact_semantic_item`: `deepcopy`
   input (không mutate), early-return nếu đã có marker (idempotent), chỉ `pop` field
   THỪA, đặt marker (`eris.personality.v1` / `eris.identity.v1` / `eris.mind_state.v1`).
   Lý do: đây là pattern tiền lệ đã merge cho đúng bài toán cắt-ở-transport; lặp lại
   giữ idempotency mà `state_difference` cần.
2. **Gọi `compact_mind_state` trong `project_self_view`** — thêm ngay TRƯỚC khối
   `persisted_mind_variants`:
   `if isinstance(result.get("mind_state"), Mapping): result["mind_state"] = compact_mind_state(result["mind_state"])`.
   `mind_state` là key TOP-LEVEL do `_read_self` đặt (`root_session.py:48-56`), KHÔNG
   nằm trong `memory_state`. Đặt trước `persisted_mind_variants` để `primary =
   result.get("mind_state")` (self_prompt_view.py) so với `ai_orchestrated_state` trên
   cùng điểm vào (xem mục g).
3. **Phần B — mở rộng `_PROFILE_AUDIT_FIELDS`** thêm `id, value_type, cardinality,
   recurrence, tier, source`; đồng thời **xóa 5 key** `cardinality/recurrence/tier/
   source/value_type` khỏi danh sách ứng viên `defaults` trong `compact_profile`
   (chỉ còn `scope, status, sensitivity, valid_until, expires_at`) để không bị
   re-promote sau khi đã pop ở record. GIỮ `path, value, status, confidence,
   explicitness, scope, sensitivity`.

Nguồn số liệu field đã đối chiếu trực tiếp trong source:
- `RuntimeMindState.to_dict` — `contracts.py:550-568` (có `schema, version,
  last_applied_turn_seq, updated_at` top-level + `relationship/appraisal/personality/
  identity/identity_learning_enabled/latest_observation/latest_intention/open_loops/
  goal_records/memory_candidates`).
- `PersonalityProfile.to_dict` — `personality.py:620-648`.
- `IdentityProfile.to_dict` — `identity.py:611-632`.

Idempotency & delta xác nhận bằng code: cả bootstrap (`project_bootstrap_self(_read_self(host))`
— root_session.py:295) lẫn self-now (`_read_self(host)` — root_session.py:360) đều gọi
`project_self_view` (root_session.py:81). `project_bootstrap_self` KHÔNG đụng
`mind_state` (chỉ pop `living_user` episodes). → cả hai nhánh đi qua cùng mind_state
đã-chiếu-gọn trước khi `_changed()` tính delta.

## (b) Field đã cắt / đã giữ

### mind_state — top-level (`_MIND_TOP_AUDIT_FIELDS`)
- CẮT: `schema`, `version`, `last_applied_turn_seq`, `updated_at`.
- GIỮ: `relationship`, `appraisal`, `personality` (compact), `identity` (compact),
  `identity_learning_enabled`, `latest_observation`, `latest_intention`, `open_loops`,
  `goal_records`, **`memory_candidates`** (chưa xác minh → giữ).

### mind_state.personality (`_PERSONALITY_AUDIT_FIELDS`)
- CẮT: `trajectory`, `consolidation_ledger`, `corroboration_records`, `corroboration`,
  `streaks`, `day_usage`, `last_consolidated_at`, `last_decay_at`, `last_updated_at`,
  `schema`, `version`.
- GIỮ: `core`, `temperament`, `mood`, `core_anchor`, `temperament_attractor`,
  `mood_baseline`, `strategy_reinforcement`, `narrative`, `relationship_profiles`.

### mind_state.identity (`_IDENTITY_AUDIT_FIELDS`)
- CẮT: `ledger`, `corroboration`, `last_updated_at`, `schema`, `version`.
- GIỮ: `values`, `motives`, `defenses`, `beliefs`, `emergent_values`, `relationships`,
  `strategies`, **`pending_strategies`**, **`imprints`**, `active_motives`,
  `active_defenses`, `active_conflict`, `latest_value_choice` (gồm belief trái chiều).

### profile (`_PROFILE_AUDIT_FIELDS`)
- CẮT (thêm mới task này): `id`, `value_type`, `cardinality`, `recurrence`, `tier`,
  `source` (và đã có sẵn từ trước: `evidence_ids`, `metadata`, `created_at`,
  `updated_at`, `last_confirmed_at`, `valid_from`).
- GIỮ: `path`, `value`, `status`, `confidence`, `explicitness`, `scope`, `sensitivity`.

## (c) Số ký tự trước/sau (script `measure_self_cut.py`, chỉ in kích thước, không in nội dung)

Lệnh: `.\.venv\Scripts\python.exe .agents/tasks/eris-token-growth/measure_self_cut.py`

### living_user.profile — store thật (copy READ-ONLY sang temp, không chạm bản live)
| | chars |
|---|---:|
| raw store snapshot | 9.627 |
| prior projection (cắt audit, GIỮ qualifier) | 3.923 |
| new projection (cắt audit + qualifier) | 2.364 |
| **marginal saved (riêng task này)** | **1.559** |
| total saved vs raw | 7.263 |

Marginal 1.559 nằm trong kỳ vọng ~1.500–2.500. `path+value` còn trên mọi record;
6 qualifier kỹ thuật biến mất khỏi cả record lẫn `defaults` (assert trong script = True).

### mind_state — fixture đại diện (trajectory 96 + ledger 24 + corroboration 16/key + counter/timestamp + core/temperament/mood + belief trái chiều)
| | chars |
|---|---:|
| before (raw) | 12.147 |
| after (cut) | 1.679 |
| **saved** | **10.468** |

Fixture cố ý nạp đầy các cap để thấy đỉnh; live sẽ tỉ lệ theo mức tích lũy thật
(phiên 9 phút đo trước cho mind_state 7.182→10.732). Mức cắt vượt kỳ vọng
~3.500–6.000 vì fixture lấp trần trajectory/ledger/counter tối đa — đúng bản chất
"nguồn phình theo phiên" mà task nhắm tới.

## (d) Kết quả test

Lệnh (từ repo root, venv; output ghi ra file `..\_pytest_cleanup.txt` rồi đọc):
```
.\.venv\Scripts\python.exe -m pytest src/tests/conversation/test_root_prompt_cleanup.py
  src/tests/conversation/test_root_session_bootstrap_v12.py
  src/tests/conversation/test_root_session_projector_v1.py
  src/tests/test_memory_interpretation_context.py -q
```
Kết quả: **47 passed in 3.06s** — không có failed/error.

Gồm:
- `test_compact_mind_state_cuts_telemetry_keeps_cognition` (MỚI): khẳng định cắt
  đúng từng field ở 3 cấp; giữ core/temperament/mood, identity.values/beliefs/
  active_conflict/emergent_values, relationship, appraisal, goal_records,
  memory_candidates, identity.imprints, identity.pending_strategies; belief trái
  chiều (`contradiction_ids`) còn; input không mutate; idempotent.
- `test_compact_profile_cuts_audit_keeps_telling_and_qualifiers` (MỞ RỘNG): assert
  id/value_type/cardinality/recurrence/tier/source không còn ở record lẫn defaults;
  scope/sensitivity/status/confidence/explicitness còn.
- `test_self_view_removes_debug_and_clones_without_changing_owner` (CẬP NHẬT): mind_state
  giờ có marker + identity compact; `persisted_mind_variants` phản ánh marker tombstone
  + persisted variant.
- **`test_every_request_can_reconstruct_current_self_and_context` (PASS)** — chứng minh
  overlay/delta reconstruct ĐÚNG current self sau khi cắt telemetry (bootstrap + apply
  overlay == `_read_self(host)` qua 3 lượt + lượt revert). Đây là test delta
  reconstruction yêu cầu.

Phân biệt regression vs đỏ-sẵn-có: 47 test trong phạm vi projection/root-session đều
PASS → KHÔNG có regression. Các test đỏ-sẵn-có đã biết (test_character_evidence_v1,
test_companion_memory_authority_consolidation, test_living_user_memory_v39,
test_memory_hygiene_v41, test_action_claim_integrity, test_character_public_claim_gate,
test_eris02_root_agency) đi qua one-shot/writer/claim, KHÔNG liên quan projection path —
không nằm trong suite đã chạy nên không ảnh hưởng kết luận; thay đổi của task không
chạm các đường đó (xem mục e).

## (e) Không đụng persistence (chứng minh)

`git diff --stat` (ghi `..\_gitstat.txt`): chỉ
`src/runtime/conversation/self_prompt_view.py` và
`src/tests/conversation/test_root_prompt_cleanup.py` thay đổi (và plan.md có sẵn thay
đổi từ bước lập kế hoạch, không do bước này). KHÔNG có
`src/runtime/ai_orchestrated/contracts.py`, `personality.py`, `identity.py`,
`src/memory/living_user/models.py` trong diff → `to_dict()` của RuntimeMindState/
PersonalityProfile/IdentityProfile/ProfileRecord nguyên vẹn. Store `save()` vẫn dùng
`to_dict()`, không dùng projection → dữ liệu lưu đĩa đủ field.

## (f) Không mất nhận thức / belief trái chiều / không cắt nhầm

- `compact_mind_state` CHỈ pop danh sách THỪA đã liệt kê; mọi field nhận thức giữ
  nguyên (test assert từng key).
- Belief trái chiều: `identity.beliefs` (gồm record có `contradiction_ids`),
  `identity.active_conflict`, `identity.emergent_values` KHÔNG nằm trong danh sách cắt
  → còn nguyên (test assert `b.conflict.contradiction_ids == ["b.keep"]` và
  `active_conflict`).
- KHÔNG cắt nhầm `memory_candidates` (top-level), `pending_strategies` (trong
  IDENTITY, không phải personality), `imprints` (identity) — không key nào trong các
  tuple audit; test assert cả ba còn.

## (g) Delta tính đúng trên hình dạng đã-chiếu

Cả bootstrap snapshot và self-now đi qua cùng `project_self_view` → cùng
`compact_mind_state` trước khi `_changed()` chạy → không phantom delta, không trộn
gọn-với-nặng. `test_every_request_can_reconstruct_current_self_and_context` PASS xác
nhận apply overlay dựng lại đúng `_read_self(host)`.

`persisted_mind_variants`: nhánh persisted (`ai_orchestrated_state`) vẫn là raw
`to_dict()`, còn `primary` (mind_state) đã compact → `state_difference` thấy các
field đã-cắt + marker là "chỉ có ở persisted" và xuất chúng dưới
`persisted_mind_variants`. Đây là hành vi ĐÚNG và vô hại (persistence evidence, nhỏ,
không phải nội dung nhận thức mới); test cập nhật phản ánh đúng shape này. KHÔNG nới
phạm vi cắt sang nhánh persisted (ngoài task).

## (h) Điều CHƯA XÁC MINH (ghi rõ)

1. `memory_candidates`, `personality`→(không có pending ở personality),
   `identity.pending_strategies`, `identity.imprints`: chưa truy được consumer prompt
   rõ → GIỮ theo quy tắc "không chắc thì giữ", KHÔNG cắt.
2. `profile.scope` / `profile.sensitivity`: chưa truy được có lái redaction/scope
   downstream không → GIỮ.
3. Đỉnh thật mind_state trên phiên dài (trajectory cap 96) chưa đo trên live; số
   10.468 là trên fixture lấp trần, không phải đo live.
4. Chưa chứng minh bản portable `Documents/eris/Eris.exe` đã nạp đúng projection này
   (đo trên source checkout chính).
