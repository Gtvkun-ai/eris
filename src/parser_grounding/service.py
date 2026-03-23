from domain import Decision

from .decision import ParserGroundingMixin

# DecisionParser là một lớp để phân tích và "ground" (định hình)
#  các quyết định được tạo ra bởi một mô hình ngôn ngữ lớn (LLM) 
# thành các đối tượng Decision có thể thực thi trong runtime của ứng dụng.
# Lớp này kế thừa từ ParserGroundingMixin, cung cấp các phương thức để xử lý 
# văn bản và đảm bảo rằng các quyết định được tạo ra phù hợp với khả năng 
# của hệ thống, đồng thời cung cấp một quyết định dự phòng (fallback) 
# để sử dụng khi LLM không thể tạo ra một quyết định hợp lệ.
class DecisionParser(ParserGroundingMixin):
    def __init__(self, fallback: Decision, logger=None):
        self.fallback_decision = fallback
        self.logger = logger
        self.fallback = {
            "text": fallback.text,
            "animation": fallback.animation,
            "extracted_fact": fallback.extracted_fact,
        }

    # _normalize_salvaged_text là một phương thức để làm sạch và 
    # chuẩn hóa văn bản được trích xuất từ LLM,
    #  loại bỏ các tiền tố không cần thiết như "Eris:", "Assistant:", "AI:", hoặc "Response:"
    #  để đảm bảo rằng chỉ còn lại phần nội dung chính của văn bản.
    def _finalize_decision(self, decision: dict, user_hint: str = ""):
        finalized = super()._finalize_decision(decision, user_hint=user_hint)
        return Decision(**finalized)

    def parse(self, raw_text: str, user_hint: str = "") -> Decision:
        return self.parse_ai_json(raw_text, user_hint=user_hint)

    def build_chat_user_message(self, *, user_message: str, last_chat_answer: str) -> str:
        if self._is_follow_up_question(user_message) and last_chat_answer:
            return (
                "Người dùng đang hỏi tiếp về chính câu trả lời ngay trước đó.\n"
                f"Câu trả lời trước của bạn: {last_chat_answer}\n"
                f"Câu hỏi mới: {user_message}"
            )
        return f"Người dùng: {user_message}"
