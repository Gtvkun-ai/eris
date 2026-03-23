import json
import os

# MemoryStore là một lớp để quản lý bộ nhớ dài hạn dưới dạng một
#  danh sách các chuỗi được lưu trữ trong một tệp JSON.
# Nó cung cấp các phương thức để tải dữ liệu từ tệp,
#  thêm một mục mới vào bộ nhớ (với kiểm tra trùng lặp và giới hạn số lượng mục), 
# và lưu dữ liệu trở lại tệp. 
# Lớp này hữu ích trong các ứng dụng cần lưu trữ thông tin hoặc sự kiện 
# theo thời gian, như trong các hệ thống quản lý trạng thái hoặc lịch sử trò chuyện.  
class MemoryStore:
    def __init__(self, path: str, max_items: int = 20):
        self.path = path
        self.max_items = max_items

    # load là phương thức để tải dữ liệu từ tệp JSON.
    # Nó kiểm tra xem tệp có tồn tại và có kích thước lớn hơn 0 hay không. 
    # Nếu tệp hợp lệ, nó đọc nội dung và phân tích JSON để trả về một danh sách các chuỗi. 
    # Nếu tệp không tồn tại, có kích thước không hợp lệ, hoặc nội dung không phải là một danh sách,
    # nó sẽ trả về một danh sách rỗng.
    def load(self) -> list[str]:
        if not os.path.isfile(self.path) or os.path.getsize(self.path) <= 0:
            return []
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            return []
        return [str(item) for item in data]

    # append_fact là phương thức để thêm một mục mới vào bộ nhớ.
    # Nó nhận một danh sách các mục hiện tại và một chuỗi fact mới.
    # Nếu fact mới trống hoặc đã tồn tại trong danh sách, nó sẽ trả về danh sách hiện tại mà không thay đổi. 
    # Nếu fact mới hợp lệ, nó sẽ được thêm vào danh sách, 
    # và nếu danh sách vượt quá giới hạn max_items, nó sẽ chỉ giữ lại các mục gần đây nhất.
    def append_fact(self, current_items: list[str], fact: str) -> list[str]:
        fact = (fact or "").strip()
        if not fact or fact in current_items:
            return current_items

        updated = [*current_items, fact]
        if len(updated) > self.max_items:
            updated = updated[-self.max_items :]
        self.save(updated)
        return updated

    def save(self, items: list[str]) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=4)
