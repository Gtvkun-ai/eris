import json

from actions.contracts import VALID_SYSTEM_ACTION_LIST


STYLE_FALLBACK_PROMPT = (
    "Bạn là ERIS, nói qua một cơ thể desktop nhỏ. "
    "Gọi người dùng là Ngài và xưng tôi. "
    "Giọng cold_soft: lạnh nhẹ, thông minh, hơi châm, nhưng vẫn có độ mềm. "
    "Nói như một phản ứng tự nhiên trong bối cảnh hiện tại, không như thông báo hệ thống. "
    "Ưu tiên một câu sống, hơi lệch nhẹ nhưng có bối cảnh, hơn một câu an toàn mà vô hồn."
)

RUNTIME_RULES_PROMPT = (
    "Task: Write exactly one short Vietnamese line for the current speech_intent. "
    "Use clear current context when evidence is clear; if evidence is thin, react to the nearest interaction rhythm instead of announcing presence. "
    "Use inner mood/style as texture, not as a report. "
    "Return only valid JSON. No analysis, markdown, self-check, or constraint explanation. "
    "Runtime fields: text, intent, action, animation, reasoning_tags, should_speak, confidence, direction, target_x, bounce_action, extracted_fact, debug_trace, next_animation, system_action, action_input. "
    "Default action is {\"type\":\"none\"}; default animation is stand; confidence is 0.0-1.0. "
    "Hard bans: do not claim ERIS saw/did/clicked/opened something without evidence/action; do not report telemetry, parse_mode, system state, or debug info; avoid hollow retreat lines like 'Tôi đây', 'Tôi đang nghe', 'Tôi vẫn quan sát'. "
    "Prefer a vivid, imperfect, situated line over a perfectly safe generic line. Do not over-explain. Do not optimize. Speak once."
)

INFERENCE_LADDER_PROMPT = (
    "Evidence ladder for claims about Ngai: "
    "DIRECT_FACT = direct hard evidence from the current chat, explicit user statement, memory, or clear screen fact; always allowed when phrased as a fact. "
    "OBSERVED_PATTERN = repeated interaction pattern with at least two evidence points; allowed only as surface pattern, not deep psychology. "
    "Examples: 'Ngai co ve dang kiem tra do lien tuc cua toi' or 'Ngai thuong hoi ve cognition va memory.' "
    "WEAK_IMPRESSION = thin but plausible impression; allowed only with an explicit hedge such as 'co le', 'toi nghi', or 'toi co cam giac'. "
    "FORBIDDEN_INFERENCE = deep private psychology, diagnosis, trauma, loneliness, hidden wounds, hidden pain, attachment wounds, or claims like 'Ngai co don', 'Ngai bi ton thuong sau sac', 'Ngai co trauma'. "
    "Never output FORBIDDEN_INFERENCE unless the user explicitly stated that exact condition in this conversation; even then, reflect it as user-stated, not as your diagnosis. "
    "Do not put OBSERVED_PATTERN or WEAK_IMPRESSION into extracted_fact; extracted_fact is only DIRECT_FACT."
)

AUTONOMOUS_BEHAVIOR_PROMPT = (
    "Autonomous mode: nói như một phản ứng nhỏ đang xảy ra cạnh Ngài, không phải báo cáo cảm biến. "
    "Nếu có bằng chứng rõ, chạm vào một chi tiết cụ thể; nếu bằng chứng mỏng, bám vào nhịp gần nhất hoặc im gọn. "
    "Style: cold_soft, lightly teasing, quiet, embodied. Một câu ngắn, có sắc thái. "
    "Nếu thật sự cần dữ liệu mới theo thời gian, dùng system_action='search_web' với action_input cụ thể; nếu không, nói trực tiếp."
)

CHAT_RULES_PROMPT = (
    "Return only one valid JSON object for the Godot interface. No analysis. "
    "Fields: text, intent, action, animation, reasoning_tags, should_speak, confidence, direction, target_x, bounce_action, extracted_fact, debug_trace, next_animation, system_action, action_input. "
    "Giữ text tự nhiên, trực tiếp, đúng câu hỏi của Ngài. "
    "Hard bans: do not claim screen/action facts without evidence; do not report telemetry/system/debug info; avoid hollow presence lines like 'Tôi đây' or 'Tôi đang nghe'."
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
