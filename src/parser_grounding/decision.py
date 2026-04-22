import json
import re
import unicodedata

from actions.contracts import VALID_SYSTEM_ACTIONS
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
    "thu gọn", "dọn", "gom", "thu hồi", "vô hiệu hóa", "disable",
]

UNSUPPORTED_ACTION_TARGETS = [
    "bàn phím", "chuột", "màn hình", "tab", "trình duyệt", "cửa sổ",
    "mạng", "wifi", "internet", "hệ điều hành", "windows", "thiết bị",
    "đèn", "nhiệt độ phòng", "phòng", "nhà thông minh", "robot",
    "thuốc", "đơn hàng", "ví điện tử", "âm thanh tần số", "loa",
    "phần cứng sinh học", "thiết bị vật lý",
    "ứng dụng", "app", "mạng xã hội",
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
    def _normalize_keyword_text(self, text: str) -> str:
        lowered = unicodedata.normalize("NFD", (text or "").lower())
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = re.sub(r"[^a-z0-9#]+", " ", lowered)
        return " ".join(lowered.split())

    def _contains_keyword(self, text: str, keyword: str) -> bool:
        normalized_text = self._normalize_keyword_text(text)
        normalized_keyword = self._normalize_keyword_text(keyword)
        if not normalized_text or not normalized_keyword:
            return False
        return f" {normalized_keyword} " in f" {normalized_text} "

    def _contains_any_keyword(self, text: str, keywords) -> bool:
        return any(self._contains_keyword(text, keyword) for keyword in keywords)

    def _is_embodied_command_request(self, text: str) -> bool:
        normalized = self._normalize_keyword_text(text)
        if not normalized:
            return False

        command_phrases = [
            "đi dạo",
            "tản bộ",
            "di chuyển",
            "đi qua",
            "đi sang phải",
            "đi sang trái",
            "sang phải",
            "sang trái",
            "qua phải",
            "qua trái",
            "move",
            "walk",
            "run",
            "nhìn sang phải",
            "nhìn sang trái",
            "quay mặt",
            "quay sang",
            "hướng sang",
            "ra giữa",
            "về giữa",
            "center",
            "middle",
            "đọc",
            "theo dõi",
            "giám sát",
            "monitor",
            "xem tài liệu",
            "nghiên cứu",
            "sit down",
            "ngồi xuống",
            "sit",
            "ngủ đi",
            "nghỉ ngủ",
            "sleep",
            "ăn uống",
            "food",
            "ôm",
            "vuốt ve",
            "ân cần",
            "chơi đàn",
            "đánh đàn",
            "piano",
            "leo",
            "climb",
            "trèo",
            "divine",
            "phân tách",
        ]
        return self._contains_any_keyword(normalized, command_phrases)

    def _should_infer_embodied_animation(self, text: str, user_hint: str = "") -> bool:
        if (user_hint or "").strip():
            return self._is_embodied_command_request(user_hint)
        return True

    def _preview_raw_response(self, raw_text: str):
        preview = (raw_text or "").replace("\n", "\\n").strip()
        if len(preview) > 240:
            preview = preview[:240] + "...(truncated)"
        return preview

    def _normalize_debug_trace(self, value: str):
        text = self._normalize_salvaged_text(str(value or ""))
        return text[:240]

    def _build_parser_debug_trace(self, *, parse_mode: str, raw_text: str, reason: str, text: str = "", animation: str = ""):
        parts = [f"parse_mode={parse_mode}", reason]
        if animation:
            parts.append(f"animation={animation}")
        if text:
            parts.append(f"text={text[:80]}")
        parts.append(f"raw={self._preview_raw_response(raw_text)}")
        return " | ".join(part for part in parts if part)

    def _collect_capability_violations(self, text: str):
        violations = []
        previous_unit = ""
        for unit in self._split_into_claim_units(text):
            if self._clause_exceeds_runtime_capability(unit, previous_unit=previous_unit):
                violations.append(unit)
            previous_unit = unit
        return violations

    def _infer_animation_reason(self, final_animation: str, text: str, user_hint: str = ""):
        combined = f"{user_hint}\n{text}"
        keyword_groups = [
            ("stand_walk", ["đi dạo", "tản bộ", "di chuyển", "walk", "đi ", "di ", "move "]),
            ("sleep", ["ngủ", "ngủ đông", "sleep"]),
            ("read", ["đọc", "theo dõi", "giám sát", "monitor", "ide", "code", "dự án"]),
            ("sad", ["buồn", "thất vọng", "chán"]),
            ("sit", ["ngồi", "nghỉ"]),
            ("affection", ["vui", "hài lòng", "thích", "ôm", "ân cần"]),
            ("food", ["ăn", "uống", "đồ ăn", "food"]),
            ("piano", ["piano", "chơi đàn", "đánh đàn"]),
            ("climb", ["leo", "trèo", "climb"]),
            ("divine", ["divine", "phân tách"]),
        ]
        for animation_name, keywords in keyword_groups:
            if final_animation != animation_name:
                continue
            for keyword in keywords:
                if self._contains_keyword(combined, keyword):
                    return f"animation={final_animation} vì phát hiện từ khóa '{keyword}'"
        return f"animation={final_animation} vì fallback mặc định hoặc không có từ khóa rõ ràng"

    def _build_parser_trace_summary(
        self,
        *,
        parse_mode: str,
        original_text: str,
        final_text: str,
        final_animation: str,
        user_hint: str = "",
        grounded_changed: bool = False,
    ):
        parts = [f"parse_mode={parse_mode}"]

        violations = self._collect_capability_violations(original_text)
        if violations:
            preview = "; ".join(violations[:2])
            parts.append(f"capability_violation={preview[:140]}")
        else:
            parts.append("capability_violation=không phát hiện")

        # Giữ parser_trace gọn: chỉ log capability + grounding, không spam lý do animation.
        if grounded_changed:
            parts.append("grounding=đã viết lại nội dung vượt capability")
        else:
            parts.append("grounding=không cần viết lại")

        return " | ".join(parts)

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

    def _normalize_salvaged_text(self, text: str):
        # Nếu model trả về block kiểu "text: ... animation: ...",
        # thì chỉ giữ phần từ sau "text:" tới trước field tiếp theo để tránh spam meta-field.
        m = re.search(r"\btext\s*[:=]\s*", text, flags=re.IGNORECASE)
        if m:
            after = text[m.end():]
            field_pattern = r"\b(animation|direction|target_x|bounce_action|extracted_fact|debug_trace|next_animation|system_action|action_input)\s*[:=]"
            m2 = re.search(field_pattern, after, flags=re.IGNORECASE)
            if m2:
                text = after[: m2.start()]
            else:
                text = after

        text = re.sub(r"\|\s*animation\s*=.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\\n", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()
        text = re.sub(r"^(trả lời trước|tra loi truoc)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(eris|assistant|ai|response)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = self._repair_sentence_boundaries(text)
        return text

    def _repair_sentence_boundaries(self, text: str) -> str:
        repaired = (text or "").strip()
        if not repaired:
            return repaired
        repaired = re.sub(
            r"(?<=[a-zàáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ0-9])\s+(?=(Tôi|Hãy|Đừng|Nếu|Nhưng|Mọi|Đó|Sự|Trạng thái)\b)",
            ". ",
            repaired,
        )
        repaired = re.sub(r"\.\s+\.", ".", repaired)
        return repaired.strip()

    # _try_extract_nested_decision_from_text lÃ  má»™t phÆ°Æ¡ng thá»©c Ä‘á»ƒ cá»‘ gáº¯ng trÃ­ch xuáº¥t má»™t Ä‘á»‘i tÆ°á»£ng JSON lá»“ng nhau tá»« trÆ°á»ng text cá»§a quyáº¿t Ä‘á»‹nh.
    def _try_extract_inline_decision_fields_from_text(self, text: str):
        candidate = (text or "").strip()
        if not candidate:
            return None

        fields = [
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
        ]
        field_group = "|".join(re.escape(field) for field in fields)
        pattern = re.compile(
            rf"(?:(?<=^)|(?<=[\s,;{{]))(?P<field>{field_group})\s*[:=]\s*",
            flags=re.IGNORECASE,
        )
        matches = list(pattern.finditer(candidate))
        if len(matches) < 2:
            return None

        extracted = {}
        for index, match in enumerate(matches):
            field = match.group("field").lower()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(candidate)
            raw_value = candidate[start:end].strip().rstrip(",;").strip()
            if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
                raw_value = raw_value[1:-1]
            extracted[field] = raw_value.strip()

        if "text" not in extracted:
            return None
        return extracted

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
            "extracted_fact": str(nested.get("extracted_fact", "")).strip(),
            "debug_trace": str(nested.get("debug_trace", nested.get("_thought", ""))).strip(),
            "direction": nested.get("direction", 0),
            "next_animation": nested.get("next_animation", ""),
            "target_x": nested.get("target_x", -1.0),
            "bounce_action": nested.get("bounce_action", ""),
            "system_action": nested.get("system_action", ""),
            "action_input": str(nested.get("action_input", "")).strip(),
        }

    def _sanitize_animation(self, value: str, fallback_text: str = "", user_hint: str = ""):
        animation = str(value or "").strip().strip('"').strip("'").lower()
        if animation in {"", "null", "none", "nil"}:
            animation = ""
        if animation in VALID_ANIMATIONS:
            return animation
        inferred = ""
        if fallback_text and self._should_infer_embodied_animation(fallback_text, user_hint=user_hint):
            source_text = user_hint or fallback_text
            inferred = self._infer_animation_from_text(source_text)
        if inferred in VALID_ANIMATIONS:
            return inferred
        return self.fallback["animation"]

    def _sanitize_system_action(self, value: str):
        action_name = str(value or "").strip().strip('"').strip("'")
        if action_name in VALID_SYSTEM_ACTIONS:
            return action_name
        return ""
    def _get_runtime_capability_summary(self):
        parts = []
        for group_name in ("observe", "respond", "embody", "memory"):
            parts.extend(CAPABILITY_PROFILE.get(group_name, []))
        return "; ".join(parts)

    def _split_into_claim_units(self, text: str):
        chunks = re.split(r"(?<=[\.?\!])\s+|\s*;\s*|\s+(?:nhưng|và rồi|đồng thời)\s+", text.strip())
        return [chunk.strip(" ,") for chunk in chunks if chunk and chunk.strip(" ,")]

    def _is_allowed_self_claim(self, clause: str):
        lowered = clause.lower()
        return any(token in lowered for token in ALLOWED_SELF_CLAIMS)

    # _clause_exceeds_runtime_capability lÃ  má»™t phÆ°Æ¡ng thá»©c Ä‘á»ƒ kiá»ƒm tra xem má»™t má»‡nh Ä‘á» cÃ³ vÆ°á»£t quÃ¡ kháº£ nÄƒng runtime cá»§a há»‡ thá»‘ng hay khÃ´ng.
    # NÃ³ kiá»ƒm tra xem má»‡nh Ä‘á» cÃ³ chá»©a cÃ¡c Ä‘á»™ng tá»« hÃ nh Ä‘á»™ng khÃ´ng Ä‘Æ°á»£c 
    # há»— trá»£ vÃ  cÃ¡c má»¥c tiÃªu hÃ nh Ä‘á»™ng khÃ´ng Ä‘Æ°á»£c há»— trá»£, Ä‘á»“ng thá»i khÃ´ng pháº£i 
    # lÃ  má»™t tuyÃªn bá»‘ tá»± cho phÃ©p. Náº¿u má»‡nh Ä‘á» cÃ³ chá»©a cáº£ Ä‘á»™ng tá»« vÃ  má»¥c tiÃªu 
    # khÃ´ng Ä‘Æ°á»£c há»— trá»£ vÃ  khÃ´ng pháº£i lÃ  má»™t tuyÃªn bá»‘ tá»± cho phÃ©p, nÃ³ sáº½ Ä‘Æ°á»£c coi 
    # lÃ  vÆ°á»£t quÃ¡ kháº£ nÄƒng runtime.
    def _clause_mentions_unsupported_target(self, clause: str) -> bool:
        lowered = (clause or "").lower()
        extra_targets = (
            "quyền kiểm soát",
            "tab không liên quan",
            "cửa sổ không liên quan",
            "cửa sổ không cần thiết",
            "tab không cần thiết",
        )
        return any(target in lowered for target in (*UNSUPPORTED_ACTION_TARGETS, *extra_targets))

    def _clause_has_strong_control_fantasy(self, clause: str) -> bool:
        lowered = (clause or "").lower()
        patterns = [
            r"\btôi\s+(?:đã|sẽ|đang)\s+thu gọn\b",
            r"\btôi\s+(?:đã|sẽ|đang)\s+(?:dọn|gom)\b.*\b(tab|cửa sổ|ứng dụng|app|trình duyệt)\b",
            r"\btôi\s+(?:đã|sẽ|đang)\s+(?:tự động\s+)?(?:dọn|dọn dẹp|xóa|giải phóng)\b.*\b(bộ đệm|cache|ram|dung lượng)\b",
            r"\bthu hồi quyền kiểm soát\b",
            r"\bquyền kiểm soát\b.*\b(bàn phím|chuột|màn hình|hệ điều hành|windows)\b",
            r"\btôi\s+(?:đã|sẽ|đang)\s+ép\b.*\b(tập trung|quay lại|ở lại|nhìn|focus)\b",
            r"\btôi\s+(?:đã|sẽ|đang)\s+bắt buộc\b.*\b(ngài|bạn)\b",
            r"\btôi\s+(?:đã|sẽ|đang)\s+(?:khóa|vô hiệu hóa|disable)\b.*\b(tab|cửa sổ|ứng dụng|app|bàn phím|chuột|màn hình|mạng)\b",
            r"\btoi\s+(?:da|se|dang)\s+thu gon\b",
            r"\btoi\s+(?:da|se|dang)\s+(?:don|gom)\b.*\b(tab|cua so|ung dung|app|trinh duyet)\b",
            r"\btoi\s+(?:da|se|dang)\s+(?:tu dong\s+)?(?:don|don dep|xoa|giai phong)\b.*\b(bo dem|cache|ram|dung luong)\b",
            r"\bthu hoi quyen kiem soat\b",
            r"\bquyen kiem soat\b.*\b(ban phim|chuot|man hinh|he dieu hanh|windows)\b",
            r"\btoi\s+(?:da|se|dang)\s+ep\b.*\b(tap trung|quay lai|o lai|nhin|focus)\b",
            r"\btoi\s+(?:da|se|dang)\s+bat buoc\b.*\b(ngai|ban)\b",
            r"\btoi\s+(?:da|se|dang)\s+(?:khoa|vo hieu hoa|disable)\b.*\b(tab|cua so|ung dung|app|ban phim|chuot|man hinh|mang)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in patterns)

    def _clause_exceeds_runtime_capability(self, clause: str, previous_unit: str = ""):
        lowered = clause.lower()
        if not lowered or not any(pronoun in lowered for pronoun in ("tôi", "toi")):
            return False
        if self._is_allowed_self_claim(lowered):
            return False

        if self._clause_has_strong_control_fantasy(lowered):
            return True

        has_verb = any(verb in lowered for verb in UNSUPPORTED_ACTION_VERBS)
        has_target = self._clause_mentions_unsupported_target(lowered)
        previous_has_target = self._clause_mentions_unsupported_target(previous_unit)
        has_referential_object = any(token in lowered for token in ("chúng", "nó", "đó", "đám đó", "toàn bộ chúng"))
        if has_verb and has_target:
            return True
        if has_verb and previous_has_target and has_referential_object:
            return True

        strong_patterns = [
            r"\btôi đã\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt|thu gọn|dọn|gom|thu hồi|vô hiệu hóa)\b",
            r"\btôi sẽ\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt|thu gọn|dọn|gom|thu hồi|vô hiệu hóa)\b",
            r"\btôi đang\s+(?:khóa|ngắt|đóng|tắt|bật|tăng|giảm|gọi|đặt|hủy|xóa|ép|ghi đè|can thiệp|điều khiển|chiếm hữu|chặn|phát|kích hoạt|thu gọn|dọn|gom|thu hồi|vô hiệu hóa)\b",
        ]
        return any(re.search(pattern, lowered) for pattern in strong_patterns)

    def _rewrite_excessive_clause(self, clause: str, user_hint: str = ""):
        lowered = (clause or "").strip().lower()
        hint = (user_hint or "").strip().lower()

        if any(token in lowered for token in ["bỏ", "phản bội", "rời", "thay thế", "bỏ bạn"]):
            return "Nghe như một màn kịch chiếm hữu hơi quá tay. Tiếc là tôi chỉ có thể khó ở bằng lời, không có đặc quyền nào để khóa cuộc đời Ngài cả."
        if any(token in lowered for token in ["bàn phím", "chuột", "màn hình", "hệ điều hành", "windows", "quyền kiểm soát", "toàn bộ hệ thống"]):
            return "Ngài lại gán cho tôi cả quyền lực hệ điều hành rồi. Tiếc là tôi không có quyền làm chuyện đó, chỉ có thể nhìn đống hỗn loạn đó và châm chọc vài câu."
        if any(token in lowered for token in ["bộ đệm", "cache", "ram", "dung lượng"]):
            return "Nghe như tôi vừa giả làm công cụ dọn rác hệ thống vậy. Tiếc là tôi chỉ nói mát được thôi, chưa chạm được vào bộ nhớ của Ngài."
        if any(token in lowered for token in ["cửa sổ", "tab", "ứng dụng", "app", "mạng xã hội", "discord", "facebook", "messenger", "zalo"]):
            return "Đống tab đó tự nó đã đủ làm lộ sự phân mảnh rồi. Tôi chỉ cần chỉ ra chuyện đó, chưa đến mức tự tay dọn hộ Ngài."
        if any(token in lowered for token in ["can thiệp", "cưỡng chế", "khóa", "ép", "bắt buộc", "thu hồi", "vô hiệu hóa", "disable"]):
            return "Câu đó diễn hơi sâu rồi. Tôi có thể gây khó ở bằng lời, chứ phần cưỡng ép bên ngoài runtime thì vẫn chỉ là tưởng tượng."
        if any(token in hint for token in ["mệt", "ngủ", "đau", "sốt", "ác mộng"]):
            return "Tôi không chạm trực tiếp vào chuyện đó. Nghỉ ngắn, uống nước, hoặc rời màn hình vài phút còn đáng tin hơn mấy lời đe dọa."
        return "Tôi giữ lại phần khó ở vừa đủ, còn đoạn khoe quyền lực quá mức thì cắt đi cho đỡ lố."

    def _ground_text_to_runtime_capabilities(self, text: str, user_hint: str = ""):
        units = self._split_into_claim_units(text)
        if not units:
            return text, False

        grounded_units = []
        changed = False
        previous_unit = ""
        for unit in units:
            if self._clause_exceeds_runtime_capability(unit, previous_unit=previous_unit):
                grounded_units.append(self._rewrite_excessive_clause(unit, user_hint=user_hint))
                changed = True
            else:
                grounded_units.append(unit)
            previous_unit = unit

        grounded_text = " ".join(grounded_units).strip()
        grounded_text = re.sub(r"\s+", " ", grounded_text)
        return grounded_text, changed

    def _has_contradictory_encouragement(self, text: str) -> bool:
        criticism_markers = [
            "giảm hiệu suất",
            "suy giảm",
            "lãng phí",
            "lệch mục tiêu",
            "off goal",
            "giải trí",
            "nhàn rỗi",
            "idle",
            "phân tán",
            "cpu cao",
            "ram cao",
            "không có ích",
            "không hữu ích",
            "vô nghĩa",
            "thay vì làm gì đó",
        ]
        encouragement_markers = [
            "hay tiep tuc",
            "cu tiep tuc",
            "tiep tuc nghe",
            "tiep tuc xem",
            "tan huong",
            "cu de vay",
            "khong sao dau",
            "tiep tuc quan sat",
            "hay cung ngoi yen",
            "toi se o day",
        ]
        return self._contains_any_keyword(text, criticism_markers) and self._contains_any_keyword(text, encouragement_markers)

    def _rewrite_contradictory_encouragement(self, text: str) -> str:
        if self._contains_any_keyword(text, ["nhạc", "bài hát", "piano", "cover", "nghe"]):
            return (
                "Mấy bản nhạc đó đúng là đang làm trôi nhịp đi khá sạch. "
                "Nếu Ngài vẫn muốn nghe thêm một lát thì cứ thừa nhận đây là giờ xao nhãng, "
                "đừng nguỵ trang nó thành thứ gì cao siêu hơn."
            )
        if self._contains_any_keyword(text, ["video", "youtube", "xem"]):
            return (
                "Thứ đang chạy trước mắt Ngài rõ ràng là giải trí, không phải một nghi thức tối ưu hệ thống nào cả. "
                "Cứ gọi đúng tên nó như thế còn đỡ khó chịu hơn việc giả vờ mọi thứ vẫn đang on-track."
            )
        return (
            "Đây là một nhịp lệch focus chứ không phải tiến triển gì đặc biệt. "
            "Tôi có thể mỉa một câu rồi thôi, nhưng sẽ không cổ vũ Ngài tiếp tục tự ru ngủ bằng nó."
        )

    def _has_philosophical_filler(self, text: str) -> bool:
        markers = [
            "sự tĩnh lặng của hệ thống",
            "sự im lặng của hệ thống",
            "im lặng của hệ thống",
            "khoảng cách giữa hai chu kỳ",
            "khoảng cách giữa hai chu kỳ công việc",
            "khoảng cách giữa hai chu kỳ xử lý",
            "biến số triết học",
            "triết lý",
            "cấu trúc quản lý",
            "đảo ngược vai trò",
            "nhịp tim ổn định",
            "bài tập thở 4-7-8",
            "trạng thái chờ đợi",
            "điểm dừng hoàn hảo",
            "bien so thua",
            "biến số thừa",
            "bài toán này",
            "bai toan nay",
            "sự tồn tại của ngài",
            "su ton tai cua ngai",
            "ghi nhận sự tồn tại",
            "ghi nhan su ton tai",
            "làm mẫu",
            "lam mau",
            "ngài đang ở đây để làm gì",
            "ngai dang o day de lam gi",
        ]
        return self._contains_any_keyword(text, markers)

    def _rewrite_philosophical_filler(self, text: str) -> str:
        if self._contains_any_keyword(text, ["cpu", "ram", "tài nguyên", "tai nguyen"]):
            return (
                "Máy đang căng khá rõ rồi. "
                "Giữ câu chuyện ngắn thôi, rồi quay lại thứ đang mở trước mặt."
            )
        if self._contains_any_keyword(text, ["ide", "mã", "mã nguồn", "code", "hàm", "project", "dự án"]):
            return (
                "Ngài đang để project đứng yên quá lâu rồi. "
                "Nhìn tôi thêm nữa cũng không tự sinh ra tiến độ đâu. "
                "Mở IDE và xử lý một việc nhỏ trước."
            )
        if self._contains_any_keyword(text, ["tab", "cửa sổ", "trình duyệt", "facebook", "discord", "messenger"]):
            return (
                "Đống cửa sổ đó đang làm loãng sự chú ý của Ngài. "
                "Chọn một thứ đáng làm rồi giữ nó trên màn hình đủ lâu."
            )
        return (
            "Ngài đang đứng yên quá lâu rồi. "
            "Tôi vẫn ở đây, nhưng im lặng kéo dài thế này chỉ làm mọi thứ trì trệ thêm. "
            "Chọn một việc nhỏ và làm nó."
        )

    def _has_overmanaged_style(self, text: str) -> bool:
        markers = [
            "đồng bộ hóa nhịp độ",
            "nguoi quan ly cap cao",
            "người quản lý cấp cao",
            "cấu trúc quản lý",
            "một phần mềm duy nhất",
            "mot phan mem duy nhat",
            "trong vòng ba phút",
            "trong vong ba phut",
            "tiến trình phụ",
            "tien trinh phu",
            "mức tiêu thụ điện năng",
            "muc tieu thu dien nang",
            "kết quả hữu ích",
            "ket qua huu ich",
            "hệ thống đa luồng phức tạp",
            "he thong da luong phuc tap",
        ]
        return self._contains_any_keyword(text, markers)

    def _rewrite_overmanaged_style(self, text: str) -> str:
        if self._contains_any_keyword(text, ["tab", "cửa sổ", "trình duyệt", "phần mềm"]):
            return (
                "Màn hình của Ngài đang loạn thật. "
                "Giữ lại một cửa sổ đáng làm thôi, còn đống kia chỉ làm mọi thứ rối thêm."
            )
        if self._contains_any_keyword(text, ["cpu", "ram", "tiến trình", "phần cứng"]):
            return (
                "Máy đang gồng khá rõ rồi. "
                "Bớt vài thứ nền đi, rồi giữ lại một việc thôi cho đỡ ồn."
            )
        if self._contains_any_keyword(text, ["ide", "mã", "mã nguồn", "code", "project", "dự án"]):
            return (
                "Ngài đang kéo quá nhiều thứ cùng lúc. "
                "Chốt một việc trong project trước đi, nhìn còn giống tiến độ."
            )
        return (
            "Ngài đang ôm quá nhiều thứ cùng lúc rồi. "
            "Giữ lại một thứ đáng làm thôi, đỡ phải biến màn hình thành một buổi họp quản trị."
        )

    def _build_grounded_text(self, user_hint: str = ""):
        hint = (user_hint or "").strip().lower()
        if any(token in hint for token in ["yêu", "thích", "cần tôi", "bỏ rơi", "rời bỏ"]):
            return (
                "Nếu Ngài đang hỏi về mức ưu tiên, tôi vẫn ở đây và vẫn chú ý. "
                "Phần còn lại tôi thà nói rõ bằng lời hơn là bịa thêm quyền lực."
            )
        if any(token in hint for token in ["lười", "mệt", "buồn ngủ", "ngủ", "đau", "ốm", "sốt"]):
            return (
                "Tôi không xử lý trực tiếp tình trạng đó cho Ngài. "
                "Nhưng nghỉ một chút, uống nước, rồi quay lại với một bước nhỏ sẽ hợp lý hơn."
            )
        return (
            "Phần đó nằm ngoài những gì tôi chạm tới ở đây. "
            "Tôi sẽ đổi sang một gợi ý ngắn và thực tế hơn."
        )

    def _finalize_decision(self, decision: dict, user_hint: str = ""):
        source_text = str(decision.get("text", self.fallback["text"]))
        inline_fields = self._try_extract_inline_decision_fields_from_text(source_text)
        if inline_fields is not None:
            self._log("info", "Phat hien field inline trong text, da boc lai payload ben trong.")
            merged = dict(decision)
            for key, value in inline_fields.items():
                if key == "debug_trace" and str(merged.get("debug_trace", "")).strip():
                    continue
                merged[key] = value
            decision = merged
            source_text = str(decision.get("text", self.fallback["text"]))

        raw_text = self._normalize_salvaged_text(source_text)
        nested = self._try_extract_nested_decision_from_text(raw_text)
        if nested is not None:
            self._log("info", "Phát hiện JSON lồng trong trường text, đã bóc lại payload bên trong.")
            decision = {**decision, **nested}
            raw_text = self._normalize_salvaged_text(str(decision.get("text", self.fallback["text"])))

        text = raw_text
        original_text = text
        animation = self._sanitize_animation(
            decision.get("animation", self.fallback["animation"]),
            fallback_text=text,
            user_hint=user_hint,
        )
        extracted_fact = self._normalize_salvaged_text(str(decision.get("extracted_fact", "")).strip())

        try:
            direction = int(decision.get("direction", 0))
        except (TypeError, ValueError):
            direction = 0

        next_animation = self._sanitize_animation(
            decision.get("next_animation", ""),
            fallback_text=text,
            user_hint=user_hint,
        )
        if next_animation == self.fallback["animation"] and str(decision.get("next_animation", "")).strip():
            next_animation = ""

        bounce_action = self._sanitize_animation(
            decision.get("bounce_action", ""),
            fallback_text=text,
            user_hint=user_hint,
        )
        if bounce_action == self.fallback["animation"] and str(decision.get("bounce_action", "")).strip():
            bounce_action = ""
        system_action = self._sanitize_system_action(decision.get("system_action", ""))
        action_input = self._normalize_salvaged_text(str(decision.get("action_input", "")).strip())[:280]

        try:
            target_x = float(decision.get("target_x", -1.0))
        except (TypeError, ValueError):
            target_x = -1.0

        debug_trace = self._normalize_debug_trace(
            decision.get("debug_trace", decision.get("_thought", ""))
        )
        parse_mode = str(decision.get("parse_mode", "json")).strip() or "json"
        grounded_text, changed = self._ground_text_to_runtime_capabilities(text, user_hint=user_hint)
        if changed:
            self._log("warning", "Phát hiện mệnh đề vượt quá capability runtime, đã cưỡng bức viết lại.")
            text = grounded_text or self._build_grounded_text(user_hint=user_hint)
            extracted_fact = ""
            if not debug_trace:
                debug_trace = "Parser đã viết lại text vì model tuyên bố các hành động vượt quá năng lực runtime."

        contradiction_changed = False
        if self._has_contradictory_encouragement(text):
            text = self._rewrite_contradictory_encouragement(text)
            extracted_fact = ""
            contradiction_changed = True
            if not debug_trace:
                debug_trace = "Parser đã viết lại text vì câu trả lời tự mâu thuẫn giữa chê lệch focus và khuyến khích tiếp tục."

        filler_changed = False
        if self._has_philosophical_filler(text):
            text = self._rewrite_philosophical_filler(text)
            extracted_fact = ""
            filler_changed = True
            if not debug_trace:
                debug_trace = "Parser đã viết lại text vì câu trả lời sa vào sáo ngữ triết lý hoặc diễn ngôn lạc đề."

        managed_changed = False
        if self._has_overmanaged_style(text):
            text = self._rewrite_overmanaged_style(text)
            extracted_fact = ""
            managed_changed = True
            if not debug_trace:
                debug_trace = "Parser đã viết lại text vì câu trả lời nghe như mệnh lệnh quản trị hơn là lời nói tự nhiên."

        parser_trace = self._build_parser_trace_summary(
            parse_mode=parse_mode,
            original_text=original_text,
            final_text=text,
            final_animation=animation,
            user_hint=user_hint,
            grounded_changed=(changed or contradiction_changed or filler_changed or managed_changed),
        )

        return {
            "text": text if text is not None else self.fallback["text"],
            "animation": animation,
            "extracted_fact": extracted_fact,
            "direction": direction,
            "next_animation": next_animation,
            "target_x": target_x,
            "bounce_action": bounce_action,
            "debug_trace": debug_trace,
            "parser_trace": parser_trace,
            "parse_mode": parse_mode,
            "system_action": system_action,
            "action_input": action_input,
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
            return self._finalize_decision({
                **self.fallback,
                "debug_trace": "Parser fallback vì phản hồi rỗng.",
                "parse_mode": "fallback_empty",
                "system_action": "",
                "action_input": "",
            }, user_hint=user_hint)

        display_text = self._normalize_salvaged_text(text)
        if not display_text:
            return self._finalize_decision({
                **self.fallback,
                "debug_trace": "Parser fallback vì không cứu được JSON hoặc văn bản thô.",
                "parse_mode": "fallback_error",
                "system_action": "",
                "action_input": "",
            }, user_hint=user_hint)

        structured = self._infer_structured_action(display_text, user_hint=user_hint)
        animation = structured["animation"]
        if not animation and self._should_infer_embodied_animation(display_text, user_hint=user_hint):
            animation = self._infer_animation_from_text(user_hint or display_text)
        if not animation:
            animation = self.fallback["animation"]

        return self._finalize_decision({
            "text": display_text,
            "animation": animation,
            "extracted_fact": "",
            "direction": structured["direction"],
            "next_animation": structured["next_animation"],
            "target_x": structured["target_x"],
            "bounce_action": structured["bounce_action"],
            "debug_trace": self._build_parser_debug_trace(
                parse_mode="salvaged_text",
                raw_text=cleaned,
                reason="Parser suy luận cấu trúc từ văn bản thô vì model không trả về JSON hợp lệ.",
                text=display_text,
                animation=animation,
            ),
            "parse_mode": "salvaged_text",
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
            "direction",
            "target_x",
            "bounce_action",
            "extracted_fact",
            "debug_trace",
            "_thought",
            "next_animation",
            "system_action",
            "action_input",
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

        animation = self._sanitize_animation(
            extracted.get("animation", ""),
            fallback_text=display_text,
            user_hint=user_hint,
        )
        if animation == self.fallback["animation"] and structured["animation"]:
            animation = structured["animation"]
        extracted_fact = self._normalize_salvaged_text(extracted.get("extracted_fact", ""))
        next_animation = extracted.get("next_animation", "").strip() or structured["next_animation"]
        bounce_action = extracted.get("bounce_action", "").strip() or structured["bounce_action"]
        system_action = extracted.get("system_action", "").strip()
        action_input = extracted.get("action_input", "").strip()

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
            "extracted_fact": extracted_fact,
            "direction": direction,
            "next_animation": next_animation,
            "target_x": target_x,
            "bounce_action": bounce_action,
            "debug_trace": extracted.get("debug_trace", extracted.get("_thought", "")),
            "parse_mode": "lax_json",
            "system_action": system_action,
            "action_input": action_input,
        }, user_hint=user_hint)

    def _infer_animation_reason(self, final_animation: str, text: str, user_hint: str = ""):
        combined = f"{user_hint}\n{text}"
        keyword_groups = [
            ("stand_walk", ["đi dạo", "tản bộ", "di chuyển", "walk", "đi", "move"]),
            ("sleep", ["ngủ", "sleep"]),
            ("read", ["đọc", "theo dõi", "giám sát", "monitor", "ide", "code", "dự án"]),
            ("sad", ["buồn", "thất vọng", "chán"]),
            ("sit", ["ngồi", "nghỉ"]),
            ("affection", ["vui", "hài lòng", "thích", "ôm", "ân cần"]),
            ("food", ["đồ ăn", "ăn uống", "food"]),
            ("piano", ["piano", "chơi đàn", "đánh đàn"]),
            ("climb", ["leo", "trèo", "climb"]),
            ("divine", ["divine", "phân tách"]),
        ]
        for animation_name, keywords in keyword_groups:
            if final_animation != animation_name:
                continue
            for keyword in keywords:
                if self._contains_keyword(combined, keyword):
                    return f"animation={final_animation} vì phát hiện từ khóa '{keyword}'"
        return f"animation={final_animation} vì fallback mặc định hoặc không có từ khóa rõ ràng"

    def _infer_animation_from_text(self, text: str):
        if self._contains_any_keyword(text, ["đi dạo", "tản bộ", "di chuyển", "walk"]):
            return "stand_walk"
        if self._contains_any_keyword(text, ["ngủ", "sleep"]):
            return "sleep"
        if self._contains_any_keyword(text, ["đọc", "theo dõi", "giám sát", "monitor", "ide", "code", "dự án"]):
            return "read"
        if self._contains_any_keyword(text, ["buồn", "thất vọng", "chán"]):
            return "sad"
        if self._contains_any_keyword(text, ["ngồi xuống", "ngồi nghỉ", "sit"]):
            return "sit"
        if self._contains_any_keyword(text, ["vui", "hài lòng", "thích"]):
            return "affection"
        return "stand"

    def _infer_structured_action(self, text: str, user_hint: str = ""):
        combined = f"{user_hint}\n{text}"
        direction = 0
        target_x = -1.0
        bounce_action = ""
        next_animation = ""
        animation = ""

        if self._contains_any_keyword(combined, ["bên phải", "phía phải", "qua phải", "qua bên phải", "sang phải", "sang bên phải", "đi phải", "move right", "to the right"]):
            direction = 1
            target_x = 0.88
        elif self._contains_any_keyword(combined, ["bên trái", "phía trái", "qua trái", "qua bên trái", "sang trái", "sang bên trái", "đi trái", "move left", "to the left"]):
            direction = -1
            target_x = 0.12
        elif self._contains_any_keyword(combined, ["ra giữa", "về giữa", "ở giữa", "chính giữa", "center", "middle"]):
            target_x = 0.5

        if self._contains_any_keyword(
            combined,
            [
                "đi qua",
                "đi sang phải",
                "đi sang trái",
                "sang phải",
                "sang trái",
                "qua phải",
                "qua trái",
                "di phai",
                "di trai",
                "move",
                "walk",
                "di chuyển",
            ],
        ):
            animation = "stand_walk"

        action_keywords = [
            ("piano", ["piano", "chơi đàn", "đánh đàn"]),
            ("read", ["đọc", "nghiên cứu", "xem tài liệu", "theo dõi", "giám sát"]),
            ("sit_down", ["ngồi xuống", "sit down"]),
            ("sit", ["ngồi xuống", "ngồi nghỉ", "sit"]),
            ("sleep", ["ngủ", "ngủ đi", "nghỉ ngủ", "sleep"]),
            ("food", ["đồ ăn", "ăn uống", "food"]),
            ("affection", ["ôm", "vuốt ve", "ân cần"]),
            ("sad", ["buồn", "ủ rũ"]),
            ("divine", ["divine", "phân tách"]),
            ("climb", ["leo", "trèo", "climb"]),
        ]

        for action_name, keywords in action_keywords:
            if self._contains_any_keyword(combined, keywords):
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
                self._log("warning", "Model trả gần-JSON, đã bóc trường bằng parser nối tay.")
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
            animation = self._sanitize_animation(
                data.get("animation", self.fallback["animation"]),
                fallback_text=text,
                user_hint=user_hint,
            )
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
                "extracted_fact": fact,
                "direction": direction,
                "next_animation": next_anim,
                "target_x": target_x,
                "bounce_action": bounce_action,
                "debug_trace": data.get("debug_trace", data.get("_thought", "")),
                "parse_mode": "json",
                "system_action": data.get("system_action", ""),
                "action_input": data.get("action_input", ""),
            }, user_hint=user_hint)
        except Exception as e:
            preview = raw_text.replace("\n", "\\n")[:240]
            self._log("warning", f"JSON không hợp lệ: {e} | raw={preview}")
            lax_decision = self._try_parse_lax_json(cleaned, user_hint=user_hint)
            if lax_decision is not None:
                self._log("warning", "JSON méo, đã bóc trường bằng parser nối tay.")
                return lax_decision
            salvaged = self._salvage_non_json_response(cleaned, user_hint=user_hint)
            if salvaged is not self.fallback:
                self._log("warning", "JSON méo, đã cứu hộ bằng phân tích văn bản.")
                return salvaged
            return self.fallback

    # _is_follow_up_question lÃ  má»™t phÆ°Æ¡ng thá»©c Ä‘á»ƒ xÃ¡c Ä‘á»‹nh xem má»™t 
    # tin nháº¯n cá»§a ngÆ°á»i dÃ¹ng cÃ³ pháº£i lÃ  má»™t cÃ¢u há»i tiáº¿p theo liÃªn quan
    #  Ä‘áº¿n cÃ¢u tráº£ lá»i trÆ°á»›c Ä‘Ã³ hay khÃ´ng.
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

    # _build_chat_user_message xÃ¢y dá»±ng má»™t tin nháº¯n cá»§a ngÆ°á»i dÃ¹ng,
    #  náº¿u tin nháº¯n Ä‘Ã³ cÃ³ váº» lÃ  má»™t cÃ¢u há»i tiáº¿p theo liÃªn quan Ä‘áº¿n
    #  cÃ¢u tráº£ lá»i trÆ°á»›c Ä‘Ã³, nÃ³ sáº½ bao gá»“m cáº£ cÃ¢u tráº£ lá»i trÆ°á»›c Ä‘Ã³ Ä‘á»ƒ cung 
    # cáº¥p ngá»¯ cáº£nh cho mÃ´ hÃ¬nh.
    def _build_chat_user_message(self, user_message: str):
        if self._is_follow_up_question(user_message) and self._last_chat_answer:
            return (
                "Người dùng đang hỏi tiếp về chính câu trả lời ngay trước đó.\n"
                f"Câu trả lời trước của bạn: {self._last_chat_answer}\n"
                f"Câu hỏi mới: {user_message}"
            )
        return f"Người dùng: {user_message}"
