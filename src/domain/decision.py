from dataclasses import dataclass
#đóng vai trò như một bản thiết kế cho đối tượng Decision, 
# thường được sử dụng trong các hệ thống quản lý trạng thái hoạt ảnh hoặc logic
#  trò chơi — có khả năng là một phần trong tích hợp giữa Python và một Engine như Godot.
@dataclass(slots=True)
#Tự động hóa: Nó tự động tạo các phương thức đặc biệt như 
# __init__, __repr__, và __eq__, loại bỏ việc viết mã lặp lại vô nghĩa.

class Decision:
    text: str
    animation: str
    productivity: int = 0
    extracted_fact: str = ""
    direction: int = 0
    next_animation: str = ""
    target_x: float = -1.0 
    bounce_action: str = "" #được sử dụng để xác định hành động bật lại nào sẽ được thực hiện sau khi hoàn thành hoạt ảnh hiện tại,

    def to_payload(self) -> dict:
        return {
            "text": self.text,
            "animation": self.animation,
            "direction": self.direction,
            "target_x": self.target_x,
            "bounce_action": self.bounce_action,
            "next_animation": self.next_animation,
        }
