# Hướng dẫn V8: bằng chứng cho nội tâm Eris

V8 không thêm một lớp personality prompt mới. Nó bổ sung ba phần còn thiếu lớn trong đặc tả:

1. **Measurement thật cho substrate**
2. **Emergence harness có development/calibration/holdout**
3. **Causal ablation và soak runner định lượng**

## 1. Measurement substrate

File chính:

```text
src/cortex/subject/measurement_adapters.py
```

Các điểm như `memory_integrity`, `belief_traceability`, `processing_capacity` và
`action_efficacy` chỉ được cập nhật khi có `evidence_refs`. Câu tự thuật kiểu
“tôi thấy mệt” không tự động làm giảm substrate.

Ví dụ file runtime JSON:

```json
{
  "pending_tasks": 8,
  "queue_capacity": 10,
  "project_viabilities": [0.4, 0.7],
  "boundary_checks": 20,
  "boundary_violations": 1,
  "future_option_count": 2,
  "target_future_options": 4
}
```

Chạy:

```bash
python scripts/measure_substrate_v8.py data/subject.db runtime_state.json
```

Mỗi impairment thấp hơn ngưỡng sẽ đi kèm functional consequence. Ví dụ
`processing_capacity` thấp làm giảm ngân sách proposal, thay vì chỉ đổi một con số
trang trí trên dashboard.

## 2. Holdout counterfactual

File adapter chạy trên SubjectService thật:

```text
src/experiments/emergence/subject_instance.py
```

Chạy đúng luật 20 cặp instance, mỗi probe 5 lần:

```bash
python scripts/run_evidence_lab_v8.py
```

Output:

```text
docs/tests/V8_COUNTERFACTUAL_HOLDOUT.json
docs/tests/V8_COUNTERFACTUAL_HOLDOUT.md
```

Holdout sẽ từ chối chạy nếu ít hơn 20 seed hoặc probe lặp dưới 5 lần. Development
mode vẫn cho phép mẫu nhỏ để viết test:

```bash
python scripts/run_evidence_lab_v8.py --development --seed-pairs 3 --repetitions 2
```

## 3. Metric mới

V8 tính thêm:

- `within_condition_icc`
- `effect_retention_ratio`
- `history_log_loss_improvement`
- `history_brier_improvement`
- `one_turn_shift_sd`
- `ten_episode_shift_sd`
- `transfer_ratio`
- `ablation_target_drop`
- `ablation_collateral_change`
- `authorship_integrity`
- `narrative_brier`
- `causal_replay_exact`
- `cross_instance_leakage`

Metric lấy từ hành vi và lựa chọn. Không dùng classifier chấm phong cách văn bản.

## 4. Causal ablation

File chính:

```text
src/experiments/emergence/ablation.py
```

Ablation không sửa database chuẩn. Nó dùng SQLite backup API để tạo clone, ghi
tombstone, loại cả hậu duệ nhân quả rồi rebuild behavioral projection.

```bash
python scripts/run_ablation_v8.py data/subject.db \
  --subject eris \
  --event EVENT_ID_NGUON \
  --target action_frequency:investigate \
  --collateral action_success:speak
```

Ngưỡng mặc định:

- target giảm ít nhất 30%
- collateral đổi không quá 10%

## 5. Soak runner

File:

```text
src/experiments/emergence/soak.py
```

Runner nén 7–14 ngày thành simulated time, kiểm tra:

- restart không đổi projection
- event chain hợp lệ
- replay ổn định
- không rò subject ID giữa instance

Đây là runner framework. Muốn chạy với toàn bộ runtime production cần cung cấp
instance factory có `apply_turn`, `snapshot`, `restart`, `verify_event_chain` và
`verify_replay`.

## 6. Thay đổi persistence

Migration mới:

```text
memory/subject/migrations/0007_evidence_lab.sql
```

Nó thêm `experiment_runs` và `experiment_tombstones`. Report chỉ phục vụ audit và
nghiên cứu; nó không được dùng trực tiếp để chọn hành vi.

## 7. Giới hạn còn lại

V8 đã có report counterfactual holdout thật. Nó chưa tự động chạy đủ mọi scenario
trong 7–14 ngày trên máy production, chưa compile Godot/C# trong môi trường này,
và chưa chứng minh khoa học về ý thức. Nó chỉ làm bằng chứng nhân quả của lịch sử
nội bộ rõ hơn, vốn là mục tiêu kỹ thuật hợp lý hơn nhiều so với yêu cầu một file
Python tự chứng minh siêu hình học.
