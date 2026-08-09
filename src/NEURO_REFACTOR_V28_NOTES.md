# ERIS Neuro Control V28 — annotated refactor notes

Ngày: 2026-08-09

## Mục tiêu

Refactor này **không cố mô phỏng não** và không dựng thêm một state machine lớn. Mục tiêu là đổi đúng *quyền lực kiến trúc*:

- Subject Core / coalition machinery tiếp tục tạo và chấm các action candidate có provenance.
- Một **fast action gate** chọn winner khi landscape rõ ràng.
- LLM Executive không còn là trọng tài của mọi tick; nó chỉ được gọi như **deliberative specialist** khi margin thấp, uncertainty/conflict/surprise đủ cao.
- Runtime ID (`coalition_id`, `proposal_ref`) không đi qua boundary của deliberator. Model chỉ thấy **choice index tạm thời của frame hiện tại**.
- Provider session của deliberator là **one-shot**, không được trở thành hidden memory của cognition.

Đây là migration phase 1. Chưa thêm learned world model hay predictive latent state; cố nhét tất cả vào một patch sẽ biến “neuro-inspired” thành một hội chợ tên module.

---

## Kiến trúc sau refactor

```text
perception / memory / needs / appraisals
                │
                ▼
          Subject Core
       proposals + coalitions
                │
                ▼
       Workspace broadcast
        (1–3 signal mạnh)
                │
                ▼
       Fast action competition
       salience/value/uncertainty
          │               │
    winner rõ          conflict thật
          │               │
          ▼               ▼
       commit        LLM deliberator
                          │
                   semantic choice index
                          │
                          ▼
                     fast gate binds
                          │
          └───────────────┘
                ▼
          Surface / Body
```

### Invariant quan trọng

> LLM có thể đánh giá semantic consequence, nhưng **không sở hữu runtime identity**.

Nếu provider nhớ một conversation cũ, hallucinate ID, hoặc trả output stale, nó không còn cách nào mang `coalition:f185...` từ frame trước sang frame mới vì ID đó **không xuất hiện trong prompt deliberation**.

---

## File thay đổi

### `cortex/subject/neuro_control.py` — mới

Lớp control nhỏ, gồm:

- `WorkspaceSignal`: một signal bounded có salience/confidence.
- `WorkspaceBroadcast`: chỉ broadcast vài signal thắng + 4 modulator (`surprise`, `precision`, `resource`, `social_drive`).
- `NeuroActionSelector`: action competition kiểu basal-ganglia-inspired, nhưng dùng score hiện có của Subject Core, không tạo policy thứ hai.
- `SelectionResult`: winner là **index local**, không phải ID model phải nhớ.

Các hệ số modulation cố ý nhỏ. Subject Core đã làm phần causal scoring; `neuro_control` chỉ điều chỉnh gain và quyết định khi nào cần deliberation.

### `runtime/ai_orchestrated/executive_cortex.py`

Thay đổi chính:

1. `commit_subject_frame()` chạy fast gate trước.
2. Nếu winner rõ: commit thẳng, **0 LLM call**.
3. Nếu conflict/uncertainty cao: `_deliberate_subject_choice()` gọi LLM.
4. Payload deliberator chỉ có:
   - `choice_index`
   - semantic action kind
   - bounded arguments
   - need/value/uncertainty summaries
   - workspace broadcast
5. Không gửi `coalition_id` hoặc `proposal_ref` cho deliberator.
6. Nếu output model hỏng/out-of-range: quay về **same fast competition**, không đoán ID, không chọn `coalitions[0]` vì một fallback bí ẩn khác.
7. Autonomous routine path cũng đi fast gate trước. Legacy capability/tool planning chỉ còn là đường fallback cho `capability_route` trong phase migration này.

### `runtime/ai_orchestrated/model_router.py`

Thêm 2 lane:

- `neuro_deliberation_required`: direct-user conflict resolution, non-optional.
- `neuro_deliberation`: autonomous conflict resolution, optional/interruptible.

Cả hai tách khỏi generic `executive -> autonomous` mapping.

### `runtime/inference_broker.py`

Thêm policy riêng cho 2 lane trên. Autonomous deliberation vẫn có thể bị preempt khi user chen vào; direct-user deliberation thì không bị shed như background work.

### `llm/client.py`

Chú thích explicit rằng deliberation lanes **không nằm trong persistent Whale2API session lanes**. Hidden provider memory không có semantic authority.

### Tests

- `tests/subject/test_neuro_control_v28.py` — mới.
- Một số test V9/V24/V27 được cập nhật vì chúng trước đây cố tình khẳng định invariant cũ: model chọn exact coalition ID hoặc degraded path phải mang prefix `subject_core_degraded`.

---

## Vì sao đây là “neuro-inspired”, không phải cargo cult

### 1. Global Workspace motif

Lấy motif **distributed specialists → limited broadcast**, không tuyên bố `WorkspaceBroadcast` là “ý thức”. Chỉ vài signal có salience cao được dùng để điều chỉnh action selection thay vì dump toàn bộ state vào một model trung tâm.

Nguồn nền:

- Dehaene & Changeux (2011), *Experimental and theoretical approaches to conscious processing*, Neuron. DOI: `10.1016/j.neuron.2011.03.018`.
- Baars / Franklin / LIDA literature về global workspace và cognitive cycles.

### 2. Basal-ganglia-like action selection

Lấy motif **các action channel cạnh tranh theo salience/utility rồi được gate**, thay vì bắt một symbolic Executive viết bài luận ở mọi tick.

Nguồn nền:

- Gurney, Prescott & Redgrave (2001), *A computational model of action selection in the basal ganglia. I*, Biological Cybernetics. PMID `11417052`.

### 3. Predictive processing / precision

`precision` và `surprise` chỉ là modulators engineering: uncertainty thấp làm competition sắc hơn; uncertainty/surprise cao làm deliberation dễ được gọi hơn. Không tự động “repair semantic” để bảo vệ hypothesis cũ.

Nguồn nền:

- Rao & Ballard (1999), *Predictive coding in the visual cortex*, Nature Neuroscience. DOI `10.1038/4580`.
- Yu & Dayan (2005), *Uncertainty, neuromodulation, and attention*, Neuron. DOI `10.1016/j.neuron.2005.04.026`.

### 4. Memory/replay motif

Patch này **chưa thay memory subsystem**. Nghiên cứu hippocampal replay ủng hộ việc tách working active state khỏi episodic consolidation/replay, nhưng implement phần đó ở patch này sẽ là scope creep.

Nguồn nền:

- Carr, Jadhav & Frank (2011), *Hippocampal replay in the awake state*, Nature Neuroscience.

---

## Những bug được loại bỏ ở cấp representation

| Bug cũ | V28 |
|---|---|
| LLM trả `coalition_id` từ frame cũ | Deliberator **không thấy coalition ID** |
| Mỗi autonomous tick gọi Executive LLM | Clear winner commit bằng fast gate |
| Provider session trở thành hidden executive memory | Deliberator lanes one-shot |
| Invalid Executive output → đoán/remap runtime object | Invalid local index → fast gate winner |
| Model giải thích lại một ranking runtime đã tính | Chỉ gọi model khi competition thực sự ambiguous |
| Executive telemetry vẫn gắn `gemma_executive` dù fast path | Fast action source được ghi `neuro_control:*` |

---

## Cái chưa làm (cố ý)

1. **World model / predicted next-state**: chưa có learned predictor cho hậu quả xã hội/cognitive. Đây là phase tiếp theo có giá trị, nhưng nên được benchmark riêng.
2. **Belief hypothesis distribution thay semantic frame repair hoàn toàn**: chưa rewrite semantic subsystem trong patch này.
3. **Memory activation + replay consolidation redesign**: chưa đụng.
4. **Capability/tool path**: vẫn có legacy Executive logic cho discovery/selection khi coalition yêu cầu capability route.
5. **Learning selector weights**: hiện dùng Subject Core score + weak fixed modulators. Chưa học weights từ outcome history.

Đây là chủ ý: phase 1 phải xóa central-LLM action authority trước. Nếu vừa đổi authority, memory, world model, replay và tools cùng lúc thì khi hành vi thay đổi sẽ không biết hệ nào gây ra, một cách khá truyền thống để biến “kiến trúc elegant” thành khảo cổ học.

---

## Test đã chạy

### Pass trực tiếp liên quan refactor

`51 passed` cho nhóm:

- neuro control mới
- MindLoop
- Subject initiative
- Executive center
- V27 runtime repairs
- chat/executive binding
- executive authority
- DS2API degraded behavior
- executive hardening

Ngoài ra `compileall` cho các package sửa chạy sạch.

### Known baseline gaps, không do V28

1. Full collection có 3 test không import được vì source ZIP thiếu:
   - `tools.package_source`
   - `tools.evaluate_social_plan_activation`
2. Một test `build_executive_client()` fail trên **baseline V2 y hệt** vì manager không dựng được DeepSeek executive worker với fixture Gemma cũ.
3. Một số test PDF/audit khác thiếu các `tools.report_pdf_acceptance`, `tools.evaluate_semantic_paraphrases`, `tools.audit_*` trong source ZIP.

Không tính các lỗi baseline này thành “pass” hay “fail do V28”.

---

## Rollback

`ERIS_NEURO_CONTROL_ENABLED=0` đưa `commit_subject_frame()` về legacy LLM Executive path trong giai đoạn migration. Đây là rollback switch, không nên trở thành hai policy chạy song song lâu dài.

---

## Điều nên quan sát khi chạy thật

Log mới đáng chú ý:

```text
[neuro-control] fast commit ... margin=... entropy=...
[neuro-control] deliberation invited ...
[neuro-control] autonomous action=... source=...
```

Kỳ vọng:

- số lần `autonomous reasoning` từ Executive giảm mạnh;
- latency autonomous giảm ở tick routine;
- không còn log `stale coalition_id` trên neuro path;
- LLM deliberation chỉ xuất hiện khi margin/uncertainty/conflict thực sự cao;
- user interrupt vẫn preempt autonomous deliberation qua broker lane optional.
