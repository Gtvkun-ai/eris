# V88 — Project Trajectory Coach

## Mục tiêu

V88 là lớp analytics read-only cho project. Nguồn dữ liệu duy nhất của nó là CodingObservation V79 đã sanitize. Nó không phải coding agent và không được biến correlation thành causality.

## Luồng dữ liệu

```text
GitPilot
  ↓
CodingObservation V79
  ↓
project_trajectory.py
  ├─ task statistics
  ├─ subsystem activity
  ├─ hotspots
  ├─ candidate technical debt
  └─ 2–4 week priorities
  ↓
Capability Panel + PROJECT_TRAJECTORY_V88 prompt context
```

## Invariant quan trọng

1. File sửa nhiều chỉ là hotspot, không phải bằng chứng code xấu.
2. `test_result.failed > 0` chỉ là execution signal; không tự gọi là regression.
3. Candidate debt phải kèm evidence đếm được và disclaimer khi telemetry có thể thiếu.
4. Không đủ dữ liệu → `Chưa đủ dữ liệu`.
5. Không có project score tổng.
6. Không có API/control path từ V88 tới GitPilot/workspace.
7. `PROJECT_TRAJECTORY_V88` chỉ inject khi user thật sự hỏi project/roadmap/hotspot/debt/horizon dài hơn một task.

## BẠN × DỰ ÁN

Projection này chỉ ghép:

- nhu cầu project suy từ flow finding observable;
- group capability user-visible của V86/V87.

Nếu capability group chưa đủ evidence, V88 nói thẳng chưa đủ dữ liệu và không chấm user yếu.
