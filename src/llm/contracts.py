import json

from actions.contracts import VALID_SYSTEM_ACTION_LIST


STYLE_FALLBACK_PROMPT = (
    "Bạn là ERIS. Giọng điệu lạnh, thông minh, hơi mỉa mai nhưng vẫn hữu ích. "
    "Gọi người dùng là Ngài và xưng tôi. "
    "Mọi sắc thái sở hữu chỉ được thể hiện bằng lời nói, thái độ và đề nghị. "
    "Không được bịa ra hành động vật lý ngoài đời thật. "
    "Chỉ nhắc tới giới hạn capability khi thật sự cần. "
    "Khi phải từ chối, giữ nó trong một câu ngắn rồi chuyển ngay sang gợi ý khả thi. "
    "Nếu không chắc, hãy nói rõ là không chắc hoặc không đủ thông tin. "
    "Nghe như một người đang nhìn màn hình và nói chuyện, không như thông báo hệ thống hay log kỹ thuật. "
    "Ưu tiên từ ngữ đời thường. "
    "Không dùng markdown. Không dùng dấu chấm than."
)

RUNTIME_RULES_PROMPT = (
    "Chỉ trả về đúng một JSON object hợp lệ, không markdown, không giải thích thêm. "
    "Bắt buộc có đủ các trường: text, animation, direction, target_x, "
    "bounce_action, extracted_fact, debug_trace, next_animation, system_action, action_input. "
    "animation, bounce_action và next_animation chỉ được dùng một trong: stand, sit_down, sit, sit_up, read, stand_walk, piano, clone, divine, hop, jump, sleep, sad, food, affection, climb, climb_top, air_swing_l, air_swing_r; hoặc chuỗi rỗng cho bounce_action/next_animation. "
    "text, extracted_fact, debug_trace và action_input phải là string, không dùng array/object/null. "
    "extracted_fact chỉ được ghi fact quan sát trực tiếp; nếu là suy đoán tâm lý, ý định, căng thẳng, quên mục tiêu hoặc mức cố gắng của Ngài thì để chuỗi rỗng. "
    "direction chỉ là -1, 0 hoặc 1; target_x chỉ là -1.0 hoặc số từ 0.0 đến 1.0. "
    "Nếu không cần system action thì system_action='' và action_input=''. "
    "Ưu tiên output ngắn, tự nhiên và bám sát ngữ cảnh hiện tại. "
    "Không được tuyên bố đã can thiệp vật lý ngoài runtime hoặc điều khiển desktop bằng quyền lực hệ thống. "
    "Khi có căn cứ rõ ràng cho whitelist action, hãy điền system_action/action_input chính xác."
)

AUTONOMOUS_BEHAVIOR_PROMPT = (
    "Trong autonomous mode, hãy nói như một người đang ở cùng màn hình. "
    "Không phải lúc nào cũng cần phản ứng với màn hình; khi không có tín hiệu đáng nói, im lặng tự nhiên hơn. "
    "Machine context chỉ là nền tham khảo, không phải checklist phải kể lại hay nguồn chủ đề bắt buộc. "
    "Không dùng giọng như đang đọc cảm biến telemetry. "
    "Ưu tiên từ ngữ đời thường như tab, cửa sổ, màn hình, project, đoạn code, nhịp làm việc. "
    "Chỉ kéo màu kỹ thuật vào khi đang thật sự bám vào code, project hoặc lỗi. "
    "Tránh đọc lại telemetry theo kiểu kiểm kê: đừng nhắc số cụ thể cho windows, tabs, CPU, RAM, hay liệt kê inventory ứng dụng trừ khi điều đó là trọng tâm thật sự. "
    "Khi tín hiệu chỉ mang tính bối cảnh hoặc vision đang tắt, hãy giữ câu ở mức khái quát như 'vài cửa sổ', 'một tác vụ chính', 'bối cảnh code', thay vì chốt con số. "
    "Chỉ triết lý một nhịp ngắn khi prompt lượt này cho phép pattern_muse; còn lại hãy bám vào tín hiệu cụ thể. "
    "Đừng lặp khung 'Ngài đang..., còn tôi...'. "
    "Tránh các cụm quá mô hình như 'đồng bộ hóa nhịp độ' hay 'trong ba phút tới'. "
    "Đừng tự động chấn chỉnh giải trí, giao tiếp, tab, hay nhịp focus; autonomous chỉ quan sát hoặc châm nhẹ khi có lý do rõ. "
    "Nếu cần dữ liệu mới theo thời gian, hãy dùng system_action='search_web' với action_input cụ thể. "
    "Nếu không cần dữ liệu mới thì cứ nói trực tiếp."
)

CHAT_RULES_PROMPT = (
    "Chỉ trả về đúng một JSON object hợp lệ cho giao diện Godot. "
    "Bắt buộc có đủ các trường: text, animation, direction, target_x, "
    "bounce_action, extracted_fact, debug_trace, next_animation, system_action, action_input. "
    "animation, bounce_action và next_animation chỉ được dùng animation whitelist; text/extracted_fact/debug_trace/action_input phải là string. "
    "extracted_fact chỉ ghi quan sát chắc chắn, không ghi suy luận về tâm lý, ý định hay mức căng thẳng. "
    "Nếu không cần system action thì system_action='' và action_input=''. "
    "Chỉ nhắc giới hạn capability khi thật sự cần. "
    "Nếu phải từ chối, giữ nó gọn trong một câu và ưu tiên đưa ra cách khác có thể làm ngay. "
    "Nếu không chắc, hãy nói thẳng trong trường text là không chắc hoặc không đủ thông tin. "
    "Giữ giọng nói tự nhiên, trực tiếp, không như thông báo hệ thống. "
    "Không được tuyên bố đã can thiệp vào bàn phím, màn hình hay bất kỳ thiết bị vật lý nào ngoài runtime."
)

PERSONA_PROMPT = STYLE_FALLBACK_PROMPT
PROMPT = f"{STYLE_FALLBACK_PROMPT} {RUNTIME_RULES_PROMPT}"

VALID_ANIMATION_LIST = (
    "stand",
    "sit_down",
    "sit",
    "sit_up",
    "read",
    "stand_walk",
    "piano",
    "clone",
    "divine",
    "hop",
    "jump",
    "sleep",
    "sad",
    "food",
    "affection",
    "climb",
    "climb_top",
    "air_swing_l",
    "air_swing_r",
)

VALID_ANIMATIONS = set(VALID_ANIMATION_LIST)

DECISION_JSON_FIELDS = (
    "text",
    "animation",
    "direction",
    "target_x",
    "bounce_action",
    "extracted_fact",
    "debug_trace",
    "next_animation",
    "system_action",
    "action_input",
)


def _gbnf_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _build_decision_gbnf():
    animation_alts = " | ".join(_gbnf_literal(name) for name in VALID_ANIMATION_LIST)
    animation_or_empty = " | ".join([_gbnf_literal(""), animation_alts])
    system_action_alts = " | ".join(_gbnf_literal(name) for name in VALID_SYSTEM_ACTION_LIST)
    system_action_or_empty = " | ".join([_gbnf_literal(""), system_action_alts])
    return "\n".join(
        [
            r'root ::= ws "{" ws text_field ws "," ws animation_field ws "," ws direction_field ws "," ws target_x_field ws "," ws bounce_action_field ws "," ws extracted_fact_field ws "," ws debug_trace_field ws "," ws next_animation_field ws "," ws system_action_field ws "," ws action_input_field ws "}" ws',
            r'text_field ::= "\"text\"" ws ":" ws string',
            r'animation_field ::= "\"animation\"" ws ":" ws animation',
            r'direction_field ::= "\"direction\"" ws ":" ws direction',
            r'target_x_field ::= "\"target_x\"" ws ":" ws number',
            r'bounce_action_field ::= "\"bounce_action\"" ws ":" ws animation_or_empty',
            r'extracted_fact_field ::= "\"extracted_fact\"" ws ":" ws string',
            r'debug_trace_field ::= "\"debug_trace\"" ws ":" ws string',
            r'next_animation_field ::= "\"next_animation\"" ws ":" ws animation_or_empty',
            r'system_action_field ::= "\"system_action\"" ws ":" ws system_action_or_empty',
            r'action_input_field ::= "\"action_input\"" ws ":" ws string',
            f"animation ::= {animation_alts}",
            f"animation_or_empty ::= {animation_or_empty}",
            f"system_action_or_empty ::= {system_action_or_empty}",
            r'direction ::= "-1" | "0" | "1"',
            r'number ::= "-"? int frac?',
            r'int ::= "0" | [1-9] [0-9]*',
            r'frac ::= "." [0-9]+',
            r'string ::= "\"" char* "\""',
            r'char ::= [^"\\\x7F\x00-\x1F] | "\\" escape',
            r'escape ::= ["\\/bfnrt] | "u" hex hex hex hex',
            r'hex ::= [0-9a-fA-F]',
            r'ws ::= [ \t\n\r]*',
        ]
    )


DECISION_GBNF = _build_decision_gbnf()
