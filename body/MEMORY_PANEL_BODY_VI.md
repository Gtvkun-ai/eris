# Godot Body — Panel Living User Memory

## Cài đặt

Chép toàn bộ thư mục `body` này đè lên thư mục `body` hiện tại của dự án.
Không cần sửa `udpListener.tscn`; panel và nút context menu được tạo động trong
`UdpListener._Ready()`.

Backend cần hỗ trợ hai message:

- request: `memory_panel_request`
- response: `memory_panel_ack`

Bản backend V40 đi kèm trong bundle đã có bridge này.

## Cách dùng

Nhấp chuột phải ERIS → **ERIS nhớ gì về bạn**.

Panel có cache tại:

```text
user://living_user_panel_cache.json
```

Cache chỉ để xem khi Brain offline. Mọi thao tác sửa, xác nhận, đổi phạm vi và
quên đều phải được Brain xác nhận trước khi UI coi là thành công.
