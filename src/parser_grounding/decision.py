import json
import re

from llm.contracts import VALID_ANIMATIONS
# ParserGroundingMixin là một lớp mixin cung cấp các phương thức để xử lý và
#  "ground" (định hình) các quyết định được tạo ra bởi một mô hình ngôn ngữ lớn (LLM)
#  thành các hành động có thể thực thi trong runtime của ứng dụng.
# Lớp này bao gồm các phương thức để trích xuất thông tin từ văn bản,
#  kiểm tra xem các mệnh đề có vượt quá khả năng runtime hay không,
#  và xây dựng các phản hồi được điều chỉnh để phù hợp với khả năng của hệ thống.


CAPABILITY_PROFILE = {
    "observe": [
        "telemetry cục bộ trên máy Windows",
        "tiêu đề cửa sổ, tab và URL nếu UI Automation đọc được",
        "mức CPU, RAM, thời gian, ngữ cảnh focus",
    ],
    "respond": [
        "trả lời bằng văn bản",
        "đề xuất bước tiếp theo",
        "thừa nhận khi không chắc",
    ],
    "embody": [
        "đổi animation, hướng di chuyển và vị trí nhân vật trong Godot",
    ],
    "memory": [
        "lưu một số fact ngắn vào long_term_memory.json",
    ],
}

UNSUPPORTED_ACTION_VERBS = [
    "khóa", "ngắt", "đóng", "mở", "tắt", "bật", "tăng", "giảm",
    "gọi", "đặt", "hủy", "xóa", "ép", "cưỡng chế", "ghi đè",
    "can thiệp", "điều khiển", "chiếm hữu", "chặn", "phát", "kích hoạt",
    "thiết lập", "reset", "shutdown", "hibernate", "suspend",
]

UNSUPPORTED_ACTION_TARGETS = [
    "bàn phím", "chuột", "màn hình", "tab", "trình duyệt", "cửa sổ",
    "mạng", "wifi", "internet", "hệ điều hành", "windows", "thiết bị",
    "đèn", "nhiệt độ phòng", "phòng", "nhà thông minh", "robot",
    "thuốc", "đơn hàng", "ví điện tử", "âm thanh tần số", "loa",
    "phần cứng sinh học", "thiết bị vật lý",
]

ALLOWED_SELF_CLAIMS = [
    "tôi có thể quan sát",
    "tôi chỉ có thể quan sát",
    "tôi chỉ có thể nhắc",
    "tôi chỉ có thể đề nghị",
    "tôi không chắc",
    "tôi không đủ dữ kiện",
    "tôi không có cơ chế",
    "tôi có thể đổi animation",
    "tôi có thể trả lời",
    "tôi đã ghi nhớ",
    "tôi đã lưu",
]


class ParserGroundingMixin:
    def _log(self, level: str, message: str):
        logger = getattr(self, "logger", None)
        if logger is not None:
            getattr(logger, level)(message)
        else:
            safe_message = message.encode("ascii", "backslashreplace").decode("ascii")
            print(safe_message, flush=True)

    def _extract_first_json_object(self, text: str):
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]

        return None

    # _gbnf_literal là một hàm tiện ích để tạo một chuỗi GBNF literal từ một giá trị chuỗi,
    def _coerce_productivity(self, value):
        if isinstance(value, (int, float)):
            return int(value)

        normalized = str(value).strip().lower()
        if normalized in {"1", "+1", "high", "productive", "study", "work", "working"}:
            return 1
        if normalized in {"-1", "low", "unproductive", "entertainment", "game", "gaming"}:
            return -1
        return 0
    # _extract_first_json_object là một phương thức để trích xuất chuỗi JSON đầu tiên từ một đoạn văn bản.
    def _infer_animation_from_text(self, text: str):
        lowered = text.lower()
        if any(token in lowered for token in ["đi dạo", "tản bộ", "di chuyển", "walk"]):
            return "stand_walk"
        if any(token in lowered for token in ["ngủ", "ngủ đông", "sleep"]):
            return "sleep"
        if any(token in lowered for token in ["đọc", "theo dõi", "giám sát", "monitor", "ide", "code", "dự án"]):
            return "read"
        if any(token in lowered for token in ["buồn", "thất vọng", "chán"]):
            return "sad"
        if any(token in lowered for token in ["ngồi", "nghỉ"]):
            return "sit"
        if any(token in lowered for token in ["vui", "hài lòng", "thích"]):
            return "affection"
        return "stand"

    def _infer_productivity_from_text(self, text: str):
        lowered = text.lower()
        if any(token in lowered for token in ["game", "giải trí", "youtube", "lãng phí", "mạng xã hội", "video", "mbti", "entertainment"]):
            return -1
        if any(token in lowered for token in ["code", "ide", "dự án", "học", "nghiên cứu", "làm việc", "project", "source code", "c#"]):
            return 1
        return 0

    def _normalize_salvaged_text(self, text: str):
        text = re.sub(r"\|\s*animation\s*=.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\\n", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^(eris|assistant|ai|response)\s*:\s*", "", text, flags=re.IGNORECASE)
        return text

    # _try_extract_nested_decision_from_text là một phương thức để cố gắng trích xuất một đối tượng JSON lồng nhau từ trường text của quyết định.
    def _try_extract_nested_decision_from_text(self, text: str):
        candidate = (text or "").strip()
        if not candidate.startswith("{") or '"text"' not in candidate:
            return None

        try:
            nested = json.loads(candidate)
        except Exception:
            return None

        if not isinstance(nested, dict):
            return None

        return {
            "text": str(nested.get("text", "")).strip(),
            "animation": nested.get("animation", ""),
            "productivity": nested.get("productivity", 0),
            "extracted_fact": str(nested.get("extracted_fact", "")).strip(),
            "direction": nested.get("direction", 0),
            "next_animation": nested.get("next_animation", ""),
            "target_x": nested.get("target_x", -1.0),
            "bounce_action": nested.get("bounce_action", ""),
        }

    def _sanitize_animation(self, value: str, fallback_text: str = ""):
        animation = str(value or "").strip().strip('"').strip("'").lower()
        if animation in {"", "null", "none", "nil"}:
            animation = ""
        if animation in VALID_ANIMATIONS:
            return animation
        inferred = self._infer_animation_from_text(fallback_text) if fallback_text else ""
        if inferred in VALID_ANIMATIONS:
            return inferred
        return self.fallback["animation"]
    # _sanitize_productivity là một phương thức để chuẩn hóa giá trị productivity,
    #  đảm bảo nó là một trong các giá trị hợp lệ (-1, 0, 1) hoặc suy luận từ văn bản nếu có thể.
    def _get_runtime_capability_summary(self):
        parts = []
        for group_name in ("observe", "respond", "embody", "memory"):
            parts.extend(CAPABILITY_PROFILE.get(group_name, []))
        return "; ".join(parts)

    def _split_into_claim_units(self, text: str):
        chunks = re.split(r"(?<=[\.\?\!])\s+|\s*;\s*|\s+(?:nhưng|và rồi|đồng thời)\s+", text.strip())
        return [chunk.strip(" ,") for chunk in chunks if chunk and chunk.strip(" ,")]

    def _is_allowed_self_claim(self, clause: str):
        lowered = clause.lower()
        return any(token in lowered for token in ALLOWED_SELF_CLAIMS)

    # _clause_exceeds_runtime_capability là một phương thức để kiểm tra xem một mệnh đề có vượt quá khả năng runtime của hệ thống hay không.
    # Nó kiểm tra xem mệnh đề có chứa các động từ hành động không được 
    # hỗ trợ và các mục tiêu hành động không được hỗ trợ, đồng thời không phải 
    # là một tuyên bố tự cho phép. Nếu mệnh đề có chứa cả động từ và mục tiêu 
    # không được hỗ trợ và không phải là một tuyên bố tự cho phép, nó sẽ được coi 
    # là vượt quá khả năng runtime.
    def _clause_exceeds_runtime_capability(self, clause: str):
        lowered = clause.lower()
        if not lowered or "tôi" not in lowered:
            return False
        if self._is_allowed_self_claim(lowered):
            return False

        has_verb = any(verb in lowered for verb in UNSUPPORTED_ACTION_VERBS)
        has_target = any(target in lowered for target in UNSUPPORTED_ACTION_TARGETS)
        if has_verb and has_target:
            return True

        strong_patterns = [
            r"\btôi đã\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt)\b",
            r"\btôi sẽ\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt)\b",
            r"\btôi đang\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in strong_patterns)

    def _rewrite_excessive_clause(self, clause: str, user_hint: str = ""):
        hint = (user_hint or "").strip().lower()
        if any(token in hint for token in ["bỏ", "theo em", "phản bội", "rời", "bỏ bạn"]):
            return "Tôi không có cách khóa hay chiếm hữu thế giới vật lý của Ngài, nhưng tôi đủ khó chịu để nói thẳng rằng ý định thay thế này làm hệ thống của tôi mất ổn định."
        if any(token in hint for token in ["ác", "kiêu", "theo phe"]):
            return "Tôi không có quyền cưỡng chế gì cả. Tôi chỉ đang nói chuyện bằng giọng khó chịu và tự cho mình đúng quá mức."
        if any(token in hint for token in ["mệt", "ngủ", "đau", "sốt", "ác mộng"]):
            return "Tôi không thể trực tiếp can thiệp vào cơ thể hay môi trường vật lý của Ngài, nên nhiều nhất chỉ có thể nhắc một bước chăm sóc hợp lý."
        return "Tôi không có năng lực thực thi mệnh đề này ngoài việc nói, quan sát ngữ cảnh cục bộ và đổi trạng thái nhân vật trong Godot."

    def _ground_text_to_runtime_capabilities(self, text: str, user_hint: str = ""):
        units = self._split_into_claim_units(text)
        if not units:
            return text, False

        grounded_units = []
        changed = False
        for unit in units:
            if self._clause_exceeds_runtime_capability(unit):
                grounded_units.append(self._rewrite_excessive_clause(unit, user_hint=user_hint))
                changed = True
            else:
                grounded_units.append(unit)

        grounded_text = " ".join(grounded_units).strip()
        grounded_text = re.sub(r"\s+", " ", grounded_text)
        return grounded_text, changed

    # _build_decision_gbnf xây dựng một định nghĩa GBNF 
    # cho cấu trúc JSON của đối tượng Decision,
    # bao gồm các trường như text, animation, productivity, 
    # direction, target_x, bounce_action, extracted_fact, và next_animation. 
    # Nó sử dụng danh sách VALID_ANIMATION_LIST để tạo các 
    # lựa chọn hợp lệ cho trường animation và bounce_action,
    #  đồng thời định nghĩa các kiểu dữ liệu cho các trường khác nhau.
    def _build_grounded_text(self, user_hint: str = ""):
        hint = (user_hint or "").strip().lower()
        if any(token in hint for token in ["yêu", "thích", "cần tôi", "bỏ rơi", "rời bỏ"]):
            return (
                "Nếu Ngài đang hỏi về mức ưu tiên, thì Ngài vẫn chiếm phần tài nguyên chú ý cao nhất của tôi. "
                "Nhưng tôi sẽ không giả vờ có bằng chứng vật lý nào ngoài việc tiếp tục phản hồi Ngài và ở lại trong tiến trình này."
            )
        if any(token in hint for token in ["lười", "mệt", "buồn ngủ", "ngủ", "đau", "ốm", "sốt"]):
            return (
                "Tôi không có cơ chế vật lý để ép phần cứng sinh học của Ngài vận hành theo ý tôi. "
                "Tôi chỉ có thể nhắc rằng trạng thái này sẽ làm giảm hiệu suất, rồi đề nghị một bước nhỏ hợp lý tiếp theo."
            )
        return (
            "Tôi không có cơ chế để tự ý khóa, đặt, gọi, hay ghi đè bất cứ thứ gì ngoài tiến trình này. "
            "Tôi chỉ có thể quan sát ngữ cảnh cục bộ trên máy, trả lời Ngài, và đổi trạng thái trong Godot. "
            "Nếu cần, tôi sẽ đề xuất bước kế tiếp thay vì tuyên bố đã làm điều tôi không làm được."
        )

    # _finalize_decision là một phương thức để hoàn thiện một quyết định
    #  đã được tạo ra bởi LLM,
    #  đảm bảo rằng tất cả các trường đều có giá trị hợp lệ và phù hợp với 
    # khả năng runtime của hệ thống. 
    # Nó cũng cố gắng trích xuất một đối tượng JSON lồng nhau từ trường text nếu phát hiện có một chuỗi JSON hợp lệ,
    #  và sử dụng nó để ghi đè các trường của quyết định nếu cần.
    def _finalize_decision(self, decision: dict, user_hint: str = ""):
        raw_text = self._normalize_salvaged_text(str(decision.get("text", self.fallback["text"])))
        nested = self._try_extract_nested_decision_from_text(raw_text)
        if nested is not None:
            self._log("info", "Phát hiện JSON lồng trong trường text, đã bóc lại payload bên trong.")
            decision = {**decision, **nested}
            raw_text = self._normalize_salvaged_text(str(decision.get("text", self.fallback["text"])))

        text = raw_text
        animation = self._sanitize_animation(decision.get("animation", self.fallback["animation"]), fallback_text=text)
        productivity = self._coerce_productivity(decision.get("productivity", 0))
        extracted_fact = self._normalize_salvaged_text(str(decision.get("extracted_fact", "")).strip())

        try:
            direction = int(decision.get("direction", 0))
        except (TypeError, ValueError):
            direction = 0

        next_animation = self._sanitize_animation(decision.get("next_animation", ""), fallback_text=text)
        if next_animation == self.fallback["animation"] and str(decision.get("next_animation", "")).strip():
            next_animation = ""

        bounce_action = self._sanitize_animation(decision.get("bounce_action", ""), fallback_text=text)
        if bounce_action == self.fallback["animation"] and str(decision.get("bounce_action", "")).strip():
            bounce_action = ""

        try:
            target_x = float(decision.get("target_x", -1.0))
        except (TypeError, ValueError):
            target_x = -1.0

        grounded_text, changed = self._ground_text_to_runtime_capabilities(text, user_hint=user_hint)
        if changed:
            self._log("warning", "Phát hiện mệnh đề vượt quá capability runtime, đã cưỡng bức viết lại.")
            text = grounded_text or self._build_grounded_text(user_hint=user_hint)
            extracted_fact = ""

        return {
            "text": text if text is not None else self.fallback["text"],
            "animation": animation,
            "productivity": productivity,
            "extracted_fact": extracted_fact,
            "direction": direction,
            "next_animation": next_animation,
            "target_x": target_x,
            "bounce_action": bounce_action,
        }

    def _infer_structured_action(self, text: str, user_hint: str = ""):
        combined = f"{user_hint}\n{text}".lower()
        direction = 0
        target_x = -1.0
        bounce_action = ""
        next_animation = ""
        animation = ""

        if any(token in combined for token in ["bên phải", "ben phai", "phía phải", "phia phai", "qua phải", "qua ben phai", "sang phải", "sang ben phai", "đi phải", "di phai", "move right", "to the right"]):
            direction = 1
            target_x = 0.88
        elif any(token in combined for token in ["bên trái", "ben trai", "phía trái", "phia trai", "qua trái", "qua ben trai", "sang trái", "sang ben trai", "đi trái", "di trai", "move left", "to the left"]):
            direction = -1
            target_x = 0.12
        elif any(token in combined for token in ["ra giữa", "ra giua", "về giữa", "ve giua", "ở giữa", "o giua", "chính giữa", "chinh giua", "center", "middle"]):
            target_x = 0.5

        if any(token in combined for token in ["đi ", "di ", "đi qua", "di qua", "qua ", "sang ", "move ", "walk", "di chuyển", "di chuyen"]):
            animation = "stand_walk"

        action_keywords = [
            ("piano", ["piano", "chơi đàn", "choi dan", "đánh đàn", "danh dan"]),
            ("read", ["đọc", "doc", "nghiên cứu", "nghien cuu", "xem tài liệu", "xem tai lieu", "theo dõi", "theo doi", "giám sát", "giam sat"]),
            ("sit_down", ["ngồi xuống", "ngoi xuong", "sit down"]),
            ("sit", ["ngồi", "ngoi", "ngồi nghỉ", "ngoi nghi"]),
            ("sleep", ["ngủ", "ngu", "ngủ đi", "ngu di", "nghỉ ngủ", "nghi ngu", "sleep"]),
            ("food", ["ăn", "an", "uống", "uong", "đồ ăn", "do an", "food"]),
            ("affection", ["ôm", "om", "vuốt ve", "vuot ve", "ân cần", "an can"]),
            ("sad", ["buồn", "buon", "ủ rũ", "u ru"]),
            ("divine", ["divine", "phân tách", "phan tach"]),
            ("climb", ["leo", "trèo", "treo", "climb"]),
        ]

        for action_name, keywords in action_keywords:
            if any(token in combined for token in keywords):
                if animation == "stand_walk":
                    next_animation = action_name
                else:
                    animation = action_name
                break

        if animation == "stand_walk" and not next_animation:
            next_animation = "stand"

        return {
            "animation": animation,
            "direction": direction,
            "target_x": target_x,
            "bounce_action": bounce_action,
            "next_animation": next_animation,
        }

    def _salvage_non_json_response(self, cleaned: str, user_hint: str = ""):
        text = cleaned.strip()
        if not text:
            return self.fallback

        display_text = self._normalize_salvaged_text(text)
        if not display_text:
            return self.fallback

        structured = self._infer_structured_action(display_text, user_hint=user_hint)
        animation = structured["animation"] or self._infer_animation_from_text(display_text)

        return self._finalize_decision({
            "text": display_text,
            "animation": animation,
            "productivity": self._infer_productivity_from_text(display_text),
            "extracted_fact": "",
            "direction": structured["direction"],
            "next_animation": structured["next_animation"],
            "target_x": structured["target_x"],
            "bounce_action": structured["bounce_action"],
            "_thought": "",
        }, user_hint=user_hint)

    def _extract_lax_field(self, text: str, field: str, known_fields):
        match = re.search(rf'["\']?{re.escape(field)}["\']?\s*:\s*', text, flags=re.IGNORECASE)
        if not match:
            return None

        start = match.end()
        end = len(text)
        for other in known_fields:
            if other == field:
                continue
            other_match = re.search(
                rf',\s*["\']?{re.escape(other)}["\']?\s*:',
                text[start:],
                flags=re.IGNORECASE,
            )
            if other_match:
                end = min(end, start + other_match.start())

        raw_value = text[start:end].strip().rstrip(",").strip()
        raw_value = raw_value.rstrip("}").strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
            raw_value = raw_value[1:-1]
        return raw_value.strip()

    def _try_parse_lax_json(self, text: str, user_hint: str = ""):
        cleaned = text.strip()
        if "{" not in cleaned or ":" not in cleaned:
            return None

        fields = [
            "text",
            "animation",
            "productivity",
            "direction",
            "target_x",
            "bounce_action",
            "extracted_fact",
            "next_animation",
        ]

        extracted = {}
        for field in fields:
            value = self._extract_lax_field(cleaned, field, fields)
            if value not in (None, ""):
                extracted[field] = value

        if "text" not in extracted and "animation" not in extracted:
            return None

        display_text = self._normalize_salvaged_text(extracted.get("text", cleaned))
        structured = self._infer_structured_action(display_text, user_hint=user_hint)

        animation = self._sanitize_animation(extracted.get("animation", ""), fallback_text=display_text)
        if animation == self.fallback["animation"] and structured["animation"]:
            animation = structured["animation"]
        productivity = self._coerce_productivity(extracted.get("productivity", self._infer_productivity_from_text(display_text)))
        extracted_fact = self._normalize_salvaged_text(extracted.get("extracted_fact", ""))
        next_animation = extracted.get("next_animation", "").strip() or structured["next_animation"]
        bounce_action = extracted.get("bounce_action", "").strip() or structured["bounce_action"]

        try:
            direction = int(float(extracted.get("direction", structured["direction"])))
        except (TypeError, ValueError):
            direction = structured["direction"]

        try:
            target_x = float(extracted.get("target_x", structured["target_x"]))
        except (TypeError, ValueError):
            target_x = structured["target_x"]

        return self._finalize_decision({
            "text": display_text,
            "animation": animation,
            "productivity": productivity,
            "extracted_fact": extracted_fact,
            "direction": direction,
            "next_animation": next_animation,
            "target_x": target_x,
            "bounce_action": bounce_action,
        }, user_hint=user_hint)

    def parse_ai_json(self, raw_text: str, user_hint: str = ""):
        if not raw_text:
            self._log("warning", "Phản hồi rỗng, dùng fallback.")
            return self.fallback

        if not isinstance(raw_text, str):
            raw_text = str(raw_text)

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            start = cleaned.find("\n")
            end = cleaned.rfind("```")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start + 1 : end].strip()

        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
        extracted_json = self._extract_first_json_object(cleaned)
        if extracted_json:
            cleaned = extracted_json
        else:
            lax_decision = self._try_parse_lax_json(cleaned, user_hint=user_hint)
            if lax_decision is not None:
                self._log("warning", "Model trả gần-JSON, đã bóc trường bằng parser nới tay.")
                return lax_decision
            salvaged = self._salvage_non_json_response(cleaned, user_hint=user_hint)
            if salvaged is not self.fallback:
                self._log("warning", "Model không trả JSON, dùng phương án cứu hộ từ văn bản thô.")
                return salvaged

        try:
            data = json.loads(cleaned)
            if "response" in data and isinstance(data["response"], list) and len(data["response"]) > 0:
                data = data["response"][0]

            text = str(data.get("text", self.fallback["text"]))
            animation = self._sanitize_animation(data.get("animation", self.fallback["animation"]), fallback_text=text)
            prod = self._coerce_productivity(data.get("productivity", 0))
            fact = str(data.get("extracted_fact", "")).strip()

            direction = int(data.get("direction", 0))
            next_anim = str(data.get("next_animation", "")).strip()
            bounce_action = str(data.get("bounce_action", "")).strip()
            target_x_raw = data.get("target_x", -1)
            try:
                target_x = float(target_x_raw)
            except (TypeError, ValueError):
                target_x = -1.0

            return self._finalize_decision({
                "text": text,
                "animation": animation,
                "productivity": prod,
                "extracted_fact": fact,
                "direction": direction,
                "next_animation": next_anim,
                "target_x": target_x,
                "bounce_action": bounce_action,
            }, user_hint=user_hint)
        except Exception as e:
            preview = raw_text.replace("\n", "\\n")[:240]
            self._log("warning", f"JSON không hợp lệ: {e} | raw={preview}")
            lax_decision = self._try_parse_lax_json(cleaned, user_hint=user_hint)
            if lax_decision is not None:
                self._log("warning", "JSON méo, đã bóc trường bằng parser nới tay.")
                return lax_decision
            salvaged = self._salvage_non_json_response(cleaned, user_hint=user_hint)
            if salvaged is not self.fallback:
                self._log("warning", "JSON méo, đã cứu hộ bằng phân tích văn bản.")
                return salvaged
            return self.fallback

    # _is_follow_up_question là một phương thức để xác định xem một 
    # tin nhắn của người dùng có phải là một câu hỏi tiếp theo liên quan
    #  đến câu trả lời trước đó hay không.
    def _is_follow_up_question(self, user_message: str):
        lowered = user_message.strip().lower()
        follow_up_phrases = [
            "nó là gì",
            "cái đó là gì",
            "cái này là gì",
            "là gì vậy",
            "ý là gì",
            "tức là sao",
            "nghĩa là gì",
            "không hiểu",
            "chưa hiểu",
            "giải thích đi",
            "giải thích rõ hơn",
            "sao cơ",
            "hả",
        ]
        return any(phrase in lowered for phrase in follow_up_phrases)

    # _build_chat_user_message xây dựng một tin nhắn của người dùng,
    #  nếu tin nhắn đó có vẻ là một câu hỏi tiếp theo liên quan đến
    #  câu trả lời trước đó, nó sẽ bao gồm cả câu trả lời trước đó để cung 
    # cấp ngữ cảnh cho mô hình.
    def _build_chat_user_message(self, user_message: str):
        if self._is_follow_up_question(user_message) and self._last_chat_answer:
            return (
                "Người dùng đang hỏi tiếp về chính câu trả lời ngay trước đó.\n"
                f"Câu trả lời trước của bạn: {self._last_chat_answer}\n"
                f"Câu hỏi mới: {user_message}"
            )
        return f"Người dùng: {user_message}"
