# Eris Subject Core V2 - báo cáo tiếp tục triển khai

Ngày thực hiện: 2026-08-05

## Phần đã làm thêm

1. Hoàn thiện lớp tương thích giữa Executive Cortex V53, V54 và hợp đồng V55 hiện tại:
   - khôi phục facade `retrieve_executive_tools` cho plugin/test cũ;
   - giữ hard filter và model-owned shortlisting của V54/V55;
   - hỗ trợ event review cũ như `strong_seed` mà không làm mất typed event mới;
   - hỗ trợ payload capability cũ và payload typed mới;
   - ưu tiên `execute_capability`; chỉ dùng adapter `execute` khi executor cũ không có typed boundary.

2. Làm capability registry chịu được capability runtime tạm thời:
   - capability ngoài static registry nhận schema object rỗng, đóng;
   - không chấp nhận arbitrary fields;
   - static registry vẫn được kiểm tra coverage đầy đủ.

3. Bổ sung toàn bộ package `tools/` từng bị thiếu trong snapshot:
   - báo cáo acceptance cho inference broker;
   - evaluator semantic paraphrase;
   - audit đường gọi remote inference;
   - audit semantic authority;
   - evaluator social-plan activation;
   - đóng gói ZIP tái lập;
   - kiểm tra và giải nén release an toàn.

4. Cập nhật `pyproject.toml` để package `tools*` được đóng gói cùng source.

## Kết quả kiểm tra

- Compile Python: thành công.
- Static audit remote inference: pass, không có parse error hoặc finding.
- Static audit semantic authority: pass, không có parse error hoặc finding.
- Toàn bộ suite: **864 pass, 2 fail**.
- Suite theo hợp đồng hiện hành, bỏ đúng hai assertion tĩnh lỗi thời: **864 pass, 2 deselected**.

Hai test còn fail không phải lỗi runtime. Chúng là các assertion nguồn mã mâu thuẫn trực tiếp với bản mới hơn:

- V53 bắt buộc chuỗi `max_items=8`, trong khi V54 bắt buộc chuỗi đó không tồn tại.
- V54 bắt buộc `encode_capability_arguments` nằm trong Executive Cortex, trong khi V55 bắt buộc việc encode thuộc `ActionExecutor` và chuỗi đó không nằm trong Cortex.

Không thể làm cả hai cặp assertion cùng pass trên cùng một file mà dùng thủ thuật sửa test hoặc tự thay đổi file trong lúc chạy test. Bản V2 giữ hợp đồng V55 mới nhất và vẫn duy trì tương thích hành vi với V53/V54.

## File thay đổi so với bundle trước

- `actions/capability_registry.py`
- `runtime/ai_orchestrated/executive_tools.py`
- `runtime/ai_orchestrated/executive_cortex.py`
- `pyproject.toml`
- `tools/__init__.py`
- `tools/report_pdf_acceptance.py`
- `tools/evaluate_semantic_paraphrases.py`
- `tools/audit_remote_inference_paths.py`
- `tools/audit_semantic_authority_paths.py`
- `tools/evaluate_social_plan_activation.py`
- `tools/package_source.py`
- `tools/verify_release.py`
