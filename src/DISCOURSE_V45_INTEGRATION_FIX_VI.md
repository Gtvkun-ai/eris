# ERIS V45 - sửa tích hợp typed discourse

Bản V44 đổi semantic frame sang dataclass typed nhưng gói changed-files thiếu
`runtime/session_turn_ledger.py` khi người dùng áp trực tiếp lên source cũ. Vì
vậy orchestrator gọi `merge_turn_meta()` trên ledger không có method này.

V44 cũng giữ object `_typed_semantic_frame` trong envelope nội bộ. Một số đường
autonomous/startup phát thẳng envelope đó vào `json.dumps`, dẫn tới lỗi
`SemanticFrame is not JSON serializable`.

V45 sửa bằng hai ranh giới rõ ràng:

1. Full source mang đúng `SessionTurnLedger.merge_turn_meta()` và toàn bộ thay đổi
   tích lũy từ V41 tới V44.
2. `runtime/json_boundary.py` là serializer chung tại JSON/UDP boundary. Nó đổi
   dataclass, enum, tuple, set, datetime và object có `to_dict()` thành dữ liệu
   JSON-safe, đồng thời bỏ mọi cache private `_typed_*`.

Object typed vẫn được giữ bên trong orchestrator để tránh parse contract hai
lần. Chỉ bản public đi qua serializer; do đó không phải quay lại dictionary ở
lõi chỉ vì JSON khá bảo thủ trong chuyện kiểu dữ liệu.
