# Audit-cut Self prefix: agent_mind + active_state + semantic_memory

Áp pattern audit-cut đã merge (`compact_profile`/`compact_episode`, commit
`77fc3a13`) sang ba nhánh còn nặng của khối Self vào prompt Root. Chỉ cắt trên
ĐƯỜNG PROJECTION (`project_self_view`), không đụng persistence, giữ nội dung thật
(belief/preference/claim) và giữ belief/fact trái chiều.

## (a) Điểm sửa + lý do (file:dòng)

Chỉ một file product thay đổi: `src/runtime/conversation/self_prompt_view.py`.

- `compact_agent_mind()` — thêm mới. Nhận `AgentMind.to_dict()` dạng
  `{schema_version, updated_at, beliefs:{key→rec}, preferences:{key→rec},
  habits, last_feedback_events}` (shape xác nhận ở
  `src/cortex/agent_mind_persistence.py` `PersistentAgentMindStore.to_dict` +
  `PersistentBeliefRecord.to_dict` / `PersistentPreferenceRecord.to_dict`).
  Cắt per-record audit, giữ cá tính.
- `compact_active_state()` + helper `_is_empty_default()` / `_prune_empty()` —
  thêm mới. Bỏ field rỗng/zero/None đệ quy (shape xác nhận trên store thật
  `ActiveStateSnapshot.to_dict`, `src/memory/active_state_snapshot.py`).
- `compact_semantic_item()` — thêm mới. Cắt per-item audit (shape xác nhận
  `SemanticMemoryItem.to_dict`, `src/memory/semantic_memory.py`).
- `project_self_view()` — thêm 3 lời gọi trong khối `memory`, SAU bước pop
  `active_state.metadata.internal_state` trùng `memory["internal_state"]` (giữ
  nguyên bước cũ) và TRƯỚC khối `ai_orchestrated_state`. Guard bằng `isinstance`
  trên đúng ba nhánh `memory["agent_mind"]` (Mapping) / `memory["active_state"]`
  (dict) / `memory["semantic_memory"]` (list).

Lý do chỗ sửa: `_read_self` (root_session.py) kết thúc bằng
`return project_self_view(result)`, nên mọi nhánh memory_state đi qua một cửa
duy nhất. Persistence (`store.save()` → `*.to_dict()`) KHÔNG đi qua đường này.
Idempotent bằng marker `projection_schema` giống tiền lệ, để `state_difference`
(so bootstrap-self với self-now, cả hai đều đã qua projection) không sinh phantom
delta giữa các lượt. deepcopy, không mutate input.

## (b) Field cắt / giữ từng nhánh

### agent_mind (cá tính — PHẢI GIỮ belief/preference)
- Belief CẮT: `created_at`, `updated_at`, `last_seen`, `source_ids`,
  `positive_evidence_count`, `negative_evidence_count`, `decay_rate`;
  `contradiction_ids` CHỈ khi rỗng.
- Belief GIỮ: `key`, `claim`, `confidence`, `domain`, `tags`;
  `contradiction_ids` khi KHÔNG rỗng (belief trái chiều = yêu cầu sản phẩm).
- Preference CẮT: `created_at`, `updated_at`, `last_reinforced`, `source`.
- Preference GIỮ: `key`, `polarity`, `strength`, `stability`, `tags`.
- Top-level: bỏ `updated_at` (epoch), bỏ `habits` nếu `{}`,
  `last_feedback_events` nếu `[]`; giữ `schema_version`.

### active_state (cắt mạnh nhất — bỏ rỗng/zero/default)
- `_is_empty_default`: True cho `None`, `""`, `[]`, `()`, `{}`, số `0`/`0.0`;
  bool KHÔNG bao giờ bị coi là 0 (False là giá trị thật → giữ).
- `_prune_empty`: đệ quy xóa key rỗng trong mọi dict lồng (kể cả
  `metadata.internal_state`, `mental_processes`, `*_dynamics`, `action_memory`);
  dict con rỗng sau khi dọn thì cha xóa luôn. List giữ nguyên phần tử, chỉ đệ quy.
- `session_arc == "unknown"` coi là default-rỗng → bỏ.
- GIỮ mọi giá trị khác mặc-định-rỗng: `trust=0.25`, `valence=0.02`,
  `curiosity=0.576`, `preferred_distance=0.58`, các string khác rỗng như
  `attachment_drift="guarded"`, `rhythm_phase="settled"`, `mode="settled"`,
  `last_event="maintenance_reset"`, `goal_persistence.status="empty"`, `version`.
- Quy tắc an toàn: chỉ bỏ rỗng/zero/None; không chắc thì giữ.

### semantic_memory (bỏ raw_content lặp + audit)
- Top-level CẮT: `evidence_ids`, `first_seen_at`, `updated_at`;
  `contradiction_ids` CHỈ khi rỗng.
- metadata CẮT: `raw_content` (trùng y hệt `claim` — xác nhận trên store thật),
  `embedding_text_hash`, `embedding_version`, `access_count`,
  `last_accessed_at`, `fact_profile_evidence`. Nếu metadata còn rỗng → bỏ hẳn.
- GIỮ: `id`, `claim`, `confidence`, `status`, `tags`, `domain`, `source`,
  `observations`, `decay_policy`, và trong metadata `fact_key`/`domain`/
  `importance`; `contradiction_ids` khi KHÔNG rỗng.
- Lưu ý bảo thủ: các field không nằm trong danh sách cắt verbatim của task
  (`source`, `observations`, `decay_policy`, `metadata.reason/source/domain`)
  được GIỮ theo quy tắc "không chắc thì giữ". Chúng nhẹ; phần nặng (raw_content
  dup + evidence_ids + embedding) đã bị cắt.

## (c) Số ký tự trước/sau — ĐO THẬT trên store thật

Đo bằng `measure_remaining_self.py`: copy `C:\Users\Gtvkun\Documents\ErisLive\
memory\core` sang temp (đọc-only), build `MemoryCognitionCore(temp).load()`,
chạy qua `project_self_view`, đếm `json.dumps(ensure_ascii=False,
separators=(',',':'))`. Before = bản đo cũ lưu trong
`_measure_before.json`; After = `remaining-self-measurement.raw.json` sau khi
sửa. CHỈ kích thước, không in nội dung cá nhân.

| Nhánh | Trước (ký tự) | Sau (ký tự) | Giảm |
|---|---|---|---|
| active_state | 6.198 | 3.102 | −3.096 (−50%) |
| agent_mind | 7.852 | 4.189 | −3.663 (−47%) |
| semantic_memory | 3.389 | 1.646 | −1.743 (−51%) |
| **projected_total** | **27.897** | **19.395** | **−8.502 (−30%)** |

`raw_per_key_chars` (pre-projection) vẫn 6.198 / 7.852 / 3.389 — bằng chứng độc
lập rằng serialization của store KHÔNG đổi (projection chạy trên deepcopy). Các
key khác không đổi: living_user 7.675, procedural 1.119, relational 742,
episodic 506.

Kỳ vọng khớp: active_state giảm mạnh nhất về tỉ lệ tuyệt đối; agent_mind giảm
vừa (giữ 10 belief + 12 preference); semantic giảm ~một nửa (bỏ raw_content lặp
+ evidence_ids + embedding hash).

## (d) Kết quả test (lệnh + pass/fail; regression vs đỏ-sẵn-có)

Lệnh (ghi output ra file, đọc file — terminal môi trường nhiễu echo):

1. Focused: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q`
   → **11 passed** (`_test_cleanup2.txt`). Gồm 3 test mới + test cũ đã cập nhật.
2. Broad (changed): `python -m pytest src/tests/conversation
   src/tests/test_memory_interpretation_context.py -q` → **582 tests, 7 failed**
   (`_junit_broad.xml`).
3. Broad (base = tháo wiring của tôi, giữ episode-fading): **582 tests, 8 failed**
   (`_junit_base.xml`).

So changed-vs-base (bằng chứng base-vs-changed thật):

- 7 fail ở changed = 6 fail KHÔNG liên quan projection + `test_character_evidence_v1`.
  Cả 7 ĐỀU đỏ trên base → **không có regression THẬT nào từ thay đổi này**.
  - `test_action_claim_integrity_v12` (×2), `test_action_claim_integrity_v2`
    (×2), `test_character_public_claim_gate_v1` (×1): về writer action-guard /
    public claim manifest / ROOT_STEP_SCHEMA enum. Grep xác nhận các file test
    này KHÔNG import `project_self_view`/`compact_*` và KHÔNG chạm
    `agent_mind`/`active_state` → không thể bị thay đổi của tôi tác động. Đây là
    đỏ-sẵn-có trong working tree (ngoài 5 đỏ-sẵn task liệt kê; nhiều khả năng do
    thay đổi chưa commit của episode-fading).
  - `test_eris02_root_agency::test_root_step_schema_...`: contract ROOT_STEP_SCHEMA,
    không liên quan projection.
  - `test_character_evidence_v1::test_public_memory_text_and_records_share_one_selection`:
    nằm trong danh sách 5 đỏ-sẵn task nêu (one-shot render path).
- Base có THÊM 1 fail: `test_root_prompt_cleanup::test_self_view_removes_debug_
  and_clones_without_changing_owner` — vì test cũ này được cập nhật assertion theo
  hành vi MỚI (metadata rỗng bị prune), nên khi tháo wiring nó đỏ. Với code của
  tôi bật lại, nó XANH. Đây là bằng chứng edit-test bám đúng code, không phải
  regression.

Kết luận: 7/7 fail ở changed-run là đỏ-sẵn-có; 0 regression do thay đổi này.

## (e) Xác nhận KHÔNG đụng persistence (bằng code)

- Diff product chỉ ở `self_prompt_view.py`. KHÔNG sửa
  `PersistentAgentMindStore.to_dict`/`PersistentBeliefRecord.to_dict`/
  `PersistentPreferenceRecord.to_dict` (`agent_mind_persistence.py`),
  `ActiveStateSnapshot.to_dict` (`active_state_snapshot.py`),
  `SemanticMemoryItem.to_dict` (`semantic_memory.py`), hay bất kỳ `save()` nào.
- Mọi `compact_*` gọi `deepcopy(dict(...))` rồi pop trên bản sao → object trong
  store in-RAM không bị mutate.
- Bằng chứng runtime độc lập: `raw_per_key_chars` (đo pre-projection từ
  `.to_dict()` trực tiếp) vẫn đúng 6.198/7.852/3.389 sau khi sửa — serialization
  lưu đĩa không đổi.
- KHÔNG đụng nhánh one-shot `render_prompt_context` (ở module khác).

## (f) Xác nhận không mất belief/preference/belief-trái-chiều

- `compact_agent_mind` KHÔNG xóa belief/preference nào; chỉ pop field audit trong
  từng record. `claim`, `confidence`, `tags`, `polarity`, `strength`, `stability`
  còn nguyên (test `test_compact_agent_mind_cuts_audit_keeps_beliefs_and_
  contradictions`).
- `contradiction_ids` giữ khi KHÔNG rỗng ở cả agent_mind và semantic; chỉ bỏ khi
  rỗng (test khẳng định `["b.keep"]` còn, `[]` bị bỏ).
- `compact_semantic_item` giữ `claim/confidence/status/tags`; không cắt nội dung
  nhận thức.
- `SELF_BOOTSTRAP_INSTRUCTION` (root_session_projector.py) yêu cầu đọc cả belief
  trái chiều/giá trị yếu và không chọn top-k — audit-cut này không vi phạm: không
  cắt claim/confidence/tags/polarity/strength, không lọc theo điểm.
- `mind_state` / `persisted_mind_variants` / `actions` KHÔNG bị projection chạm.

## (g) Điều CHƯA xác minh

- Số % cắt đo trên store thật hiện tại (3 record semantic, 10 belief + 12
  preference, 1 episode). Dữ liệu lớn hơn/nhỏ hơn sẽ cho % khác; hướng và độ lớn
  vững (bỏ raw_content lặp + evidence_ids + embedding + rỗng/zero), con số tuyệt
  đối là ảnh của store hiện tại, không phải mọi phiên.
- Chưa đo byte wire của một request portable live (không build app, không gọi
  LLM); đây là đo projection tĩnh qua `project_self_view`, nhất quán với cách đo
  đã dùng cho profile/episode.
- 6 fail không liên quan (action-guard/claim/schema) chưa truy nguyên tận gốc vì
  ngoài phạm vi task; chỉ xác nhận chúng đỏ-sẵn trên base và không do thay đổi này.
