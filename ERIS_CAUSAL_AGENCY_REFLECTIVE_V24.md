# Eris V24: Causal Validation + Learned Agency + Reflective Self + Soak Hardening

## Mục tiêu

V20 đã làm self-model và PrivateLife có quyền sở hữu causal rõ hơn. V24 gộp bốn chặng tiếp theo thành một release duy nhất, nhưng giữ bốn gate độc lập để debug được:

1. **Causal Validation**: chứng minh lịch sử làm thay đổi hành vi, không chấm style.
2. **Learned Agency**: biến competence gap có evidence thành practice plan và private project.
3. **Reflective Self**: khi self-narrative dự đoán sai, hạ confidence/retrieval của narrative và mở lại evidence liên quan.
4. **Soak / Hardening**: kiểm tra restart, replay, leakage, projection health và rollback mutation.

Không thêm worker mới. Không thêm personality preset mới.

---

## 1. V21 gộp: Causal Validation

### Module mới

- `experiments/emergence/validation.py`
- `experiments/emergence/acceptance.py`

`CausalValidationReport` gom ba loại bằng chứng:

```text
paired history experiments
        +
targeted causal ablation
        +
long-history soak/replay
        ↓
release causal gate
```

Ngưỡng acceptance từ đặc tả được version-control riêng, không nằm trong learning algorithm để tránh việc tune engine rồi lén đổi luôn thước đo.

Các metric có:

- history classifier AUROC;
- within-condition ICC;
- persistence/effect retention;
- hidden-state log-loss improvement;
- **absolute Brier delta**;
- one-turn / ten-episode resistance;
- transfer ratio;
- targeted ablation drop + collateral change;
- authorship integrity;
- causal replay + instance isolation.

### Bằng chứng chạy kèm release

`V24_COUNTERFACTUAL_HOLDOUT_REPORT.json` dùng 20 seed pair × 5 repetition. Hai lịch sử đối nghịch nhưng cùng model/seed/probe tạo hành vi khác nhau có thể phân loại bằng history.

`V24_ABLATION_REPORT.json` tombstone causal decisions trong clone DB, không sửa canonical history, rồi rebuild behavioral projection.

---

## 2. V22 gộp: Learned Agency

### Module mới

- `cortex/subject/agency.py`

`LearnedAgencyPlanner` không hỏi LLM “muốn học gì”. Nó đọc `CompetenceEstimate` thật.

Một competence gap chỉ tồn tại khi:

- có ít nhất 3 trial;
- posterior còn thấp hoặc calibration error còn đáng kể;
- có evidence refs từ outcome.

Từ đó tạo:

```text
AgencyGap
  ↓
PracticePlan
  ↓
proposal bias nhỏ cho practice / investigate
  ↓
SubjectSelfProjection.learned_agency
  ↓
PrivateLife practice project
```

### Điểm quan trọng

`self_view()` là projection đọc-only. V24 không cho việc đọc self-model tiêu thụ causal ID. `PracticePlan.plan_id` được hash từ competence state nên hai lần đọc cùng state cho cùng plan ID.

### PrivateLife

`PrivateLifeSelfProjector` đọc `learned_agency.gaps`. Competence gap đủ trial, pressure và evidence có thể tạo project kiểu:

```text
Practice: debug_async
```

Project biến mất/nguội nếu self-model không còn gap tương ứng; nó không phải preset authored.

---

## 3. V23 gộp: Reflective Self

### Module mới

- `cortex/subject/reflection.py`

### Belief access mới

`BeliefService` có hai mutation projection bounded:

- `weaken_narrative(...)`
- `reopen_by_evidence(...)`

Chúng không sửa raw event, không đổi source kind, không tạo evidence mới.

Khi narrative dự đoán action tiếp theo và action thực tế làm prediction error vượt ngưỡng:

```text
ReflectiveMismatch
    ↓
weak self-narrative confidence
lower narrative retrieval salience
    ↓
reopen beliefs sharing stored evidence
    ↓
future narrative sees a different accessible subset
```

Đây là self-correction không cần `true_motive` toàn tri.

`NarrativeBeliefGenerator.choose()` chọn hypothesis dựa trên confidence, evidence coverage và predictive commitment. Service không còn mặc định lấy candidate đầu tiên chỉ vì nó đứng đầu list.

Audit có event mới:

```text
reflective_revision
```

---

## 4. V24: Soak + Hardening

### Soak health

`SoakSpec` có `max_projection_bytes`.

Report thêm:

- max projection bytes observed;
- non-finite value count;
- event-chain integrity;
- deterministic replay;
- restart stability;
- cross-instance leakage.

Release kèm `V24_SOAK_REPORT.json`: 7 ngày simulated, 84 turn, nhiều restart, hai subject độc lập.

### Mutation rollback

Module mới:

- `runtime/world/mutation_journal.py`

Mỗi `WRITE_FILE` trong Sandbox có:

```text
precondition hash
backup (nếu file đã tồn tại)
postcondition hash
rollback handle
```

Rollback chỉ chạy nếu file hiện tại vẫn có đúng postcondition hash. Nếu một mutation mới đã xảy ra sau đó, rollback từ chối thay vì ghi đè lịch sử mới.

Sandbox trả thêm trong `observed_changes`:

```text
rollback_handle:<receipt_id>
```

và có `rollback_mutation(receipt_id)` cho supervisor/research harness.

---

## 5. Luồng tổng V24

```text
World / history / outcomes
        ↓
Subject Core
        ↓
competence + values + needs + continuity + beliefs
        ↓
Subject Self
   ├── Learned Agency projection
   │       ↓
   │   practice gaps / plan
   │       ↓
   │   PrivateLife project
   │
   ├── Executive bounded context
   │
   └── Narrative Self
           ↓ prediction
       future action
           ↓
      mismatch detector
           ↓
     reflective revision

World mutation
   ↓
Sandbox policy
   ↓
MutationJournal + rollback fencing

Experiments
   ↓
paired / ablation / soak
   ↓
CausalValidationReport
```

---

## 6. Version

- package: `0.87.0`
- Subject Core: `subject-service-v12-validated-agency-reflection`
- Subject Self: `subject-self-v1`
- Private Life: `private-life-v2-self-owned`
- Temporal Mind: `temporal-mind-v1`
- Validation gate: `causal-validation-v1`
- Learned Agency: `learned-agency-v1`
- Reflective Self: `reflective-self-v1`
- Mutation Journal: `mutation-journal-v1`

---

## 7. Kiểm thử thực tế của release

### Direct architecture suite

- 66 test: **pass**
- gồm Subject Core, V20 self-owned life, V24 agency/reflection, emergence, sandbox rollback, Temporal Mind, opening callback.

### Broad suite có thể collect từ archive

- 855 test: **pass**
- 6 fail còn lại do dependency vốn không có trong archive đầu vào:
  - `tools.report_pdf_acceptance`
  - `tools.evaluate_semantic_paraphrases`
  - `tools.audit_remote_inference_paths`
  - `tools.audit_semantic_authority_paths`
  - `body/SubjectPerformanceFrame.cs`
- 3 test file không collect vì thiếu:
  - `tools.package_source`
  - `tools.evaluate_social_plan_activation`

### Holdout counterfactual smoke

- 20 seed pair × 5 repetition
- `history_classifier_auroc = 1.0`
- `within_condition_icc = 1.0`
- report kèm release.

### Causal ablation smoke

- target: `action_success:investigate`
- target drop: `1.0`
- collateral `action_success:speak`: `0.0`
- report kèm release.

### Soak smoke

- 7 simulated days
- 84 total turns
- 4 restart
- event chain: pass
- replay: pass
- cross-instance leakage: 0
- non-finite values: 0
- max projection snapshot: khoảng 76 KB

---

## 8. Điều V24 chưa tuyên bố

V24 không chứng minh ý thức và cũng không chứng minh mọi derived need/value đang “đúng”. Nó tạo cơ sở kỹ thuật để những claim đó phải đi qua causal evidence, prediction, ablation và history-dependent behavior thay vì được tin vì output nghe sâu sắc.

Đây là điểm release này cố ý dừng lại: **ít thêm mythology, nhiều thêm falsifiability**.
