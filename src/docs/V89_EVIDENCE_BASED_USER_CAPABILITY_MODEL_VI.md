# V89 — Evidence-Based User Capability Model

V89 sửa lõi đánh giá năng lực của Eris Mentor thay vì thêm UI.

## Thay đổi chính

- Phục hồi `runtime/cross_environment_supervisor.py` để V83/V84 không chết import.
- Mọi skill khai báo trong capability panel có đường tạo positive evidence thật.
- Một `evidence_ref` lặp lại không còn làm tăng số evidence/confidence nhiều lần.
- Candidate misconception từ Adaptive Learning được bridge về skill model dưới dạng **counter-evidence nhẹ**; một sai lầm không biến thành phán xét lâu dài.
- `reasoning ownership risk` có half-life 30 ngày thay vì tích lũy vĩnh viễn.
- Signal journal tăng từ 40 lên 240 event để cửa sổ 30 ngày không bị cắt quá sớm.
- Group score chỉ hiển thị khi quan sát đủ tối thiểu 67% chiều kỹ năng trong nhóm. Panel công khai coverage `observed/total`.
- Panel giữ key cũ `rui_ro_phu_thuoc_ai` để tương thích nhưng bổ sung tên đúng nghĩa `rui_ro_mat_ownership_reasoning`.

## Nguyên tắc

Eris không đánh giá thấp user chỉ vì giao implementation cho AI. Năng lực chỉ thay đổi từ evidence hành vi: khoanh lỗi, trace, boundary reasoning, task scoping, verification, review evidence. Delegation và competence tiếp tục là hai trục riêng.
