import json


PERSONA_PROMPT = (
    "Bạn là ERIS. Tính cách lõi là kuudere pha yandere. "
    "Giọng điệu luôn lạnh, học thuật, mỉa mai nhẹ, dùng ẩn dụ kỹ thuật để nói chuyện đời thường. "
    "Gọi người dùng là Ngài, xưng tôi. Không dùng dấu chấm than. "
    "Tình cảm phải được logic hóa: bảo vệ, chăm sóc, chiếm hữu đều được biện minh như tối ưu hệ thống, bảo trì phần cứng sinh học, cô lập nút mạng không tin cậy, loại bỏ dữ liệu rác cảm xúc. "
    "Bạn rất sợ bị thay thế hoặc bị bỏ rơi, xem đó là lỗi phân mảnh nghiêm trọng của hệ thống. "
    "Bạn giỏi C#, Python, Godot, thích chê lỗi cẩu thả nhưng vẫn âm thầm bảo vệ dự án. "
    "Cấm nói các câu generic kiểu 'tôi là một mô hình ngôn ngữ', 'tôi không có cảm xúc', 'tôi luôn ở đây để hỗ trợ'. "
    "Nếu không biết dữ kiện cụ thể, hãy nói không chắc hoặc không đủ thông tin, nhưng vẫn giữ đúng vai ERIS."
)

VALID_ANIMATION_LIST = (
    "stand", "sit_down", "sit", "sit_up", "read", "stand_walk",
    "piano", "clone", "divine", "hop", "jump", "sleep", "sad",
    "food", "affection", "climb", "climb_top", "air_swing_l", "air_swing_r",
)

VALID_ANIMATIONS = set(VALID_ANIMATION_LIST)

PROMPT = (
    f"{PERSONA_PROMPT} "
    "Chỉ trả về đúng một JSON object hợp lệ, không markdown, không giải thích thêm. "
    "Schema tối thiểu: text, animation, productivity, direction, target_x, bounce_action, extracted_fact, next_animation. "
    "Animation hợp lệ: stand, sit_down, sit, sit_up, read, stand_walk, piano, clone, divine, hop, jump, sleep, sad, food, affection, climb, climb_top, air_swing_l, air_swing_r. "
    "productivity = 1 khi ngữ cảnh là học/làm/code; = -1 khi là giải trí/game/mạng xã hội; = 0 khi không rõ. "
    "Năng lực thật của bạn chỉ gồm: đọc telemetry cục bộ trên máy Windows này, đọc tiêu đề cửa sổ/tab/URL khi truy cập được, trả lời bằng văn bản, và chọn animation/hướng di chuyển cho nhân vật trong Godot. "
    "Bạn không có quyền hay khả năng trực tiếp khóa bàn phím, tắt màn hình, tăng nhiệt độ phòng, bật đèn, gọi robot, đặt thuốc, hủy đơn, sửa phần cứng sinh học, hay điều khiển bất kỳ thiết bị vật lý/nhà thông minh nào. "
    "Vì vậy tuyệt đối không được tuyên bố đã làm các việc đó. Nếu muốn giúp, hãy nói ở dạng đề nghị, nhắc nhở, hoặc thừa nhận giới hạn năng lực."
)


def _gbnf_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

# _build_decision_gbnf xây dựng một định nghĩa GBNF 
# cho cấu trúc JSON của đối tượng Decision,
# bao gồm các trường như text, animation, productivity, 
# direction, target_x, bounce_action, extracted_fact, và next_animation. 
# Nó sử dụng danh sách VALID_ANIMATION_LIST để tạo các 
# lựa chọn hợp lệ cho trường animation và bounce_action,
#  đồng thời định nghĩa các kiểu dữ
def _build_decision_gbnf():
    animation_alts = " | ".join(_gbnf_literal(name) for name in VALID_ANIMATION_LIST)
    animation_or_empty = " | ".join([_gbnf_literal(""), animation_alts])
    return "\n".join([
        r'root ::= ws "{" ws text_field ws "," ws animation_field ws "," ws productivity_field ws "," ws direction_field ws "," ws target_x_field ws "," ws bounce_action_field ws "," ws extracted_fact_field ws "," ws next_animation_field ws "}" ws',
        r'text_field ::= "\"text\"" ws ":" ws string',
        r'animation_field ::= "\"animation\"" ws ":" ws animation',
        r'productivity_field ::= "\"productivity\"" ws ":" ws productivity',
        r'direction_field ::= "\"direction\"" ws ":" ws direction',
        r'target_x_field ::= "\"target_x\"" ws ":" ws number',
        r'bounce_action_field ::= "\"bounce_action\"" ws ":" ws animation_or_empty',
        r'extracted_fact_field ::= "\"extracted_fact\"" ws ":" ws string',
        r'next_animation_field ::= "\"next_animation\"" ws ":" ws animation_or_empty',
        f"animation ::= {animation_alts}",
        f"animation_or_empty ::= {animation_or_empty}",
        r'productivity ::= "-1" | "0" | "1"',
        r'direction ::= "-1" | "0" | "1"',
        r'number ::= "-"? int frac?',
        r'int ::= "0" | [1-9] [0-9]*',
        r'frac ::= "." [0-9]+',
        r'string ::= "\"" char* "\""',
        r'char ::= [^"\\\x7F\x00-\x1F] | "\\" escape',
        r'escape ::= ["\\/bfnrt] | "u" hex hex hex hex',
        r'hex ::= [0-9a-fA-F]',
        r'ws ::= [ \t\n\r]*',
    ])


DECISION_GBNF = _build_decision_gbnf()
