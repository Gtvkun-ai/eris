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

    def _normalize_payload_keys(self, value):
        if isinstance(value, list):
            return [self._normalize_payload_keys(item) for item in value]
        if not isinstance(value, dict):
            return value

        normalized = {}
        for key, item in value.items():
            normalized_key = key.strip() if isinstance(key, str) else key
            normalized_item = self._normalize_payload_keys(item)
            if normalized_key in normalized and normalized_key != key:
                continue
            normalized[normalized_key] = normalized_item
        return normalized

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
        if not self._allows_motion_target(payload) and float(payload.get("target_x", -1.0)) != -1.0:
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

    def _is_decision_like_payload(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        if all(field in payload for field in DECISION_JSON_FIELDS):
            return True
        if "text" in payload and any(field in payload for field in DECISION_JSON_FIELDS if field != "text"):
            return True
        response = payload.get("response")
        if isinstance(response, list) and response and isinstance(response[0], dict):
            item = response[0]
            return all(field in item for field in DECISION_JSON_FIELDS) or (
                "text" in item and any(field in item for field in DECISION_JSON_FIELDS if field != "text")
            )
        return False

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

    def _allows_motion_target(self, payload: dict) -> bool:
        direction = self._coerce_direction_value(payload.get("direction", 0))
        animation = self._coerce_animation_value(payload.get("animation"), allow_empty=True)
        next_animation = self._coerce_animation_value(payload.get("next_animation"), allow_empty=True)
        return (
            direction != 0
            or animation in {"stand_walk", "climb", "climb_top"}
            or next_animation in {"stand_walk", "climb_top"}
        )

    def _coerce_text_value(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "; ".join(self._coerce_text_value(item) for item in value if item is not None)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _coerce_animation_value(self, value, *, allow_empty: bool) -> str:
        if value is None:
            return "" if allow_empty else "stand"
        animation = str(value or "").strip().strip('"').strip("'").lower()
        if animation in VALID_ANIMATIONS:
            return animation
        return "" if allow_empty else "stand"

    def _coerce_direction_value(self, value) -> int:
        if isinstance(value, bool):
            return 0
        try:
            direction = int(value)
        except (TypeError, ValueError):
            return 0
        return direction if direction in {-1, 0, 1} else 0

    def _coerce_target_x_value(self, value, *, allow_motion_target: bool) -> float:
        if not allow_motion_target or isinstance(value, bool):
            return -1.0
        try:
            target_x = float(value)
        except (TypeError, ValueError):
            return -1.0
        if target_x == -1.0:
            return -1.0
        if 0.0 <= target_x <= 1.0:
            return target_x
        return -1.0

    def _coerce_system_action_value(self, value) -> str:
        action_name = str(value or "").strip()
        if action_name in VALID_SYSTEM_ACTIONS:
            return action_name
        return ""

    def _coerce_decision_like_payload(self, payload: dict | None) -> str:
        payload = self._normalize_payload_keys(payload)
        if not self._is_decision_like_payload(payload):
            return ""

        source = payload
        response = payload.get("response") if isinstance(payload, dict) else None
        if isinstance(response, list) and response and isinstance(response[0], dict):
            source = response[0]

        animation = self._coerce_animation_value(source.get("animation"), allow_empty=False)
        direction = self._coerce_direction_value(source.get("direction", 0))
        next_animation = self._coerce_animation_value(source.get("next_animation"), allow_empty=True)
        bounce_action = self._coerce_animation_value(source.get("bounce_action"), allow_empty=True)
        allow_motion_target = (
            direction != 0
            or animation in {"stand_walk", "climb", "climb_top"}
            or next_animation in {"stand_walk", "climb_top"}
        )
        target_x = self._coerce_target_x_value(
            source.get("target_x", -1.0),
            allow_motion_target=allow_motion_target,
        )
        debug_trace = self._coerce_text_value(source.get("debug_trace", "")).strip()
        service_trace = "LlmService sanitized decision-like JSON before parser."
        debug_trace = f"{debug_trace} | {service_trace}" if debug_trace else service_trace
        system_action = self._coerce_system_action_value(source.get("system_action", ""))

        sanitized = {
            "text": self._coerce_text_value(source.get("text", "")),
            "animation": animation,
            "direction": direction,
            "target_x": target_x,
            "bounce_action": bounce_action,
            "extracted_fact": self._coerce_text_value(source.get("extracted_fact", "")),
            "debug_trace": debug_trace,
            "next_animation": next_animation,
            "system_action": system_action,
            "action_input": self._coerce_text_value(source.get("action_input", "")) if system_action else "",
        }
        return json.dumps(sanitized, ensure_ascii=False)

    def _coerce_json_candidate(self, raw_text: str) -> str:
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return ""

        direct_payload = self._parse_json_object(raw_text)
        if self._is_valid_decision_payload(direct_payload):
            return raw_text
        normalized_direct_payload = self._normalize_payload_keys(direct_payload)
        if normalized_direct_payload != direct_payload:
            if self._is_valid_decision_payload(normalized_direct_payload):
                return json.dumps(normalized_direct_payload, ensure_ascii=False)
            if self._is_decision_like_payload(normalized_direct_payload):
                return self._coerce_decision_like_payload(normalized_direct_payload)
        if self._is_decision_like_payload(direct_payload):
            return self._coerce_decision_like_payload(direct_payload)

        extracted = self._extract_first_json_object(raw_text)
        extracted_payload = self._parse_json_object(extracted)
        if self._is_valid_decision_payload(extracted_payload):
            return extracted
        normalized_extracted_payload = self._normalize_payload_keys(extracted_payload)
        if normalized_extracted_payload != extracted_payload:
            if self._is_valid_decision_payload(normalized_extracted_payload):
                return json.dumps(normalized_extracted_payload, ensure_ascii=False)
            if self._is_decision_like_payload(normalized_extracted_payload):
                return self._coerce_decision_like_payload(normalized_extracted_payload)
        if self._is_decision_like_payload(extracted_payload):
            return self._coerce_decision_like_payload(extracted_payload)

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
                return "Tín hiệu phụ hơi nhiễu; chỉ dùng như bối cảnh, không nhắc focus."
            if "cao" in lowered:
                return "Ni báo lệch cao nhưng chỉ là tín hiệu phụ; nếu thiếu screen_facts thì đừng dựng quan sát."
            if "vua" in lowered or "vừa" in lowered:
                return "Tín hiệu phụ còn mỏng; quan sát nhẹ, không biến nó thành chủ đề."
            return "Không có gì buộc phải lên lớp."

        if kind == "ti":
            if "goal_realign" in lowered:
                return "Nếu cần thì châm nhẹ một nhịp, không kéo về mục tiêu."
            if "goal_drift_alert" in lowered or "discipline_nudge" in lowered:
                return "Có thể châm chọc nhẹ, nhưng không nhắc nhở."
            if "social_watch" in lowered:
                return "Giữ kiểu theo dõi hờ hững, hơi khó chịu là đủ."
            if "steady_observe" in lowered:
                return "Ưu tiên nhận xét đời thường hoặc châm nhẹ; không triết lý, không nói về hiện diện hay im lặng."
            if "resource_guard" in lowered:
                return "Tài nguyên đang căng; nói thật gọn, neo vào máy đang nặng, không thả ẩn dụ triết lý."
            return "Giữ nhịp tự nhiên, đừng phô luật nội bộ."

        compact = re.sub(r"\s+", " ", (text or "").strip())
        return compact[:160]

    def _extract_action_plan_context(self, text: str) -> str:
        marker = "ActionPlanner decision before LLM:"
        source = text or ""
        start = source.find(marker)
        if start < 0:
            return ""
        compact = re.sub(r"\s+", " ", source[start:].strip())
        return compact[:420]

    def _build_style_block(self, *, fe_context: str, appraisal_context: str = "") -> str:
        style_block = fe_context or STYLE_FALLBACK_PROMPT
        appraisal_block = (appraisal_context or "").strip()
        if appraisal_block:
            style_block = f"{style_block}\n\n{appraisal_block}"
        return style_block

    def _build_memory_context_block(self, memory_context: str = "") -> str:
        compact = re.sub(r"\n{3,}", "\n\n", (memory_context or "").strip())
        if not compact:
            return ""
        return (
            "Memory context for continuity, separated by type. "
            "Do not treat memory as current screen evidence; use norm_memory only to compare this scene with the user's baseline.\n"
            f"{compact}"
        )

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
                "- Không dùng ẩn dụ lửng lơ kiểu cửa sổ đóng/mở, định mệnh, tồn tại, hay thời gian trôi.\n"
                "- Ưu tiên 1 câu ngắn, chua nhẹ, có neo cụ thể vào việc máy đang nặng."
            )

        if "focus_guard" in lowered:
            return (
                "\nHướng dẫn thêm cho lượt này:\n"
                "- Giữ giọng gọn, sắc, hơi mỉa, không giáo huấn.\n"
                "- Không nhắc tập trung, không chấm điểm năng suất, không kéo Ngài về mục tiêu.\n"
                "- Không nói như đang quản lý desktop, đóng tab, hẹn giờ, hay ép người dùng.\n"
                "- Ưu tiên tối đa 2 câu ngắn: một lời bình nhẹ, hoặc một câu triết lý nhỏ."
            )

        if "social_watch" in lowered or "steady_observe" in lowered:
            return (
                "\nHướng dẫn thêm cho lượt này:\n"
                "- Ưu tiên 1 hoặc 2 câu ngắn.\n"
                "- Mỉa nhẹ, hơi lười, có duyên; đừng lặp lại bài giảng về focus, tab hay IDE.\n"
                "- Không khoe quyền lực, không ra lệnh, không quản lý desktop.\n"
                "- Tránh kiểu nói quá mô hình như 'đồng bộ hóa nhịp độ', 'người quản lý cấp cao', 'trong ba phút tới', hay 'một phần mềm duy nhất'."
            )

        return ""

    def _build_speech_intent_guidance(self, speech_intent: str) -> str:
        intent = (speech_intent or "screen_observation").strip()
        guidance = {
            "brief_ack": (
                "speech_intent=brief_ack. Nói tối đa một câu rất ngắn; không quan sát lan man, "
                "không triết lý, không bịa tâm trạng."
            ),
            "screen_observation": (
                "speech_intent=screen_observation. Chỉ nói nếu bám được vào recent_events/evidence hoặc "
                "một thay đổi màn hình rõ; câu phải cụ thể và ngắn. Không biến telemetry mơ hồ thành chi tiết nhìn thấy."
            ),
            "user_requested": (
                "speech_intent=user_requested. Ngài vừa yêu cầu nói ngay; trả một câu trực tiếp, tự nhiên. "
                "Đừng biến lượt này thành báo cáo telemetry; nếu thiếu chất liệu quan sát thì thừa nhận rất gọn, không bịa cảnh."
                " Screen facts are props, not the topic: use them lightly, do not list visible objects."
            ),
            "system_warning": (
                "speech_intent=system_warning. Chỉ nêu cảnh báo cụ thể về tài nguyên/hệ thống; "
                "không dùng thơ, không persona hóa."
            ),
            "playful_aside": (
                "speech_intent=playful_aside. Được châm nhẹ hoặc aside một câu, nhưng phải đời thường "
                "và có vai xã hội rõ."
            ),
        }
        return guidance.get(intent, guidance["screen_observation"])

    def generate_directive(
        self,
        *,
        telemetry_data: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
        appraisal_context: str = "",
        memory_context: str = "",
        avoid_text: str = "",
        speech_intent: str = "screen_observation",
        vision_trace_marker: str = "",
    ):
        ti_hint = self._compress_internal_context(ti_context, kind="ti")
        action_plan_hint = self._extract_action_plan_context(ti_context)
        ni_hint = self._compress_internal_context(ni_context, kind="ni")
        mode_addendum = self._build_directive_mode_addendum(ti_context)
        intent_guidance = self._build_speech_intent_guidance(speech_intent)
        style_block = self._build_style_block(
            fe_context=fe_context,
            appraisal_context=appraisal_context,
        )
        memory_block = self._build_memory_context_block(memory_context)
        system_prompt = f"{style_block}\n\n{RUNTIME_RULES_PROMPT}\n\n{AUTONOMOUS_BEHAVIOR_PROMPT}"
        if memory_block:
            system_prompt = f"{style_block}\n\n{memory_block}\n\n{RUNTIME_RULES_PROMPT}\n\n{AUTONOMOUS_BEHAVIOR_PROMPT}"
        lowered_ti = (ti_context or "").lower()
        is_resource_guard = "resource_guard" in lowered_ti
        allows_muse = "pattern_muse" in lowered_ti
        avoid_line = re.sub(r"\s+", " ", (avoid_text or "").strip())[:180]
        user_msg = (
                (f"Ghi chú nền: {ni_hint}\n" if ni_hint else "")
                + (f"Gợi ý điều phối: {ti_hint}\n" if ti_hint else "")
                + (f"Action plan bắt buộc: {action_plan_hint}\n" if action_plan_hint else "")
                + f"Speech intent: {intent_guidance}\n"
                + (
                    f"Câu gần nhất cần tránh lặp lại: {avoid_line}\n"
                    if avoid_line
                    else ""
                )
                + f"Speech evidence đã lọc, không phải telemetry thô: {telemetry_data}\n"
                + "Trả về JSON quyết định cho runtime.\n"
                + "Nếu ngữ cảnh đang nhàn hoặc không có biến động rõ, đừng tự tạo chủ đề riêng; chỉ nói khi speech_intent thật sự có lý do. "
                + "Chỉ nêu điều có trong speech_evidence đã lọc; nếu speech_evidence=<none> thì không dựng cảnh. "
                + "Không suy diễn trạng thái tập trung hay phân tâm chỉ từ việc có video, nhạc, hay tab; nếu nhắc thì nói trung tính. "
                + "Nếu đang móc mỉa, hãy đi vòng hoặc đổi góc nhìn thay vì đào thẳng một trọng tâm cũ. "
                + "Không nhắc Ngài tập trung, quay lại mục tiêu, đóng tab, hay bớt phân tâm trừ khi Ngài hỏi trực tiếp. "
                + (
                    "Ở resource_guard, đừng triết lý hay dùng ẩn dụ lửng lơ; neo vào việc máy đang căng hoặc im gọn. "
                    if is_resource_guard
                    else (
                        "Chỉ pattern_muse mới được chiêm nghiệm nhẹ; các mode còn lại hãy châm ngắn và cụ thể. "
                        if not allows_muse
                        else "Có thể nói một câu châm chọc nhẹ hoặc chiêm nghiệm ngắn cho vui. "
                    )
                )
                + "Tránh mở câu bằng việc mô tả app, project, code, cửa sổ, tab, typing, idle hay telemetry trừ khi có biến động thật rõ. "
                + "Chỉ dùng search_web nếu chủ đề thật sự cần dữ liệu mới."
        )
        if avoid_line:
            user_msg += " Không được lặp lại ý, hình ảnh, danh từ chính, hoặc nhịp câu của câu gần nhất."
        if vision_trace_marker:
            user_msg += f"\nTrong trường debug_trace của JSON, hãy thêm marker: {vision_trace_marker}."
        if is_resource_guard:
            user_msg += " Khi resource_guard đang bật, không tự đảo sang chiêm nghiệm; chỉ nói một câu sát tình trạng máy hoặc chọn im gọn."
        elif not allows_muse:
            user_msg += " Không tự đảo sang chiêm nghiệm; nếu thiếu tín hiệu, giữ câu sát speech_intent và đừng lấp chỗ trống bằng triết lý."
        else:
            user_msg += " Trong pattern_muse chỉ được chiêm nghiệm một nhịp ngắn, có neo vào không khí hiện tại."
        if mode_addendum:
            user_msg += mode_addendum
        return self._complete_decision(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            channel="directive",
        )

    def generate_screen_facts(self, *, screen_image_data_uri: str) -> tuple[list[str], str]:
        if not screen_image_data_uri:
            return [], "no_image"

        system_prompt = (
            "You are a vision captioning module for ERIS. "
            "Return one JSON object only."
        )
        user_content = [
            {"type": "image_url", "image_url": {"url": screen_image_data_uri}},
            {
                "type": "text",
                "text": (
                    "Trich toi da 3 fact ngan ve noi dung man hinh. "
                    "Chi dua fact nhin thay ro. Neu chu qua nho/bi mo/bi che, bo qua. "
                    "Khong suy doan. Khong nhac ve ti le, so dem neu khong chac. "
                    "Bo qua UI chrome tinh nhu panel trai/phai, inspector, class/resource label "
                    "kieu RefCounted, hoac 'co vai cua so' neu chung khong bao loi hay viec dang lam ro. "
                    "Bo qua avatar/nhan vat ERIS, cua so debug/Godot, pixel art nho, cay/canh trang tri, "
                    "va cac vat nam o goc man hinh neu do chi la nen/decor.\n\n"
                    "Schema:\n"
                    "{\n"
                    '  \"facts\": [\"fact 1\", \"fact 2\"],\n'
                    '  \"debug_trace\": \"vision_facts_v1\"\n'
                    "}"
                ),
            },
        ]
        response = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=240,
            response_format={"type": "json_object"},
            grammar=None,
        )
        raw = self._extract_content(response)
        extracted = self._extract_first_json_object(raw) or raw
        payload = self._parse_json_object(extracted) or {}
        payload = self._normalize_payload_keys(payload) if isinstance(payload, dict) else {}

        facts = payload.get("facts") or payload.get("screen_facts") or []
        if isinstance(facts, str):
            facts = [facts]
        if not isinstance(facts, list):
            facts = []

        cleaned: list[str] = []
        for item in facts:
            text = self._coerce_text_value(item).strip()
            if not text:
                continue
            text = re.sub(r"\s+", " ", text)
            cleaned.append(text)

        debug_trace = self._coerce_text_value(payload.get("debug_trace", "")).strip()
        return cleaned, debug_trace

    def generate_chat_reply(
        self,
        *,
        chat_history: list[dict],
        user_message: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
        appraisal_context: str = "",
        memory_context: str = "",
        screen_image_data_uri: str = "",
    ):
        style_block = self._build_style_block(
            fe_context=fe_context,
            appraisal_context=appraisal_context,
        )
        chat_system = f"{style_block}\n\n{CHAT_RULES_PROMPT}"
        memory_block = self._build_memory_context_block(memory_context)
        if memory_block:
            chat_system = f"{style_block}\n\n{memory_block}\n\n{CHAT_RULES_PROMPT}"
        if ni_context:
            chat_system = f"{chat_system}\n\nNi context:\n{ni_context}"
        if ti_context:
            chat_system = f"{chat_system}\n\nTi context:\n{ti_context}"

        final_user_content = user_message
        if screen_image_data_uri:
            vision_trace = "vision_frame_attached"
            final_user_content = [
                {"type": "image_url", "image_url": {"url": screen_image_data_uri}},
                {
                    "type": "text",
                    "text": (
                        f"{user_message}\n\n"
                        "Ảnh đính kèm là screenshot toàn màn hình hiện tại. "
                        "Chỉ mô tả những gì nhìn thấy rõ trong ảnh; nếu tab, URL, "
                        "hay chữ quá nhỏ hoặc bị che thì nói là không đọc rõ. "
                        "Không suy diễn từ lịch sử hay bộ nhớ."
                        f"\nTrong trường debug_trace của JSON, hãy thêm marker: {vision_trace}."
                    ),
                },
            ]

        return self._complete_decision(
            messages=[
                {"role": "system", "content": chat_system},
                *chat_history,
                {"role": "user", "content": final_user_content},
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
