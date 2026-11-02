# Implementation Plan — Audit-cut Self prefix: agent_mind + active_state + semantic_memory

Mục tiêu: lặp lại pattern audit-cut đã merge (commit `77fc3a13`, `compact_profile` /
`compact_episode` trong `self_prompt_view.py`) sang BA nhánh còn nặng của khối Self vào
prompt Root — `agent_mind` (7.852 ký tự), `active_state` (6.198), `semantic_memory`
(3.389). CHỈ cắt ở đường projection (`project_self_view`), KHÔNG đụng `to_dict()` của
store/persistence, GIỮ nội dung thật (belief/preference/claim) và GIỮ belief trái chiều
(`contradiction_ids` khi không rỗng).

## Quyết định thiết kế (ghi ngắn, grounded trong code đã đọc)

- **Nơi sửa duy nhất:** `src/runtime/conversation/self_prompt_view.py`. Thêm ba hàm thuần
  `compact_agent_mind`, `compact_active_state`, `compact_semantic_item`, và gọi chúng
  trong `project_self_view` trên đúng ba nhánh `memory_state.agent_mind` /
  `memory_state.active_state` / `memory_state.semantic_memory`. Đây là chỗ sạch nhất:
  `_read_self` (root_session.py:35) kết thúc bằng `return project_self_view(result)`, nên
  mọi nhánh memory_state đi qua một cửa. Persistence tách biệt: `store.save()` dùng
  `AgentMind/ActiveStateSnapshot/SemanticMemoryItem.to_dict()` (đã đọc:
  `cortex/agent_mind_persistence.py` `PersistentAgentMindStore.to_dict`,
  `memory/active_state_snapshot.py` `ActiveStateSnapshot.to_dict`,
  `memory/semantic_memory.py` `SemanticMemoryItem.to_dict`), KHÔNG đi qua
  `project_self_view`. Sửa projection không chạm file lưu.
- **Idempotent bằng marker `projection_schema`** y như tiền lệ: mỗi nhánh gắn marker riêng
  (`eris.agent_mind.v1`, `eris.active_state.v1`, `eris.semantic_item.v1`), gặp lại thì
  return sớm. Lý do bắt buộc: `state_difference` (self_prompt_view.py:22, alias `_changed`
  trong root_session.py) so bootstrap-self với self-now; cả hai đều đã qua
  `project_self_view`, nên delta tính trên hình-dạng-đã-gọn. Marker chặn mọi khả năng
  hàm chạy hai lần tạo phantom delta.
- **deepcopy, không mutate input** y như `compact_profile`/`compact_episode`.
- **agent_mind:** `to_dict()` trả `{schema_version, updated_at, beliefs:{key→rec},
  preferences:{key→rec}, habits:{key→rec}, last_feedback_events:[...]}` (đã đọc store thật
  11 KB → 7.852 ký tự vào prompt). Cắt theo dạng dict-of-records, KHÔNG phải list.
- **active_state:** cắt theo "bỏ rỗng/zero/default, giữ field khác mặc định". 6,2k gần như
  toàn bộ nằm trong `metadata.internal_state` (xác nhận trên store thật
  `active_state_snapshot.json`: top-level toàn rỗng, nặng là internal_state với hàng chục
  `last_*`/`recent_*` rỗng, 9 `mental_processes`, `desire_dynamics`/`goal_persistence`/
  `conversation_dynamics`/`relationship_dynamics`/`action_memory` phần lớn 0).
- **semantic_memory:** `project_self_view` nhận LIST các `SemanticMemoryItem.to_dict()`
  (memory_cognition.py:486 `"semantic_memory": [item.to_dict() ...]`). Cắt per-item,
  đặc biệt bỏ `metadata.raw_content` (xác nhận trên store thật: trùng y hệt `claim`).

## Điều CHƯA xác minh (ghi rõ)

- Con số cắt được cho ba nhánh **chưa định lượng** từ số đo hiện có (báo cáo chỉ đo tổng
  khối, không tách audit-vs-telling như đã làm cho profile). Bước verify dùng
  `measure_remaining_self.py` để đo lại sau khi sửa và chốt % cắt thật.
- `mind_state` và `subject_self` là runtime-only, KHÔNG nằm trong phạm vi task này và
  KHÔNG đo được tĩnh — không đụng.
- Không có consumer nào trong `root_session_projector.py` đọc trực tiếp các field con của
  `active_state`/`agent_mind` (grep xác nhận 0 match); nhưng chưa chạy toàn hệ runtime live
  để loại trừ consumer động khác. Quy tắc an toàn khi không chắc: GIỮ field.

---

## Các bước

- [ ] 1. Thêm `compact_agent_mind(agent_mind)` vào `self_prompt_view.py`.
      Chữ ký: `def compact_agent_mind(agent_mind: Mapping[str, Any]) -> dict[str, Any]`.
      Hành vi: `result = deepcopy(dict(agent_mind))`; nếu `result.get("projection_schema")
      == "eris.agent_mind.v1"` → return sớm (idempotent). Với mỗi record trong
      `result["beliefs"]` (dict key→record) và `result["preferences"]` (dict key→record):
      CẮT các field audit khi áp dụng — belief: `created_at`, `updated_at`, `last_seen`,
      `source_ids`, `positive_evidence_count`, `negative_evidence_count`, `decay_rate`, và
      `contradiction_ids` CHỈ khi rỗng (`[]`); preference: `created_at`, `updated_at`,
      `last_reinforced`, `source`. GIỮ: belief → `claim`, `confidence`, `tags`, `domain`,
      `key` (nếu có), `contradiction_ids` khi KHÔNG rỗng (belief trái chiều = yêu cầu sản
      phẩm); preference → `key`, `polarity`, `strength`, `stability`, `tags`. Bỏ
      `habits` nếu `== {}` và `last_feedback_events` nếu `== []`. Giữ `schema_version`,
      bỏ `updated_at` top-level (epoch audit). Gắn `result["projection_schema"] =
      "eris.agent_mind.v1"`. Không cắt nếu `beliefs`/`preferences` không phải dict (phòng
      thủ: return result nguyên).
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` vẫn
      pass (chưa có test mới, chỉ đảm bảo không vỡ import/hiện có).

- [ ] 2. Thêm `compact_active_state(active_state)` vào `self_prompt_view.py`.
      Chữ ký: `def compact_active_state(active_state: Mapping[str, Any]) -> dict[str, Any]`.
      Hành vi: `result = deepcopy(dict(active_state))`; marker sớm
      `"eris.active_state.v1"`. Định nghĩa helper nội bộ
      `_is_empty_default(value) -> bool`: True khi value là `""`, `[]`, `{}`, `0`, `0.0`
      (dùng `value == 0 and not isinstance(value, bool)` để KHÔNG coi `False`/`True` là 0 —
      bool giữ nguyên), hoặc `None`. Đệ quy làm sạch dict/list: với mọi dict (kể cả lồng
      sâu trong `metadata.internal_state`, `mental_processes`, `desire_dynamics`,
      `goal_persistence`, `conversation_dynamics`, `relationship_dynamics`, `action_memory`)
      xóa key mà value `_is_empty_default`; với dict con sau khi làm sạch trở nên `{}` thì
      cũng xóa khỏi cha. GIỮ mọi field có giá trị khác mặc-định-rỗng (ví dụ `trust=0.25`,
      `valence=0.02`, `curiosity=0.576`, `version`, các string không rỗng như
      `attachment_drift="guarded"`, `rhythm_phase="settled"`, `mode="settled"`). Quy tắc an
      toàn: chỉ bỏ rỗng/zero/None; nếu không chắc thì giữ. Gắn marker. KHÔNG đụng các field
      top-level có nghĩa nếu khác rỗng (`current_goal` khi có giá trị, `session_arc` khác
      `"unknown"` thì giữ — lưu ý `"unknown"` là default của `session_arc` nên có thể bỏ;
      an toàn: coi `session_arc == "unknown"` là default-rỗng và bỏ).
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` pass.

- [ ] 3. Thêm `compact_semantic_item(item)` vào `self_prompt_view.py`.
      Chữ ký: `def compact_semantic_item(item: Mapping[str, Any]) -> dict[str, Any]`.
      Hành vi: `result = deepcopy(dict(item))`; marker sớm `"eris.semantic_item.v1"`.
      CẮT top-level: `evidence_ids`, `first_seen_at`, `updated_at`, `decay_policy`,
      `observations`, `source`; và `contradiction_ids` CHỈ khi rỗng. Trong `result["metadata"]`
      (dict) CẮT: `raw_content` (trùng `claim` — xác nhận trên store thật),
      `embedding_text_hash`, `embedding_version`, `access_count`, `last_accessed_at`,
      `fact_profile_evidence`, `reason`, `source` (lặp), `domain` (lặp top-level), `aliases`
      khi rỗng. GIỮ top-level: `id`, `claim`, `confidence`, `status`, `tags`, `domain`, và
      `contradiction_ids` khi KHÔNG rỗng (belief trái chiều). GIỮ trong metadata qualifier
      ngữ nghĩa nhẹ: `fact_key`, `importance`. Nếu `metadata` sau khi cắt thành `{}` thì bỏ
      luôn key `metadata`. Gắn marker. Return nguyên nếu `item` không phải Mapping.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` pass.

- [ ] 4. Gọi ba hàm compact mới trong `project_self_view` (self_prompt_view.py, trong khối
      `memory` đã có, sau đoạn xử lý `living_user`/`active_state.metadata.internal_state`
      hiện tại nhưng TRƯỚC khối `ai_orchestrated_state`).
      - `agent_mind`: nếu `isinstance(memory.get("agent_mind"), Mapping)` →
        `memory["agent_mind"] = compact_agent_mind(memory["agent_mind"])`.
      - `active_state`: SAU bước hiện có pop `metadata.internal_state` trùng
        `memory["internal_state"]` (giữ nguyên bước đó), thêm: nếu
        `isinstance(memory.get("active_state"), dict)` →
        `memory["active_state"] = compact_active_state(memory["active_state"])`. (Thứ tự:
        pop-trùng chạy trước để không cắt nhầm; compact_active_state idempotent nên chạy
        sau an toàn.)
      - `semantic_memory`: nếu `isinstance(memory.get("semantic_memory"), list)` →
        `memory["semantic_memory"] = [compact_semantic_item(it) if isinstance(it, Mapping)
        else it for it in memory["semantic_memory"]]`.
      Files: `src/runtime/conversation/self_prompt_view.py`
      Verify: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` pass
      (đặc biệt `test_every_request_can_reconstruct_current_self_and_context`,
      `test_self_view_removes_debug_and_clones_without_changing_owner`,
      `project_self_view(view) == view` idempotency).

- [ ] 5. Thêm regression test mới trong `test_root_prompt_cleanup.py` cho ba hàm.
      Import thêm `compact_agent_mind, compact_active_state, compact_semantic_item`.
      Ba test, mỗi cái theo mẫu `test_compact_profile_cuts_audit_keeps_telling_and_qualifiers`:
      (a) `test_compact_agent_mind_cuts_audit_keeps_beliefs_and_contradictions`: dựng input
      giống `PersistentAgentMindStore.to_dict()` với >=1 belief có `contradiction_ids`
      không rỗng và >=1 belief rỗng; assert `claim/confidence/tags/polarity/strength/
      stability` CÒN; `created_at/updated_at/last_seen/source_ids/evidence counts` BỊ CẮT;
      `contradiction_ids` CÒN khi không rỗng và BỊ bỏ khi rỗng; `habits`/`last_feedback_events`
      rỗng bị bỏ; input không bị mutate (`source == before`); idempotent
      (`compact_agent_mind(projected) == projected`).
      (b) `test_compact_active_state_drops_empty_zero_keeps_meaningful`: dùng payload giống
      `active_state_snapshot.json` thật (có `trust=0.25`, `valence=0.02`, nhiều `last_*=""`,
      `silence_ticks=0`, `goal_persistence.status="empty"`); assert field khác-mặc-định
      CÒN (trust, valence, curiosity, các string khác rỗng), field rỗng/zero BỊ CẮT,
      `False` KHÔNG bị coi là 0 (nếu có field bool False có nghĩa — hoặc test rõ bool giữ
      nguyên kiểu), input bất biến, idempotent.
      (c) `test_compact_semantic_item_drops_raw_content_dupe_and_audit`: dùng item giống
      store thật (metadata.raw_content == claim); assert `raw_content` BỊ CẮT,
      `evidence_ids/embedding_*/access_count/last_accessed_at/fact_profile_evidence` BỊ CẮT,
      `claim/confidence/status/tags` CÒN, `fact_key`/`importance` CÒN, `contradiction_ids`
      giữ khi không rỗng, input bất biến, idempotent.
      Files: `src/tests/conversation/test_root_prompt_cleanup.py`
      Verify: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q` —
      tất cả test (cũ + 3 mới) pass.

- [ ] 6. Chạy regression rộng quanh đường Self/projection để chắc không vỡ.
      Files: (không sửa; chỉ chạy)
      Verify: `python -m pytest src/tests/conversation -q` pass (bao gồm
      `test_self_to_root_projection_v12.py`, `test_root_session_bootstrap_v12.py`,
      `test_root_session_projector_v1.py`, `test_architecture_v12.py`). Nếu có test đỏ
      KHÔNG liên quan tới thay đổi (đã đỏ từ trước), ghi rõ trong findings và đối chiếu bằng
      cách chạy cùng test trên HEAD trước khi sửa.

- [ ] 7. Đo lại kích thước vào-prompt thật để định lượng phần cắt (đọc-only, không ghi store).
      Chạy script đo có sẵn; nó copy `memory/core` thật sang temp, dựng
      `MemoryCognitionCore(temp).load()`, chạy qua `project_self_view` đã sửa và in ký tự
      per-key. So `projected_per_key` MỚI với báo cáo cũ (agent_mind 7.852, active_state
      6.198, semantic_memory 3.389).
      Files: (không sửa product code) `.agents/tasks/eris-token-growth/measure_remaining_self.py`
      Verify: `python .agents/tasks/eris-token-growth/measure_remaining_self.py` chạy xong,
      đọc `.agents/tasks/eris-token-growth/remaining-self-measurement.raw.json`: ba key
      `agent_mind`/`active_state`/`semantic_memory` NHỎ HƠN rõ rệt so với số cũ, trong khi
      tổng `projected_total` giảm tương ứng; các key khác không đổi. Ghi số mới + % cắt vào
      findings (và cập nhật `remaining-self-measurement.md` nếu muốn, nhưng không bắt buộc
      sửa tài liệu). KHÔNG coi script này là verification thay cho pytest — nó là phép đo
      bổ sung.

## Checklist ràng buộc sản phẩm (phải đúng trước khi coi là xong)

- [ ] KHÔNG sửa `to_dict()` của `PersistentAgentMindStore`/belief/preference,
      `ActiveStateSnapshot`, `SemanticMemoryItem` hay bất kỳ file store/persistence nào.
      Chỉ `self_prompt_view.py` + file test thay đổi. (Xác nhận bằng `git diff --name-only`.)
- [ ] KHÔNG đụng nhánh one-shot `render_prompt_context` / `render_context`.
- [ ] KHÔNG cắt nội dung belief/preference/claim: `claim`, `confidence`, `tags`,
      `polarity`, `strength`, `stability` còn nguyên.
- [ ] GIỮ belief trái chiều: `contradiction_ids` còn khi KHÔNG rỗng ở cả agent_mind và
      semantic.
- [ ] Idempotent: `compact_*(compact_*(x)) == compact_*(x)` và
      `project_self_view(project_self_view(s)) == project_self_view(s)` (test bước 5 + 4).
- [ ] deepcopy: input gốc không bị mutate (assert `source == before` trong mỗi test).
- [ ] Delta vẫn đúng: `test_every_request_can_reconstruct_current_self_and_context` xanh
      (delta tính trên hình-dạng-đã-chiếu, marker chặn phantom delta).

## Lệnh build/test của dự án (đã xác nhận)

- Test runner: `pytest` (pytest.ini: `pythonpath = src .`, `testpaths = src/tests`).
- Chạy nhóm trọng tâm: `python -m pytest src/tests/conversation/test_root_prompt_cleanup.py -q`
- Chạy rộng vùng conversation: `python -m pytest src/tests/conversation -q`
- Đo token (read-only): `python .agents/tasks/eris-token-growth/measure_remaining_self.py`
- Python 3.12.10, venv, Windows PowerShell. (Lưu ý môi trường: terminal có thể echo lặp
  ký tự lệnh và báo exit code ảo; đọc stdout thật để xác nhận kết quả pytest, đừng tin
  riêng exit code nếu output cho thấy test đã chạy.)
