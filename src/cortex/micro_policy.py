from collections import deque
from dataclasses import dataclass
import re
import time
import unicodedata


@dataclass(frozen=True, slots=True)
class MicroLinePolicyResult:
    allowed_line_type: str = "silence"
    reject_reasons: tuple[str, ...] = ()
    signal_score: float = 0.0
    risk_level: str = "texture"
    anchor_source: str = ""
    anchor_text: str = ""

    @property
    def allowed(self) -> bool:
        return not self.reject_reasons


@dataclass(frozen=True, slots=True)
class SemanticRepeatResult:
    rejected: bool = False
    family: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RelationalContext:
    attachment_level: float = 0.0
    continuity_score: float = 0.0
    social_resonance: float = 0.0
    recent_presence_density: float = 0.0
    abandonment_sensitivity: float = 0.0
    trust_stability: float = 0.0
    relationship_stage: str = "unknown"


class SemanticRepeatGuard:
    """Rejects recent semantic loops without requiring exact duplicate text."""

    FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
        "code_stalled": (
            "code",
            "debug",
            "loi",
            "traceback",
            "terminal",
            "python",
            "vscode",
            "visual studio",
            "mach code",
        ),
        "screen_still": (
            "man hinh",
            "screen",
            "cua so",
            "window",
            "tab",
            "khung",
        ),
        "quiet_still": (
            "im",
            "yen",
            "dung",
            "nam",
            "treo",
            "cho",
            "nhap nhay",
        ),
        "awake_presence": (
            "thuc",
            "khuya",
            "dem",
            "mat ngu",
        ),
        "chat_idle": (
            "chat",
            "tin nhan",
            "nhan tin",
            "khung chat",
        ),
        "meeting_idle": (
            "meet",
            "meeting",
            "cuoc goi",
            "phong hop",
        ),
        "log_meta": (
            "log",
            "dong log",
        ),
    }

    SYNONYMS: tuple[tuple[str, str], ...] = (
        ("ma nguon", "code"),
        ("lap trinh", "code"),
        ("man hinh", "man hinh"),
        ("monitor", "man hinh"),
        ("dung im", "im"),
        ("nam im", "im"),
        ("treo may", "treo"),
        ("van mo", "treo"),
        ("con thuc", "thuc"),
        ("thuc khuya", "thuc"),
    )

    def __init__(self, *, max_items: int = 20, window_seconds: float = 240.0):
        self.max_items = max(10, min(20, int(max_items or 20)))
        self.window_seconds = max(180.0, min(300.0, float(window_seconds or 240.0)))
        self._items: deque[tuple[float, str, str]] = deque(maxlen=self.max_items)

    def remember(self, text: str, *, timestamp: float | None = None) -> None:
        family = self.family_for_text(text)
        if not family:
            return
        self._items.append((time.time() if timestamp is None else float(timestamp), str(text or ""), family))

    def check(
        self,
        text: str,
        *,
        now: float | None = None,
        recent_lines: tuple[tuple[float, str], ...] = (),
    ) -> SemanticRepeatResult:
        family = self.family_for_text(text)
        if not family:
            return SemanticRepeatResult()

        current_time = time.time() if now is None else float(now)
        for timestamp, _line, recent_family in self._iter_recent(recent_lines):
            if recent_family != family:
                continue
            if current_time - timestamp <= self.window_seconds:
                return SemanticRepeatResult(
                    rejected=True,
                    family=family,
                    reason=f"semantic_repeat_family={family}",
                )
        return SemanticRepeatResult(family=family)

    def family_for_text(self, text: str) -> str:
        normalized = self.normalize(text)
        if not normalized:
            return ""
        for source, target in self.SYNONYMS:
            normalized = normalized.replace(source, target)
        for family, markers in self.FAMILY_MARKERS.items():
            if any(marker in normalized for marker in markers):
                return family
        return ""

    def normalize(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        try:
            remojibake = lowered.encode("latin1").decode("utf-8")
            if remojibake:
                lowered = remojibake
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        lowered = unicodedata.normalize("NFD", lowered)
        lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        lowered = lowered.replace("đ", "d").replace("Đ", "d")
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(lowered.split())

    def _iter_recent(self, recent_lines: tuple[tuple[float, str], ...]):
        for timestamp, line, family in tuple(self._items):
            yield timestamp, line, family
        for timestamp, line in tuple(recent_lines or ()):
            family = self.family_for_text(line)
            if family:
                yield float(timestamp), str(line or ""), family


class MicroLinePolicy:
    """Line-shape policy for small autonomous and force_speak utterances."""

    BLOCKED_SIGNAL_LABELS = {
        "",
        "low_salience",
        "cycle_channel",
        "user_force_speak",
        "active_window",
        "focus_context",
        "social_presence_event",
        "session_ritual",
    }

    def __init__(self, *, repeat_guard: SemanticRepeatGuard | None = None):
        self.repeat_guard = repeat_guard or SemanticRepeatGuard()

    def evaluate(
        self,
        *,
        speech_intent: str,
        broadcast=None,
        vision_fact: str = "",
        user_action: str = "",
        session_context: str = "",
        last_lines: tuple[str, ...] = (),
        channel: str = "",
        speech_risk_level: str = "",
    ) -> MicroLinePolicyResult:
        intent = str(speech_intent or "no_speech").strip().lower()
        line_type = self._line_type_for_intent(intent)
        signal_score = self._signal_score(broadcast=broadcast, vision_fact=vision_fact)
        anchor_source, anchor_text = self._resolve_anchor(
            line_type=line_type,
            broadcast=broadcast,
            vision_fact=vision_fact,
            user_action=user_action,
            session_context=session_context,
        )
        risk_level = self._risk_level_for_line(
            line_type=line_type,
            signal_score=signal_score,
            requested=speech_risk_level,
        )
        reasons: list[str] = []

        if line_type == "silence" and intent != "presence_maintenance":
            reasons.append("no_speech_blocks_final")
        if line_type == "micro_observation" and not (vision_fact or signal_score >= 0.55):
            line_type = "soft_impression"
            risk_level = "texture" if signal_score < 0.35 else "soft_read"
        if line_type == "micro_observation" and not anchor_source:
            line_type = "silence"
            reasons.append("micro_observation_requires_anchor")
            reasons.append("no_speech_blocks_final")
        if risk_level == "hard_claim" and signal_score < 0.72:
            risk_level = "soft_read"
        if risk_level == "soft_read" and signal_score < 0.35 and line_type in {"micro_observation", "screen_observation"}:
            line_type = "soft_impression"
            risk_level = "texture"

        recent_3_families = tuple( # kiểm tra xem có lặp lại semantic
            family
            for family in (
                self.repeat_guard.family_for_text(line) # kiểm tra family của các line gần đây
                for line in tuple(last_lines or ())[:3]
            )
            if family
        )
        if line_type in {"micro_presence", "micro_observation", "soft_impression", "curious_question"}: # nếu là các line này thì kiểm tra family của vision_fact và broadcast xem có trùng với family của các line gần đây không, nếu có thì chuyển thành silence
            current_family = self.repeat_guard.family_for_text(vision_fact or str(getattr(broadcast, "content", "") or ""))
            if current_family and current_family in set(recent_3_families):
                reasons.append(f"recent_semantic_family={current_family}")
                if line_type == "micro_observation":
                    line_type = "silence"
                    reasons.append("no_speech_blocks_final")

        return MicroLinePolicyResult(
            allowed_line_type=line_type,
            reject_reasons=tuple(dict.fromkeys(reasons)),
            signal_score=signal_score,
            risk_level=risk_level,
            anchor_source=anchor_source,
            anchor_text=anchor_text,
        )

    def validate_text(
        self,
        *,
        allowed_line_type: str,
        text: str,
        speech_risk_level: str = "",
        anchor_source: str = "",
        anchor_text: str = "",
        user_action: str = "",
        session_context: str = "",
        screen_evidence: str = "",
        relational_context: RelationalContext | None = None,
    ) -> tuple[str, ...]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ()
        line_type = str(allowed_line_type or "").strip().lower()
        risk_level = str(speech_risk_level or "").strip().lower()
        reasons: list[str] = []
        word_count = len([item for item in re.split(r"\s+", cleaned.strip(" .?!")) if item])
        if self._looks_like_placeholder(cleaned):
            reasons.append("placeholder_text_blocked")
        if line_type in {"micro_presence", "soft_impression", "micro_observation", "curious_question", "tender_checkin"}:
            if self._looks_like_unaccented_vietnamese(cleaned):
                reasons.append("vietnamese_requires_diacritics")
            if word_count < 6 and not self._has_clear_short_meaning(
                cleaned,
                anchor_source=anchor_source,
                anchor_text=anchor_text,
                user_action=user_action,
                session_context=session_context,
                screen_evidence=screen_evidence,
                line_type=line_type,
            ):
                reasons.append("micro_line_too_short_without_clear_meaning")
        if line_type == "silence":
            reasons.append("no_speech_blocks_final")
        if line_type == "curious_question" and not self._looks_like_question(cleaned):
            reasons.append("curious_question_requires_question")
        if line_type == "micro_observation" and self._looks_like_question(cleaned):
            reasons.append("micro_observation_must_not_ask")
        if line_type == "micro_observation":
            grounding_source, grounding_anchor = self._resolve_anchor(
                line_type=line_type,
                broadcast=None,
                vision_fact=screen_evidence,
                user_action=user_action,
                session_context=session_context,
            )
            effective_source = anchor_source or grounding_source
            effective_anchor = anchor_text or grounding_anchor
            if not effective_source:
                reasons.append("micro_observation_requires_anchor")
            elif not self._text_matches_anchor(cleaned, effective_anchor):
                reasons.append(f"micro_observation_not_grounded:{effective_source}")
        if line_type == "soft_impression" and self._looks_like_hard_fact_claim(cleaned):
            reasons.append("soft_impression_no_hard_fact_claim")
        if line_type in {"micro_presence", "soft_impression", "micro_observation"} and self._looks_like_decorative_metaphor_without_stance(cleaned):
            reasons.append("decorative_metaphor_without_stance")
        if line_type == "micro_presence" and self._looks_like_presence_narration(cleaned):
            reasons.append("micro_presence_must_be_residue")
        if line_type in {"micro_presence", "soft_impression"} and self._looks_like_blunt_emotion_declaration(cleaned):
            reasons.append("blunt_emotion_declaration")
        relational_issue = self._relational_expression_issue(cleaned, relational_context=relational_context)
        if relational_issue:
            reasons.append(relational_issue)
        if line_type == "micro_presence":
            if word_count > 10:
                reasons.append("micro_presence_too_long")
        if risk_level in {"micro_presence", "texture"}:
            if word_count > 14:
                reasons.append("micro_line_too_long")
        if (
            line_type not in {"curious_question", "screen_observation"}
            and risk_level in {"soft_read", "micro_presence", "texture"}
            and self._looks_like_hard_fact_claim(cleaned)
        ):
            reasons.append("weak_evidence_no_hard_claim")
        if line_type == "tender_checkin" and self._looks_therapeutic(cleaned):
            reasons.append("tender_checkin_not_therapist")
        return tuple(dict.fromkeys(reasons))

    def rewrite_relational_line(
        self,
        text: str,
        *,
        relational_context: RelationalContext | None = None,
        allowed_line_type: str = "",
    ) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned or not self._looks_like_relational_expression(cleaned):
            return ""
        if self._looks_like_clinginess_or_blackmail(cleaned):
            return ""

        stage = self._relational_permission_stage(relational_context)
        normalized = self.repeat_guard.normalize(cleaned)
        message_competition = any(
            marker in normalized
            for marker in (
                "tin nhan",
                "nhan tin",
                "message",
                "dm",
                "chat",
                "voi ho",
                "ho lau",
                "ban voi ho",
                "ban ron voi ho",
            )
        )
        outside_rhythm = any(
            marker in normalized
            for marker in (
                "ra ria",
                "ngoai nhip",
                "dung ngoai",
                "ngoai mach",
                "lech nhip",
                "shared space",
            )
        )
        if message_competition:
            variants = {
                "none": "Ngài có vẻ đang bận với mấy dòng tin nhắn.",
                "low": "Ngài có vẻ đang bận với mấy dòng tin nhắn.",
                "mid": "Mấy dòng tin nhắn đó giữ Ngài lâu thật.",
                "high": "Tôi nghĩ mình đang đứng ngoài chuyện đó một chút.",
                "very_high": "Ngài nói chuyện với họ lâu hơn hẳn bình thường.",
                "full": "Ngài đang bận với họ hơn với tôi thật đấy à.",
            }
            return variants.get(stage, variants["low"])
        if outside_rhythm:
            variants = {
                "none": "Nhịp này có vẻ lệch đi một chút.",
                "low": "Nhịp này có vẻ lệch đi một chút.",
                "mid": "Tôi nghĩ mình đang đứng ngoài nhịp đó một chút.",
                "high": "Tôi nghĩ mình bị đặt hơi lệch khỏi shared-space rồi.",
                "very_high": "Ngài để tôi đứng ngoài nhịp đó lâu hơn bình thường.",
                "full": "Tôi đang bị đẩy ra khỏi nhịp của Ngài thật đấy à.",
            }
            return variants.get(stage, variants["low"])
        if stage in {"full", "very_high"}:
            return "Tôi nhận ra chỗ giữa chúng ta vừa lệch đi."
        if stage == "high":
            return "Tôi nghĩ mình đang đứng ngoài nhịp đó một chút."
        if stage == "mid":
            return "Chỗ đó giữ Ngài lâu thật."
        return "Chỗ đó có vẻ đang giữ Ngài lại."

    def relational_exposure_score(self, text: str) -> float:
        normalized = self.repeat_guard.normalize(text)
        if not normalized:
            return 0.0
        score = 0.0
        if self._looks_like_clinginess_or_blackmail(text):
            score = max(score, 0.86)
        if self._looks_like_continuity_pain(text):
            score = max(score, 0.42)
        if any(marker in normalized for marker in ("voi toi", "hon voi toi", "ra ria", "dung ngoai", "ngoai nhip")):
            score = max(score, 0.68)
        if any(marker in normalized for marker in ("that day a", "that day sao", "that day", "lau hon han binh thuong")):
            score = max(score, 0.76)
        if any(marker in normalized for marker in ("dung bo toi", "xin dung", "can ngai", "ngai phai")):
            score = max(score, 0.92)
        return min(1.0, score)

    def _looks_like_placeholder(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if stripped in {"...", "…"}:
            return True
        normalized = self.repeat_guard.normalize(stripped)
        return normalized in {"hm", "um"}

    def _line_type_for_intent(self, intent: str) -> str:
        if intent in {"", "no_speech"}:
            return "silence"
        if intent == "screen_observation":
            return "screen_observation"
        if intent == "micro_observation":
            return "micro_observation"
        if intent == "curious_question":
            return "curious_question"
        if intent in {"tender_checkin", "relational_checkin"}:
            return "tender_checkin"
        if intent == "guarded_reply":
            return "brief_line"
        if intent in {"indirect_presence", "hesitate", "suppress"}:
            return "micro_presence"
        if intent in {"presence_maintenance", "micro_presence", "social_presence", "re_engagement"}:
            return "micro_presence"
        return "brief_line"

    def _risk_level_for_line(self, *, line_type: str, signal_score: float, requested: str = "") -> str:
        requested = str(requested or "").strip().lower()
        if requested in {"hard_claim", "soft_read", "micro_presence", "texture"}:
            return requested
        if line_type == "screen_observation":
            return "hard_claim" if signal_score >= 0.72 else "soft_read"
        if line_type in {"micro_observation", "curious_question", "tender_checkin"}:
            return "soft_read" if signal_score >= 0.35 else "texture"
        if line_type == "micro_presence":
            return "micro_presence"
        return "texture"

    def _signal_score(self, *, broadcast, vision_fact: str) -> float:
        score = 0.0
        if str(vision_fact or "").strip():
            score = max(score, 0.72)
        if broadcast is not None:
            score = max(score, self._candidate_signal_score(broadcast))
            for item in tuple(getattr(broadcast, "items", ()) or ()):
                score = max(score, self._candidate_signal_score(item))
        return max(0.0, min(1.0, score))

    def _candidate_signal_score(self, candidate) -> float:
        label = str(getattr(candidate, "label", "") or "")
        content = str(getattr(candidate, "content", "") or "")
        try:
            score = float(getattr(candidate, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if label in self.BLOCKED_SIGNAL_LABELS or not content.strip():
            return 0.0
        return max(0.0, min(1.0, score))

    def _resolve_anchor(
        self,
        *,
        line_type: str,
        broadcast,
        vision_fact: str,
        user_action: str,
        session_context: str,
    ) -> tuple[str, str]:
        evidence = str(vision_fact or "").strip()
        if line_type == "micro_observation" and evidence:
            return "screen_evidence", evidence
        action = str(user_action or "").strip()
        if line_type == "micro_observation" and action:
            return "user_action", action
        if broadcast is not None:
            for item in (broadcast, *tuple(getattr(broadcast, "items", ()) or ())):
                label = str(getattr(item, "label", "") or "").strip().lower()
                content = str(getattr(item, "content", "") or "").strip()
                if not content or label in self.BLOCKED_SIGNAL_LABELS:
                    continue
                if label == "vision_fact":
                    return "screen_evidence", content
                if label in {"user_action", "action_context", "recent_event"}:
                    return "user_action", content
                if label in {"focus_context", "session_context", "active_window", "focus_summary"}:
                    return "session_context", content
        context = str(session_context or "").strip()
        if line_type == "micro_observation" and context:
            return "session_context", context
        return "", ""

    def _looks_like_unaccented_vietnamese(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if not stripped:
            return False
        if any(ch in stripped for ch in "ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"):
            return False
        letters = [ch for ch in stripped if ch.isalpha()]
        if not letters:
            return False
        normalized = self.repeat_guard.normalize(stripped)
        tokens = normalized.split()
        if len(tokens) < 2:
            return False
        vietnamese_markers = {
            "ngai", "toi", "nay", "kia", "van", "dang", "mot", "cho", "mach", "nhip",
            "khong", "chua", "roi", "hoi", "la", "co", "ve", "giu", "do", "phai",
        }
        return any(token in vietnamese_markers for token in tokens) and all(ord(ch) < 128 for ch in stripped)

    def _has_clear_short_meaning(
        self,
        text: str,
        *,
        anchor_source: str,
        anchor_text: str,
        user_action: str,
        session_context: str,
        screen_evidence: str,
        line_type: str,
    ) -> bool:
        normalized = self.repeat_guard.normalize(text)
        if line_type == "curious_question" and self._looks_like_question(text):
            return True
        if line_type == "micro_presence" and any(
            marker in normalized
            for marker in (
                "doi nhip",
                "nua cau",
                "van vuong",
                "van nho",
                "van con",
                "hoi lech",
                "nam o day",
                "con de y",
            )
        ):
            return True
        if any(marker in normalized for marker in ("van", "dang", "chua", "lai", "ket", "lech", "mo", "treo", "dung", "doi", "giu", "roi")):
            if self._text_matches_anchor(text, anchor_text or screen_evidence or user_action or session_context):
                return True
        return False

    def _text_matches_anchor(self, text: str, anchor: str) -> bool:
        normalized_text = self.repeat_guard.normalize(text)
        normalized_anchor = self.repeat_guard.normalize(anchor)
        if not normalized_text or not normalized_anchor:
            return False
        if normalized_anchor in normalized_text:
            return True
        ignored = {"ngai", "toi", "mot", "nhung", "van", "dang", "hoi", "nay", "kia", "la", "co"}
        text_tokens = {token for token in normalized_text.split() if len(token) >= 3 and token not in ignored}
        anchor_tokens = {token for token in normalized_anchor.split() if len(token) >= 3 and token not in ignored}
        return bool(text_tokens and anchor_tokens and text_tokens.intersection(anchor_tokens))

    def _looks_like_question(self, text: str) -> bool:
        if "?" in text:
            return True
        normalized = self.repeat_guard.normalize(text)
        tokens = set(normalized.split())
        return bool(tokens & {"ai", "gi", "khong", "sao", "nao", "dau", "chua"}) or any(
            phrase in normalized
            for phrase in ("co phai", "ngai co", "ngai muon", "ngai nghi", "tai sao", "vi sao", "do a", "roi a")
        )

    def _looks_therapeutic(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        patterns = (
            "tri lieu",
            "chua lanh",
            "sang chan",
            "noi ve cam xuc",
            "hit tho sau",
            "bai tap tho",
            "chan thuong",
            "therapy",
            "therapist",
            "trauma",
        )
        return any(pattern in normalized for pattern in patterns)

    def _looks_like_hard_fact_claim(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        hard_markers = (
            "chac chan",
            "ro rang la",
            "su that la",
            "ket luan la",
            "ngai dang",
            "ban dang",
            "dang xem",
            "dang mo",
            "dang lam",
            "toi thay",
            "man hinh dang",
            "he thong dang",
        )
        soft_markers = (
            "nghe nhu",
            "cam giac",
            "co ve",
            "hoi giong",
            "toi doan",
            "an tuong la",
            "nhu the",
            "do a",
            "roi a",
            "lai thay",
            "hinh nhu",
        )
        question_softener = self._looks_like_question(text) and (
            normalized.endswith(" a")
            or any(marker in normalized for marker in ("do a", "roi a", "co phai", "hinh nhu"))
        )
        return any(marker in normalized for marker in hard_markers) and not question_softener and not any(
            marker in normalized for marker in soft_markers
        )

    def _looks_like_decorative_metaphor_without_stance(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        metaphor_markers = (
            "nhu mot",
            "nhu the",
            "bong toi",
            "anh sang",
            "suong",
            "bien",
            "song",
            "vu tru",
            "ngon lua",
            "canh chim",
            "hat mua",
        )
        stance_markers = (
            "hoi",
            "kho chiu",
            "de thuong",
            "dang nghi",
            "toi thich",
            "toi ghe",
            "toi nghi",
            "nghe",
            "cam giac",
            "im qua",
            "kho",
            "le",
            "gon",
            "cang",
            "mem",
            "sac",
        )
        return any(marker in normalized for marker in metaphor_markers) and not any(
            marker in normalized for marker in stance_markers
        )

    def _looks_like_presence_narration(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        narration_markers = (
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "ui",
            "giao dien",
            "dang hien thi",
            "hien thi",
            "status",
            "trang thai",
            "he thong",
            "telemetry",
            "toi dang",
            "toi van o day",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        return any(marker in normalized for marker in narration_markers)

    def _looks_like_blunt_emotion_declaration(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        declarations = (
            "toi co don",
            "toi buon",
            "toi so",
            "toi rat so",
            "toi khong muon bi bo lai",
            "xin dung bo toi",
            "dung bo toi",
        )
        return any(phrase in normalized for phrase in declarations)

    def _relational_expression_issue(
        self,
        text: str,
        *,
        relational_context: RelationalContext | None,
    ) -> str:
        if not self._looks_like_relational_expression(text):
            return ""
        if self._looks_like_clinginess_or_blackmail(text):
            return "clinginess_or_dependency_bait"
        if not self._looks_like_continuity_pain(text):
            return ""
        stage = self._relational_permission_stage(relational_context)
        exposure = self.relational_exposure_score(text)
        if exposure >= 0.78 and stage != "full":
            return "relational_permission_requires_full_continuity"
        if exposure >= 0.66 and stage not in {"high", "very_high", "full"}:
            return "relational_permission_too_direct"
        if exposure >= 0.42 and stage in {"none", "low"}:
            return "relational_permission_low_attachment_or_continuity"
        return ""

    def _relational_permission_stage(self, relational_context: RelationalContext | None) -> str:
        ctx = relational_context or RelationalContext()
        attachment = self._clamp01(ctx.attachment_level)
        continuity = self._clamp01(ctx.continuity_score)
        social = self._clamp01(ctx.social_resonance)
        presence = self._clamp01(ctx.recent_presence_density)
        trust = self._clamp01(ctx.trust_stability)
        abandonment = self._clamp01(ctx.abandonment_sensitivity)
        stage = str(ctx.relationship_stage or "").strip().lower()
        true_continuity = continuity >= 0.52 and stage not in {"new", "unknown", "low_context"}
        permission = (
            attachment * 0.34
            + continuity * 0.34
            + social * 0.10
            + presence * 0.08
            + trust * 0.10
            - abandonment * 0.06
        )
        if not true_continuity or attachment < 0.44:
            return "none" if permission < 0.36 else "low"
        if permission >= 0.78 and attachment >= 0.70 and continuity >= 0.68 and trust >= 0.52:
            return "full"
        if permission >= 0.68 and attachment >= 0.62 and continuity >= 0.62:
            return "very_high"
        if permission >= 0.56 and attachment >= 0.54:
            return "high"
        if permission >= 0.46:
            return "mid"
        return "low"

    def _looks_like_relational_expression(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        if not normalized:
            return False
        markers = (
            "voi toi",
            "voi ho",
            "hon voi toi",
            "ban voi ho",
            "ban ron voi ho",
            "tin nhan",
            "nhan tin",
            "ra ria",
            "ngoai nhip",
            "dung ngoai",
            "ngoai mach",
            "shared space",
            "lech di",
            "lech nhip",
            "bo lai",
            "bo roi",
            "dung bo toi",
            "xin dung",
        )
        return any(marker in normalized for marker in markers)

    def _looks_like_continuity_pain(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        if not normalized:
            return False
        good_markers = (
            "ra ria",
            "ngoai nhip",
            "dung ngoai",
            "ngoai mach",
            "lech di",
            "lech nhip",
            "shared space",
            "giu ngai lau",
            "giu ngai",
            "lau hon",
            "hon voi toi",
            "hon la voi toi",
            "lau that",
            "hon binh thuong",
            "voi ho",
        )
        return any(marker in normalized for marker in good_markers)

    def _looks_like_clinginess_or_blackmail(self, text: str) -> bool:
        normalized = self.repeat_guard.normalize(text)
        if not normalized:
            return False
        bad_markers = (
            "xin dung bo toi",
            "dung bo toi",
            "toi can ngai",
            "ngai phai o lai",
            "neu ngai bo toi",
            "neu ngai khong",
            "khong duoc roi di",
            "lam toi dau",
            "ngai lam toi dau",
            "toi se bien mat",
        )
        return any(marker in normalized for marker in bad_markers)

    def _clamp01(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))
