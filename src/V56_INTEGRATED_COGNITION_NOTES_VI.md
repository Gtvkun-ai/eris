# Eris V56 - Kiến trúc nhận thức tích hợp theo bản lớn trong PDF

## Mục tiêu

V56 hiện thực phần **Kiến trúc tích hợp đề xuất** của PDF theo nguyên tắc không tạo thêm một “bộ não song song”. Các authority đã có trong source (Subject Core, Need, relational, initiative, affect, memory, competence, narrative, Neuro) được nối bằng causal state có thể kiểm toán.

Luồng mục tiêu:

`Observation -> Substrate/Internal State -> Appraisal theo Goal -> Need/Modulation -> Persistent Intention -> Coalition/Neuro -> Decision -> Action -> Outcome -> Learning/Memory/Hindsight`

## 1. Appraisal theo mục tiêu có dấu

Trước V56, `goal_relevance` chỉ cho biết một sự kiện quan trọng tới đâu. Nó không phân biệt sự kiện đó **giúp** hay **cản** mục tiêu. V56 thêm:

- `goal_congruence`: `[-1, 1]`, âm là đe doạ/cản goal, dương là hỗ trợ goal.
- `goal_progress_delta`: `[-1, 1]`, ước lượng tiến/lùi của goal.
- `affected_goal_ids`: provenance tới persistent intention/goal liên quan.

Nguồn ưu tiên:

1. Dữ liệu explicit từ ingress (`goal_congruence`, `goal_progress_delta`).
2. Outcome thật của persistent intention vừa được user phản hồi.
3. Prior có dấu của event type đã chuẩn hoá (`task_failure`, `shared_success`, `promise_broken`...).
4. Nếu không đủ evidence thì giữ `0.0`, không đoán sentiment thành goal state.

## 2. Need modulation theo goal

Need pressure không còn tăng đơn thuần vì event vừa quan trọng vừa bất ngờ.

- Congruence âm tăng pressure/urgency.
- Congruence dương tạo relief và tăng opportunity.
- Tất cả vẫn bị saturation trong `[0, 1]`.

Điều này tránh lỗi “user vừa xác nhận thành công nhưng competence pressure lại tăng vì event rất salient”.

## 3. Appraisal -> Affect modulation

V56 nối Subject Appraisal sang `AffectiveDynamicsRuntime` bằng event idempotent:

`cogevt:appraisal:<appraisal_id>`

Delta chỉ dùng trạng thái của Eris: goal congruence, progress, uncertainty, controllability, relational/identity significance. Nó **không** suy diễn cảm xúc của user.

Ví dụ:

- goal threat + low controllability -> anxiety tăng nhẹ;
- goal threat + high controllability -> irritation/friction tăng nhẹ;
- goal support/progress -> valence/delight tăng nhẹ.

Social appraisal V43 vẫn chạy riêng cho tín hiệu interaction. V56 chỉ thêm modulation goal-relative sau Subject commit.

## 4. Unified Decision Ledger

File mới `cortex/subject/decision_ledger.py` tạo một projection kiểm toán xuyên suốt causal loop.

Mỗi record giữ:

- observation/frame identity;
- state trước appraisal;
- state sau appraisal: substrate, needs, modulators, persistent intentions, relational projection, belief/value refs;
- decision + Executive commit summary;
- outcome + learning receipt;
- state sau learning.

Ledger **không** lưu chain-of-thought và **không** có quyền chọn hành động. Nó chỉ chụp state từ authority hiện hữu.

Ledger được persist bounded trong `inner_life` projection và restore qua restart.

## 5. Invariants / Acceptance

File mới `cortex/subject/acceptance.py` kiểm tra tối thiểu:

- mỗi observation có một trace;
- goal congruence/progress luôn hữu hạn trong `[-1, 1]`;
- need/modulator luôn trong `[0, 1]`;
- outcome không được xuất hiện trước decision;
- state snapshot phải có substrate provenance.

CLI:

```bash
python tools/v56_integrated_acceptance.py subject_state.json --strict
```

## 6. Mapping với 11 lĩnh vực trong PDF

| Lĩnh vực PDF | Nền hiện có + phần V56 nối thêm |
|---|---|
| Motivational architecture | `subject/needs.py`, initiative, coalition; V56 thêm signed goal modulation |
| Computational appraisal/affect | `SubjectAppraisal`, `appraisal_engine.py`; V56 thêm congruence/progress và bridge sang affect |
| Relational dynamics | `subject/relational.py`, relationship state được snapshot trong ledger |
| Theory of Mind/user model | epistemic/private user model vẫn là authority; ledger chỉ giữ refs/projection bounded |
| Curiosity | initiative/tutor curiosity giữ nguyên; uncertainty/surprise có mặt trong modulator snapshot |
| Autobiographical memory/identity | narrative, continuity, beliefs, values; outcome->learning nằm trong cùng trace |
| Metacognition | competence prediction error, reflective mismatch, cognitive review vẫn nằm trong causal loop |
| Persistent intentions | lifecycle `PENDING -> EXPRESSED -> AWAITING_OUTCOME -> SATISFIED/REVISED`; V56 đưa outcome lifecycle vào appraisal |
| Open-ended learning | value/derived need/competence consolidation được ledger ghi sau outcome |
| Embodied/interoception | affect state tiếp tục là nguồn cho voice/body; V56 thêm goal appraisal modulation |
| Dynamical systems/control | signed score + saturation + idempotency + invariant evaluator chống runaway |

## 7. Test V56

Test mới: `tests/subject/test_integrated_cognition_v56.py`

Bao phủ:

- positive goal support tạo pressure thấp hơn goal threat;
- causal appraisal có signed relation;
- persistent intention outcome trở thành appraisal của đúng user turn;
- full decision ledger đi tới `learned` và restore qua restart;
- goal appraisal thực sự modulate affect và không pump state khi retry;
- acceptance evaluator pass trên causal trace hoàn chỉnh.

## 8. Những gì V56 cố ý chưa giả vờ đã giải quyết

- Ledger chưa lưu raw emotion vector của runtime vào Subject projection vì affect authority nằm ở `PersistentInternalState`; V56 nối affect bằng event, không sao chép authority.
- ToM không được phép tự biến inference thành fact. V56 không nới lỏng provenance của user model.
- “1 tuần” trong PDF là acceptance horizon; source có primitive persistence/continuity nhưng production soak nhiều ngày vẫn cần chạy trong môi trường thật hoặc simulator riêng.
- Không thêm PID giả chỉ để có tên “control theory”. Saturation, decay, refractory/cooldown, idempotency và bounded update tiếp tục là controller thực tế hiện có.

## 9. File chính thay đổi

- `cortex/subject/contracts.py`
- `cortex/causal_affect_models.py`
- `cortex/appraisal_engine.py`
- `cortex/subject/needs.py`
- `cortex/subject/neuro_control.py`
- `cortex/subject/service.py`
- `cortex/affective_dynamics.py`
- `runtime/affective_dynamics_runtime.py`
- `runtime/ai_orchestrated/orchestrator.py`
- `cortex/subject/decision_ledger.py` (mới)
- `cortex/subject/acceptance.py` (mới)
- `tools/v56_integrated_acceptance.py` (mới)
- `tests/subject/test_integrated_cognition_v56.py` (mới)
