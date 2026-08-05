# BẢN ĐỒ THAY ĐỔI V1 + V2

## V1

- Thêm `cortex/subject/`: substrate, needs, episodes, coalitions, beliefs, values, narrative, self-deception, authorship, continuity, competence, existential, consolidation và SubjectService.
- Thêm `memory/subject/`: SQLite schema/migrations, repository, CAS, idempotency, append-only event chain.
- Thêm `runtime/audit/`: forensic store, causal trace, replay.
- Thêm `runtime/world/`: typed contracts, capability policy, sandbox, actuator, consequences, TTS broker.
- Thêm `runtime/dialogue/`: rolling thoughts, discourse, realizer, incremental speech, body adapter.
- Thêm `runtime/subject_bootstrap.py` và `runtime/subject_runtime.py`.
- Thêm `experiments/emergence/` và test tương ứng.
- Sửa các compatibility points ở executor, causal affect, outcome observer, coordinator bootstrap và pyproject.
- Thêm `body/SubjectPerformanceFrame.cs`.

## V2

- Sửa capability registry và Executive Cortex/Tools để giữ typed boundary mới nhưng tương thích runtime cũ.
- Khôi phục package `tools/` và các static audit/evaluator/release utilities.
- Cập nhật pyproject để đóng gói tools.
- Giữ hợp đồng V55 trước hai assertion source-level V53/V54 mâu thuẫn.

## Bản Mega

- Không tạo thêm một nhánh logic Subject Core thứ ba.
- Dùng source V2 làm nguồn chính.
- Làm phẳng body directory.
- Gộp đặc tả, snapshot gốc, patch lịch sử, log, báo cáo và checksum.
- Thêm README tiếng Việt, báo cáo tổng hợp cực dài, script test và verify toàn bundle.
