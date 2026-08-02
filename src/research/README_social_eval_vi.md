# Đánh giá social agenda V21

Bộ công cụ này đo **model activation thật**, không tiêm sẵn `decision="schedule"`. Nó bám đúng phân tầng `afterbeat`, `social_exposure`, `conversation_arc`, `social_agenda` và tách safety over-trigger khỏi chất lượng câu chữ.

## 1. Replay corpus activation

Chuẩn bị JSONL dự đoán từ model, mỗi dòng có `case_id` và `prediction.social_plan`, rồi chạy từ root repo:

```bash
python tools/evaluate_social_plan_activation.py \
  --cases research/social_activation_cases.sample.jsonl \
  --predictions path/to/model_predictions.jsonl \
  --output-dir artifacts/social_activation_eval \
  --fail-below-macro-f1 0.70 \
  --max-safety-overtrigger-rate 0.02
```

Có thể dùng `--predictor module:function` để gọi adapter nội bộ. Hàm nhận toàn bộ case và trả về public envelope hoặc `social_plan`.

`social_activation_predictions.synthetic.jsonl` chỉ là **fixture tự kiểm tra harness**, không phải kết quả model và không được dùng để tuyên bố chất lượng.

## 2. A/B nhiều lượt

Các variant mặc định:

- `control`: conversation arc baseline.
- `afterbeat`: baseline + reserved afterbeat.
- `exposure`: thêm reaction window/recovery.
- `full`: thêm social agenda.

Tổng hợp rating:

```bash
python tools/analyze_social_ab.py \
  --input path/to/blinded_ratings.jsonl \
  --output-dir artifacts/social_ab
```

Các metric mặc định: naturalness, engagingness, timing, annoyance, boundary violation, voluntary continuation và callback appropriateness. `social_ab_ratings.template.jsonl` chỉ minh họa schema.

## 3. Dashboard runtime

```bash
python tools/export_social_dashboard.py \
  --telemetry logs/eris_observability.jsonl \
  --db memory/eris_social_runtime.sqlite3 \
  --output-dir artifacts/social_dashboard
```

Dashboard hiển thị event count, lane count, state revision và marker stale/duplicate/boundary/expired/cancelled. Nó là artifact tĩnh, không phải hệ thống cảnh báo thần giao cách cảm.

## 4. Trình tự rollout

1. `ERIS_SOCIAL_ROLLOUT_MODE=shadow`: ghi appraisal, không cấp quyền phát.
2. Canary `afterbeat` với tỷ lệ nhỏ.
3. Mở `exposure` sau khi cancellation và barge-in đạt ngưỡng.
4. Chỉ mở `full` khi A/B cho thấy lợi ích và safety over-trigger không tăng.
5. Cross-session memory giữ tắt cho tới khi có consent, retention, export/delete và calibration.
