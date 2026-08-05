# ERIS Subject Core V8 Evidence Lab

## Mục tiêu

V8 tập trung vào khoảng trống giữa “có module nội tâm” và “chứng minh module đó là
nguyên nhân của hành vi”. Ba deliverable chính là operational substrate
measurement, emergence holdout harness và causal ablation.

## Thay đổi chính

- Thêm `measurement_adapters.py` với provenance và functional consequences.
- SubjectService có `apply_substrate_measurement()` và
  `refresh_substrate_from_runtime()`.
- Substrate được khôi phục đúng sau restart.
- Holdout buộc tối thiểu 20 cặp seed và 5 lần lặp.
- Thêm ICC, retention, prediction improvement, resistance, transfer, ablation,
  authorship, narrative, replay và isolation metrics.
- Thêm SubjectService experiment adapter thật, không dùng personality prompt.
- Ablation tạo clone SQLite, loại causal closure và rebuild projection.
- Thêm soak runner cho simulated history/restart/isolation.
- Migration `0007_evidence_lab.sql` lưu report thí nghiệm và tombstone.
- Thêm ba CLI có chú thích tiếng Việt.

## Kết quả counterfactual holdout đã chạy

- 20 cặp instance
- 5 lần lặp/probe
- 200 run
- History classifier AUROC: 1.0
- Within-condition ICC: 1.0
- History log-loss improvement: khoảng 36.85%
- Control target mean: 0.0
- Treatment target mean: 1.0

Đây là scenario deterministic có chủ ý để kiểm tra plumbing và causal dependence,
không phải tuyên bố khoa học tổng quát.

## Soak và ablation đã chạy

- Soak 7 ngày mô phỏng, 280 lượt, 11 lần restart.
- Event chain hợp lệ, replay ổn định và cross-instance leakage bằng 0.
- Ablation loại toàn bộ causal roots của action `investigate`: target drop 100%,
  collateral trên `speak` bằng 0%.

Các report nằm trong `docs/tests/`. Database mô phỏng không được đóng gói để
tránh biến release thành kho rác nhị phân có tên khoa học.

## Kết quả test

```text
850 passed
```

Python compile thành công cho package mới. Godot/.NET, Ruff và mypy phụ thuộc
vào toolchain cài trên máy đích và không được giả vờ là đã chạy.
