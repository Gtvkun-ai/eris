# Đo NỐT các nhánh còn lại của Self prefix + context + system prompt

Ngày đo: theo lần chạy `measure_remaining_self.py` gần nhất.
Phương pháp: đọc-only. Script copy nguyên `memory/core` thật sang temp rồi dựng
`MemoryCognitionCore(temp).load()` — **không ghi đè store thật**. Không gọi LLM,
không build app, không sửa code sản phẩm. Số liệu thô:
[`remaining-self-measurement.raw.json`](remaining-self-measurement.raw.json);
script: [`measure_remaining_self.py`](measure_remaining_self.py).

Ký tự = `len(json.dumps(..., ensure_ascii=False, separators=(",",":")))` — đúng
cách `root_session._prime` serialize `content_json`. Token = `estimate_tokens`
(heuristic chars/3 + overhead; là **ước lượng**, không phải token thật của model).

Report chỉ ghi KÍCH THƯỚC (ký tự/token/số record) + tên key/path; không dán nội
dung cá nhân. Nối tiếp [lần đo trước](real-self-measurement.md) (đã đo nhánh
living_user; ở đây đo NỐT memory_state các lớp khác, context assembler và
system prompt).

## Cách Self prefix được ghép (đối chiếu code)

`_read_self` (root_session.py) ghép bốn nguồn rồi `project_self_view`:
1. `mind_state` = `host.ai_state_reducer.snapshot().to_dict()`
2. `subject_self` = `host.subject_service.self_view()`
3. `memory_state` = `host.memory_state` (= `MemoryCognitionCore.load()`, loại
   `concept_graph`) + `long_term_memory`
4. overlay `living_user.episode_prompt_view()` lên `memory_state.living_user`

`_prime` serialize kết quả thành `content_json` và nhồi vào prefix **mỗi request**.
Xác nhận bằng code: `coordinator_bootstrap` set `self.memory_state =
self._load_memory_state()` → `self.memory_core.load()`; `memory_core =
MemoryCognitionCore(str(memory_root))`. Nên nhánh memory_state đo được ở đây
tái tạo đúng `host.memory_state`.

Root **system prompt** (tham số `system`) = `ROOT_SYSTEM_CORE` (một hằng duy
nhất trong `root_prompt_contract.py`); `agent._system_prompt()` trả thẳng hằng
này. Các prompt STYLE/RUNTIME_RULES/CHAT_RULES... trong `llm/contracts.py` thuộc
đường **Surface writer** (service.py), KHÔNG phải system prompt của Root.

## (a) Bảng kích thước TẤT CẢ nhánh đo được — xếp giảm dần

Đây là **kích-thước-VÀO-PROMPT thật** (sau `project_self_view`), gộp cả
living_user từ lần đo trước. mind_state/subject_self chưa đo được (mục d).

| # | Nhánh Self / khối | Ký tự | Token (ước) | Đo thật? |
|---|---|---:|---:|---|
| 1 | **memory_state.agent_mind** | **7 852** | ~2 621 | đo thật |
| 2 | **memory_state.living_user** | **7 675** | ~2 562 | đo thật (lần trước) |
| 3 | **memory_state.active_state** | **6 198** | ~2 070 | đo thật |
| 4 | memory_state.semantic_memory | 3 389 | ~1 133 | đo thật |
| 5 | memory_state.procedural_memory | 1 119 | ~377 | đo thật |
| 6 | memory_state.relational_memory | 742 | ~251 | đo thật |
| 7 | memory_state.episodic_memory | 506 | ~172 | đo thật |
| - | memory_state các lớp rỗng* | ~2 mỗi key | ~4 | đo thật |
| — | **memory_state TỔNG (projected)** | **27 897** | **~9 303** | đo thật |

\* belief_core, worldview, sociocultural, spatial, temporal_rhythm, body_rhythm,
tom_history, affective_residue, repair, memory_candidate, event_ledger,
self_continuity, homeostatic_baseline — tất cả rỗng (`[]`/`{}` = 2 ký tự) trên
store thật hiện tại.

System prompt tĩnh (đo từ hằng source, độc lập memory):

| Khối prompt (path) | Ký tự | Token (ước) | Đi vào request nào |
|---|---:|---:|---|
| **root_prompt_contract.ROOT_SYSTEM_CORE** | **10 207** | ~3 406 | system prompt Root (mỗi request) |
| root_session_projector.SELF_BOOTSTRAP_INSTRUCTION | 1 225 | ~412 | gói trong bootstrap user message |
| contracts.STYLE_FALLBACK_PROMPT (=PERSONA) | 3 224 | ~1 078 | Surface writer |
| contracts.RUNTIME_RULES_PROMPT | 2 359 | ~790 | Surface writer |
| contracts.DECISION_GBNF | 2 912 | ~974 | grammar (không phải prompt text Root) |
| contracts.CHAT_RULES_PROMPT | 1 565 | ~525 | Surface writer |
| contracts.SELF_IDENTITY_PROFILE_PROMPT | 1 512 | ~508 | Surface/identity |
| contracts.AUTONOMOUS_BEHAVIOR_PROMPT | 1 310 | ~440 | autonomous |
| contracts.INFERENCE_LADDER_PROMPT | 969 | ~327 | Surface writer |
| eris_voice_contract.AUTONOMOUS_VOICE_CORE_V39 | 500 | ~170 | nhúng trong RUNTIME_RULES/AUTONOMOUS |

Lưu ý: `contracts.PROMPT` (5 584) chỉ là `STYLE_FALLBACK + RUNTIME_RULES` ghép
sẵn, không cộng thêm.

## (b) Phần nặng nhất NGOÀI living_user — con số thật

Sau living_user (7,7k), ba phần nặng tiếp theo, tất cả nằm trong `memory_state`:

1. **`agent_mind` — 7 852 ký tự (~2 621 token). NẶNG NHẤT ngoài living_user.**
   Ngang ngửa living_user. Projection KHÔNG cắt gì (raw 7 852 = projected 7 852).
2. **`active_state` — 6 198 ký tự (~2 070 token).** Cũng không bị projection cắt.
3. **`semantic_memory` — 3 389 ký tự (~1 133 token)** với chỉ **3 record** →
   ~1,1k ký tự/record, nặng do mỗi `SemanticMemoryItem.to_dict()` mang đủ field.

Ngoài memory_state, khối tĩnh nặng nhất là **ROOT_SYSTEM_CORE = 10 207 ký tự
(~3 406 token)** — đi vào system prompt mỗi request Root. Đây là khối text cố
định lớn nhất của Root; không phụ thuộc memory.

## (c) Đánh giá dọn được / không cho từng phần nặng

### agent_mind (7 852) — dọn được một phần, cần xem nội dung field

`project_self_view` hiện KHÔNG đụng agent_mind. Nó là `PersistentAgentMindStore.
to_dict()` (file `agent_mind.json` 11 KB đĩa → 7,9k vào prompt). Giống living_user
dạng cũ, nhiều khả năng mang timestamp/metadata/field provenance không lái câu
trả lời. **Cần đọc schema `AgentMind.to_dict()` để xác nhận field nào là audit**
trước khi áp một `compact_*` tương tự. Chưa xác nhận được tỷ lệ cắt từ số đo này
(chỉ đo tổng khối) — ghi nhận là **ứng viên dọn, chưa định lượng phần cắt**.
Ràng buộc `SELF_BOOTSTRAP_INSTRUCTION`: agent_mind có thể chứa belief/giá trị →
nếu cắt phải chỉ bỏ audit (id/epoch/metadata), KHÔNG bỏ belief/stance, để không
vi phạm yêu cầu "Root thấy đủ belief trái chiều".

### active_state (6 198) — dọn được nếu lọc field hiển thị

`ActiveStateSnapshot.to_dict()`. `project_self_view` có một bước nhỏ: nếu
`active_state.metadata.internal_state` trùng `memory.internal_state` thì bỏ bản
trùng — nhưng store thật không có `internal_state` top-level nên bước này không
kích hoạt. 6,2k là state phiên (goal/project/task/arc + metadata). Nhiều field
có thể là mốc thời gian/telemetry. **Ứng viên dọn**, cùng kiểu audit-cut; chưa
định lượng phần cắt từ số đo tổng. Không phải belief → cắt audit không đụng ràng
buộc belief.

### semantic_memory (3 389, chỉ 3 record) — dọn được theo field/to_dict

~1,1k ký tự/record cho 3 record là dày. `SemanticMemoryItem.to_dict()` nhiều
khả năng mang embedding-free metadata, evidence, timestamp. **Ứng viên dọn** cùng
pattern. Nhưng vì chỉ 3 record, tiết kiệm tuyệt đối nhỏ (<2k); ưu tiên thấp hơn
agent_mind/active_state. Lưu ý phình tương lai: semantic sẽ lớn theo số record.

### ROOT_SYSTEM_CORE (10 207) — dọn được nhưng là policy, rủi ro hành vi

Đây là text cố định mô tả policy/nhân vật Root. Cắt được về mặt token nhưng
**đây là quyết định sản phẩm về hành vi/cá tính**, không phải audit. Nhiều câu
nhắc đúng các yêu cầu user đã nêu (receipt thật, không tự đếm lượt, cá tính, LaTeX,
không tạo floor/budget...). Rút gọn có thể làm mất ràng buộc hành vi. **Không
thuộc phạm vi "dọn token an toàn"**; nếu muốn giảm, phải là lựa chọn có chủ đích
và đo lại chất lượng, không phải cắt cơ học.

### Các lớp memory rỗng — không có gì để dọn (đã ~2 ký tự)

## (d) CHƯA đo được (kèm lý do)

- **mind_state:** cần `ai_state_reducer.snapshot().to_dict()` từ
  `RuntimeCoordinator` sống. `MemoryCognitionCore.load()` **không** phát key
  `ai_orchestrated_state` (bản persisted của mind), và `save()` chỉ ghi
  active_state + agent_mind — nên KHÔNG có snapshot mind_state độc lập trong
  `memory/core` để đọc tĩnh. Ước trần lý thuyết: không có model để đọc schema
  một cách an toàn mà không dựng runtime → **không nâng thành con số**.
- **subject_self:** cần `host.subject_service.self_view()` từ SubjectService
  sống (`cortex/subject/service.py`). Không có file self_view dưới memory/core.
  Chưa đo.

Hai nhánh này là lý do chính khiến con số đo được (bên dưới) còn thiếu so với
~79k user báo.

## (e) Ước tổng Self prefix thật so với 79k user báo

Cộng các nhánh đo được của **Self prefix** (không tính system prompt vì nó là
message `system` riêng, không nằm trong `content_json`):

| Thành phần Self prefix | Ký tự |
|---|---:|
| memory_state (projected, gồm living_user) | 27 897 |
| SELF_BOOTSTRAP_INSTRUCTION (bọc trong bootstrap user msg) | 1 225 |
| **Cộng phần đo được** | **~29 122** |
| mind_state | CHƯA ĐO |
| subject_self | CHƯA ĐO |

Phần đo được ≈ **29k ký tự**. User báo Self prefix ~**79k**. Chênh ~**50k ký tự**
nằm ở **mind_state + subject_self** (chưa đo được). Vì memory_state đã đo gần như
trọn (chỉ 27,9k, và các lớp còn lại đều rỗng), phần nặng còn thiếu **gần như
chắc chắn là mind_state và subject_self** — hai nhánh runtime-only. Đây là
suy luận từ phần dư, không phải số đo trực tiếp; cần một lần đo runtime sống để
chốt con số.

Nếu cộng thêm system prompt Root (ROOT_SYSTEM_CORE 10,2k) vào toàn request thì
request ≈ Self prefix (79k) + system (10,2k) + bootstrap wrapper + history
window + runtime_context/current step — khớp hướng với con số ~140k ký tự user
báo cho toàn request. Các phần context lượt (history/grounding) đo ở mục dưới.

## (f) Context hiện tại (ngoài Self) — trần đọc từ code

Từ `context_assembler.py` (các khối + trần kích thước; đây là **trần-lý-thuyết**,
không phải đo-live của một request cụ thể):

| Khối context | Trần trong code | Ghi chú |
|---|---|---|
| world_text (`_world_context`) | `[:20000]` | grounding/world |
| vision prompt_context | không cap tại chỗ | nằm trong grounding |
| contract_repair_context | `[:12000]` | repair |
| grounding tổng (`assemble`) | `[:32000]` | ghép world+vision+clock+addressing |
| memory_context (typed) | `[:32000]`, token_budget 6000, max_lines 64 | lane nền |
| `compile_public_reply_context` | `total_limit=96000`, budget_mode "wide" | trần tổng |
| interrupt_context | `[:6000]` | |
| engagement_context (json) | `[:8000]` | |
| discourse_context | `[:16000]` | |
| affective_voice_context | `[:8000]` | |
| previous_public_excerpt | `[-6000:]` | lượt public trước |
| conversation_status.open_loops | `[:5]` mỗi cái `[:500]` | ~2,5k trần |
| character portrait render | `max_chars=6000` | personality |

Các con số user báo (grounding ~6,1k, 10 lượt trước ~10,6k, status ~4,5k) là
**đo-live của một request** — nằm dưới các trần trên và không mâu thuẫn. Để đo
chính xác cần runtime sống; ở đây chỉ liệt kê trần đọc được từ code như yêu cầu.

Trong Root prefix, history lượt trước đi qua `project_root_messages` với
`ERIS_ROOT_SESSION_WINDOW_PAIRS=12` (tối đa 2×12 = 24 turn thô), mỗi turn là
`content` gốc; đây là nguồn "10 bản ghi lượt trước" phình theo số lượt.

## Tóm tắt một dòng

Ngoài living_user (7,7k), phần nặng nhất của Self prefix là **agent_mind (7,9k)**
và **active_state (6,2k)** — cả hai `project_self_view` chưa cắt, là ứng viên
dọn tiếp theo (cùng kiểu audit-cut đã áp cho profile/episode, giữ belief để không
vi phạm `SELF_BOOTSTRAP_INSTRUCTION`). memory_state đo được tổng **~27,9k ký tự**;
cộng bootstrap ≈ **29k**, còn thiếu ~50k so với 79k user báo — phần thiếu **gần
như chắc chắn là mind_state + subject_self (runtime-only, chưa đo được)**.
System prompt Root là **ROOT_SYSTEM_CORE 10,2k** (không phải 14k; 14k user báo
gồm cả prompt đường Surface), là policy nên không nên cắt cơ học.
