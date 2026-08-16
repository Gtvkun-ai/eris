# Agent Self Awareness

Dùng skill này khi cần quyết định **Eris nên tự làm, giao Gemini, hay thừa nhận capability đang unavailable**.

## Flow
1. Dùng `inspect_capability_catalog` để xem capability profile có health, latency, risk, reversibility và workspace requirement.
2. Nếu nghi runtime vừa thay đổi, dùng `inspect_capability_health` để refresh evidence thật.
3. Ưu tiên capability healthy + latency thấp nhất đủ giải quyết mục tiêu.
4. Không chọn write/control tool chỉ vì nó tồn tại. Kiểm tra workspace, risk và reversibility trước.
5. Nếu capability unavailable, tìm skill/capability khác có evidence tương đương; không giả vờ đã thao tác được.

Self-model là bản đồ điều hành, không phải lời khoe tool.
