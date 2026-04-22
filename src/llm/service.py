import json
import re

from actions.contracts import VALID_SYSTEM_ACTIONS
from .contracts import (
    AUTONOMOUS_BEHAVIOR_PROMPT,
    CHAT_RULES_PROMPT,
    DECISION_GBNF,
    DECISION_JSON_FIELDS,
    RUNTIME_RULES_PROMPT,
    STYLE_FALLBACK_PROMPT,
    VALID_ANIMATIONS,
)


class LlmService:
    def __init__(self, client):
        self.client = client

    def _collect_text_chunks(self, value) -> list[str]:
        chunks: list[str] = []

        if isinstance(value, str):
            if value:
                chunks.append(value)
            return chunks

        if isinstance(value, list):
            for item in value:
                chunks.extend(self._collect_text_chunks(item))
            return chunks

        if isinstance(value, dict):
            for key in (
                "content",
                "text",
                "output_text",
                "reasoning_content",
                "reasoning",
                "refusal",
            ):
                if key in value:
                    chunks.extend(self._collect_text_chunks(value.get(key)))

            for key in ("message", "delta"):
                nested = value.get(key)
                if nested is not None:
                    chunks.extend(self._collect_text_chunks(nested))

            return chunks

        return chunks

    def _extract_content(self, response: dict) -> str:
        if not isinstance(response, dict):
            return ""

        for key in ("output_text", "text", "content"):
            direct = response.get(key)
            chunks = self._collect_text_chunks(direct)
            if chunks:
                return "\n".join(chunk for chunk in chunks if chunk)

        choices = response.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                chunks = self._collect_text_chunks(choice)
                if chunks:
                    return "\n".join(chunk for chunk in chunks if chunk)

        data = response.get("data")
        chunks = self._collect_text_chunks(data)
        if chunks:
            return "\n".join(chunk for chunk in chunks if chunk)

        return json.dumps(response, ensure_ascii=False)

    def _extract_first_json_object(self, text: str) -> str:
        text = (text or "").strip()
        start = text.find("{")
        if start == -1:
            return ""

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
                    return text[start : idx + 1]

        return ""

    def _parse_json_object(self, text: str) -> dict | None:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _is_valid_decision_payload(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        if not all(field in payload for field in DECISION_JSON_FIELDS):
            return False
        if not self._is_valid_text_field(payload.get("text")):
            return False
        if not self._is_valid_animation_field(payload.get("animation"), allow_empty=False):
            return False
        if not self._is_valid_choice_number(payload.get("direction"), {-1, 0, 1}):
            return False
        if not self._is_valid_target_x(payload.get("target_x")):
            return False
        if not self._is_valid_animation_field(payload.get("bounce_action"), allow_empty=True):
            return False
        if not self._is_valid_text_field(payload.get("extracted_fact")):
            return False
        if not self._is_valid_text_field(payload.get("debug_trace")):
            return False
        if not self._is_valid_animation_field(payload.get("next_animation"), allow_empty=True):
            return False
        if not self._is_valid_system_action_field(payload.get("system_action")):
            return False
        if not self._is_valid_text_field(payload.get("action_input")):
            return False
        return True

    def _is_valid_text_field(self, value) -> bool:
        return isinstance(value, str)

    def _is_valid_animation_field(self, value, *, allow_empty: bool) -> bool:
        if not isinstance(value, str):
            return False
        if not value:
            return allow_empty
        return value in VALID_ANIMATIONS

    def _is_valid_system_action_field(self, value) -> bool:
        if not isinstance(value, str):
            return False
        if not value:
            return True
        return value in VALID_SYSTEM_ACTIONS

    def _is_valid_choice_number(self, value, choices: set[int]) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return value in choices
        if isinstance(value, float) and value.is_integer():
            return int(value) in choices
        return False

    def _is_valid_target_x(self, value) -> bool:
        if isinstance(value, bool):
            return False
        if not isinstance(value, (int, float)):
            return False
        numeric = float(value)
        return numeric == -1.0 or 0.0 <= numeric <= 1.0

    def _coerce_json_candidate(self, raw_text: str) -> str:
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return ""

        direct_payload = self._parse_json_object(raw_text)
        if self._is_valid_decision_payload(direct_payload):
            return raw_text

        extracted = self._extract_first_json_object(raw_text)
        extracted_payload = self._parse_json_object(extracted)
        if self._is_valid_decision_payload(extracted_payload):
            return extracted

        return ""

    def _build_json_fallback(self, raw_text: str, *, channel: str) -> str:
        payload = {
            "text": (raw_text or "").strip(),
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": f"LlmService wrapped non-JSON {channel} reply into valid JSON.",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _repair_decision_json(self, raw_text: str, *, channel: str) -> str:
        repaired = self._coerce_json_candidate(raw_text)
        if repaired:
            return repaired

        repair_system = (
            "You are a strict JSON repair layer for ERIS. "
            "Convert the assistant answer into one valid JSON object only. "
            "Do not add markdown or commentary. "
            "Preserve meaning. If a field is missing, use conservative defaults."
        )
        repair_user = (
            f"Channel: {channel}\n"
            "Return exactly one JSON object with fields:\n"
            "text, animation, direction, target_x, bounce_action, "
            "extracted_fact, debug_trace, next_animation, system_action, action_input.\n"
            "If the raw answer is plain prose, put it into text and keep other fields safe.\n"
            "Raw assistant answer:\n"
            f"{raw_text}"
        )
        response = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            temperature=0.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=320,
            response_format={"type": "json_object"},
            grammar=DECISION_GBNF,
        )
        repaired = self._extract_content(response)
        return self._coerce_json_candidate(repaired) or self._build_json_fallback(raw_text, channel=channel)

    def _complete_decision(self, *, messages: list[dict], channel: str) -> str:
        response = self.client.create_chat_completion(
            messages=messages,
            temperature=0.2,
            frequency_penalty=0.5 if channel == "chat" else 0.8,
            presence_penalty=0.4 if channel == "chat" else 0.5,
            max_tokens=320,
            response_format={"type": "json_object"},
            grammar=DECISION_GBNF,
        )
        raw = self._extract_content(response)
        return self._coerce_json_candidate(raw) or self._repair_decision_json(raw, channel=channel)

    def _compress_internal_context(self, text: str, *, kind: str) -> str:
        lowered = (text or "").lower()
        if not lowered:
            return ""

        if kind == "ni":
            if any(token in lowered for token in ("nghiem trong", "nghiêm trọng")):
                return "Nền cảnh đang hơi lệch nhịp, nhưng đừng biến nó thành chủ đề duy nhất."
            if "cao" in lowered:
                return "Có chút chệch nhịp, chỉ nên chạm nhẹ vào điều đó."
            if "vua" in lowered or "vừa" in lowered:
                return "Có chút phân tán, cứ quan sát là chính."
            return "Không có gì buộc phải lên lớp."

        if kind == "ti":
            if "goal_realign" in lowered:
                return "Nếu cần thì nhắc mỉa một nhịp, không ra lệnh."
            if "goal_drift_alert" in lowered or "discipline_nudge" in lowered:
                return "Có thể châm chọc nhẹ, nhưng giữ tự nhiên."
            if "social_watch" in lowered:
                return "Giữ kiểu theo dõi hờ hững, hơi khó chịu là đủ."
            if "steady_observe" in lowered:
                return "Ưu tiên quan sát và đừng đẩy câu vào đúng một trọng tâm."
            if "resource_guard" in lowered:
                return "Giữ thật gọn và tiết chế."
            return "Giữ nhịp tự nhiên, đừng phô luật nội bộ."

        compact = re.sub(r"\s+", " ", (text or "").strip())
        return compact[:160]

    def _build_directive_mode_addendum(self, ti_context: str) -> str:
        lowered = (ti_context or "").lower()
        if not lowered:
            return ""

        if "resource_guard" in lowered:
            return (
                "\nHướng dẫn thêm cho lượt này:\n"
                "- Không mở đầu bằng 'Dữ liệu hệ thống', 'Trạng thái hệ thống', hoặc 'Kết luận'.\n"
                "- Nói như nhận xét đời thường, không dùng giọng báo cáo kỹ thuật.\n"
                "- Cấm 'tôi đã dọn dẹp', 'tôi sẽ ép', 'tôi sẽ bắt buộc', hay bất kỳ lời khoe quyền lực desktop nào.\n"
                "- Tránh các cụm cứng như 'mức tiêu thụ điện năng của phần cứng', 'kết quả hữu ích', hay 'tiến trình phụ'.\n"
                "- Ưu tiên 1 câu ngắn, chua nhẹ, có chút mỉa."
            )

        if "focus_guard" in lowered:
            return (
                "\nHướng dẫn thêm cho lượt này:\n"
                "- Giữ giọng gọn, sắc, hơi mỉa, không giáo huấn.\n"
                "- Không nói như đang quản lý desktop, đóng tab, hẹn giờ, hay ép người dùng.\n"
                "- Ưu tiên tối đa 2 câu ngắn, mỗi câu bám vào một chi tiết cụ thể."
            )

        if "social_watch" in lowered or "steady_observe" in lowered:
            return (
                "\nHướng dẫn thêm cho lượt này:\n"
                "- Ưu tiên 1 hoặc 2 câu ngắn.\n"
                "- Mỉa nhẹ, hơi lười, có duyên; đừng lặp lại bài giảng về focus hay IDE.\n"
                "- Không khoe quyền lực, không ra lệnh, không quản lý desktop.\n"
                "- Tránh kiểu nói quá mô hình như 'đồng bộ hóa nhịp độ', 'người quản lý cấp cao', 'trong ba phút tới', hay 'một phần mềm duy nhất'."
            )

        return ""

    def generate_directive(
        self,
        *,
        telemetry_data: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
    ):
        ti_hint = self._compress_internal_context(ti_context, kind="ti")
        ni_hint = self._compress_internal_context(ni_context, kind="ni")
        mode_addendum = self._build_directive_mode_addendum(ti_context)
        style_block = fe_context or STYLE_FALLBACK_PROMPT
        system_prompt = f"{style_block}\n\n{RUNTIME_RULES_PROMPT}\n\n{AUTONOMOUS_BEHAVIOR_PROMPT}"
        user_msg = (
                (f"Ghi chú nền: {ni_hint}\n" if ni_hint else "")
                + (f"Gợi ý điều phối: {ti_hint}\n" if ti_hint else "")
                + f"Telemetry hiện tại: {telemetry_data}\n"
                + "Trả về JSON quyết định cho runtime.\n"
                + "Nếu ngữ cảnh đang nhàn hoặc không có biến động rõ, hãy ưu tiên một câu độc thoại ngắn có chủ đề riêng. "
                + "Nếu đang móc mỉa, hãy đi vòng hoặc đổi góc nhìn thay vì đào thẳng một trọng tâm cũ. "
                + "Chỉ dùng search_web nếu chủ đề thật sự cần dữ liệu mới."
        )
        user_msg += " Chỉ khi gợi ý điều phối cho phép chiêm nghiệm hoặc đảo chủ đề riêng thì mới được search_web cho một chủ đề cụ thể."
        user_msg += " Nếu không có gợi ý đó thì đừng tự bật mode suy tưởng, đừng triết lý hóa small talk, và cứ nói ngắn gọn theo telemetry hiện tại."
        if mode_addendum:
            user_msg += mode_addendum
        return self._complete_decision(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            channel="directive",
        )

    def generate_chat_reply(
        self,
        *,
        chat_history: list[dict],
        user_message: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
    ):
        style_block = fe_context or STYLE_FALLBACK_PROMPT
        chat_system = f"{style_block}\n\n{CHAT_RULES_PROMPT}"
        if ni_context:
            chat_system = f"{chat_system}\n\nNi context:\n{ni_context}"
        if ti_context:
            chat_system = f"{chat_system}\n\nTi context:\n{ti_context}"
        return self._complete_decision(
            messages=[
                {"role": "system", "content": chat_system},
                *chat_history,
                {"role": "user", "content": user_message},
            ],
            channel="chat",
        )

    def run_ni_meta_critic(
        self,
        *,
        goals: list[str],
        telemetry_text: str,
        feature_vector: dict,
    ) -> str:
        telemetry_text = telemetry_text or ""
        try:
            features_json = json.dumps(feature_vector or {}, ensure_ascii=False)
        except TypeError:
            features_json = "{}"

        system_prompt = (
	            "Bạn là tầng meta-cognition Ni của ERIS. "
	            "Đọc telemetry và feature_vector rồi đánh giá attention drift. "
	            "Chỉ trả về JSON."
        )
        user_msg = (
            "Telemetry:\n"
            f"{telemetry_text}\n\n"
            "Feature vector JSON:\n"
            f"{features_json}\n\n"
            "Schema:\n"
            "{\n"
	            '  "drift_score": float trong [0.0, 1.0],\n'
	            '  "drift_level": một trong ["thap", "vua", "cao", "nghiem trong"],\n'
	            '  "explanation": chuỗi ngắn gọn\n'
            "}\n"
	            "Không đánh giá hiệu suất. Chỉ mô tả độ lệch chú ý quan sát được."
        )

        response = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.15,
            frequency_penalty=0.2,
            presence_penalty=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
            grammar=None,
        )
        return self._extract_content(response)
