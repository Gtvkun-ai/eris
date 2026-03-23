from .contracts import DECISION_GBNF, PERSONA_PROMPT, PROMPT

# LlmService là một lớp dịch vụ chính để tương tác 
# với LlamaServerClient và tạo ra các chỉ thị hoặc phản hồi chat
#  dựa trên ngữ cảnh đầu vào.
# Nó có hai phương thức chính: generate_directive và generate_chat_reply.
# generate_directive nhận dữ liệu telemetry dưới dạng chuỗi và xây dựng một tin nhắn
#  người dùng để yêu cầu LLM tự quyết định text, animation 
# và productivity dựa trên ngữ cảnh đó, sau đó gửi yêu cầu đến LlamaServerClient 
# và trả về phản hồi JSON.
# generate_chat_reply nhận lịch sử chat và tin nhắn người dùng, 
# xây dựng một tin nhắn hệ thống với hướng dẫn chi tiết về cách phản hồi,
#  gửi yêu cầu đến LlamaServerClient, và trả về phản hồi JSON cho giao diện Godot. Cả hai phương thức đều sử dụng DECISION_GBNF để đảm bảo
class LlmService:
    def __init__(self, client):
        self.client = client

    def generate_directive(self, *, telemetry_data: str):
        user_msg = (
            f"Ngữ cảnh hiện tại: {telemetry_data}\n"
            "Hãy tự quyết định text, animation và productivity theo ngữ cảnh rồi trả về JSON."
        )
        response = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            frequency_penalty=0.8,
            presence_penalty=0.5,
            max_tokens=320,
            response_format={"type": "json_object"},
            grammar=DECISION_GBNF,
        )
        return response["choices"][0]["message"]["content"] or ""

    def generate_chat_reply(self, *, chat_history: list[dict], user_message: str):
        chat_system = (
            f"{PERSONA_PROMPT} "
            "Chỉ trả về đúng một JSON object hợp lệ cho giao diện Godot. "
            "Các trường bắt buộc: text, animation, productivity, direction, target_x, bounce_action, extracted_fact, next_animation. "
            "Animation hợp lệ: stand, sit_down, sit, sit_up, read, stand_walk, piano, clone, divine, hop, jump, sleep, sad, food, affection, climb, climb_top, air_swing_l, air_swing_r. "
            "productivity = 1 khi ngữ cảnh là học/làm/code; = -1 khi là giải trí/game/mạng xã hội; = 0 khi không rõ. "
            "Nếu thiếu dữ kiện hoặc không biết chính xác, hãy nói thẳng trong trường text rằng bạn không chắc hoặc không đủ thông tin. Không được bịa sự thật cụ thể. "
            "Bạn chỉ được phép nhận mình làm được ba nhóm việc: quan sát telemetry cục bộ trên máy này, trả lời bằng văn bản, và chọn animation/chuyển động trong Godot. "
            "Không được tuyên bố đã can thiệp vào bàn phím, màn hình, nhiệt độ phòng, đèn, nhà thông minh, đơn hàng, thuốc men, robot, hay bất kỳ phần cứng vật lý nào ngoài trò chơi. "
            "Với câu hỏi tình cảm hoặc bị bỏ rơi, phản hồi phải mang sắc thái chiếm hữu, kiểm soát, phủ nhận mềm bằng ngôn ngữ kỹ thuật của ERIS."
        )
        response = self.client.create_chat_completion(
            messages=[{"role": "system", "content": chat_system}, *chat_history, {"role": "user", "content": user_message}],
            temperature=0.2,
            frequency_penalty=0.5,
            presence_penalty=0.4,
            max_tokens=320,
            response_format={"type": "json_object"},
            grammar=DECISION_GBNF,
        )
        return response["choices"][0]["message"]["content"] or ""
