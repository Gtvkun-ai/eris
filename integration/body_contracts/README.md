# Godot body contract fixtures

Các file C# trong thư mục này là **fixture hợp đồng tĩnh** cho CI của source runtime. Chúng chỉ giữ những symbol mà backend/test cần xác nhận khi dự án Godot body không có mặt trong cùng checkout.

Khi tích hợp production, áp dụng thay đổi tương ứng vào body repo thật. Không chép hai fragment này đè lên implementation đầy đủ của `UdpListener` như một nghi lễ hiến tế mã nguồn.
