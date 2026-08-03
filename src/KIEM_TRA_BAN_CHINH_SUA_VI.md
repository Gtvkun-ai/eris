# Kiểm tra bản chỉnh sửa

## Phạm vi

Bản này chỉ sửa bốn nhóm yêu cầu:

1. quyền tạo public intent;
2. fallback chéo;
3. lane startup mặc định;
4. race, cancel và trace.

Chi tiết kiến trúc nằm trong `GHI_CHU_KIEN_TRUC_4_TRONG_TAM_VI.md`.

## Kết quả kiểm tra

- `python -m compileall -q .`: đạt.
- Test trọng tâm Surface / Initiative / Social / PrivateMind: đạt.
- Test dự án, sau khi bỏ các file phụ thuộc module `tools/*` không có trong
  archive nguồn: **662 passed**.
- Bộ test nguyên vẹn không thể collect hoàn toàn vì archive gốc thiếu các module:
  - `tools.package_source`
  - `tools.evaluate_social_plan_activation`
  - `tools.report_pdf_acceptance`
  - `tools.evaluate_semantic_paraphrases`
  - `tools.audit_remote_inference_paths`
  - `tools.audit_semantic_authority_paths`

Đây là thiếu hụt sẵn có của file nguồn, không phải lỗi import do bản chỉnh sửa.

## Điểm cấu hình mặc định

- Private cognition surface export: tắt.
- Surface cross-worker fallback: tắt.
- Legacy model lanes: tắt.
- Inner diary model call: tắt.
- Background tutor/research startup: tắt.
- Legacy social fallback: tắt.
- Event trace: bật.
