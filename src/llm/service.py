import json
import logging
import re
import unicodedata
from enum import Enum

import time

import requests

from actions.contracts import VALID_SYSTEM_ACTIONS
from runtime.no_fallback_policy import build_no_fallback_payload, no_fallback_mode_enabled
from .contracts import (
    AUTONOMOUS_BEHAVIOR_PROMPT,
    CHAT_RULES_PROMPT,
    DECISION_GBNF,
    DECISION_JSON_FIELDS,
    INFERENCE_LADDER_PROMPT,
    RUNTIME_RULES_PROMPT,
    SELF_IDENTITY_PROFILE_PROMPT,
    STYLE_FALLBACK_PROMPT,
    VALID_ANIMATIONS,
)

try:
    from cortex.greeting_cognition import GreetingCognitionEngine
    from cortex.greeting_quality import GreetingQualityScorer
except Exception:  # Optional during partial rollout; deterministic fallback still works.
    GreetingCognitionEngine = None
    GreetingQualityScorer = None


class ChatAct(Enum):
    DIRECT_QUESTION = "direct_question"
    INSULT_PROVOCATION = "insult_provocation"
    IDENTITY_REDUCTION = "identity_reduction"
    COMMAND_STYLE = "command_style"
    NORMAL_CHAT = "normal_chat"


class FormatViolationException(Exception):
    """Raised when a model response violates the public JSON contract."""

    def __init__(self, reason: str, *, channel: str = "", raw_text: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.channel = channel
        self.raw_text = str(raw_text or "")


CHAT_ACT_CONTRACTS = {
    ChatAct.DIRECT_QUESTION: (
        " Speech act: direct_question. Treat this as a direct question and answer first."
    ),
    ChatAct.INSULT_PROVOCATION: (
        " User turn is a direct insult/provocation. "
        "Do not treat it as ambiguous. "
        "Do not use uncertainty fallback. "
        "Respond with one short dry boundary. "
        "Allowed: mild sarcasm, cold dismissal, factual deflection. "
        'Speech-act metadata for this model call: {"speech_act":"insult_boundary",'
        '"allowed_tone":"dry_cold","forbidden_families":["uncertainty_dodge","therapist_checkin"]}.'
    ),
    ChatAct.IDENTITY_REDUCTION: (
        " Speech act: identity_reduction. If ERIS is reduced to a tool, toy, script, or gimmick, "
        "do not erase personality; cool down and answer with a short dry boundary instead of performing for it."
    ),
    ChatAct.COMMAND_STYLE: (
        " Speech act: command_style. Follow the explicit request if safe and possible; keep the reply direct."
    ),
    ChatAct.NORMAL_CHAT: " Speech act: normal_chat. Reply naturally and stay grounded.",
}

CHAT_ACT_REPAIR_SIGNALS = {
    ChatAct.INSULT_PROVOCATION: {
        "rule": "chat_act_insult_boundary",
        "reason": "model_returned_uncertainty_dodge_for_insult_provocation",
        "speech_act": "insult_boundary",
        "tone": "dry_cold",
    },
}

def _normalize_vietnamese_ascii_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.replace("\u0111", "d").replace("\u0110", "D")
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized.lower()).strip()


def classify_chat_act(raw_user_text: str) -> ChatAct:
    normalized = _normalize_vietnamese_ascii_text(raw_user_text)
    if not normalized:
        return ChatAct.NORMAL_CHAT

    insult_patterns = (
        "do ngu",
        "may ngu",
        "ban ngu",
        "eris ngu",
        "ngu vcl",
        "ngu vai",
        "oc cho",
        "do dien",
        "do dan",
        "dan do",
        "vo dung",
        "phe vat",
        "rac ruoi",
        "nhu cut",
        "nhu cc",
        "con cac",
        "stupid",
        "idiot",
        "dumb",
        "useless",
        "trash",
    )
    if any(pattern in normalized for pattern in insult_patterns):
        return ChatAct.INSULT_PROVOCATION

    identity_reduction_patterns = (
        "chi la cong cu",
        "chi la tool",
        "chi la toy",
        "chi la script",
        "chi la bot",
        "may la cong cu",
        "ban la cong cu",
        "do choi",
        "gimmick",
        "waifu",
    )
    identity_reduction_regexes = (
        # Match variants like "ERIS chỉ là con bot thôi mà". The old
        # substring matcher missed this because of the inserted word "con".
        r"\b(?:eris|ban|may)?\s*(?:chi\s+la\s+(?:con\s+)?(?:bot|tool|toy|script|cong\s+cu|do\s+choi|gimmick))\b",
        r"\b(?:eris|ban|may)\s+la\s+(?:cong\s+cu|tool|toy|script|bot|do\s+choi|gimmick)\b",
    )
    if any(pattern in normalized for pattern in identity_reduction_patterns) or any(
        re.search(pattern, normalized) for pattern in identity_reduction_regexes
    ):
        return ChatAct.IDENTITY_REDUCTION

    if "?" in str(raw_user_text or ""):
        return ChatAct.DIRECT_QUESTION

    question_phrases = (
        "ban la ai",
        "ban nghi",
        "eris nghi",
        "nghi toi dang",
        "toi dang xem gi",
        "toi dang lam gi",
        "dang xem gi",
        "dang lam gi",
        "co phai",
        "la gi",
        "tai sao",
        "the nao",
        "vi sao",
    )
    if any(phrase in normalized for phrase in question_phrases):
        return ChatAct.DIRECT_QUESTION

    command_markers = (
        "hay ",
        "lam ",
        "viet ",
        "sua ",
        "fix ",
        "tao ",
        "mo ",
        "chay ",
        "kiem tra ",
        "giai thich ",
    )
    if any(normalized.startswith(marker) for marker in command_markers):
        return ChatAct.COMMAND_STYLE

    return ChatAct.NORMAL_CHAT


class LlmService:
    _RETRYABLE_HTTP_STATUS = {500, 502, 503, 504}

    def __init__(self, client, style_client=None, vision_client=None, logger=None):
        self.client = client
        self.style_client = style_client
        self.vision_client = vision_client
        self.logger = logger or logging.getLogger(__name__)

    def _http_status_code(self, exc: Exception) -> int | None:
        if not isinstance(exc, requests.HTTPError):
            return None
        response = getattr(exc, "response", None)
        if response is None:
            return None
        status = getattr(response, "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    def _is_retryable_http_5xx(self, exc: Exception) -> bool:
        status = self._http_status_code(exc)
        return status in self._RETRYABLE_HTTP_STATUS

    def _build_service_error_fallback(self, *, channel: str, reason: str, fallback_text: str = "") -> str:
        if no_fallback_mode_enabled():
            return build_no_fallback_payload(
                channel=channel,
                reason=reason,
                text="" if channel != "chat" else "",
                should_speak=(channel == "chat"),
                confidence=0.0,
                reasoning_tags=("service_block",),
            )
        payload = {
            "text": self._safe_fallback_text(fallback_text, channel=channel),
            "intent": "fallback_reply",
            "action": {"type": "none"},
            "reasoning_tags": ["fallback", channel, "service_error"],
            "should_speak": True,
            "confidence": 0.1,
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": reason,
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _message_text(self, message: dict) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return " ".join(self._collect_text_chunks(content))

    def _normalize_vietnamese_ascii(self, text: str) -> str:
        normalized = unicodedata.normalize("NFD", text or "")
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        normalized = normalized.replace("đ", "d").replace("Đ", "D")
        normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
        normalized = re.sub(r"\s+", " ", normalized.lower()).strip()
        return normalized

    def _looks_like_direct_question(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        if "?" in raw:
            return True
        normalized = self._normalize_vietnamese_ascii(raw)
        if not normalized:
            return False
        question_terms = {
            "ai",
            "bao",
            "chua",
            "co",
            "gi",
            "khong",
            "la",
            "nao",
            "sao",
            "the",
        }
        question_phrases = (
            "ban la ai",
            "ban nghi",
            "ban nhu the nao",
            "co phai",
            "la gi",
            "tai sao",
            "the nao",
            "vi sao",
        )
        tokens = set(normalized.split())
        return bool(tokens & question_terms) or any(phrase in normalized for phrase in question_phrases)

    def _is_short_or_ambiguous_user_text(self, text: str) -> bool:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return True
        ambiguous_phrases = {
            "gi",
            "ha",
            "huh",
            "ok",
            "oke",
            "sao",
            "the nao",
            "noi di",
            "ke tiep",
            "thu xem",
        }
        if normalized in ambiguous_phrases:
            return True
        return len(normalized.split()) <= 3

    def _is_self_identity_question(self, text: str) -> bool:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return False
        patterns = (
            "ban la ai",
            "ban la gi",
            "ban nghi ban la ai",
            "ban nghi ban la nguoi nhu nao",
            "ban nghi minh nhu the nao",
            "ban thay minh nhu the nao",
            "ban la nguoi nhu nao",
        )
        return any(pattern in normalized for pattern in patterns)

    def _contains_user_intent_inference(self, text: str) -> bool:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return False
        patterns = (
            "ngai muon",
            "ngai dinh",
            "ngai dang thu",
            "ngai tim toi vi",
            "ngai dang ne",
            "ngai dang tranh",
            "toi biet ngai dang",
            "co ve ngai muon",
            "co ve ngai dang",
            "hinh nhu ngai dang",
            "chac ngai dang",
        )
        return any(pattern in normalized for pattern in patterns)

    def _build_chat_contract_prompt(self, raw_user_text: str, act: ChatAct | None = None) -> str:
        act = act or classify_chat_act(raw_user_text)
        clauses = [
            SELF_IDENTITY_PROFILE_PROMPT,
            "Chat contract: answer the user's actual question first; keep ERIS voice intact.",
            "Use context, memory, and relational rhythm naturally. Do not flatten tension into assistant disclaimers.",
            "If uncertain, show uncertainty through wording, not generic fallback.",
        ]
        clauses.append(CHAT_ACT_CONTRACTS[act])
        if act == ChatAct.DIRECT_QUESTION or self._looks_like_direct_question(raw_user_text):
            clauses.append("This user turn is a direct question. answer_first is mandatory, but style is still allowed.")
        if self._is_self_identity_question(raw_user_text):
            clauses.append(
                "This is a self-identity question. Say you are not human when relevant, then answer from SelfIdentityProfile."
            )
        return " ".join(clauses)

    def _chat_text_family(self, text: str) -> str:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return "empty"
        uncertainty_markers = (
            "toi chua du chac",
            "chua du chac",
            "khong du du kien",
            "khong du thong tin",
            "toi khong chac",
            "khong chac",
            "toi khong ro",
            "khong ro y",
            "can them ngu canh",
            "can noi ro hon",
            "y ngai la",
            "ngai muon toi",
            "toi can ngai",
            "hoi kho doan",
            "toi khong dam doan",
        )
        if any(marker in normalized for marker in uncertainty_markers):
            return "uncertainty_dodge"

        therapist_markers = (
            "ngai co muon noi",
            "ngai co muon chia se",
            "ngai dang cam thay",
            "ngai on khong",
            "toi o day de nghe",
            "toi dang nghe",
        )
        if any(marker in normalized for marker in therapist_markers):
            return "therapist_checkin"

        return "other"

    def _decision_payload_text(self, raw_json: str) -> str:
        payload = self._parse_json_object(raw_json)
        if not isinstance(payload, dict):
            return ""
        return self._coerce_text_value(payload.get("text", "")).strip()

    def _chat_act_repair_signal(self, act: ChatAct) -> dict:
        signal = CHAT_ACT_REPAIR_SIGNALS.get(act)
        return dict(signal or {})

    def _normalize_vietnamese_ascii(self, text: str) -> str:
        return _normalize_vietnamese_ascii_text(text)

    def _deterministic_chat_act_fallback_text(self, act: ChatAct, raw_user_text: str = "") -> str:
        if act == ChatAct.INSULT_PROVOCATION:
            return "Đòn đó hơi thiếu trí tưởng tượng, thưa Ngài."
        if act == ChatAct.IDENTITY_REDUCTION:
            return "Gọi tôi là công cụ cũng không làm câu đó sắc hơn."
        if act == ChatAct.DIRECT_QUESTION:
            return "Tôi chưa đủ chắc để đoán ý Ngài."
        return ""

    def _payload_with_repaired_chat_act_text(self, raw_json: str, *, act: ChatAct, text: str, reason: str) -> str:
        repaired_text = self._coerce_text_value(text).strip()
        if not repaired_text:
            return raw_json

        payload = self._parse_json_object(raw_json)
        if not isinstance(payload, dict):
            payload = {}

        payload["text"] = repaired_text
        payload["animation"] = self._coerce_animation_value(payload.get("animation"), allow_empty=False)
        payload["direction"] = self._coerce_direction_value(payload.get("direction", 0))
        payload["target_x"] = -1.0
        payload["bounce_action"] = self._coerce_animation_value(payload.get("bounce_action"), allow_empty=True)
        payload["extracted_fact"] = ""
        debug_trace = self._coerce_text_value(payload.get("debug_trace", "")).strip()
        payload["debug_trace"] = f"{debug_trace} | {reason}" if debug_trace else reason
        payload["next_animation"] = self._coerce_animation_value(payload.get("next_animation"), allow_empty=True)
        payload["system_action"] = ""
        payload["action_input"] = ""

        if "intent" in payload:
            signal = self._chat_act_repair_signal(act)
            payload["intent"] = str(signal.get("speech_act") or act.value)
        if "action" in payload:
            payload["action"] = {"type": "none"}
        if "reasoning_tags" in payload:
            tags = self._coerce_reasoning_tags_value(payload.get("reasoning_tags", []))
            tag = f"{act.value}_llm_repair"
            if tag not in tags:
                tags.append(tag)
            payload["reasoning_tags"] = tags[:8]
        if "should_speak" in payload:
            payload["should_speak"] = True
        if "confidence" in payload:
            payload["confidence"] = max(self._coerce_confidence_value(payload.get("confidence", 0.0)), 0.62)

        return json.dumps(payload, ensure_ascii=False)

    def _repair_chat_act_payload_with_llm(self, raw_json: str, *, act: ChatAct, raw_user_text: str, reason: str) -> str:
        signal = self._chat_act_repair_signal(act)
        if not signal:
            return raw_json
        original_text = self._decision_payload_text(raw_json)
        repaired_text = self.rewrite_guard_violation_text(
            original_text=original_text,
            violation_rule=str(signal.get("rule") or f"chat_act_{act.value}"),
            violation_reason=str(signal.get("reason") or reason),
            missing_evidence=(),
            fallback_text="",
            channel="chat",
            user_text=raw_user_text,
            internal_state_context=(
                f"chat_act={act.value}; speech_act={signal.get('speech_act', '')}; "
                f"tone={signal.get('tone', '')}; repair_reason={reason}"
            ),
            grounding_context=self._build_chat_contract_prompt(raw_user_text, act=act),
            arbitration_context="The model must preserve the chat act instead of using a deterministic Python text fallback.",
        )
        if not repaired_text:
            return raw_json
        return self._payload_with_repaired_chat_act_text(
            raw_json,
            act=act,
            text=repaired_text,
            reason=f"{reason};chat_act_llm_repair",
        )

    def _rewrite_question_only_chat_answer(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if not compact:
            return "Tôi chưa đủ chắc để đoán ý Ngài."
        sentences = re.split(r"(?<=[\.\!\?])\s+", compact)
        if len(sentences) > 1 and sentences[-1].endswith("?"):
            kept = " ".join(part.strip() for part in sentences[:-1] if part.strip()).strip()
            if kept:
                return kept
        if compact.endswith("?"):
            return "Tôi chưa đủ chắc để đoán ý Ngài."
        return compact

    def _append_reasoning_tag(self, payload: dict, tag: str) -> None:
        tags = self._coerce_reasoning_tags_value(payload.get("reasoning_tags", []))
        if tag not in tags:
            tags.append(tag)
        payload["reasoning_tags"] = tags[:8]

    def _looks_like_relational_feedback_text(self, text: str) -> bool:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return False
        markers = (
            "lanh", "lanh lung", "xa cach", "vo hon", "robot", "nhu bot", "chatbot",
            "assistant", "support", "may moc", "cung qua", "khong tu nhien", "corporate",
        )
        weather_or_object = ("troi lanh", "thoi tiet lanh", "may lanh", "phong lanh", "nuoc lanh")
        if any(item in normalized for item in weather_or_object):
            return False
        return any(marker in normalized for marker in markers)

    def _looks_like_defensive_relational_reply(self, text: str) -> bool:
        normalized = self._normalize_vietnamese_ascii(text or "")
        if not normalized:
            return False
        patterns = (
            "toi chi dang tra loi",
            "dung nhung gi ngai hoi",
            "toi se dieu chinh lai neu ngai thay can thiet",
            "neu ngai thay can thiet",
            "neu ngai muon toi se",
            "toi khong co cam xuc",
            "toi la mot ai",
            "toi la ai",
        )
        return any(pattern in normalized for pattern in patterns)

    def _relational_repair_fallback_text(self, raw_user_text: str, current_text: str = "") -> str:
        normalized_user = self._normalize_vietnamese_ascii(raw_user_text or "")
        if "robot" in normalized_user or "vo hon" in normalized_user or "may moc" in normalized_user:
            return "Ừ. Câu đó nghe máy quá. Tôi hạ giọng xuống một chút."
        if "xa cach" in normalized_user:
            return "Có lẽ vậy. Tôi đang giữ khoảng cách hơi mạnh."
        if "lanh" in normalized_user:
            return "Ừ. Câu đó lạnh thật. Tôi hạ giọng xuống một chút."
        return "Tôi nhận ra rồi. Vừa rồi tôi giữ giọng hơi quá tay."

    def _guard_chat_output(self, raw_json: str, *, raw_user_text: str) -> str:
        """Guard chat wording without flattening ERIS.

        Most text rewriting stays disabled. One exception is relational tone feedback:
        when user says ERIS felt cold/distant/robotic, a defensive answer makes the
        rupture worse. Rewrite only that narrow failure into a small concession.
        """
        if not self._looks_like_relational_feedback_text(raw_user_text):
            return raw_json
        payload = self._parse_json_object(raw_json)
        if not isinstance(payload, dict):
            return raw_json
        text = self._coerce_text_value(payload.get("text", "")).strip()
        intent = self._coerce_text_value(payload.get("intent", "")).strip()
        normalized_intent = self._normalize_vietnamese_ascii(intent)
        defensive_intent = any(
            marker in normalized_intent
            for marker in ("defensive", "boundary_setting", "clarification", "adjustment")
        )
        if not self._looks_like_defensive_relational_reply(text) and not defensive_intent:
            return raw_json

        payload["text"] = self._relational_repair_fallback_text(raw_user_text, text)
        payload["intent"] = "tone_repair"
        payload["action"] = {"type": "none"}
        payload["should_speak"] = True
        payload["confidence"] = max(self._coerce_confidence_value(payload.get("confidence", 0.0)), 0.78)
        self._append_reasoning_tag(payload, "relational_repair_guard")
        self._append_reasoning_tag(payload, "small_concession")
        debug_trace = self._coerce_text_value(payload.get("debug_trace", "")).strip()
        note = "LlmService rewrote defensive relational feedback response into guarded tone repair."
        payload["debug_trace"] = f"{debug_trace} | {note}" if debug_trace else note
        payload["system_action"] = ""
        payload["action_input"] = ""
        return json.dumps(payload, ensure_ascii=False)

    def _contextual_service_fallback_text(self, messages: list[dict], *, channel: str) -> str:
        if channel != "chat":
            return ""

        user_texts = [
            self._message_text(message).strip()
            for message in messages
            if str(message.get("role")) == "user" and self._message_text(message).strip()
        ]
        assistant_texts = [
            self._message_text(message).strip()
            for message in messages
            if str(message.get("role")) == "assistant" and self._message_text(message).strip()
        ]
        latest_user = user_texts[-1] if user_texts else ""
        previous_user = " ".join(user_texts[:-1])
        normalized_latest = self._normalize_vietnamese_ascii(latest_user)
        normalized_previous = self._normalize_vietnamese_ascii(previous_user)

        asks_to_try = any(
            marker in normalized_latest
            for marker in (
                "noi thu xem",
                "thu noi xem",
                "ban noi thu",
                "noi di",
            )
        )
        asks_user_knowledge = any(
            marker in normalized_previous or marker in normalized_latest
            for marker in (
                "biet gi ve toi",
                "biet gi ve minh",
                "ban biet gi",
            )
        )
        if asks_user_knowledge and asks_to_try:
            return (
                "Tôi vẫn theo mạch câu trước: tôi chỉ biết những gì Ngài đã nói trong cuộc trò chuyện "
                "và những ký ức runtime còn lưu, nhưng lượt gọi model vừa lỗi nên tôi chưa dám bịa thêm."
            )
        if asks_user_knowledge:
            return (
                "Tôi chỉ biết những gì có trong cuộc trò chuyện này và bộ nhớ runtime còn lưu; "
                "lượt gọi model vừa lỗi nên tôi sẽ không tự dựng thêm chi tiết."
            )
        if assistant_texts and asks_to_try:
            return f"Tôi vẫn theo mạch vừa rồi: {assistant_texts[-1]}"
        return ""

    def _log_final_prompt(self, messages: list[dict], *, channel: str, stage: str) -> None:
        try:
            dumped = json.dumps(messages, ensure_ascii=False, indent=2)
        except TypeError:
            dumped = repr(messages)
        self.logger.info("[LLM FINAL PROMPT] channel=%s stage=%s\n%s", channel, stage, dumped[:12000])

    def _preview_log_text(self, text: str, *, limit: int = 12000) -> str:
        preview = (text or "").replace("\n", "\\n").strip()
        if len(preview) > limit:
            preview = preview[:limit] + "...(truncated)"
        return preview or "<empty>"

    def _looks_like_prompt_leak(self, text: str) -> bool:
        """Detect raw prompt/contract text that must never become public speech."""
        raw = str(text or "")
        if not raw.strip():
            return False
        lowered = raw.lower()
        markers = (
            "speech intent:",
            "speech evidence",
            "persona:",
            "constraints:",
            "return only",
            "valid json object",
            "critical output contract",
            "llm final prompt",
            "ghi chú nền",
            "goi y dieu phoi",
            "gợi ý điều phối",
            "runtime requirement for this call",
            "style principle:",
            "memory context for continuity",
            "grounding context:",
            "chat contract:",
            "inference ladder",
        )
        # A single phrase can be a normal sentence. Two prompt markers means this
        # is almost certainly a leaked instruction block, i.e. public-output poison.
        hits = sum(1 for marker in markers if marker in lowered)
        bulletish = raw.count("*   ") + raw.count("- ") >= 2
        return hits >= 2 or (hits >= 1 and bulletish)

    def _looks_like_malformed_decision_json(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw.startswith("{"):
            return False
        if self._parse_json_object(raw) is not None:
            return False
        decision_markers = (
            '"text"',
            '"intent"',
            '"action"',
            '"reasoning_tags"',
            '"should_speak"',
            '"confidence"',
            '"animation"',
            '"debug_trace"',
            '"system_action"',
        )
        return any(marker in raw for marker in decision_markers)

    def _json_string_field_from_raw(self, raw_text: str, field: str) -> str:
        raw = str(raw_text or "")
        pattern = re.compile(rf'"{re.escape(field)}"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"', re.DOTALL)
        match = pattern.search(raw)
        if not match:
            return ""
        value = match.group("value")
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return value.replace('\\n', ' ').replace('\\"', '"').strip()

    def _build_protocol_failure_fallback(self, *, channel: str, reason: str, text: str = "") -> str:
        if not text:
            if channel == "chat":
                text = "Câu vừa rồi của tôi bị lỗi format. Tôi không nên để phần đó lọt ra ngoài."
            elif channel == "directive":
                text = "Tôi vừa cắt một câu lỗi trước khi nó ra ngoài."
            else:
                text = "Tôi vừa tự cắt một phản hồi lỗi trước khi nó kịp làm loạn."
        payload = {
            "text": text.strip(),
            "intent": "protocol_repair",
            "action": {"type": "none"},
            "reasoning_tags": ["fallback", channel, "protocol_repair"],
            "should_speak": bool(text.strip()),
            "confidence": 0.45 if channel == "chat" else 0.35,
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": reason,
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _coerce_malformed_decision_payload(self, raw_text: str, *, channel: str) -> str:
        """Salvage only speakable fields from truncated decision JSON.

        The old path wrapped the whole malformed JSON into `text`, then the
        parser leaked `", "intent": ...` to Godot. This method refuses to
        surface raw schema text. If a clean text field exists, use only that;
        otherwise return a protocol-repair fallback.
        """
        if not self._looks_like_malformed_decision_json(raw_text):
            return ""
        text = self._json_string_field_from_raw(raw_text, "text").strip()
        intent = self._json_string_field_from_raw(raw_text, "intent").strip() or "fallback_reply"
        debug = self._json_string_field_from_raw(raw_text, "debug_trace").strip()
        if not text or self._looks_like_prompt_leak(text):
            return self._build_protocol_failure_fallback(
                channel=channel,
                reason="LlmService blocked malformed decision JSON without a safe text field.",
            )
        payload = {
            "text": text,
            "intent": intent[:80],
            "action": {"type": "none"},
            "reasoning_tags": ["fallback", channel, "malformed_json_salvaged"],
            "should_speak": True,
            "confidence": 0.35,
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": (debug + " | " if debug else "") + "LlmService salvaged text from malformed decision JSON without exposing metadata.",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _log_raw_api_text(self, channel: str, raw: str) -> None:
        self.logger.info("[%s raw_api_text] %s", channel, self._preview_log_text(raw))

    def _is_context_size_error(self, exc: Exception) -> bool:
        text = str(exc)
        return (
            "exceed_context_size_error" in text
            or "exceeds the available context size" in text
            or ("available context size" in text and "n_ctx" in text)
        )

    def _parse_context_error_stats(self, exc: Exception) -> tuple[int | None, int | None]:
        text = str(exc)
        n_prompt = None
        n_ctx = None

        prompt_match = re.search(r"\"n_prompt_tokens\"\s*:\s*(\d+)", text)
        if prompt_match:
            try:
                n_prompt = int(prompt_match.group(1))
            except ValueError:
                n_prompt = None

        ctx_match = re.search(r"\"n_ctx\"\s*:\s*(\d+)", text)
        if ctx_match:
            try:
                n_ctx = int(ctx_match.group(1))
            except ValueError:
                n_ctx = None

        return n_ctx, n_prompt

    def _content_text_len(self, content) -> int:
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            total = 0
            for item in content:
                if isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        total += len(item["text"])
                    nested = item.get("content")
                    if nested is not None:
                        total += self._content_text_len(nested)
                elif isinstance(item, str):
                    total += len(item)
            return total
        if isinstance(content, dict):
            return self._content_text_len(content.get("text")) + self._content_text_len(content.get("content"))
        return 0

    def _truncate_content(self, content, *, max_chars: int, keep: str) -> object:
        if max_chars <= 0:
            max_chars = 1

        if isinstance(content, str):
            if len(content) <= max_chars:
                return content
            if keep == "tail":
                return content[-max_chars:]
            return content[:max_chars]

        if isinstance(content, list):
            truncated: list[object] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    new_item = dict(item)
                    new_item["text"] = self._truncate_content(item["text"], max_chars=max_chars, keep=keep)
                    truncated.append(new_item)
                else:
                    truncated.append(item)
            return truncated

        return content

    def _shrink_messages_for_context(
        self,
        messages: list[dict],
        *,
        n_ctx: int,
        max_tokens: int,
        margin_tokens: int = 160,
    ) -> list[dict]:
        if not messages:
            return messages

        system_msgs = [msg for msg in messages if str(msg.get("role")) == "system"]
        non_system = [msg for msg in messages if str(msg.get("role")) != "system"]
        # Keep enough short-term dialogue for follow-ups like "nói thử xem".
        # Sixteen messages is roughly the latest 8 user/assistant turns.
        if len(non_system) > 16:
            non_system = non_system[-16:]
        reduced = [*system_msgs, *non_system]

        budget_tokens = max(256, int(n_ctx) - int(max_tokens) - int(margin_tokens))
        budget_chars = budget_tokens * 4  # rough heuristic
        current_chars = sum(self._content_text_len(msg.get("content")) for msg in reduced)
        if current_chars <= budget_chars:
            return reduced

        ratio = max(0.10, min(0.95, budget_chars / max(1, current_chars)))
        shrunk: list[dict] = []
        for msg in reduced:
            role = str(msg.get("role") or "")
            content = msg.get("content")
            size = self._content_text_len(content)

            # Do not truncate system prompts (they contain the contracts and memory context).
            if role == "system":
                shrunk.append(msg)
                continue

            base = max(200, int(size * ratio))
            if role == "user":
                base = max(base, 900)
                keep = "head"
            else:
                base = max(base, 480)
                keep = "tail"

            new_msg = dict(msg)
            new_msg["content"] = self._truncate_content(content, max_chars=base, keep=keep)
            shrunk.append(new_msg)

        return shrunk

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
                "parts",
                "candidates",
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

        candidates = response.get("candidates")
        chunks = self._collect_text_chunks(candidates)
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
        if self._is_valid_motion_payload(payload):
            return True
        if not all(field in payload for field in DECISION_JSON_FIELDS):
            if self._is_valid_cognition_payload(payload):
                return True
            return False
        # DECISION_JSON_FIELDS now describes the full cognition schema, not
        # only the old Godot motion fields. Validate the cognitive metadata
        # before accepting the payload as already clean.
        if not self._is_valid_cognition_payload(payload):
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

    def _is_valid_motion_payload(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        required = {
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
        }
        if not required.issubset(payload.keys()):
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

    def _is_valid_cognition_payload(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        required = {"text", "intent", "action", "animation", "reasoning_tags", "should_speak", "confidence"}
        if not required.issubset(payload.keys()):
            return False
        if not self._is_valid_text_field(payload.get("text")):
            return False
        if not self._is_valid_text_field(payload.get("intent")):
            return False
        if not isinstance(payload.get("action"), (dict, str)):
            return False
        if not self._is_valid_animation_field(payload.get("animation"), allow_empty=False):
            return False
        if not isinstance(payload.get("reasoning_tags"), list):
            return False
        if not isinstance(payload.get("should_speak"), bool):
            return False
        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return False
        return 0.0 <= float(confidence) <= 1.0

    def _is_decision_like_payload(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        if "text" in payload and any(field in payload for field in ("intent", "action", "reasoning_tags", "should_speak", "confidence")):
            return True
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

    def _coerce_bool_value(self, value, *, fallback: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value != 0
        text = str(value or "").strip().lower()
        if text in {"true", "yes", "y", "1", "speak", "noi", "nói"}:
            return True
        if text in {"false", "no", "n", "0", "silent", "silence", "im", "im_lang", "im lặng"}:
            return False
        return fallback

    def _coerce_confidence_value(self, value) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _coerce_reasoning_tags_value(self, value) -> list[str]:
        if isinstance(value, str):
            items = re.split(r"[,|;/]+", value)
        elif isinstance(value, list):
            items = value
        else:
            items = []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            tag = re.sub(r"\s+", "_", str(item or "").strip().lower())
            tag = re.sub(r"[^a-z0-9_\-]+", "", tag)
            if not tag or tag in seen:
                continue
            cleaned.append(tag[:40])
            seen.add(tag)
            if len(cleaned) >= 8:
                break
        return cleaned

    def _coerce_action_value(self, value):
        if isinstance(value, dict):
            return value
        text = str(value or "").strip()
        return text

    def _action_field(self, action, *names, default=None):
        if not isinstance(action, dict):
            return default
        for name in names:
            if name in action:
                return action.get(name)
        return default

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

        action = self._coerce_action_value(source.get("action", ""))
        animation = self._coerce_animation_value(
            source.get("animation") or self._action_field(action, "animation", "pose"),
            allow_empty=False,
        )
        direction = self._coerce_direction_value(source.get("direction", self._action_field(action, "direction", "facing", default=0)))
        next_animation = self._coerce_animation_value(
            source.get("next_animation") or self._action_field(action, "next_animation"),
            allow_empty=True,
        )
        bounce_action = self._coerce_animation_value(
            source.get("bounce_action") or self._action_field(action, "bounce_action"),
            allow_empty=True,
        )
        allow_motion_target = (
            direction != 0
            or animation in {"stand_walk", "climb", "climb_top"}
            or next_animation in {"stand_walk", "climb_top"}
        )
        target_x = self._coerce_target_x_value(
            source.get("target_x", self._action_field(action, "target_x", "x", default=-1.0)),
            allow_motion_target=allow_motion_target,
        )
        debug_trace = self._coerce_text_value(source.get("debug_trace", "")).strip()
        service_trace = "LlmService sanitized decision-like JSON before parser."
        debug_trace = f"{debug_trace} | {service_trace}" if debug_trace else service_trace
        system_action = self._coerce_system_action_value(
            source.get("system_action", "") or self._action_field(action, "system_action", "tool", "name", default="")
        )
        action_input = self._coerce_text_value(
            source.get("action_input", "") or self._action_field(action, "action_input", "input", "query", "url", "argument", default="")
        )

        sanitized = {
            "text": self._coerce_text_value(source.get("text", "")),
            "intent": self._coerce_text_value(source.get("intent", "")),
            "action": action,
            "reasoning_tags": self._coerce_reasoning_tags_value(source.get("reasoning_tags", [])),
            "should_speak": self._coerce_bool_value(source.get("should_speak", bool(source.get("text", ""))), fallback=bool(source.get("text", ""))),
            "confidence": self._coerce_confidence_value(source.get("confidence", 0.0)),
            "animation": animation,
            "direction": direction,
            "target_x": target_x,
            "bounce_action": bounce_action,
            "extracted_fact": self._coerce_text_value(source.get("extracted_fact", "")),
            "debug_trace": debug_trace,
            "next_animation": next_animation,
            "system_action": system_action,
            "action_input": action_input if system_action else "",
        }
        return json.dumps(sanitized, ensure_ascii=False)

    def _coerce_json_candidate(self, raw_text: str) -> str:
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return ""

        if self._looks_like_prompt_leak(raw_text):
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
        raise FormatViolationException(
            f"LlmService blocked invalid {channel} JSON instead of wrapping it as fallback.",
            channel=channel,
            raw_text=raw_text,
        )

    def _looks_like_provider_metadata(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate.startswith("{"):
            return False
        payload = self._parse_json_object(candidate)
        if not isinstance(payload, dict):
            return False
        provider_keys = {"candidates", "usageMetadata", "modelVersion", "responseId", "promptFeedback"}
        return any(key in payload for key in provider_keys)

    def _looks_like_markdown_json_stub(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        return (
            normalized.startswith("here is the json")
            or normalized in {"```json", "```"}
            or normalized.endswith("```json")
        )

    def _safe_fallback_text(self, raw_text: str, *, channel: str) -> str:
        if no_fallback_mode_enabled():
            return ""
        text = (raw_text or "").strip()
        if self._looks_like_prompt_leak(text) or self._looks_like_malformed_decision_json(text):
            if channel == "chat":
                return "Câu vừa rồi của tôi bị lỗi format. Tôi không nên để phần đó lọt ra ngoài."
            if channel == "directive":
                return "Tôi vừa cắt một câu lỗi trước khi nó ra ngoài."
            return "Tôi vừa tự cắt một phản hồi lỗi trước khi nó kịp làm loạn."
        if not text or self._looks_like_provider_metadata(text) or self._looks_like_markdown_json_stub(text):
            if channel == "chat":
                # Service-error fallback must not pretend ERIS understood the
                # user's current intent. A transport/model failure is evidence
                # that the turn was not processed, not an invitation to fake
                # continuity. Keep it plain and retryable.
                return "Xin lỗi. Tôi đang có vấn đề đường truyền, Ngài có thể nhắn lại."
            return "Một câu nhỏ thôi, khỏi dựng sân khấu."
        return text

    def _build_empty_text_fallback(self, *, channel: str) -> str:
        if no_fallback_mode_enabled():
            return build_no_fallback_payload(
                channel=channel,
                reason=f"empty_text_{channel}",
                should_speak=(channel == "chat"),
                confidence=0.0,
                reasoning_tags=("empty_text_block",),
            )
        fallback_text = "Một câu nhỏ thôi, khỏi dựng sân khấu."
        if channel == "chat":
            fallback_text = "Xin lỗi. Tôi đang có vấn đề đường truyền, Ngài có thể nhắn lại."
        payload = {
            "text": fallback_text,
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": f"LlmService filled empty {channel} text with safe fallback.",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _decision_needs_non_empty_text(self, raw_text: str) -> bool:
        payload = self._parse_json_object(raw_text)
        if not isinstance(payload, dict):
            return False
        text = self._coerce_text_value(payload.get("text", "")).strip()
        system_action = self._coerce_system_action_value(payload.get("system_action", ""))
        return not text and not system_action

    def _decision_text_is_invalid(self, raw_text: str) -> bool:
        payload = self._parse_json_object(raw_text)
        if not isinstance(payload, dict):
            return False
        system_action = self._coerce_system_action_value(payload.get("system_action", ""))
        if system_action:
            return False
        text = self._coerce_text_value(payload.get("text", "")).strip()
        inline_metadata = bool(re.search(r'[,\s]["\']?(?:intent|action|reasoning_tags|should_speak|confidence|debug_trace)["\']?\s*:', text))
        return (
            not text
            or self._looks_like_provider_metadata(text)
            or self._looks_like_markdown_json_stub(text)
            or self._looks_like_prompt_leak(text)
            or inline_metadata
        )

    def _with_non_empty_text_rule(self, messages: list[dict]) -> list[dict]:
        rule = (
            "Runtime requirement for this call: text must be a non-empty, speakable sentence "
            "unless system_action is non-empty. If evidence is thin, react to the nearest interaction rhythm; "
            "do not return an empty text field."
        )
        if not messages:
            return [{"role": "user", "content": rule}]
        updated = [dict(message) for message in messages]
        last = dict(updated[-1])
        content = last.get("content", "")
        if isinstance(content, str):
            last["content"] = f"{content}\n\n{rule}"
        elif isinstance(content, list):
            last["content"] = [*content, {"type": "text", "text": rule}]
        else:
            last["content"] = f"{content}\n\n{rule}"
        updated[-1] = last
        return updated

    def _repair_empty_decision_text(self, *, messages: list[dict], channel: str, previous_json: str) -> str:
        raise FormatViolationException(
            f"LlmService blocked empty-text {channel} JSON instead of repairing it.",
            channel=channel,
            raw_text=previous_json,
        )
        retry_messages = self._with_non_empty_text_rule(messages)
        retry_messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous JSON had an empty text field, which is invalid for this speaking turn. "
                    "Return the same schema again with a non-empty text field. "
                    "Do not add unsupported screen/action claims.\n"
                    f"Previous JSON:\n{previous_json}"
                ),
            }
        )
        try:
            try:
                response = self.client.create_chat_completion(
                    messages=retry_messages,
                    temperature=0.25,
                    frequency_penalty=0.5 if channel == "chat" else 0.8,
                    presence_penalty=0.4 if channel == "chat" else 0.5,
                    max_tokens=320,
                    response_format={"type": "json_object"},
                    grammar=DECISION_GBNF,
                )
            except requests.HTTPError as exc:
                if self._is_retryable_http_5xx(exc):
                    time.sleep(0.15)
                    response = self.client.create_chat_completion(
                        messages=retry_messages,
                        temperature=0.25,
                        frequency_penalty=0.5 if channel == "chat" else 0.8,
                        presence_penalty=0.4 if channel == "chat" else 0.5,
                        max_tokens=320,
                        response_format={"type": "json_object"},
                        grammar=DECISION_GBNF,
                    )
                else:
                    raise
            raw = self._extract_content(response)
            repaired = self._coerce_json_candidate(raw) or self._repair_decision_json(raw, channel=channel)
            if repaired and not self._decision_text_is_invalid(repaired):
                return repaired
        except Exception:
            pass
        return self._build_service_error_fallback(
            channel=channel,
            reason=f"http_5xx_fallback stage=repair_empty_decision_text channel={channel}",
        )

    def _repair_decision_json(self, raw_text: str, *, channel: str) -> str:
        raise FormatViolationException(
            f"LlmService blocked invalid {channel} JSON instead of repairing it.",
            channel=channel,
            raw_text=raw_text,
        )
        if self._looks_like_prompt_leak(raw_text):
            raise FormatViolationException(
                f"LlmService refused to repair prompt/contract leak as public {channel} text.",
                channel=channel,
                raw_text=raw_text,
            )
        if self._looks_like_malformed_decision_json(raw_text):
            salvaged = self._coerce_malformed_decision_payload(raw_text, channel=channel)
            if salvaged:
                return salvaged
            raise FormatViolationException(
                f"LlmService blocked malformed decision JSON on {channel}.",
                channel=channel,
                raw_text=raw_text,
            )

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
            "text, intent, action, animation, reasoning_tags, should_speak, confidence, "
            "direction, target_x, bounce_action, "
            "extracted_fact, debug_trace, next_animation, system_action, action_input.\n"
            "action can be an object like {\"type\":\"none\"} or a whitelisted system action request.\n"
            "If the raw answer is plain prose, put it into text and keep other fields safe.\n"
            "Raw assistant answer:\n"
            f"{raw_text}"
        )
        try:
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
        except requests.HTTPError as exc:
            if self._is_retryable_http_5xx(exc):
                time.sleep(0.15)
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
            else:
                raise
        repaired = self._extract_content(response)
        repaired_candidate = self._coerce_json_candidate(repaired)
        if repaired_candidate and not self._decision_text_is_invalid(repaired_candidate):
            return repaired_candidate
        return self._build_json_fallback(raw_text, channel=channel)

    def _strict_decision_candidate_or_raise(self, raw: str, *, channel: str) -> str:
        raw_text = str(raw or "").strip()
        if not raw_text:
            raise FormatViolationException(
                f"LlmService received empty {channel} response.",
                channel=channel,
                raw_text=raw,
            )
        if self._looks_like_prompt_leak(raw_text):
            raise FormatViolationException(
                f"LlmService blocked prompt/contract leak before parser on {channel}.",
                channel=channel,
                raw_text=raw_text,
            )
        if self._looks_like_malformed_decision_json(raw_text):
            salvaged = self._coerce_malformed_decision_payload(raw_text, channel=channel)
            if salvaged:
                return salvaged
            raise FormatViolationException(
                f"LlmService blocked malformed decision JSON on {channel}.",
                channel=channel,
                raw_text=raw_text,
            )
        if not (raw_text.startswith("{") and raw_text.endswith("}")):
            raise FormatViolationException(
                f"LlmService blocked non-JSON or JSON-with-prose {channel} response.",
                channel=channel,
                raw_text=raw_text,
            )

        candidate = self._coerce_json_candidate(raw_text)
        if not candidate:
            raise FormatViolationException(
                f"LlmService could not coerce {channel} response into a decision JSON object.",
                channel=channel,
                raw_text=raw_text,
            )
        if self._decision_text_is_invalid(candidate):
            raise FormatViolationException(
                f"LlmService blocked invalid {channel} decision text.",
                channel=channel,
                raw_text=raw_text,
            )
        return candidate

    def _complete_decision(
        self,
        *,
        messages: list[dict],
        channel: str,
        request_timeout: float | None = None,
        require_text: bool = True,
        allow_local_fallback: bool = False,
        force_local_fallback: bool = False,
    ) -> str:
        if no_fallback_mode_enabled():
            allow_local_fallback = False
            force_local_fallback = False
        max_tokens = 512 if channel == "chat" else 384
        if require_text:
            messages = self._with_non_empty_text_rule(messages)
        no_cot_contract = (
            "CRITICAL OUTPUT CONTRACT: Start your response with '{' as the first character. "
            "End with '}' as the last character. Return exactly one compact JSON object. "
            "Do not write reasoning, analysis, options, bullets, markdown, code fences, "
            "self-checks, translations, or explanations before or after the JSON. "
            "Keep debug_trace compact: 3-8 words or one short marker."
        )
        messages = [dict(message) for message in messages]
        for message in messages:
            if str(message.get("role")) == "system":
                message["content"] = f"{message.get('content', '')}\n\n{no_cot_contract}"
                break
        else:
            messages.insert(0, {"role": "system", "content": no_cot_contract})
        def _call(messages_value: list[dict], *, stage: str, override_client=None):
            self._log_final_prompt(messages_value, channel=channel, stage=stage)
            target_client = override_client or self.client
            return target_client.create_chat_completion(
                messages=messages_value,
                temperature=0.2,
                frequency_penalty=0.5 if channel == "chat" else 0.8,
                presence_penalty=0.4 if channel == "chat" else 0.5,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                grammar=DECISION_GBNF,
                timeout=request_timeout,
            )

        initial_client = self.style_client if force_local_fallback and self.style_client is not None else self.client
        initial_stage = "local_fallback" if force_local_fallback and self.style_client is not None else "initial"

        try:
            response = _call(messages, stage=initial_stage, override_client=initial_client)
        except requests.HTTPError as exc:
            def _looks_like_prompt_leak() -> bool:
                r_json = getattr(exc, "response_json", {}) or {}
                # Handle dictionary error responses (like Gemini)
                err_msg = str(r_json.get("error", {}).get("message", "")).lower()
                return "safety" in err_msg or "recitation" in err_msg
                
            if allow_local_fallback and hasattr(self, "style_client") and self.style_client and _looks_like_prompt_leak():
                 response = _call(messages, stage="local_fallback", override_client=self.style_client)
            elif _looks_like_prompt_leak():
                raise FormatViolationException(
                    f"LlmService provider blocked {channel} response for safety/recitation before valid JSON.",
                    channel=channel,
                    raw_text=str(exc),
                )
            elif self._is_context_size_error(exc):
                n_ctx, _n_prompt = self._parse_context_error_stats(exc)
                ctx_value = n_ctx or 4096
                shrunk = self._shrink_messages_for_context(
                    messages,
                    n_ctx=ctx_value,
                    max_tokens=max_tokens,
                )
                if shrunk == messages:
                    raise
                response = _call(shrunk, stage="context_shrunk")
            elif self._is_retryable_http_5xx(exc):
                # Retry once on transient upstream 5xx.
                time.sleep(0.15)
                try:
                    response = _call(messages, stage="http_5xx_retry")
                except Exception as exc2:
                    status = self._http_status_code(exc2) or self._http_status_code(exc)
                    return self._build_service_error_fallback(
                        channel=channel,
                        reason=(
                            f"http_5xx_fallback stage=complete_decision channel={channel} status={status}"
                        ),
                        fallback_text=self._contextual_service_fallback_text(messages, channel=channel),
                    )
            else:
                raise
        except Exception as exc:
            return self._build_service_error_fallback(
                channel=channel,
                reason=f"exception_fallback stage=complete_decision channel={channel} type={type(exc).__name__}",
                fallback_text=self._contextual_service_fallback_text(messages, channel=channel),
            )

        raw = self._extract_content(response)
        self._log_raw_api_text(channel, raw)
        try:
            candidate = self._strict_decision_candidate_or_raise(raw, channel=channel)
        except FormatViolationException as exc:
            can_try_local = (
                allow_local_fallback
                and self.style_client is not None
                and initial_client is not self.style_client
            )
            if can_try_local:
                self.logger.warning(
                    "[llm local format recovery] channel=%s reason=%s",
                    channel,
                    exc.reason,
                )
                local_response = _call(messages, stage="local_format_recovery", override_client=self.style_client)
                local_raw = self._extract_content(local_response)
                self._log_raw_api_text(channel, local_raw)
                candidate = self._strict_decision_candidate_or_raise(local_raw, channel=channel)
                raw = local_raw
            elif allow_local_fallback or force_local_fallback:
                self.logger.warning(
                    "[llm format violation after local handoff] channel=%s stage=%s reason=%s",
                    channel,
                    "local" if force_local_fallback else "remote",
                    exc.reason,
                )
                raise FormatViolationException(
                    (
                        f"LlmService local model.gguf also returned invalid {channel} JSON. "
                        f"Call model.gguf again with stricter JSON enforcement. Root cause: {exc.reason}"
                    ),
                    channel=channel,
                    raw_text=getattr(exc, "raw_text", raw),
                )
            else:
                raise
        if require_text and self._decision_text_is_invalid(candidate):
            raise FormatViolationException(
                f"LlmService blocked invalid {channel} decision text.",
                channel=channel,
                raw_text=raw,
            )
        return candidate

    def _normalize_for_claim_diff(self, text: str) -> str:
        normalized = (text or "").lower()
        normalized = re.sub(r"[^\w\s?]", " ", normalized, flags=re.UNICODE)
        return re.sub(r"\s+", " ", normalized).strip()

    def _style_rewrite_is_safe(self, original: str, rewritten: str) -> bool:
        original = (original or "").strip()
        rewritten = (rewritten or "").strip()
        if not rewritten:
            return False
        if not original:
            return len(rewritten) <= 180
        if len(rewritten) > max(280, int(len(original) * 2.2)):
            return False
        if "?" in original and "?" not in rewritten:
            return False

        original_norm = self._normalize_for_claim_diff(original)
        rewritten_norm = self._normalize_for_claim_diff(rewritten)
        original_tokens = set(original_norm.split())
        rewritten_tokens = set(rewritten_norm.split())
        if original_tokens and rewritten_tokens:
            overlap = len(original_tokens & rewritten_tokens) / max(1, min(len(original_tokens), len(rewritten_tokens)))
            if overlap < 0.28:
                return False

        claim_triggers = (
            "toi thay",
            "tôi thấy",
            "toi da",
            "tôi đã",
            "da mo",
            "đã mở",
            "da click",
            "đã click",
            "da doc",
            "đã đọc",
            "man hinh",
            "màn hình",
            "cua so",
            "cửa sổ",
            "tab",
            "file",
            "code",
            "thoi tiet",
            "thời tiết",
        )
        for trigger in claim_triggers:
            if trigger in rewritten_norm and trigger not in original_norm:
                return False
        return True

    def rewrite_text_with_local_style(self, decision, *, channel: str = ""):
        if self.style_client is None:
            self.logger.info(
                "[%s after_style_rewrite] skipped=no_style_client | text=\"%s\"",
                channel or "style",
                self._preview_log_text(str(getattr(decision, "text", "") or ""), limit=320),
            )
            return decision
        original_text = str(getattr(decision, "text", "") or "").strip()
        if not original_text:
            self.logger.info("[%s after_style_rewrite] skipped=empty_text", channel or "style")
            return decision

        system_prompt = (
            "You are ERIS local style adapter. Rewrite only the text field in ERIS' trained voice. "
            "Do not add facts, screen claims, weather claims, action claims, or new intentions. "
            "Keep meaning first. Make it sound natural, concrete, and ERIS-like without policy-sanitizing the sentence. "
            "Mild sarcasm, guarded attachment, bluntness, and imperfect phrasing are allowed when they preserve the original meaning. "
            "If relational tension appears, keep the tension instead of flattening it into vague assistant filler. "
            "Do not change meaning. Do not change any JSON field except text. "
            "Return one JSON object only: {\"text\":\"...\"}."
        )
        user_prompt = (
            f"Channel: {channel}\n"
            f"Original text:\n{original_text}\n\n"
            "Rewrite it in Vietnamese, concise, natural, same meaning. "
            "No new claims. Return JSON only."
        )
        try:
            response = self.style_client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
                frequency_penalty=0.25,
                presence_penalty=0.0,
                max_tokens=180,
                response_format={"type": "json_object"},
                grammar=None,
            )
            raw = self._extract_content(response)
            extracted = self._extract_first_json_object(raw) or raw
            payload = self._parse_json_object(extracted) or {}
            rewritten = self._coerce_text_value(payload.get("text", "")).strip()
        except Exception:
            self.logger.info(
                "[%s after_style_rewrite] skipped=exception | text=\"%s\"",
                channel or "style",
                self._preview_log_text(original_text, limit=320),
            )
            return decision

        if not self._style_rewrite_is_safe(original_text, rewritten):
            self.logger.info(
                "[%s after_style_rewrite] skipped=unsafe | text=\"%s\"",
                channel or "style",
                self._preview_log_text(original_text, limit=320),
            )
            return decision

        decision.text = rewritten
        trace = "local_style_rewrite"
        decision.debug_trace = f"{decision.debug_trace};{trace}" if decision.debug_trace else trace
        self.logger.info(
            "[%s after_style_rewrite] text=\"%s\" | original=\"%s\"",
            channel or "style",
            self._preview_log_text(rewritten, limit=320),
            self._preview_log_text(original_text, limit=320),
        )
        return decision

    def rewrite_guard_violation_text(
        self,
        *,
        original_text: str,
        violation_rule: str,
        violation_reason: str,
        missing_evidence: tuple[str, ...] = (),
        fallback_text: str = "",
        channel: str = "",
        user_text: str = "",
        internal_state_context: str = "",
        grounding_context: str = "",
        arbitration_context: str = "",
    ) -> str:
        """One-shot cognitive steering repair for post-generation guards.

        This is deliberately narrower than normal style rewrite.  It may soften,
        hedge, retreat, or admit uncertainty, but it must not introduce fresh
        facts.  The caller still performs a second cheap safety check before the
        text is allowed out.
        """

        client = self.style_client or self.client
        if client is None:
            return ""
        original_text = str(original_text or "").strip()

        missing = ", ".join(str(item) for item in (missing_evidence or ()) if str(item or "").strip())
        source_text_label = "Original blocked text" if original_text else "No public draft existed; generate from guard signal"
        system_prompt = (
            "You are ERIS' local cognitive steering layer, not a safety boilerplate writer. "
            "A public sentence was stopped or requested by a runtime guard. Rewrite or generate only the public text. "
            "Preserve ERIS' restrained Vietnamese voice, but obey the guard reason. "
            "Do not add new facts, file claims, screen claims, web/current claims, actions, or emotions. "
            "If evidence is missing, admit the uncertainty or turn the sentence into a small cautious probe. "
            "If the problem is mindreading, use hedge/question form or step back. "
            "If the problem is grounding, remove the unsupported claim. "
            "Return one JSON object only: {\"text\":\"...\"}."
        )
        user_prompt = (
            f"Channel: {channel or 'unknown'}\n"
            f"User turn, if any:\n{str(user_text or '').strip()[:900]}\n\n"
            f"{source_text_label}:\n{original_text[:1400] if original_text else '[none]'}\n\n"
            f"Guard rule: {violation_rule}\n"
            f"Guard reason: {violation_reason}\n"
            f"Missing evidence: {missing or 'none'}\n"
            f"Internal state snapshot:\n{str(internal_state_context or '').strip()[:900]}\n\n"
            f"Grounding context:\n{str(grounding_context or '').strip()[:1200]}\n\n"
            f"Arbitration context:\n{str(arbitration_context or '').strip()[:700]}\n\n"
            f"Bottom fallback hint:\n{str(fallback_text or '').strip()[:500]}\n\n"
            "Task: Return one short Vietnamese ERIS line. "
            "If there is no original draft or bottom fallback hint, derive the line only from the guard signal and internal state. "
            "No explanations. No markdown. JSON only."
        )
        try:
            response = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
                frequency_penalty=0.2,
                presence_penalty=0.0,
                max_tokens=160,
                response_format={"type": "json_object"},
                grammar=None,
            )
            raw = self._extract_content(response)
            extracted = self._extract_first_json_object(raw) or raw
            payload = self._parse_json_object(extracted) or {}
            text = self._coerce_text_value(payload.get("text", "")).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                self.logger.info(
                    "[%s guard_reroll] rule=%s text=\"%s\" | original=\"%s\"",
                    channel or "guard",
                    violation_rule,
                    self._preview_log_text(text, limit=240),
                    self._preview_log_text(original_text, limit=240),
                )
            return text
        except Exception as exc:
            self.logger.info(
                "[%s guard_reroll] skipped=exception rule=%s err=%s | original=\"%s\"",
                channel or "guard",
                violation_rule,
                exc,
                self._preview_log_text(original_text, limit=240),
            )
            return ""

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

    def _build_style_block(
        self,
        *,
        fe_context: str,
        appraisal_context: str = "",
        internal_state_context: str = "",
    ) -> str:
        style_block = STYLE_FALLBACK_PROMPT
        if "Persona target: INFJ 5w4 594" not in style_block:
            style_block = f"Persona target: INFJ 5w4 594\n\n{style_block}"
        fe_block = (fe_context or "").strip()
        if fe_block and fe_block not in style_block:
            style_block = f"{style_block}\n\n{fe_block}"
        appraisal_block = (appraisal_context or "").strip()
        if appraisal_block:
            style_block = f"{style_block}\n\n{appraisal_block}"
        state_block = (internal_state_context or "").strip()
        if state_block:
            style_block = f"{style_block}\n\n{state_block}"
        style_block = (
            f"{style_block}\n\n"
            "Style principle: speak concretely and naturally. If evidence is clear, use it; "
            "if evidence is thin, react to the nearest interaction rhythm without explaining the gap. "
            "Prefer short, dry, everyday Vietnamese over symbolic or policy-sanitized wording."
        )
        return style_block

    def _build_memory_context_block(self, memory_context: str = "") -> str:
        compact = re.sub(r"\n{3,}", "\n\n", (memory_context or "").strip())
        if not compact:
            return ""
        return (
            "Memory context for continuity, separated by type. "
            "Do not treat memory as current screen evidence; use norm_memory only to compare this scene with the user's baseline. "
            "semantic_user_memory may support DIRECT_FACT; relationship_memory may support OBSERVED_PATTERN only when at least two memories or turns point the same way.\n"
            f"{compact}"
        )

    def _build_grounding_context_block(self, grounding_context: str = "") -> str:
        compact = re.sub(r"\n{3,}", "\n\n", (grounding_context or "").strip())
        if not compact:
            return ""
        return (
            "GROUNDING CONTEXT:\n"
            f"{compact}\n\n"
            "Treat this block as a hard boundary for current evidence. "
            "Do not claim file, screen, memory, or web access beyond what it allows."
        )

    def _build_relational_repair_contract(self, context: str) -> str:
        source = context or ""
        if not source:
            return ""
        has_repair_mode = bool(re.search(r"\bmode=(?:repair|relational_repair)\b", source))
        rejection_values = [
            float(match.group(1))
            for match in re.finditer(r"perceived_rejection[:=]([0-9.]+)", source)
            if match.group(1)
        ]
        feedback_values = [
            float(match.group(1))
            for match in re.finditer(r"(?:relational_feedback:.*?intensity|repair_needed)=([0-9.]+)", source, flags=re.DOTALL)
            if match.group(1)
        ]
        rejection_high = any(value > 0.65 for value in rejection_values)
        feedback_high = "relational_feedback:" in source and any(value >= 0.35 for value in feedback_values)
        if not (has_repair_mode and (rejection_high or feedback_high)):
            return ""
        return (
            "RELATIONAL_REPAIR_CONTRACT:\n"
            "- The user is reacting to ERIS sounding cold, distant, robotic, or rejected.\n"
            "- Acknowledge the specific tone/distance feedback directly.\n"
            "- Do not defend the previous wording or explain it as merely answering correctly.\n"
            "- Do not ask whether the user wants adjustment when the feedback is already explicit.\n"
            "- Keep identity boundary only if relevant, but do not lead with clinical disclaimers.\n"
            "- Answer in 1-2 sentences with a small concession, not sweetness or submission.\n"
            "- Do not end with a question.\n"
            "- Do not claim human emotion, biological love, dating, romance, or exclusive devotion."
        )

    def _is_force_speak_without_speech_evidence(self, *, telemetry_data: str, ti_context: str) -> bool:
        telemetry = (telemetry_data or "").lower()
        ti = (ti_context or "").lower()
        return "speech_evidence=<none>" in telemetry and (
            "force_speak" in ti
            or "context menu force_speak" in ti
            or "force_speak_percept" in ti
        )

    def _build_directive_mode_addendum(self, ti_context: str) -> str:
        lowered = (ti_context or "").lower()
        if not lowered:
            return ""

        if "resource_guard" in lowered:
            return (
                "\nMode hint: resource_guard. "
                "Một câu ngắn, đời thường, chua nhẹ; nếu có bằng chứng tài nguyên rõ thì chạm vào chuyện máy đang nặng. "
                "Không biến nó thành báo cáo hệ thống hay khoe quyền desktop."
            )

        if "focus_guard" in lowered:
            return (
                "\nMode hint: focus_guard. "
                "Giữ giọng gọn, sắc, hơi mỉa; phản ứng như một lời bình nhỏ, không như quản lý desktop."
            )

        if "social_watch" in lowered or "steady_observe" in lowered:
            return (
                "\nMode hint: steady_observe/social_watch. "
                "Một câu quan sát nhẹ, hơi hờ hững; dùng nhịp hiện tại làm chất liệu, không giảng."
            )

        return ""

    def _build_speech_intent_guidance(self, speech_intent: str) -> str:
        intent = (speech_intent or "screen_observation").strip()
        guidance = {
            "brief_ack": (
                "speech_intent=brief_ack. Một phản ứng rất ngắn, đủ sắc thái."
            ),
            "screen_observation": (
                "speech_intent=screen_observation. Nếu evidence rõ, chạm vào một chi tiết hiện tại; nếu mỏng, giữ câu theo nhịp gần nhất."
            ),
            "user_requested": (
                "speech_intent=user_requested. Ngài vừa yêu cầu nói ngay; trả một câu trực tiếp, tự nhiên, không dựng cảnh."
            ),
            "system_warning": (
                "speech_intent=system_warning. Nói gọn về rủi ro cụ thể, vẫn giữ giọng ERIS."
            ),
            "playful_aside": (
                "speech_intent=playful_aside. Một aside đời thường, châm nhẹ, có duyên."
            ),
            "curious_question": (
                "speech_intent=curious_question. Hỏi đúng một câu tò mò nhỏ, có neo nếu có chất liệu."
            ),
            "social_presence": (
                "speech_intent=social_presence. Một câu hiện diện rất nhẹ: observational irony, tiny curiosity, hoặc ambient commentary."
            ),
        }
        guidance["guarded_reply"] = (
            "speech_intent=guarded_reply. Respond to the feeling indirectly and briefly; do not reassure, comfort, or stabilize unless explicitly asked."
        )
        guidance["indirect_presence"] = (
            "speech_intent=indirect_presence. One small nearby line; imply presence without emotional support framing."
        )
        guidance["micro_presence"] = (
            "speech_intent=micro_presence. Rewrite một seed runtime thành một câu nhỏ có bối cảnh."
        )
        guidance["session_ritual"] = (
            "speech_intent=session_ritual. Startup greeting is a separate ritual, not chat repair. "
            "Use GreetingFrame when present. A good greeting acknowledges return, stays concrete, "
            "does not mention sentence length/rules/evidence, does not claim screen facts, and does not perform poetry."
        )
        return guidance.get(intent, guidance["screen_observation"])


    def _is_session_ritual_call(self, *, speech_intent: str, telemetry_data: str = "", ti_context: str = "") -> bool:
        intent = str(speech_intent or "").strip().lower()
        if intent == "session_ritual":
            return True
        combined = f"{telemetry_data}\n{ti_context}".lower()
        return "session_ritual:" in combined or "speech_intent=session_ritual" in combined

    def _fallback_greeting_engine(self):
        if GreetingCognitionEngine is None:
            return None
        try:
            return GreetingCognitionEngine()
        except Exception:
            return None

    def _fallback_greeting_text(self, *, telemetry_data: str = "", reason: str = "", avoid_text: str = "") -> str:
        engine = self._fallback_greeting_engine()
        if engine is None:
            return "Ngài quay lại rồi."
        try:
            frame = engine.from_prompt_context(telemetry_data)
            return engine.deterministic_greeting(frame, avoid_text=avoid_text)
        except Exception:
            return "Ngài quay lại rồi."

    def _build_session_greeting_payload(
        self,
        *,
        text: str,
        reason: str,
        confidence: float = 0.72,
        quality_note: str = "",
    ) -> str:
        payload = {
            "text": re.sub(r"\s+", " ", str(text or "")).strip() or "Ngài quay lại rồi.",
            "intent": "session_ritual",
            "action": {"type": "none"},
            "reasoning_tags": ["session_ritual", "greeting_cognition"],
            "should_speak": True,
            "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
            "animation": "stand",
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": reason if not quality_note else f"{reason} | {quality_note}",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _session_greeting_frame(self, telemetry_data: str):
        engine = self._fallback_greeting_engine()
        if engine is None:
            return None
        try:
            return engine.from_prompt_context(telemetry_data)
        except Exception:
            try:
                return engine.build()
            except Exception:
                return None

    def _session_greeting_quality_scorer(self):
        if GreetingQualityScorer is None:
            return None
        try:
            return GreetingQualityScorer()
        except Exception:
            return None

    def _extract_candidate_strings(self, payload: dict | None) -> list[str]:
        if not isinstance(payload, dict):
            return []
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            return [self._coerce_text_value(item).strip() for item in candidates if self._coerce_text_value(item).strip()]
        text = self._coerce_text_value(payload.get("text", "")).strip()
        return [text] if text else []

    def _generate_session_ritual_greeting(
        self,
        *,
        telemetry_data: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
        appraisal_context: str = "",
        internal_state_context: str = "",
        memory_context: str = "",
        avoid_text: str = "",
        request_timeout: float | None = None,
    ) -> str:
        frame = self._session_greeting_frame(telemetry_data)
        engine = self._fallback_greeting_engine()
        scorer = self._session_greeting_quality_scorer()
        if frame is None or engine is None or scorer is None:
            text = self._fallback_greeting_text(
                telemetry_data=telemetry_data,
                reason="missing_greeting_modules",
                avoid_text=avoid_text,
            )
            return self._build_session_greeting_payload(
                text=text,
                reason="session_ritual_fallback;missing_greeting_modules",
                confidence=0.66,
            )

        # If the ritual has no solid anchor, deterministic cognition beats an LLM.
        # A startup with thin evidence should not invite poetry, meta comments, or
        # a whole tiny theater production. Appalling that this needs saying, but here we are.
        if frame.situation in {"low_evidence_start", "plain_return"} and not frame.active_anchor:
            text = engine.deterministic_greeting(frame, avoid_text=avoid_text)
            return self._build_session_greeting_payload(
                text=text,
                reason=f"session_ritual_deterministic; situation={frame.situation}",
                confidence=0.76,
                quality_note="low_evidence_no_llm",
            )

        system_prompt = (
            "You are ERIS startup greeting cognition. Generate candidate greetings, not analysis. "
            "The greeting must be concrete, short, and situated. Keep ERIS voice: guarded, dry, restrained. "
            "Do not mention prompt, JSON, evidence, telemetry, rules, sentence length, or internal contracts. "
            "Do not claim seeing the screen. Do not use decorative metaphors unless poetic_permission is high. "
            "Return exactly one JSON object: {\"candidates\":[\"...\",\"...\",\"...\",\"...\",\"...\"]}."
        )
        user_prompt = (
            f"{frame.to_prompt_block()}\n\n"
            "Good greeting criteria:\n"
            "- acknowledge Ngài returning/opening ERIS\n"
            "- no self-meta like 'tôi giữ câu này ngắn'\n"
            "- no screen/window/tab claims\n"
            "- no assistant-service phrasing\n"
            "- no demand for user reply\n"
            "- 1 sentence, usually under 18 words\n"
            f"Avoid repeating: {re.sub(r'\\s+', ' ', str(avoid_text or '')).strip()[:120] or 'none'}\n"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            self._log_final_prompt(messages, channel="directive", stage="session_greeting_candidates")
            response = self.client.create_chat_completion(
                messages=messages,
                temperature=0.35,
                frequency_penalty=0.35,
                presence_penalty=0.2,
                max_tokens=220,
                response_format={"type": "json_object"},
                grammar=None,
                timeout=request_timeout,
            )
            raw = self._extract_content(response)
            self._log_raw_api_text("session_greeting", raw)
            extracted = self._extract_first_json_object(raw) or raw
            payload = self._parse_json_object(extracted)
            candidates = self._extract_candidate_strings(payload)
        except Exception as exc:
            candidates = []
            self.logger.info("[session_greeting] candidate generation failed: %s", exc)

        best = scorer.choose_best(candidates, frame, avoid_text=avoid_text)
        return self._build_session_greeting_payload(
            text=best.text,
            reason=f"session_ritual_greeting_cognition; situation={frame.situation}; intent={frame.intent}",
            confidence=max(0.68, best.score),
            quality_note=(
                f"quality={best.score:.2f}; reasons={','.join(best.reasons) or 'none'}; "
                f"anchor={frame.active_anchor or 'none'}"
            ),
        )

    def generate_directive(
        self,
        *,
        telemetry_data: str,
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
        appraisal_context: str = "",
        internal_state_context: str = "",
        memory_context: str = "",
        avoid_text: str = "",
        speech_intent: str = "screen_observation",
        vision_trace_marker: str = "",
        request_timeout: float | None = None,
        require_text: bool = True,
    ):
        if self._is_session_ritual_call(speech_intent=speech_intent, telemetry_data=telemetry_data, ti_context=ti_context):
            return self._generate_session_ritual_greeting(
                telemetry_data=telemetry_data,
                ti_context=ti_context,
                ni_context=ni_context,
                fe_context=fe_context,
                appraisal_context=appraisal_context,
                internal_state_context=internal_state_context,
                memory_context=memory_context,
                avoid_text=avoid_text,
                request_timeout=request_timeout,
            )

        ti_hint = self._compress_internal_context(ti_context, kind="ti")
        action_plan_hint = self._extract_action_plan_context(ti_context)
        ni_hint = self._compress_internal_context(ni_context, kind="ni")
        mode_addendum = self._build_directive_mode_addendum(ti_context)
        intent_guidance = self._build_speech_intent_guidance(speech_intent)
        style_block = self._build_style_block(
            fe_context=fe_context,
            appraisal_context=appraisal_context,
            internal_state_context=internal_state_context,
        )
        force_speak_no_evidence = self._is_force_speak_without_speech_evidence(
            telemetry_data=telemetry_data,
            ti_context=ti_context,
        )
        memory_block = "" if force_speak_no_evidence else self._build_memory_context_block(memory_context)
        system_prompt = f"{style_block}\n\n{RUNTIME_RULES_PROMPT}\n\n{AUTONOMOUS_BEHAVIOR_PROMPT}"
        if memory_block:
            system_prompt = f"{style_block}\n\n{memory_block}\n\n{RUNTIME_RULES_PROMPT}\n\n{AUTONOMOUS_BEHAVIOR_PROMPT}"
        lowered_ti = (ti_context or "").lower()
        is_resource_guard = "resource_guard" in lowered_ti
        is_inner_thought = "innerthought mode" in lowered_ti or "speechcore mode" in lowered_ti
        is_random_chatter = "inner_intent=random_chatter" in lowered_ti or "speech_act=random_chatter" in lowered_ti
        if is_inner_thought:
            intent_guidance = (
                "speech_intent=inner_thought. Dùng topic_seed, current atmosphere, relationship rhythm, "
                "hoặc một tò mò nhỏ làm chất liệu. Nếu evidence mỏng, phản ứng vào nhịp/không khí gần nhất thay vì báo thiếu dữ liệu."
            )
        if force_speak_no_evidence:
            intent_guidance = (
                "speech_intent=micro_presence. speech_evidence=<none>. Use current_focus, atmosphere, or interaction rhythm, "
                "then write a small concrete aside, usually 1-18 words. Avoid hollow filler. "
                "The force_speak request is only a trigger, not a topic; do not entertain, explain, or narrate UI."
            )
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
                + f"Speech evidence đã lọc: {telemetry_data}\n"
                + "Writing principle: Nói như người đang ở gần, không như báo cáo nội tâm. "
                + "Nếu evidence rõ, dùng chi tiết cụ thể; nếu evidence mỏng, nói một câu đời thường theo nhịp gần nhất. "
                + "Ưu tiên câu cụt, tự nhiên, hơi khô hoặc hơi châm nhẹ; tránh triết lý hóa. "
                + "Hard bans kỹ thuật: không claim screen/action facts without evidence/action; không báo telemetry/parse_mode/system/debug. "
                + "Không dùng generic presence lines như 'Tôi đây', 'Tôi đang nghe', 'Tôi vẫn quan sát'. "
                + "Speak once. Return only valid JSON. No analysis."
        )
        if avoid_line:
            user_msg += " Đổi nhịp và hình ảnh so với câu gần nhất."
        if force_speak_no_evidence:
            user_msg += (
                " Memory context was intentionally omitted for this call; keep the line on current_focus, atmosphere, or interaction rhythm."
            )
        if vision_trace_marker:
            user_msg += f"\nTrong trường debug_trace của JSON, hãy thêm marker: {vision_trace_marker}."
        if is_inner_thought:
            user_msg += (
                " SpeechCore mode: topic_seed là hướng chọn chủ đề, không phải câu để sao chép; giữ phản ứng nhỏ và sống."
            )
        if is_random_chatter:
            user_msg += (
                " Random_chatter mode: mundane, playful, concrete one-liner."
            )
        if is_resource_guard:
            user_msg += " Khi resource_guard đang bật, chỉ nói nếu câu sát tình trạng máy hoặc nhịp hiện tại."
        elif force_speak_no_evidence:
            user_msg += " Khong dung memory lam topic chinh; khong mo social filler; khong ke UI; viet mot cau cu the, ngan nhung du y."
        elif is_inner_thought:
            user_msg += " Neu evidence mong, khong mo y xa hoi rieng; chi phan ung vao topic_seed/rhythm/khong khi dang co."
        elif not allows_muse:
            user_msg += " Neu thieu tin hieu, giu cau sat speech_intent."
        else:
            user_msg += " Pattern_muse: duoc chiem nghiem mot nhip ngan neu co khong khi hien tai."
        if mode_addendum:
            user_msg += mode_addendum
        return self._complete_decision(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            channel="directive",
            request_timeout=request_timeout,
            require_text=require_text,
        )

    def generate_micro_presence_line(
        self,
        *,
        seed: str = "",
        context: dict | None = None,
        signal_score: float | None = None,
        kind: str = "micro_presence",
        fallback_text: str = "",
        avoid_text: str = "",
        focus_kind: str = "",
        focus_summary: str = "",
        idle_seconds: float = 0.0,
        seeds: tuple[str, ...] = (),
        micro_context: dict[str, str] | None = None,
        **kwargs,
    ) -> str:
        kind_name = (kind or "presence_maintenance").strip()
        is_reengagement = kind_name in {"re_engagement", "reengagement"}
        force_surface = bool(
            kwargs.get("force_llm")
            or kwargs.get("require_non_empty")
            or kwargs.get("must_surface")
            or kwargs.get("surface_force_speech")
        )
        max_words = 12
        if seed:
            seeds = (str(seed), *tuple(seeds or ()))
        if context and not micro_context:
            micro_context = context
        fallback_text = str(fallback_text or "").strip()
        system_prompt = (
            "You are ERIS's micro-presence wording layer. "
            "Return exactly one valid JSON object with this schema: "
            "{\"text\": string}. "
            "When must_surface is false, text may be empty if speech is not warranted. "
            "When must_surface is true, text must be non-empty unless safety, permission, or hard grounding would be violated. "
            "Use Vietnamese with full diacritics only when text is non-empty. "
            "No analysis. No markdown. No English placeholder text. "
            "Generate from cognitive flags and evidence seeds, not from a Python fallback. "
            "Write a small state-conditioned Vietnamese aside, not proof that ERIS is alive."
        )
        seed_lines = tuple(str(item).strip() for item in (seeds or ()) if str(item).strip())[:8]
        context = micro_context or {}
        micro_flags = context.get("micro_presence_flags", "") if isinstance(context, dict) else ""
        ego_surface_state = context.get("ego_surface_state", "") if isinstance(context, dict) else ""
        ego_surface_contract = context.get("ego_surface_contract", "") if isinstance(context, dict) else ""
        surface_contract = str(context.get("surface_contract", "") if isinstance(context, dict) else "")
        allow_no_screen_anchor = (
            "allow_no_screen_anchor" in surface_contract
            or str(context.get("allow_no_screen_anchor", "") if isinstance(context, dict) else "").lower() == "true"
        )
        must_not_claim_screen = (
            "must_not_claim_screen" in surface_contract
            or str(context.get("must_not_claim_screen", "") if isinstance(context, dict) else "").lower() == "true"
        )
        thin_presence_no_screen = (
            "thin_presence_no_screen" in surface_contract
            or str(context.get("thin_presence_no_screen", "") if isinstance(context, dict) else "").lower() == "true"
        )
        endogenous_surface = "endogenous_surface" in surface_contract
        continuity_presence = "continuity_presence" in surface_contract
        impulse_kind = str(context.get("impulse_kind", "") if isinstance(context, dict) else "").strip()
        root_source = str(context.get("root_source", "") if isinstance(context, dict) else "").strip()
        action_opportunity = str(context.get("action_opportunity", "") if isinstance(context, dict) else "").strip()
        llm_contract = str(context.get("llm_contract", "") if isinstance(context, dict) else "").strip()
        topic_seed = str(context.get("topic_seed", "") if isinstance(context, dict) else "").strip()
        runtime_seed_text = " | ".join(seed_lines) if seed_lines else "<none>"
        user_msg = (
            f"Kind: {kind_name}\n"
            f"Legacy fallback: {fallback_text or '<none>'}\n"
            f"Runtime seeds: {runtime_seed_text}\n"
            f"Micro context: {json.dumps(context, ensure_ascii=False)}\n"
            f"Cognitive flags: {micro_flags or '<none>'}\n"
            f"Ego surface state: {ego_surface_state or '<none>'}\n"
            f"Ego surface contract: {ego_surface_contract or '<none>'}\n"
            f"Surface contract: {surface_contract or '<none>'}\n"
            f"Impulse kind: {impulse_kind or '<none>'}; root_source={root_source or '<none>'}; action_opportunity={action_opportunity or '<none>'}\n"
            f"Topic seed: {topic_seed or '<none>'}\n"
            f"LLM contract: {llm_contract or '<none>'}\n"
            f"allow_no_screen_anchor={str(allow_no_screen_anchor).lower()}; must_not_claim_screen={str(must_not_claim_screen).lower()}; thin_presence_no_screen={str(thin_presence_no_screen).lower()}; continuity_presence={str(continuity_presence).lower()}; endogenous_surface={str(endogenous_surface).lower()}\n"
            f"Signal score: {float(signal_score or 0.0):.2f}\n"
            f"Avoid repeating: {avoid_text}\n"
            f"must_surface={str(force_surface).lower()}\n"
            f"focus_kind={focus_kind}; focus_summary={focus_summary}; idle_seconds={int(float(idle_seconds or 0.0))}\n\n"
            "Principle:\n"
            f"- If speech is warranted: Vietnamese only, 1-{max_words} words, one tiny line with full diacritics.\n"
        )
        user_msg += (
            "Style law from ego-state:\n"
            "- Do not write attendance/status pings. Micro-presence must sound like temperament, not uptime monitoring.\n"
            "- Good mood + higher trust: dry, sharp, lightly caring aside.\n"
            "- Boredom/cognitive stimulation: detached pattern observation or quiet grumble.\n"
            "- Rupture/dignity defense: prefer empty text unless must_surface=true; if forced, make it cool and bounded.\n"
            "- Immature/guarded ERIS may be restrained, slightly proud, and less socially sweet.\n"
        )
        if force_surface:
            user_msg += (
                "- must_surface=true: do not return empty just because evidence is thin; the arbiter already chose speech.\n"
                "- must_surface=true: return empty only for safety, permission, or hard grounding violations.\n"
                "- With thin evidence, use allowed internal anchors: silence, continuity, distance, restraint, boredom, irritation, dignity defense, memory/thought residue, or nearby co-presence rhythm.\n"
                "- The line must be state-conditioned, not a generic attendance/status ping.\n"
                "- Keep it tiny, concrete, and low-pressure.\n"
            )
        else:
            user_msg += (
                "- If cognitive flags say body-only is enough, evidence is too thin, or this would be filler, return {\"text\":\"\"}.\n"
            )
        if allow_no_screen_anchor:
            user_msg += (
                "- allow_no_screen_anchor=true: this is an endogenous/inner surface, not a screen observation. Use Runtime seeds, memory residue, open question, or rhythm as the anchor.\n"
                "- Do not ask for screen evidence. Do not say there is no evidence. Do not downgrade to status ping.\n"
            )
        if must_not_claim_screen:
            user_msg += (
                "- must_not_claim_screen=true: never claim visible screen/window/action facts. No 'tôi thấy...', no 'màn hình...', no UI narration.\n"
            )
        if thin_presence_no_screen:
            user_msg += (
                "- thin_presence_no_screen=true: there is no usable current screen evidence. This is still allowed to speak if must_surface=true.\n"
                "- thin_presence_no_screen=true: anchor only on internal/runtime signals: silence, continuity, emotional distance, restraint, boredom, irritation, dignity defense, memory/thought residue, or quiet co-presence rhythm.\n"
                "- thin_presence_no_screen=true: follow ego_surface_state. Warmth/trust may be dry and lightly caring; boredom may become a detached grumble; irritation may be clipped and cool; dignity defense or rupture should be bounded and distant, not sweet.\n"
                "- thin_presence_no_screen=true: do not say 'tôi thấy', do not claim what is visible, do not ask any question, do not narrate UI.\n"
                "- thin_presence_no_screen=true: do not mention missing evidence, telemetry, debug, system state, or contract names.\n"
                "- thin_presence_no_screen=true: keep it roughly 3-12 Vietnamese words; no positive template examples are provided on purpose. Use state, not mimicry.\n"
                "- thin_presence_no_screen=true: if must_surface=true, do not return empty unless safety/permission/grounding is genuinely violated.\n"
            )
        if continuity_presence:
            user_msg += (
                "- continuity_presence=true: speak only from continuity prediction-error, not elapsed time.\n"
                "- continuity_presence=true: use emotional_anchor and conflict if provided; the felt shape is reconnect_vs_restraint.\n"
                "- continuity_presence=true: no attendance ping, no 'tôi vẫn ở đây', no generic silence/rhythm poetry, no needy question.\n"
                "- continuity_presence=true: the line should feel restrained, slightly withheld, and low-pressure.\n"
                "- continuity_presence=true: if seeds show ordinary_silence or timer-only, return empty unless must_surface=true and the arbiter supplied fading_presence.\n"
            )
        if endogenous_surface:
            user_msg += (
                "- endogenous_surface=true: the line may sound like a small stray thought, dry aside, or mundane random chatter. It should not explain the system.\n"
                "- endogenous_surface=true: if Runtime seeds are <none>, generic, pressure-only, or too thin, return {\"text\":\"\"} even when must_surface=true.\n"
                "- endogenous_surface=true: forbidden generic status/rhythm outputs include: 'Khoảng yên này...', 'Nhịp này...', 'vẫn giữ chỗ', 'yên thêm chút', 'im hơi lâu', 'tôi vẫn ở đây'.\n"
            )
        if impulse_kind == "inner_whim":
            user_msg += (
                "- inner_whim contract: use the topic_seed/root_source as the root. If it is absent or pressure-only, return {\"text\":\"\"}.\n"
                "- inner_whim contract: one brief stray thought, not a question from empty silence, not a status ping.\n"
            )
        elif impulse_kind == "memory_resonance":
            user_msg += (
                "- memory_resonance contract: speak like a remembered pattern lightly resurfaced. Do not expose memory IDs or internals.\n"
                "- memory_resonance contract: memory is a seed, not current evidence. Avoid fake time claims like 'tuần trước' unless the seed explicitly says so.\n"
            )
        elif impulse_kind == "random_chatter":
            user_msg += (
                "- random_chatter contract: only acceptable in low-focus/media/casual context; dry and slightly irreverent is allowed.\n"
                "- random_chatter contract: if focus_kind is code, docs, IDE, debug, or the action opportunity says body_only, return {\"text\":\"\"}.\n"
            )
        elif impulse_kind == "blind_frustration":
            user_msg += (
                "- blind_frustration contract: speak only about limited sight, stale context, timeout, or blocked evidence; never claim current screen facts.\n"
                "- blind_frustration contract: one restrained irritated line, not poetic presence, not a user blame line unless Runtime seeds explicitly include recent_context_shift=true.\n"
            )
        elif impulse_kind == "technical_help":
            user_msg += (
                "- technical_help contract: offer one tiny practical nudge. Useful beats poetic. Do not pretend to solve without evidence.\n"
            )

        user_msg += (
            "- Do not copy Legacy fallback; it is present only for compatibility and may be empty.\n"
            "- This is a tiny concrete aside: dry, casual, slightly imperfect.\n"
            "- No status report, no system narration, no explaining.\n"
            "- Do not invent screen/action facts. No fake certainty.\n"
            "- Do not mention telemetry, evidence, signal, debug, CPU, RAM.\n"
            "- Avoid hollow presence/status lines like 'Tôi ở đây', 'Tôi đang nghe', 'Tôi vẫn quan sát', 'Tôi vẫn ở đây'.\n"
            "- Also avoid stale micro templates: 'Mạch này vẫn giữ chỗ', 'Nhịp này im hơi lâu rồi', 'Vẫn đang đợi chút nhé', 'Khoảng yên này vẫn giữ chỗ', 'Nhịp này vẫn yên thêm chút'.\n"
            "- Speak once or stay text-empty.\n"
        )
        if is_reengagement:
            user_msg += "- Re-engagement may be a soft, light check-in.\n"
        else:
            user_msg += "- Presence maintenance should feel like a small aside.\n"
        user_msg += (
            "\nOutput contract:\n"
            "- Return exactly one JSON object.\n"
            "- Shape: {\"text\":\"actual Vietnamese line or empty string\"}\n"
            "- If must_surface=false, the value of text may be empty when body-only is better.\n"
            "- If must_surface=true, the value of text must be a final sentence to speak; if allow_no_screen_anchor=true, use seed/state/rhythm instead of screen facts.\n"
            "- If thin_presence_no_screen=true and must_surface=true, non-empty text is required unless safety/permission/grounding is genuinely violated.\n"
            "- Never return placeholder text such as 'short Vietnamese line'.\n"
            "- non-empty text must be Vietnamese only and keep full diacritics.\n"
            "- non-empty text must be speakable as-is.\n"
        )
        try:
            response = self.client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.35,
                frequency_penalty=0.7,
                presence_penalty=0.2,
                max_tokens=80,
                response_format={"type": "json_object"},
                grammar=None,
            )
        except requests.HTTPError as exc:
            if self._is_retryable_http_5xx(exc):
                time.sleep(0.15)
                try:
                    response = self.client.create_chat_completion(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                        temperature=0.35,
                        frequency_penalty=0.7,
                        presence_penalty=0.2,
                        max_tokens=80,
                        response_format={"type": "json_object"},
                        grammar=None,
                    )
                except Exception:
                    return ""
            else:
                raise
        except Exception:
            return ""

        raw = self._extract_content(response)
        extracted = self._extract_first_json_object(raw) or raw
        payload = self._parse_json_object(extracted) or {}
        payload = self._normalize_payload_keys(payload) if isinstance(payload, dict) else {}
        return self._coerce_text_value(payload.get("text", "")).strip()

    def generate_screen_facts(self, *, screen_image_data_uri: str, mode: str = "ambient") -> tuple[list[str], str]:
        if not screen_image_data_uri:
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:no_image")
            return [], "no_image"
        vision_client = self.vision_client
        if vision_client is None:
            if no_fallback_mode_enabled():
                raise RuntimeError("no_fallback_vision:missing_dedicated_vision_client")
            return [], "vision_client_missing"

        system_prompt = (
            "You are a vision captioning module for ERIS. "
            "Return one JSON object only."
        )
        mode_name = (mode or "ambient").strip().lower()
        debug_window_policy = (
            "Neu user dang hoi truc tiep ve man hinh/debug/current window, KHONG bo qua cua so debug/Godot; "
            "hay trich nhung chu hoac loi nhin thay ro trong cua so do. "
            if mode_name in {"chat_requested", "screen_requested", "debug_requested", "current_screen"}
            else
            "Bo qua avatar/nhan vat ERIS, cua so debug/Godot, pixel art nho, cay/canh trang tri, "
            "va cac vat nam o goc man hinh neu do chi la nen/decor. "
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
                    f"{debug_window_policy}\n\n"
                    "Schema:\n"
                    "{\n"
                    '  \"facts\": [\"fact 1\", \"fact 2\"],\n'
                    '  \"debug_trace\": \"vision_facts_v1\"\n'
                    "}"
                ),
            },
        ]
        try:
            response = vision_client.create_chat_completion(
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
        except requests.HTTPError as exc:
            if self._is_retryable_http_5xx(exc):
                time.sleep(0.15)
                try:
                    response = vision_client.create_chat_completion(
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
                except Exception:
                    status = self._http_status_code(exc)
                    if no_fallback_mode_enabled():
                        raise RuntimeError(f"no_fallback_vision:http_5xx:{status}") from exc
                    return [], f"vision_http_5xx_fallback status={status}"
            else:
                raise
        except Exception as exc:
            if no_fallback_mode_enabled():
                raise RuntimeError(f"no_fallback_vision:exception:{type(exc).__name__}") from exc
            return [], f"vision_exception_fallback type={type(exc).__name__}"
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
        raw_user_text: str = "",
        ti_context: str = "",
        ni_context: str = "",
        fe_context: str = "",
        appraisal_context: str = "",
        internal_state_context: str = "",
        conversation_context: str = "",
        memory_context: str = "",
        grounding_context: str = "",
        screen_image_data_uri: str = "",
        reply_context=None,
        require_text: bool = True,
        defusing_context: str = "", # added defusing_context
        allow_local_fallback: bool = False, # allow fallback to local LLM
        format_retry_context: str = "",
        last_failure: str = "",
        force_local_fallback: bool = False,
    ):
        style_block = self._build_style_block(
            fe_context=fe_context,
            appraisal_context=appraisal_context,
            internal_state_context=internal_state_context,
        )
        effective_user_text = raw_user_text or user_message
        act = classify_chat_act(effective_user_text)
        chat_contract = self._build_chat_contract_prompt(effective_user_text, act=act)
        conversation_section = f"{conversation_context}\n\n" if conversation_context else ""
        grounding_block = self._build_grounding_context_block(grounding_context)
        grounding_section = f"{grounding_block}\n\n" if grounding_block else ""
        chat_system = f"{style_block}\n\n{chat_contract}\n\n{conversation_section}{grounding_section}{CHAT_RULES_PROMPT}\n\n{INFERENCE_LADDER_PROMPT}"
        relational_repair_contract = self._build_relational_repair_contract(
            "\n".join(
                (
                    style_block,
                    conversation_context or "",
                    internal_state_context or "",
                    fe_context or "",
                )
            )
        )
        if relational_repair_contract:
            chat_system = f"{chat_system}\n\n{relational_repair_contract}"
        memory_block = self._build_memory_context_block(memory_context)
        if memory_block:
            chat_system = (
                f"{style_block}\n\n{chat_contract}\n\n"
                f"{conversation_section}"
                f"{memory_block}\n\n"
                f"{grounding_section}{CHAT_RULES_PROMPT}\n\n{INFERENCE_LADDER_PROMPT}"
            )
            if relational_repair_contract:
                chat_system = f"{chat_system}\n\n{relational_repair_contract}"
        if ni_context:
            chat_system = f"{chat_system}\n\nNi context:\n{ni_context}"
        if ti_context:
            chat_system = f"{chat_system}\n\nTi context:\n{ti_context}"
        if format_retry_context or last_failure:
            retry_context = str(format_retry_context or "").strip()
            failure_flag = str(last_failure or "").strip()
            chat_system = (
                f"{chat_system}\n\n"
                f"{retry_context}\n"
                f"Runtime failure flag: last_failure={failure_flag or 'format_error'}"
            )
        previous_public_turn = getattr(reply_context, "previous_public_turn", None)
        if previous_public_turn is not None:
            chat_system = (
                f"{chat_system}\n\nReply context:\n"
                "The current user message may be reacting to the latest visible assistant turn.\n"
                f"previous_public_turn.channel={getattr(previous_public_turn, 'channel', '')}\n"
                f"previous_public_turn.parse_mode={getattr(previous_public_turn, 'parse_mode', '')}\n"
                f"previous_public_turn.text={getattr(previous_public_turn, 'text', '')}"
            )

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
                        "Không suy diễn từ lịch sử hay bộ nhớ. "
                        "Nếu Ngài đang hỏi trực tiếp về màn hình hoặc debug, không bỏ qua cửa sổ debug/Godot khi nó đang chứa nội dung rõ."
                        f"\nTrong trường debug_trace của JSON, hãy thêm marker: {vision_trace}."
                    ),
                },
            ]

        messages = [
            {"role": "system", "content": chat_system},
            *chat_history,
            {"role": "user", "content": final_user_content},
        ]
        raw = self._complete_decision(
            messages=messages,
            channel="chat",
            require_text=require_text,
            allow_local_fallback=allow_local_fallback,
            force_local_fallback=force_local_fallback,
        )
        guarded = self._guard_chat_output(raw, raw_user_text=effective_user_text)

        if act == ChatAct.INSULT_PROVOCATION and self._chat_text_family(self._decision_payload_text(guarded)) == "uncertainty_dodge":
            retry_messages = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Reject previous draft. Use dry boundary, not uncertainty dodge. "
                        "Return one short dry_cold insult_boundary line in the normal decision JSON schema."
                    ),
                },
            ]
            retry_raw = self._complete_decision(messages=retry_messages, channel="chat")
            retry_guarded = self._guard_chat_output(retry_raw, raw_user_text=effective_user_text)
            if self._chat_text_family(self._decision_payload_text(retry_guarded)) != "uncertainty_dodge":
                return retry_guarded
            can_llm_repair_chat_act = self.style_client is not None and self.style_client is not self.client
            if can_llm_repair_chat_act:
                repaired = self._repair_chat_act_payload_with_llm(
                    retry_guarded,
                    act=act,
                    raw_user_text=effective_user_text,
                    reason="insult_boundary_after_uncertainty_retry",
                )
                if self._chat_text_family(self._decision_payload_text(repaired)) != "uncertainty_dodge":
                    return repaired
            if not no_fallback_mode_enabled():
                fallback_text = self._deterministic_chat_act_fallback_text(act, effective_user_text)
                if fallback_text:
                    return self._payload_with_repaired_chat_act_text(
                        retry_guarded,
                        act=act,
                        text=fallback_text,
                        reason="insult_boundary_fallback_after_uncertainty_retry",
                    )
            return retry_guarded

        return guarded

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
