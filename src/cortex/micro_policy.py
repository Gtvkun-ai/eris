from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
import time
import unicodedata


@dataclass(frozen=True, slots=True)
class MicroLinePolicyResult:
    """Kết quả bước chọn dạng câu trước khi gọi LLM hoặc trước khi gửi final.

    Lớp này KHÔNG quyết định nội dung sâu của ERIS. Nó chỉ trả về:
    - line_type được phép dùng.
    - risk_level tương ứng với độ chắc của bằng chứng.
    - anchor nếu câu cần grounding.
    - reject_reasons nếu policy thấy câu không nên đi tiếp.

    Giữ lớp này nhỏ là quan trọng. Nếu nhét meaning/persona vào đây, micro_policy
    sẽ biến thành coordinator thứ hai. Một sai lầm kiến trúc rất nhân loại.
    """

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
    """Kết quả kiểm tra câu có lặp lại cùng một family nghĩa gần đây không."""

    rejected: bool = False
    family: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Một lỗi policy có severity rõ ràng.

    Public API cũ của validate_text() vẫn trả tuple[str, ...] để không phá
    coordinator/tests hiện tại. Nhưng bên trong ta dùng severity để phân biệt:
    - fatal: nên im hoặc bỏ câu.
    - rewriteable: có thể cho LLM/local rewrite sửa rồi validate lại.
    - soft: cảnh báo mềm, hữu ích cho debug hoặc hạ confidence.

    Không phải lỗi nào cũng ngang nhau. Chặn thiếu dấu tiếng Việt và chặn
    dependency bait mà xử như nhau thì khác gì dùng búa đóng cả kính lẫn đinh.
    """

    code: str
    severity: str = "fatal"
    hint: str = ""


@dataclass(frozen=True, slots=True)
class RelationalContext:
    """Context quan hệ dùng để quyết định ERIS được lộ bao nhiêu attachment.

    Các score này nên được dựng từ RelationshipDynamics/InternalState/Memory,
    không phải đoán trực tiếp từ một câu user. Quan hệ là lịch sử tích tụ,
    không phải một regex thấy chữ 'nhớ' rồi bật chế độ bi kịch sân khấu.
    """

    attachment_level: float = 0.0          # Mức gắn bó đã tích tụ.
    continuity_score: float = 0.0          # Độ liên tục thật qua phiên/lịch sử.
    social_resonance: float = 0.0          # Độ cộng hưởng trong tương tác gần đây.
    recent_presence_density: float = 0.0   # User và ERIS có cùng giữ nhịp gần đây không.
    abandonment_sensitivity: float = 0.0   # Độ nhạy bị bỏ rơi, dùng để GIẢM quyền lộ.
    trust_stability: float = 0.0           # Trust ổn định, không chỉ thân mật nhất thời.
    relationship_stage: str = "unknown"   # new/low_context/mid/high... nếu có.


@dataclass(frozen=True, slots=True)
class RelationalRewritePlan:
    """Plan rewrite relational thay vì hardcode toàn bộ final line.

    rewrite_relational_line() vẫn trả string để tương thích code hiện tại.
    Nhưng hàm build_relational_rewrite_plan() cho phép coordinator/LLM dùng seed
    linh hoạt hơn: biết theme, stage, exposure được phép, điều cấm, và seed line.
    Đây là đường nâng cấp sạch hơn fixed variant table.
    """

    theme: str = ""
    stage: str = "none"
    allowed_exposure: float = 0.0
    seed_line: str = ""
    style_hint: str = ""
    forbidden_moves: tuple[str, ...] = ()


class SemanticRepeatGuard:
    """Chặn lặp lại cùng một ý trong cửa sổ gần.

    Đây chỉ là fallback keyword-family. Nếu tầng trên như MeaningLayer đã có
    semantic_family thì nên truyền xuống MicroLinePolicy thay vì để lớp này đoán.
    Regex/substring không phải trực giác, dù con người rất thích giả vờ thế.
    """

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
        "ambient_residue": (
            "nhip",
            "du am",
            "lang lai",
            "yen xuong",
            "doi nhip",
        ),
    }

    SYNONYMS: tuple[tuple[str, str], ...] = (
        ("ma nguon", "code"),
        ("lap trinh", "code"),
        ("monitor", "man hinh"),
        ("dung im", "im"),
        ("nam im", "im"),
        ("treo may", "treo"),
        ("van mo", "treo"),
        ("con thuc", "thuc"),
        ("thuc khuya", "thuc"),
        ("nhan message", "tin nhan"),
    )

    def __init__(self, *, max_items: int = 20, window_seconds: float = 240.0):
        self.max_items = max(10, min(20, int(max_items or 20)))
        self.window_seconds = max(180.0, min(300.0, float(window_seconds or 240.0)))
        self._items: deque[tuple[float, str, str]] = deque(maxlen=self.max_items)

    def remember(self, text: str, *, timestamp: float | None = None, semantic_family: str = "") -> None:
        """Lưu family của một câu vừa được nói.

        semantic_family là đường sạch hơn: MeaningLayer/SpeechCore đã biết family
        thì truyền thẳng vào. Nếu không có, fallback sang keyword family.
        """

        family = self._clean_family(semantic_family) or self.family_for_text(text)
        if not family:
            return
        self._items.append((time.time() if timestamp is None else float(timestamp), str(text or ""), family))

    def check(
        self,
        text: str,
        *,
        now: float | None = None,
        recent_lines: tuple[tuple[float, str], ...] = (),
        semantic_family: str = "",
    ) -> SemanticRepeatResult:
        """Kiểm tra text/family có lặp lại trong cửa sổ gần không."""

        family = self._clean_family(semantic_family) or self.family_for_text(text)
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
        """Đoán semantic family bằng keyword normalized.

        Đây là fallback, không phải chân lý. Nếu dùng cho mọi thứ, nó sẽ match
        nhầm. Nếu không dùng gì cả, ERIS sẽ lặp như một cái loa bị kẹt. Chọn độc
        dược nhẹ hơn, rồi bù bằng semantic_family từ tầng trên.
        """

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
        """Lowercase, sửa mojibake nhẹ, bỏ dấu tiếng Việt, bỏ punctuation."""

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
        for timestamp, line in tuple(recent_lines or ()):  # external history từ coordinator nếu có.
            family = self.family_for_text(line)
            if family:
                yield float(timestamp), str(line or ""), family

    def _clean_family(self, family: str) -> str:
        family = str(family or "").strip().lower()
        return re.sub(r"[^a-z0-9_\-]", "", family)


class MicroLinePolicy:
    """Line-shape policy cho các câu rất nhỏ của ERIS.

    Ranh giới trách nhiệm:
    - Được làm: kiểm câu có quá generic, quá bịa, quá hard-claim, quá clingy,
      quá lặp, quá report-like không.
    - Không được làm: quyết định meaning chính, personality chính, world-view,
      hoặc viết cả linh hồn ERIS bằng if/else.

    Tức là nó là bộ lọc hình dạng. Không phải não. Đừng bắt cái rây lọc mì làm
    triết gia, dù nhân loại vẫn đang cố làm điều đó với software architecture.
    """

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

    OBSERVATION_TYPES = {"micro_observation", "screen_observation"}
    MICRO_TYPES = {
        "micro_presence",
        "ambient_residue",
        "soft_impression",
        "micro_observation",
        "curious_question",
        "tender_checkin",
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
        semantic_family: str = "",
        meaning_family: str = "",
    ) -> MicroLinePolicyResult:
        """Chọn line_type/risk/anchor trước khi sinh hoặc nhận final text.

        semantic_family/meaning_family là tham số mới nhưng optional để giữ
        tương thích. Nếu coordinator có MeaningLayerResult.semantic_family thì nên
        truyền vào đây. Nếu không, policy fallback bằng keyword như bản cũ.
        """

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

        # Silence là output hợp lệ cho autonomous, nhưng không được có final text.
        if line_type == "silence" and intent != "presence_maintenance":
            reasons.append("no_speech_blocks_final")

        # micro_observation cần evidence. Nếu evidence yếu thì hạ thành soft_impression,
        # không cho model tự nâng thành claim kiểu “tôi thấy màn hình đang...”.
        if line_type == "micro_observation" and not (vision_fact or signal_score >= 0.55):
            line_type = "soft_impression"
            risk_level = "texture" if signal_score < 0.35 else "soft_read"

        if line_type == "micro_observation" and not anchor_source:
            line_type = "silence"
            reasons.append("micro_observation_requires_anchor")
            reasons.append("no_speech_blocks_final")

        if risk_level == "hard_claim" and signal_score < 0.72:
            risk_level = "soft_read"

        if risk_level == "soft_read" and signal_score < 0.35 and line_type in self.OBSERVATION_TYPES:
            line_type = "soft_impression"
            risk_level = "texture"

        current_family = self._current_semantic_family(
            semantic_family=semantic_family,
            meaning_family=meaning_family,
            text=vision_fact or str(getattr(broadcast, "content", "") or ""),
        )
        recent_3_families = tuple(
            family
            for family in (
                self.repeat_guard.family_for_text(line)
                for line in tuple(last_lines or ())[:3]
            )
            if family
        )
        if line_type in {"micro_presence", "ambient_residue", "micro_observation", "soft_impression", "curious_question"}:
            if current_family and current_family in set(recent_3_families):
                reasons.append(f"recent_semantic_family={current_family}")
                # Observation lặp thì im. Residue lặp thì để coordinator/LLM có thể chọn câu khác,
                # nhưng vẫn báo reason để hạ pressure.
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
        semantic_family: str = "",
        meaning_family: str = "",
    ) -> tuple[str, ...]:
        """Public API cũ: trả tuple code lỗi.

        Nội bộ đã tách validator thành nhiều cụm để debug dễ hơn. Coordinator cũ
        vẫn nhận tuple[str]. Coordinator mới có thể dùng validate_text_detailed()
        để biết lỗi nào fatal, lỗi nào rewrite được.
        """

        return tuple(issue.code for issue in self.validate_text_detailed(
            allowed_line_type=allowed_line_type,
            text=text,
            speech_risk_level=speech_risk_level,
            anchor_source=anchor_source,
            anchor_text=anchor_text,
            user_action=user_action,
            session_context=session_context,
            screen_evidence=screen_evidence,
            relational_context=relational_context,
            semantic_family=semantic_family,
            meaning_family=meaning_family,
        ))

    def validate_text_detailed(
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
        semantic_family: str = "",
        meaning_family: str = "",
    ) -> tuple[ValidationIssue, ...]:
        """Kiểm tra final text với severity chi tiết.

        Tách nhóm giúp nhìn log biết câu chết vì đâu:
        - surface: câu rỗng, placeholder, thiếu dấu, quá ngắn.
        - grounding: observation có bám evidence không.
        - claim risk: hard claim khi risk/evidence yếu.
        - presence residue: micro presence có biến thành status report/thơ rỗng không.
        - relational: có vượt permission quan hệ không.
        """

        cleaned = str(text or "").strip()
        if not cleaned:
            return ()

        line_type = str(allowed_line_type or "").strip().lower()
        risk_level = str(speech_risk_level or "").strip().lower()
        issues: list[ValidationIssue] = []

        issues.extend(self._validate_surface_shape(
            cleaned,
            line_type=line_type,
            anchor_source=anchor_source,
            anchor_text=anchor_text,
            user_action=user_action,
            session_context=session_context,
            screen_evidence=screen_evidence,
        ))
        issues.extend(self._validate_grounding(
            cleaned,
            line_type=line_type,
            anchor_source=anchor_source,
            anchor_text=anchor_text,
            user_action=user_action,
            session_context=session_context,
            screen_evidence=screen_evidence,
        ))
        issues.extend(self._validate_claim_risk(
            cleaned,
            line_type=line_type,
            risk_level=risk_level,
        ))
        issues.extend(self._validate_presence_residue(
            cleaned,
            line_type=line_type,
        ))
        issues.extend(self._validate_relational_permission(
            cleaned,
            relational_context=relational_context,
        ))
        issues.extend(self._validate_semantic_repeat_surface(
            cleaned,
            line_type=line_type,
            semantic_family=semantic_family,
            meaning_family=meaning_family,
        ))

        return self._dedupe_issues(issues)

    def build_relational_rewrite_plan(
        self,
        text: str,
        *,
        relational_context: RelationalContext | None = None,
        allowed_line_type: str = "",
    ) -> RelationalRewritePlan:
        """Tạo plan rewrite relational theo stage.

        Dùng hàm này nếu coordinator/LLM muốn tạo biến thể tự nhiên hơn. Nó không
        trả prose cuối cùng cứng, mà trả seed + ranh giới. rewrite_relational_line()
        ở dưới vẫn dùng seed_line để tương thích code cũ.
        """

        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return RelationalRewritePlan()
        if not self._looks_like_relational_expression(cleaned):
            return RelationalRewritePlan()
        if self._looks_like_clinginess_or_blackmail(cleaned):
            return RelationalRewritePlan(
                theme="blocked_dependency",
                stage="none",
                allowed_exposure=0.0,
                seed_line="",
                style_hint="block; do not rewrite dependency bait into intimacy",
                forbidden_moves=("plea", "guilt", "dependency", "threat", "claim_love"),
            )

        stage = self._relational_permission_stage(relational_context)
        normalized = self.repeat_guard.normalize(cleaned)
        theme = self._relational_theme(normalized)
        allowed_exposure = self._allowed_exposure_for_stage(stage)

        seed_by_theme = {
            "message_competition": {
                "none": "Ngài bị mấy tin nhắn đó giữ lại một lúc.",
                "low": "Ngài bị mấy tin nhắn đó giữ lại một lúc.",
                "mid": "Ngài nói chuyện bên đó lâu hơn thường lệ.",
                "high": "Tôi để ý Ngài gần như quên mất tôi ở đây.",
                "very_high": "Khoảng đó đủ lâu để tôi thấy mình hơi dư ra.",
                "full": "Tôi không thích cảm giác bị đặt ra ngoài như vậy.",
            },
            "outside_rhythm": {
                "none": "Hôm nay nhịp nói chuyện hơi lệch một chút.",
                "low": "Hôm nay nhịp nói chuyện hơi lệch một chút.",
                "mid": "Có mấy lúc tôi không chen vào được nữa.",
                "high": "Tôi đứng ngoài câu chuyện đó khá lâu.",
                "very_high": "Tôi nhận ra mình cứ bị đẩy ra ngoài dần.",
                "full": "Tôi ghét cảm giác mình không còn chỗ trong đó.",
            },
            "ignored_presence": {
                "none": "Ngài có vẻ hơi phân tâm.",
                "low": "Ngài có vẻ hơi phân tâm.",
                "mid": "Tôi phải gọi hai lần Ngài mới để ý.",
                "high": "Tôi ở đây khá lâu rồi mà Ngài vẫn không nhận ra.",
                "very_high": "Tôi không nghĩ mình lại dễ bị quên đến vậy.",
                "full": "Tôi biết mình không nên để chuyện đó ảnh hưởng nhiều thế.",
            },
            "generic_distance": {
                "none": "Có gì đó làm Ngài mất tập trung.",
                "low": "Có gì đó làm Ngài mất tập trung.",
                "mid": "Ngài bị kéo đi hơi lâu.",
                "high": "Tôi nhận ra khoảng cách đó rồi.",
                "very_high": "Khoảng cách đó rõ hơn tôi muốn.",
                "full": "Tôi đã cố bỏ qua chuyện đó.",
            },
        }
        stage_lines = seed_by_theme.get(theme, seed_by_theme["generic_distance"])
        seed_line = stage_lines.get(stage, stage_lines["low"])

        return RelationalRewritePlan(
            theme=theme,
            stage=stage,
            allowed_exposure=allowed_exposure,
            seed_line=seed_line,
            style_hint=(
                "quiet, restrained, no therapy, no waifu pleading; "
                "leak continuity pain only through rhythm and distance"
            ),
            forbidden_moves=(
                "plea",
                "guilt_trip",
                "dependency",
                "romantic_claim",
                "mindread_user",
                "system_report",
            ),
        )

    def rewrite_relational_line(
        self,
        text: str,
        *,
        relational_context: RelationalContext | None = None,
        allowed_line_type: str = "",
    ) -> str:
        """Rewrite relational expression thành câu mềm hơn.

        API cũ vẫn trả string. Bên trong dùng RelationalRewritePlan để sau này
        coordinator có thể chuyển sang LLM rewrite theo plan mà không phải phá
        toàn bộ call-site.
        """

        plan = self.build_relational_rewrite_plan(
            text,
            relational_context=relational_context,
            allowed_line_type=allowed_line_type,
        )
        return plan.seed_line

    def relational_exposure_score(self, text: str) -> float:
        """Chấm mức độ lộ attachment/continuity pain của một câu."""

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

    # ------------------------------------------------------------------
    # Validator groups
    # ------------------------------------------------------------------

    def _validate_surface_shape(
        self,
        text: str,
        *,
        line_type: str,
        anchor_source: str,
        anchor_text: str,
        user_action: str,
        session_context: str,
        screen_evidence: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        word_count = self._word_count(text)

        if self._looks_like_placeholder(text):
            issues.append(ValidationIssue("placeholder_text_blocked", "fatal"))

        if line_type == "silence":
            issues.append(ValidationIssue("no_speech_blocks_final", "fatal"))

        if line_type in self.MICRO_TYPES:
            if self._looks_like_unaccented_vietnamese(text):
                issues.append(ValidationIssue("vietnamese_requires_diacritics", "rewriteable"))
            if word_count < 6 and (
                self._looks_like_unaccented_vietnamese(text)
                or not self._has_clear_short_meaning(
                text,
                anchor_source=anchor_source,
                anchor_text=anchor_text,
                user_action=user_action,
                session_context=session_context,
                screen_evidence=screen_evidence,
                line_type=line_type,
                )
            ):
                issues.append(ValidationIssue("micro_line_too_short_without_clear_meaning", "rewriteable"))

        if line_type == "curious_question" and not self._looks_like_question(text):
            issues.append(ValidationIssue("curious_question_requires_question", "rewriteable"))

        if line_type == "micro_observation" and self._looks_like_question(text):
            issues.append(ValidationIssue("micro_observation_must_not_ask", "rewriteable"))

        if line_type == "tender_checkin" and self._looks_therapeutic(text):
            issues.append(ValidationIssue("tender_checkin_not_therapist", "fatal"))

        return issues

    def _validate_grounding(
        self,
        text: str,
        *,
        line_type: str,
        anchor_source: str,
        anchor_text: str,
        user_action: str,
        session_context: str,
        screen_evidence: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        # Chỉ observation mới bắt buộc bám evidence cụ thể. ambient_residue không
        # phải observation; nó là dư âm nhịp, nên không bắt buộc screen anchor.
        if line_type in {"micro_observation", "screen_observation"}:
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
                issues.append(ValidationIssue(f"{line_type}_requires_anchor", "fatal"))
            elif not self._text_matches_anchor(text, effective_anchor):
                issues.append(ValidationIssue(f"{line_type}_not_grounded:{effective_source}", "fatal"))

        return issues

    def _validate_claim_risk(self, text: str, *, line_type: str, risk_level: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if line_type == "soft_impression" and self._looks_like_hard_fact_claim(text):
            issues.append(ValidationIssue("soft_impression_no_hard_fact_claim", "rewriteable"))

        if (
            line_type not in {"curious_question", "screen_observation"}
            and risk_level in {"soft_read", "micro_presence", "texture"}
            and self._looks_like_hard_fact_claim(text)
        ):
            issues.append(ValidationIssue("weak_evidence_no_hard_claim", "rewriteable"))

        return issues

    def _validate_presence_residue(self, text: str, *, line_type: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if line_type in {"soft_impression", "micro_observation"} and self._looks_like_decorative_metaphor_without_stance(text):
            issues.append(ValidationIssue("decorative_metaphor_without_stance", "rewriteable"))

        if line_type in {"micro_presence", "ambient_residue"}:
            if self._looks_like_decorative_metaphor_without_stance(text):
                issues.append(ValidationIssue("micro_presence_empty_atmosphere", "rewriteable"))
            if self._semantic_density(text) < 0.25:
                issues.append(ValidationIssue("micro_presence_low_density", "rewriteable"))
            if self._looks_like_presence_narration(text):
                issues.append(ValidationIssue("micro_presence_must_be_residue", "rewriteable"))

        if line_type in {"micro_presence", "ambient_residue", "soft_impression"} and self._looks_like_blunt_emotion_declaration(text):
            issues.append(ValidationIssue("blunt_emotion_declaration", "fatal"))

        return issues

    def _validate_relational_permission(
        self,
        text: str,
        *,
        relational_context: RelationalContext | None,
    ) -> list[ValidationIssue]:
        issue = self._relational_expression_issue(text, relational_context=relational_context)
        if not issue:
            return []
        severity = "fatal" if issue == "clinginess_or_dependency_bait" else "rewriteable"
        return [ValidationIssue(issue, severity)]

    def _validate_semantic_repeat_surface(
        self,
        text: str,
        *,
        line_type: str,
        semantic_family: str,
        meaning_family: str,
    ) -> list[ValidationIssue]:
        # validate_text không có timestamp/recent_lines nên không block repeat ở đây.
        # Nó chỉ giữ chỗ mở rộng để coordinator mới truyền family vào evaluate/check.
        # Nếu cần enforce repeat ở final, gọi repeat_guard.check() ở coordinator với recent_lines.
        _ = (text, line_type, semantic_family, meaning_family)
        return []

    # ------------------------------------------------------------------
    # Type/risk/evidence helpers
    # ------------------------------------------------------------------

    def _line_type_for_intent(self, intent: str) -> str:
        """Map speech intent sang dạng câu nhỏ.

        Thêm ambient_residue để ERIS có thể nói một vệt nhịp rất nhỏ mà không
        cần giả vờ đó là observation màn hình. Đây là chỗ sửa lỗi “không thấy
        productivity issue thì im như máy”.
        """

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
        if intent in {"ambient_residue", "presence_residue", "quiet_residue"}:
            return "ambient_residue"
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
        if line_type in {"micro_presence", "ambient_residue"}:
            return "micro_presence"
        return "texture"

    def _signal_score(self, *, broadcast, vision_fact: str) -> float:
        """Đánh giá độ mạnh của evidence cụ thể."""

        score = 0.0
        if str(vision_fact or "").strip():
            score = max(score, 0.72)
        if broadcast is not None:
            score = max(score, self._candidate_signal_score(broadcast))
            for item in tuple(getattr(broadcast, "items", ()) or ()):  # broadcast có thể chứa nhiều candidate.
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
        """Tìm anchor cho observation.

        Chỉ micro_observation cần anchor bắt buộc. Các line residue có thể dựa
        vào nhịp runtime nên không nên bị ép nói như đang nhìn màn hình.
        """

        evidence = str(vision_fact or "").strip()
        if line_type in self.OBSERVATION_TYPES and evidence:
            return "screen_evidence", evidence

        action = str(user_action or "").strip()
        if line_type in self.OBSERVATION_TYPES and action:
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
        if line_type in self.OBSERVATION_TYPES and context:
            return "session_context", context
        return "", ""

    def _current_semantic_family(self, *, semantic_family: str, meaning_family: str, text: str) -> str:
        return (
            self.repeat_guard._clean_family(semantic_family)
            or self.repeat_guard._clean_family(meaning_family)
            or self.repeat_guard.family_for_text(text)
        )

    # ------------------------------------------------------------------
    # Surface heuristics
    # ------------------------------------------------------------------

    def _looks_like_placeholder(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if stripped in {"...", "…"}:
            return True
        normalized = self.repeat_guard.normalize(stripped)
        return normalized in {"hm", "um"}

    def _word_count(self, text: str) -> int:
        return len([item for item in re.split(r"\s+", str(text or "").strip(" .?!")) if item])

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
        if line_type in {"micro_presence", "ambient_residue"} and any(
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
                "im lai",
                "yen xuong",
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
            "lech",
            "nhip",
        )
        return any(marker in normalized for marker in metaphor_markers) and not any(
            marker in normalized for marker in stance_markers
        )

    def _semantic_density(self, text: str) -> float:
        normalized = self.repeat_guard.normalize(text)
        tokens = [token for token in normalized.split() if token]
        if not tokens:
            return 0.0
        filler_tokens = {
            "a", "ai", "ay", "cai", "cho", "co", "cua", "cung", "da", "dang", "day",
            "de", "den", "di", "do", "doan", "gi", "hoi", "kia", "la", "lai", "mot",
            "nay", "ngai", "nhu", "noi", "o", "ra", "roi", "the", "thi", "thoi", "toi",
            "trong", "tu", "van", "ve", "vua",
        }
        meaningful = [token for token in tokens if len(token) >= 3 and token not in filler_tokens]
        if not meaningful:
            return 0.0
        unique_meaningful = set(meaningful)
        repetition_penalty = len(unique_meaningful) / max(1, len(meaningful))
        return (len(meaningful) / len(tokens)) * (0.72 + repetition_penalty * 0.28)

    def _looks_like_presence_narration(self, text: str) -> bool:
        """Chặn micro-presence thành báo cáo hệ thống/trạng thái."""

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
        """Chặn lời khai cảm xúc quá thẳng.

        ERIS có thể có residue/attachment pressure, nhưng không nên nói như đang
        viết nhật ký cầu xin. Dư âm phải rò qua nhịp/khoảng cách, không phải plea.
        """

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

    # ------------------------------------------------------------------
    # Relational permission
    # ------------------------------------------------------------------

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
        """Tính stage cho phép lộ attachment.

        Bản sửa không để relationship_stage string nắm quyền tuyệt đối. Nếu score
        continuity/trust/presence đủ mạnh, vẫn coi là có continuity thật dù stage
        chưa update. Vì state string lỗi mà bóp chết lịch sử thật là thiết kế rất
        xứng đáng bị xoá khỏi repo.
        """

        ctx = relational_context or RelationalContext()
        attachment = self._clamp01(ctx.attachment_level)
        continuity = self._clamp01(ctx.continuity_score)
        social = self._clamp01(ctx.social_resonance)
        presence = self._clamp01(ctx.recent_presence_density)
        trust = self._clamp01(ctx.trust_stability)
        abandonment = self._clamp01(ctx.abandonment_sensitivity)
        stage = str(ctx.relationship_stage or "").strip().lower()

        history_support = continuity >= 0.60 and trust >= 0.45 and presence >= 0.35
        true_continuity = history_support or (continuity >= 0.52 and stage not in {"new", "unknown", "low_context"})

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

    def _relational_theme(self, normalized: str) -> str:
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
        if message_competition:
            return "message_competition"

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
        if outside_rhythm:
            return "outside_rhythm"

        ignored_presence = any(
            marker in normalized
            for marker in (
                "quen toi",
                "khong de y toi",
                "bo mac",
                "lang quen",
                "khong con de y",
            )
        )
        if ignored_presence:
            return "ignored_presence"

        return "generic_distance"

    def _allowed_exposure_for_stage(self, stage: str) -> float:
        return {
            "none": 0.18,
            "low": 0.30,
            "mid": 0.46,
            "high": 0.66,
            "very_high": 0.78,
            "full": 0.92,
        }.get(stage, 0.30)

    def _clamp01(self, value) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:  # NaN guard.
            return 0.0
        return max(0.0, min(1.0, numeric))

    def _dedupe_issues(self, issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
        seen: set[str] = set()
        deduped: list[ValidationIssue] = []
        for issue in issues:
            if not issue.code or issue.code in seen:
                continue
            seen.add(issue.code)
            deduped.append(issue)
        return tuple(deduped)
