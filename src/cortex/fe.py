from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from .affect_semantics import AffectSemanticClassifier, AffectSemanticSignal
from .internal_state import PersistentInternalState
from .contracts import (
    FeStyleMemory,
    FeStylePlan,
    GoalDriftReport,
    PersonalityLensResult,
    TelemetrySnapshot,
    TiPolicyReport,
)

"""
FeRenderer v2
=============

Mục tiêu của file này:
- Fe chỉ render style từ state, không tự cosplay personality.
- Giảm keyword routing cứng; chuyển sang affect signal dạng score đa trục.
- Tạo style pressure có nguyên nhân: distance, warmth, restraint, attachment visibility,
  symbolic bias, exposure recoil, precision.
- Strangeness chỉ được bật khi có causal support: residue, recoil, repeated motif,
  symbolic pressure, hoặc personality lens đủ rõ.
- Topic/repetition memory không soi lại câu ERIS vừa render bằng keyword thô.
  Nó ưu tiên causal signal từ plan/intent/affect/Ti/context; lexical chỉ là fallback yếu.
- Giữ public API cũ để RuntimeCoordinator không vỡ. Nếu coordinator chưa truyền
  affect_signal thì file tự derive bằng semantic-lite scorer nội bộ.

Lưu ý lạnh lùng: đây chưa phải “cảm xúc thật”. Đây là control layer có quán tính.
Ít nhất nó bớt ngu hơn việc thấy chữ “buồn” rồi cosplay therapist.
"""


@dataclass(frozen=True)
class FeAffectSignal:
    """Score đa trục cho chat intent.

    Đây là semantic-lite signal. Coordinator có thể truyền signal tốt hơn về sau
    từ embedding/LLM classifier. Khi chưa có, FeRenderer tự suy bằng phrase family
    và structural cues. Không dùng keyword đơn để hard-route nữa.
    """

    attachment: float = 0.0
    distress: float = 0.0
    intimacy: float = 0.0
    technicality: float = 0.0
    conflict: float = 0.0
    ambiguity: float = 0.0
    playfulness: float = 0.0
    relational_pressure: float = 0.0
    perceived_rejection: float = 0.0
    attachment_bid: float = 0.0
    playful_distress: float = 0.0
    romantic_boundary_probe: float = 0.0
    evidence: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "FeAffectSignal":
        return cls()

    @classmethod
    def from_semantic_signal(cls, signal: AffectSemanticSignal) -> "FeAffectSignal":
        return cls(
            attachment=_clamp01(getattr(signal, "attachment", 0.0)),
            distress=_clamp01(getattr(signal, "distress", 0.0)),
            intimacy=_clamp01(getattr(signal, "intimacy", 0.0)),
            technicality=_clamp01(getattr(signal, "technicality", 0.0)),
            conflict=_clamp01(getattr(signal, "conflict", 0.0)),
            ambiguity=_clamp01(getattr(signal, "ambiguity", 0.0)),
            playfulness=_clamp01(getattr(signal, "playfulness", 0.0)),
            relational_pressure=_clamp01(getattr(signal, "relational_pressure", 0.0)),
            perceived_rejection=_clamp01(getattr(signal, "perceived_rejection", 0.0)),
            attachment_bid=_clamp01(getattr(signal, "attachment_bid", 0.0)),
            playful_distress=_clamp01(getattr(signal, "playful_distress", 0.0)),
            romantic_boundary_probe=_clamp01(getattr(signal, "romantic_boundary_probe", 0.0)),
            evidence=tuple(str(item) for item in (getattr(signal, "evidence", ()) or ()) if str(item or "").strip()),
        )

    @classmethod
    def from_text(cls, text: str) -> "FeAffectSignal":
        raw = (text or "").strip()
        if not raw:
            return cls(ambiguity=0.55, evidence=("empty_text",))

        lowered = raw.lower()
        normalized = _normalize_text(lowered)
        haystack = f" {lowered} {normalized} "
        evidence: list[str] = []

        # Phrase families, không phải keyword -> intent. Mỗi family chỉ đẩy score.
        technical_terms = (
            "code", "python", "c#", "godot", "file", "class", "function", "method",
            "bug", "fix", "debug", "runtime", "api", "json", "prompt", "model",
            "kiến trúc", "kien truc", "module", "pipeline", "error", "traceback",
            "lỗi", "loi", "sửa", "sua", "đánh giá", "danh gia", "giải thích", "giai thich",
        )
        distress_terms = (
            "mệt", "met", "buồn", "buon", "chán", "chan", "stress", "burnout",
            "cô đơn", "co don", "áp lực", "ap luc", "khó sống", "kho song",
            "nản", "nan", "tệ", "te", "rối", "roi", "cay", "khổ", "kho",
        )
        attachment_terms = (
            "nhớ", "nho", "yêu", "yeu", "thương", "thuong", "gắn bó", "gan bo",
            "bạn gái", "ban gai", "ở cạnh", "o canh", "hiểu mình", "hieu minh",
            "quan tâm", "quan tam", "infj", "relationship", "người yêu", "nguoi yeu",
        )
        intimacy_terms = (
            "tôi thấy", "toi thay", "tôi nghĩ", "toi nghi", "tôi muốn", "toi muon",
            "tôi sợ", "toi so", "tôi biết", "toi biet", "cuộc đời", "cuoc doi",
            "tâm trạng", "tam trang", "thật ra", "that ra", "nhìn lại", "nhin lai",
        )
        conflict_terms = (
            "sai", "ngu", "dở", "do", "bực", "buc", "khó chịu", "kho chiu",
            "ghét", "ghet", "cay", "dcm", "đm", "dm", "vl", "vcl", "xàm", "xam",
            "không đúng", "khong dung", "ảo", "ao", "fake", "bẩn", "ban",
        )
        playful_terms = (
            "haha", "hehe", "lol", "vui", "chill", "đùa", "dua", "meme", "joke",
        )

        technicality = _phrase_score(haystack, technical_terms, evidence, "technical")
        distress = _phrase_score(haystack, distress_terms, evidence, "distress")
        attachment = _phrase_score(haystack, attachment_terms, evidence, "attachment")
        intimacy = _phrase_score(haystack, intimacy_terms, evidence, "intimacy")
        conflict = _phrase_score(haystack, conflict_terms, evidence, "conflict")
        playfulness = _phrase_score(haystack, playful_terms, evidence, "playfulness")

        token_count = len(re.findall(r"\w+", normalized, flags=re.UNICODE))
        question_marks = raw.count("?") + raw.count("？")
        ambiguity = 0.0
        if token_count <= 3:
            ambiguity += 0.32
            evidence.append("short_text")
        if question_marks >= 2:
            ambiguity += 0.12
            evidence.append("many_questions")
        if raw.endswith(("à", "ha", "nhỉ", "không", "ko", "k")):
            ambiguity += 0.08
            evidence.append("soft_question_tail")

        # Nếu text technical mạnh thì giảm distress mơ hồ. Không phải mọi câu có "lỗi"
        # đều là suy sụp tinh thần, thật đáng tiếc cho những bộ lọc non nớt.
        if technicality >= 0.45:
            distress *= 0.72
            attachment *= 0.82
            intimacy *= 0.86

        # Câu thân mật nhưng có kỹ thuật: thường là trust/familiarity, không phải therapy.
        if technicality >= 0.45 and intimacy >= 0.25:
            evidence.append("technical_with_personal_frame")

        relational_tone_feedback_terms = (
            "lanh lung", "lanh qua", "qua lanh", "xa cach", "vo hon",
            "robot", "nhu bot", "chatbot", "assistant", "support",
            "cung qua", "khong tu nhien", "may moc",
        )
        perceived_rejection = 0.0
        relational_pressure = 0.0
        if any(term in haystack for term in relational_tone_feedback_terms):
            perceived_rejection = 0.68
            relational_pressure = 0.62
            attachment = max(attachment, 0.46)
            intimacy = max(intimacy, 0.30)
            conflict = min(max(conflict, 0.22), 0.45)
            evidence.append("relational_tone_feedback")

        return cls(
            attachment=_clamp01(attachment),
            distress=_clamp01(distress),
            intimacy=_clamp01(intimacy),
            technicality=_clamp01(technicality),
            conflict=_clamp01(conflict),
            ambiguity=_clamp01(ambiguity),
            playfulness=_clamp01(playfulness),
            relational_pressure=_clamp01(relational_pressure),
            perceived_rejection=_clamp01(perceived_rejection),
            attachment_bid=_clamp01(relational_pressure * 0.35),
            evidence=tuple(dict.fromkeys(evidence)),
        )


@dataclass(frozen=True)
class FeDevelopmentSnapshot:
    """Development state derive từ FeStyleMemory + internal_state.

    Không thêm field vào FeStyleMemory để file này thay thế được ngay. Nếu muốn phát
    triển thật sâu, hãy đưa class này vào contracts/persistent memory sau.
    """

    familiarity: float
    trust: float
    rupture_pressure: float
    ritual_strength: float
    attachment_baseline: float
    preferred_distance: float
    exposure_recoil: float
    user_tolerates_strangeness: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class FeStylePressure:
    distance: float
    warmth: float
    restraint: float
    attachment_visibility: float
    symbolic_bias: float
    exposure_recoil: float
    precision: float
    dry_edge: float
    strangeness_allowed: bool
    evidence: tuple[str, ...]

    def to_label(self) -> str:
        return (
            f"distance={self.distance:.2f}; "
            f"warmth={self.warmth:.2f}; "
            f"restraint={self.restraint:.2f}; "
            f"attachment_visibility={self.attachment_visibility:.2f}; "
            f"symbolic_bias={self.symbolic_bias:.2f}; "
            f"exposure_recoil={self.exposure_recoil:.2f}; "
            f"precision={self.precision:.2f}; "
            f"dry_edge={self.dry_edge:.2f}; "
            f"strangeness={'allowed' if self.strangeness_allowed else 'disabled'}"
        )




@dataclass(frozen=True)
class FeTopicCandidate:
    """Ứng viên topic dùng cho memory repetition của Fe.

    Lưu ý quan trọng:
    - Topic ở đây KHÔNG phải intent người dùng.
    - Topic ở đây KHÔNG phải nhãn cảm xúc.
    - Topic chỉ là nhãn thô để biết ERIS có đang lặp cùng một vùng nói hay không.

    Vì vậy nó cần đủ chắc mới được ghi vào FeStyleMemory. Ghi thiếu thì chỉ mất
    một chút continuity; ghi sai thì tạo repeated_topic ảo và làm ERIS tự né một
    chủ đề chưa hề lặp. Con người đã đủ giỏi tự hiểu lầm bản thân rồi, runtime
    không cần bắt chước phần đó quá sớm.
    """

    tag: str
    score: float
    evidence: tuple[str, ...] = ()

class FeRenderer:
    def create_memory(self) -> FeStyleMemory:
        return FeStyleMemory()

    def apply_personality_lens(self, plan: FeStylePlan, lens: PersonalityLensResult | None) -> FeStylePlan:
        """Apply PersonalityLens như pressure, không để lens biến Fe thành prompt dump.

        Lens vẫn được đưa vào context, nhưng context phải là causal pressure. Nếu lens
        suppression cao thì hạ độ lộ cảm xúc và tăng brevity. Không overwrite toàn bộ
        giọng nói bằng một persona script.
        """
        if lens is None:
            return plan

        prompt_context = str(getattr(lens, "prompt_context", "") or "").strip()
        if prompt_context and prompt_context not in (plan.style_context or ""):
            plan.style_context = f"{plan.style_context}\n{prompt_context}" if plan.style_context else prompt_context

        evidence = list(tuple(getattr(plan, "evidence", ()) or ()))
        interpretation = str(getattr(lens, "interpretation", "") or "")
        stance = str(getattr(lens, "stance", "") or "")
        restraint_mode = str(getattr(lens, "restraint_mode", "") or "")
        rhythm = str(getattr(lens, "rhythm", "") or "")

        if interpretation:
            evidence.append(f"personality_lens={interpretation}")
        if stance:
            evidence.append(f"personality_stance={stance}")
        if restraint_mode:
            evidence.append(f"restraint_mode={restraint_mode}")
        if rhythm:
            evidence.append(f"personality_rhythm={rhythm}")

        want_to_say = self._float(getattr(lens, "want_to_say", 0.0))
        allowed_expression = self._float(getattr(lens, "allowed_expression", 0.0))
        suppression_pressure = self._float(getattr(lens, "suppression_pressure", 0.0))
        evidence.append(f"expression_gate={want_to_say:.2f}->{allowed_expression:.2f}")

        if rhythm == "dense_sparse" and plan.brevity_bias == "medium":
            plan.brevity_bias = "short"
            plan.style_context = plan.style_context.replace("brevity=medium", "brevity=short", 1)

        if suppression_pressure >= 0.72:
            plan.warmth_level = min(plan.warmth_level, 0.34)
            plan.brevity_bias = "short"
            plan.style_context += "\nlens_gate: expression suppressed; leak less, imply less, do not perform intimacy."
        elif suppression_pressure <= 0.24 and allowed_expression >= 0.55:
            plan.style_context += "\nlens_gate: expression can surface, but keep it grounded in current evidence."

        plan.evidence = tuple(dict.fromkeys(str(item) for item in evidence if str(item or "").strip()))
        return plan

    def decay_memory(self, memory: FeStyleMemory) -> FeStyleMemory:
        return FeStyleMemory(
            recent_modes=memory.recent_modes[-4:],
            recent_tones=memory.recent_tones[-4:],
            recent_intents=memory.recent_intents[-4:],
            recent_topic_tags=memory.recent_topic_tags[-4:],
            last_mode=memory.last_mode,
            last_tone_label=memory.last_tone_label,
            last_intent=memory.last_intent,
            last_response_excerpt=memory.last_response_excerpt[:120],
            repeated_topic_tag=memory.repeated_topic_tag,
            repeated_topic_streak=max(0, memory.repeated_topic_streak - 1),
            session_arc=memory.session_arc,
            sarcasm_level=memory.sarcasm_level,
            warmth_level=memory.warmth_level,
            brevity_bias=memory.brevity_bias,
            continuity_strength=max(0.12, memory.continuity_strength * 0.55),
            session_turn_count=0,
            arc_strength=max(0.0, memory.arc_strength * 0.45),
            technical_pull=memory.technical_pull * 0.60,
            discipline_pull=memory.discipline_pull * 0.60,
            attachment_pull=memory.attachment_pull * 0.60,
            neutral_pull=memory.neutral_pull * 0.60,
        )

    def remember_style(
        self,
        memory: FeStyleMemory,
        *,
        plan: FeStylePlan,
        rendered_text: str,
    ) -> FeStyleMemory:
        base_tone_label = self._base_tone_label(plan.tone_label)
        recent_modes = (*memory.recent_modes, plan.mode)[-6:]
        recent_tones = (*memory.recent_tones, base_tone_label)[-6:]
        recent_intents = (*memory.recent_intents, plan.intent_label)[-8:]

        # Topic repetition phải lấy từ nguyên nhân tạo câu nói trước, không phải
        # soi lại câu ERIS vừa render rồi match keyword. Rendered text chỉ còn
        # là fallback yếu khi plan không có đủ semantic evidence.
        topic_tag = self._infer_topic_tag(rendered_text=rendered_text, plan=plan)
        recent_topic_tags = memory.recent_topic_tags[-6:]
        if topic_tag:
            recent_topic_tags = (*recent_topic_tags, topic_tag)[-6:]
        repeated_topic_tag, repeated_topic_streak = self._measure_topic_repetition(recent_topic_tags)

        excerpt = (rendered_text or "").strip().replace("\n", " ")[:140]
        continuity_gain = 0.08
        if plan.intent_label in {"technical_support", "attachment_dialogue", "boundary_repair"}:
            continuity_gain += 0.03
        if repeated_topic_streak >= 2:
            continuity_gain += 0.02
        strength = min(0.86, memory.continuity_strength + continuity_gain)

        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._updated_intent_pulls(
            memory=memory,
            intent_label=plan.intent_label,
        )

        return FeStyleMemory(
            recent_modes=recent_modes,
            recent_tones=recent_tones,
            recent_intents=recent_intents,
            recent_topic_tags=recent_topic_tags,
            last_mode=plan.mode,
            last_tone_label=base_tone_label,
            last_intent=plan.intent_label,
            last_response_excerpt=excerpt,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            session_arc=plan.session_arc,
            sarcasm_level=plan.sarcasm_level,
            warmth_level=plan.warmth_level,
            brevity_bias=plan.brevity_bias,
            continuity_strength=strength,
            session_turn_count=memory.session_turn_count + 1,
            arc_strength=self._estimate_arc_strength(
                technical_pull=technical_pull,
                discipline_pull=discipline_pull,
                attachment_pull=attachment_pull,
                neutral_pull=neutral_pull,
            ),
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        internal_state: PersistentInternalState | None = None,
        last_text: str,
    ) -> FeStylePlan:
        affect_signal = self._affect_from_autonomous_context(snapshot=snapshot, ti_report=ti_report)
        evidence = [
            getattr(snapshot, "focus_summary", ""),
            f"ti_mode={getattr(ti_report, 'mode', '')}",
            f"ni_drift={self._float(getattr(ni_report, 'drift_score', 0.0)):.2f}",
            self._render_affect_evidence(affect_signal),
        ]

        mode, sarcasm_level, warmth_level, brevity_bias = self._initial_autonomous_controls(
            snapshot=snapshot,
            ti_report=ti_report,
            affect_signal=affect_signal,
        )
        intent_label = self._infer_autonomous_intent(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
        )

        return self._finalize_plan(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=style_memory,
            internal_state=internal_state,
            affect_signal=affect_signal,
            evidence=evidence,
            mode=mode,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            intent_label=intent_label,
            chat_like=False,
        )

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        internal_state: PersistentInternalState | None = None,
        user_text: str,
        affect_signal: FeAffectSignal | AffectSemanticSignal | dict[str, Any] | None = None,
    ) -> FeStylePlan:
        affect = self._coerce_affect_signal(affect_signal) or FeAffectSignal.from_text(user_text)
        evidence = [
            getattr(snapshot, "focus_summary", ""),
            f"ti_mode={getattr(ti_report, 'mode', '')}",
            f"ni_drift={self._float(getattr(ni_report, 'drift_score', 0.0)):.2f}",
            self._render_affect_evidence(affect),
        ]

        intent_label = self._infer_chat_intent(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            user_text=user_text,
            affect_signal=affect,
        )
        mode, sarcasm_level, warmth_level, brevity_bias = self._initial_chat_controls(
            ti_report=ti_report,
            ni_report=ni_report,
            affect_signal=affect,
            intent_label=intent_label,
        )
        if affect.perceived_rejection >= 0.65 and affect.attachment >= 0.45:
            intent_label = "relational_repair"
            mode = "relational_repair"
            sarcasm_level = min(sarcasm_level, 0.10)
            warmth_level = max(warmth_level, 0.34)
            brevity_bias = "short"

        return self._finalize_plan(
            snapshot=snapshot,
            ni_report=ni_report,
            ti_report=ti_report,
            style_memory=style_memory,
            internal_state=internal_state,
            affect_signal=affect,
            evidence=evidence,
            mode=mode,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            intent_label=intent_label,
            chat_like=True,
        )

    def _finalize_plan(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        style_memory: FeStyleMemory,
        internal_state: PersistentInternalState | None,
        affect_signal: FeAffectSignal,
        evidence: list[str],
        mode: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        intent_label: str,
        chat_like: bool,
    ) -> FeStylePlan:
        sarcasm_level, warmth_level, brevity_bias, internal_note = self._apply_internal_state_bias(
            internal_state=internal_state,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )
        if internal_note:
            evidence.append(internal_note)

        (
            mode,
            sarcasm_level,
            warmth_level,
            brevity_bias,
            continuity_note,
        ) = self._apply_memory_continuity(
            memory=style_memory,
            mode=mode,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=chat_like,
        )
        if continuity_note:
            evidence.append(continuity_note)

        (
            session_arc,
            arc_strength,
            transition_note,
            sarcasm_level,
            warmth_level,
            brevity_bias,
        ) = self._apply_session_arc(
            memory=style_memory,
            intent_label=intent_label,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            chat_like=chat_like,
        )
        if intent_label == "relational_repair":
            session_arc = "repair_without_submission"
            arc_strength = max(arc_strength, 0.62)
            transition_note = transition_note or "relational_repair"

        development = self._derive_development_snapshot(
            memory=style_memory,
            internal_state=internal_state,
            affect_signal=affect_signal,
            chat_like=chat_like,
        )
        style_pressure = self._derive_style_pressure(
            mode=mode,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            memory=style_memory,
            internal_state=internal_state,
            affect_signal=affect_signal,
            development=development,
            chat_like=chat_like,
        )
        sarcasm_level, warmth_level, brevity_bias = self._apply_style_pressure_to_controls(
            style_pressure=style_pressure,
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            mode=mode,
        )

        evidence.extend(
            (
                f"fe_intent={intent_label}",
                f"fe_arc={session_arc}:{arc_strength:.2f}",
                f"development={self._render_development_evidence(development)}",
                f"style_pressure={style_pressure.to_label()}",
            )
        )
        if style_memory.repeated_topic_streak >= 2 and style_memory.repeated_topic_tag:
            evidence.append(f"repeat_topic={style_memory.repeated_topic_tag}:{style_memory.repeated_topic_streak}")
        if transition_note:
            evidence.append(transition_note)

        tone_label = self._build_tone_label(
            mode=mode,
            warmth_level=warmth_level,
            intent_label=intent_label,
            session_arc=session_arc,
            style_pressure=style_pressure,
        )
        style_context = self._build_style_context(
            mode=mode,
            tone_label=tone_label,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
            internal_state=internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            memory=style_memory,
            continuity_note=continuity_note,
            intent_label=intent_label,
            session_arc=session_arc,
            arc_strength=arc_strength,
            transition_note=transition_note,
            affect_signal=affect_signal,
            development=development,
            style_pressure=style_pressure,
        )

        return FeStylePlan(
            mode=mode,
            tone_label=tone_label,
            style_context=style_context,
            intent_label=intent_label,
            session_arc=session_arc,
            transition_note=transition_note,
            evidence=tuple(dict.fromkeys(str(item) for item in evidence if str(item or "").strip())),
            sarcasm_level=sarcasm_level,
            warmth_level=warmth_level,
            brevity_bias=brevity_bias,
        )

    def _initial_autonomous_controls(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ti_report: TiPolicyReport,
        affect_signal: FeAffectSignal,
    ) -> tuple[str, float, float, str]:
        mode = "grounded"
        sarcasm_level = 0.24
        warmth_level = 0.24
        brevity_bias = "medium"
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        window_kind = str(getattr(snapshot, "active_window_kind", "") or "")

        if ti_mode in {"focus_guard", "chat_code"} or affect_signal.technicality >= 0.55:
            return "technical", 0.16, 0.30, "short"
        if ti_mode in {"goal_drift_alert", "discipline_nudge"}:
            return "grounded", 0.30, 0.20, "short"
        if ti_mode == "goal_realign":
            return "grounded", 0.28, 0.22, "short"
        if ti_mode == "reengage":
            return "grounded", 0.22, 0.24, "short"
        if ti_mode == "resource_guard":
            return "grounded", 0.18, 0.18, "short"
        if ti_mode == "pattern_muse":
            return "grounded", 0.16, 0.28, "medium"
        if window_kind == "communication":
            return "grounded", 0.14, 0.27, "short"
        return mode, sarcasm_level, warmth_level, brevity_bias

    def _initial_chat_controls(
        self,
        *,
        ti_report: TiPolicyReport,
        ni_report: GoalDriftReport,
        affect_signal: FeAffectSignal,
        intent_label: str,
    ) -> tuple[str, float, float, str]:
        mode = "grounded"
        sarcasm_level = 0.22
        warmth_level = 0.28
        brevity_bias = "medium"
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        drift_score = self._float(getattr(ni_report, "drift_score", 0.0))
        should_raise_guard = bool(getattr(ni_report, "should_raise_guard", False))

        if ti_mode == "chat_code" or intent_label == "technical_support":
            return "technical", 0.14, 0.32, "medium"
        if intent_label == "relational_repair":
            return "relational_repair", 0.08, 0.34, "short"
        if ti_mode == "chat_emotional" or intent_label == "attachment_dialogue":
            return "grounded", 0.14, 0.36, "medium"
        if intent_label == "boundary_repair":
            return "grounded", 0.12, 0.26, "short"
        if ti_mode in {"goal_drift_alert", "goal_realign"} or (should_raise_guard and drift_score >= 0.88):
            return "grounded", 0.26, 0.24, "medium"

        if affect_signal.conflict >= 0.45:
            sarcasm_level = 0.20
            warmth_level = 0.24
            brevity_bias = "short"
        elif affect_signal.playfulness >= 0.35:
            sarcasm_level = 0.26
            warmth_level = 0.30
        return mode, sarcasm_level, warmth_level, brevity_bias

    def _infer_autonomous_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
    ) -> str:
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        window_kind = str(getattr(snapshot, "active_window_kind", "") or "")

        if ti_mode in {"focus_guard", "chat_code"}:
            return "technical_support"
        if ti_mode == "resource_guard":
            if window_kind in {"coding", "documentation", "system"}:
                return "technical_support"
            return "ordinary_dialogue"
        if ti_mode in {"goal_drift_alert", "goal_realign", "discipline_nudge", "reengage"}:
            return "ordinary_dialogue"
        if ti_mode == "pattern_muse":
            return "ordinary_dialogue"
        if window_kind == "communication":
            return "social_watch" if ti_mode == "social_watch" else "ordinary_dialogue"
        return "ordinary_dialogue"

    def _infer_chat_intent(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        user_text: str,
        affect_signal: FeAffectSignal | None = None,
    ) -> str:
        affect = affect_signal or FeAffectSignal.from_text(user_text)
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        drift_score = self._float(getattr(ni_report, "drift_score", 0.0))
        should_raise_guard = bool(getattr(ni_report, "should_raise_guard", False))
        window_kind = str(getattr(snapshot, "active_window_kind", "") or "")

        if ti_mode == "chat_code" or affect.technicality >= 0.62:
            return "technical_support"
        if affect.perceived_rejection >= 0.65 and affect.attachment >= 0.45:
            return "relational_repair"
        if affect.attachment >= 0.52 or affect.intimacy >= 0.58:
            return "attachment_dialogue"
        if affect.conflict >= 0.54:
            return "boundary_repair"
        if ti_mode in {"goal_drift_alert", "goal_realign"} or (should_raise_guard and drift_score >= 0.88):
            return "goal_guard"
        if window_kind == "communication" and affect.technicality < 0.35:
            return "social_watch"
        return "ordinary_dialogue"

    def _apply_memory_continuity(
        self,
        *,
        memory: FeStyleMemory,
        mode: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, float, float, str, str]:
        if memory.continuity_strength <= 0.0 or not memory.last_mode:
            return mode, sarcasm_level, warmth_level, brevity_bias, ""

        strength = 0.42 if chat_like else 0.26
        strength *= min(1.0, max(0.0, memory.continuity_strength))
        family_now = self._style_family(mode)
        family_prev = self._style_family(memory.last_mode)

        if family_now == family_prev:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength)
            brevity_bias = self._blend_brevity(memory.brevity_bias, brevity_bias)
        elif chat_like and family_prev in {"technical", "grounded", "comforting"}:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, strength * 0.55)
            warmth_level = self._blend(memory.warmth_level, warmth_level, strength * 0.36)
            if brevity_bias == "medium":
                brevity_bias = memory.brevity_bias

        return mode, sarcasm_level, warmth_level, brevity_bias, f"continuity_from={memory.last_mode}"

    def _apply_internal_state_bias(
        self,
        *,
        internal_state: PersistentInternalState | None,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
    ) -> tuple[float, float, str, str]:
        state = internal_state or PersistentInternalState()
        attachment = self._float(getattr(state, "attachment", 0.0))
        tenderness = self._float(getattr(state, "tenderness", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))
        protectiveness = self._float(getattr(state, "protectiveness", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        desire = getattr(state, "desire", None)
        want = self._float(getattr(desire, "want", 0.0))
        cling = self._float(getattr(desire, "cling", 0.0))
        avoid = self._float(getattr(desire, "avoid", 0.0))
        residue = self._float(getattr(desire, "unresolved_residue", 0.0))
        drift_label = str(getattr(desire, "attachment_drift", "") or "")

        # Bias nhẹ. StylePressure phía sau mới là nơi quyết định texture sâu hơn.
        warmth_level = self._clamp(
            warmth_level
            + attachment * 0.07
            + tenderness * 0.10
            + social_energy * 0.03
            + cling * 0.025
            - fatigue * 0.06
            - avoid * 0.05
        )
        sarcasm_level = self._clamp(
            sarcasm_level
            + irritation * 0.07
            + residue * 0.025
            - protectiveness * 0.08
            - fatigue * 0.10
        )
        if protectiveness >= 0.56 or fatigue >= 0.42 or drift_label in {"defensive", "avoidant"}:
            brevity_bias = "short"
        elif (social_energy >= 0.66 or want >= 0.42) and brevity_bias == "short":
            brevity_bias = "medium"

        return (
            sarcasm_level,
            warmth_level,
            brevity_bias,
            f"internal_state_bias=attach:{attachment:.2f},protect:{protectiveness:.2f},fatigue:{fatigue:.2f},desire:{want:.2f}/{cling:.2f}/{avoid:.2f}/{residue:.2f}",
        )

    def _apply_session_arc(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        chat_like: bool,
    ) -> tuple[str, float, str, float, float, str]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        session_arc = self._dominant_arc(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )
        arc_strength = self._estimate_arc_strength(
            technical_pull=technical_pull,
            discipline_pull=discipline_pull,
            attachment_pull=attachment_pull,
            neutral_pull=neutral_pull,
        )

        if session_arc == "technical_guardianship":
            sarcasm_level = self._blend(self._anchor_value(memory.sarcasm_level, 0.13), sarcasm_level, 0.28)
            warmth_level = self._blend(self._anchor_value(memory.warmth_level, 0.32), warmth_level, 0.32)
            if brevity_bias == "short" and chat_like:
                brevity_bias = "medium"
        elif session_arc == "discipline_pressure":
            sarcasm_level = max(sarcasm_level, 0.25 if chat_like else 0.23)
            warmth_level = min(warmth_level, 0.25 if chat_like else 0.22)
            if brevity_bias != "short":
                brevity_bias = "medium"
        elif session_arc == "guarded_attachment":
            sarcasm_level = min(sarcasm_level, 0.22)
            warmth_level = max(warmth_level, 0.33 if chat_like else 0.26)
            if brevity_bias == "short" and not chat_like:
                brevity_bias = "medium"
        else:
            sarcasm_level = self._blend(memory.sarcasm_level, sarcasm_level, 0.13)
            warmth_level = self._blend(memory.warmth_level, warmth_level, 0.13)

        transition_note = ""
        if memory.last_intent and memory.last_intent != intent_label:
            transition_note = f"intent_shift={memory.last_intent}->{intent_label}"
        elif memory.session_arc and memory.session_arc != session_arc and memory.session_turn_count > 0:
            transition_note = f"arc_shift={memory.session_arc}->{session_arc}"

        return session_arc, arc_strength, transition_note, sarcasm_level, warmth_level, brevity_bias

    def _derive_development_snapshot(
        self,
        *,
        memory: FeStyleMemory,
        internal_state: PersistentInternalState | None,
        affect_signal: FeAffectSignal,
        chat_like: bool,
    ) -> FeDevelopmentSnapshot:
        state = internal_state or PersistentInternalState()
        desire = getattr(state, "desire", None)
        evidence: list[str] = []

        familiarity = self._clamp(memory.continuity_strength * 0.55 + min(memory.session_turn_count, 12) / 12.0 * 0.30)
        trust = self._clamp(
            0.18
            + familiarity * 0.28
            + memory.attachment_pull * 0.20
            + memory.technical_pull * 0.10
            + affect_signal.intimacy * 0.10
            - affect_signal.conflict * 0.14
        )
        rupture_pressure = self._clamp(
            affect_signal.conflict * 0.42
            + self._float(getattr(state, "irritation", 0.0)) * 0.30
            + self._float(getattr(state, "fatigue", 0.0)) * 0.12
        )
        ritual_strength = self._clamp(memory.continuity_strength * 0.35 + memory.arc_strength * 0.25 + familiarity * 0.22)
        attachment_baseline = self._clamp(
            self._float(getattr(state, "attachment", 0.0)) * 0.36
            + memory.attachment_pull * 0.30
            + affect_signal.attachment * 0.18
            + trust * 0.10
        )
        exposure_recoil = self._clamp(
            self._float(getattr(desire, "avoid", 0.0)) * 0.24
            + self._float(getattr(state, "fatigue", 0.0)) * 0.18
            + rupture_pressure * 0.20
            + (0.12 if memory.last_intent == "attachment_dialogue" else 0.0)
            + (0.07 if chat_like and affect_signal.intimacy >= 0.45 else 0.0)
        )
        preferred_distance = self._clamp(0.56 + exposure_recoil * 0.22 + rupture_pressure * 0.16 - trust * 0.18)
        user_tolerates_strangeness = self._clamp(
            0.22
            + memory.arc_strength * 0.20
            + familiarity * 0.12
            + affect_signal.playfulness * 0.10
            - rupture_pressure * 0.16
        )

        if familiarity >= 0.45:
            evidence.append("familiarity_accumulated")
        if rupture_pressure >= 0.35:
            evidence.append("rupture_pressure")
        if exposure_recoil >= 0.34:
            evidence.append("exposure_recoil")
        if ritual_strength >= 0.42:
            evidence.append("ritual_continuity")

        return FeDevelopmentSnapshot(
            familiarity=familiarity,
            trust=trust,
            rupture_pressure=rupture_pressure,
            ritual_strength=ritual_strength,
            attachment_baseline=attachment_baseline,
            preferred_distance=preferred_distance,
            exposure_recoil=exposure_recoil,
            user_tolerates_strangeness=user_tolerates_strangeness,
            evidence=tuple(evidence),
        )

    def _derive_style_pressure(
        self,
        *,
        mode: str,
        intent_label: str,
        session_arc: str,
        arc_strength: float,
        sarcasm_level: float,
        warmth_level: float,
        memory: FeStyleMemory,
        internal_state: PersistentInternalState | None,
        affect_signal: FeAffectSignal,
        development: FeDevelopmentSnapshot,
        chat_like: bool,
    ) -> FeStylePressure:
        state = internal_state or PersistentInternalState()
        desire = getattr(state, "desire", None)
        attachment = self._float(getattr(state, "attachment", 0.0))
        tenderness = self._float(getattr(state, "tenderness", 0.0))
        irritation = self._float(getattr(state, "irritation", 0.0))
        protectiveness = self._float(getattr(state, "protectiveness", 0.0))
        fatigue = self._float(getattr(state, "fatigue", 0.0))
        curiosity = self._float(getattr(state, "curiosity", 0.0))
        social_energy = self._float(getattr(state, "social_energy", 0.0))
        avoid = self._float(getattr(desire, "avoid", 0.0))
        residue = self._float(getattr(desire, "unresolved_residue", 0.0))
        want = self._float(getattr(desire, "want", 0.0))
        cling = self._float(getattr(desire, "cling", 0.0))

        evidence: list[str] = []

        precision = 0.28
        if mode == "technical":
            precision += 0.42
        precision += affect_signal.technicality * 0.24
        if intent_label == "technical_support":
            precision += 0.12
        precision = self._clamp(precision)

        distance = self._clamp(
            development.preferred_distance * 0.46
            + fatigue * 0.12
            + avoid * 0.16
            + development.exposure_recoil * 0.18
            + development.rupture_pressure * 0.16
            + precision * 0.06
            - development.trust * 0.16
            - tenderness * 0.08
        )
        warmth = self._clamp(
            warmth_level * 0.56
            + attachment * 0.10
            + tenderness * 0.18
            + development.trust * 0.12
            + affect_signal.intimacy * 0.08
            + social_energy * 0.04
            - fatigue * 0.08
            - development.exposure_recoil * 0.12
            - development.rupture_pressure * 0.08
        )
        restraint = self._clamp(
            0.42
            + protectiveness * 0.16
            + fatigue * 0.14
            + development.exposure_recoil * 0.22
            + development.rupture_pressure * 0.16
            + affect_signal.ambiguity * 0.12
            + (0.12 if not chat_like else 0.04)
            - social_energy * 0.05
        )
        attachment_visibility = self._clamp(
            development.attachment_baseline * 0.42
            + attachment * 0.18
            + tenderness * 0.16
            + affect_signal.attachment * 0.18
            + want * 0.06
            + cling * 0.04
            - restraint * 0.28
            - development.exposure_recoil * 0.24
            - precision * 0.10
        )
        symbolic_bias = self._clamp(
            curiosity * 0.18
            + residue * 0.28
            + memory.arc_strength * 0.16
            + affect_signal.intimacy * 0.10
            + affect_signal.ambiguity * 0.08
            + (0.12 if session_arc == "guarded_attachment" else 0.0)
            - precision * 0.18
            - fatigue * 0.08
        )
        exposure_recoil = self._clamp(
            development.exposure_recoil * 0.58
            + avoid * 0.14
            + residue * 0.08
            + affect_signal.conflict * 0.10
            + (0.08 if intent_label == "attachment_dialogue" and warmth >= 0.40 else 0.0)
        )
        dry_edge = self._clamp(
            sarcasm_level * 0.54
            + irritation * 0.16
            + affect_signal.playfulness * 0.12
            + development.rupture_pressure * 0.08
            - protectiveness * 0.08
            - affect_signal.distress * 0.10
        )

        if precision >= 0.58:
            symbolic_bias = min(symbolic_bias, 0.42)
            attachment_visibility = min(attachment_visibility, 0.38)
            evidence.append("technical_precision_caps_symbolic_leak")

        if affect_signal.distress >= 0.45:
            dry_edge = min(dry_edge, 0.22)
            warmth = max(warmth, 0.32)
            evidence.append("distress_softens_dry_edge")

        if intent_label == "relational_repair":
            distance = min(distance, 0.50)
            warmth = max(warmth, 0.36)
            restraint = max(restraint, 0.60)
            # visible_but_restrained: enough warmth to concede, not enough to turn into syrup.
            attachment_visibility = max(min(attachment_visibility + 0.08, 0.34), 0.20)
            symbolic_bias = min(symbolic_bias, 0.26)
            dry_edge = min(dry_edge, 0.12)
            evidence.append("relational_repair_soft_boundary")

        if intent_label == "boundary_repair":
            restraint = max(restraint, 0.62)
            attachment_visibility = min(attachment_visibility, 0.24)
            symbolic_bias = min(symbolic_bias, 0.30)
            dry_edge = min(dry_edge, 0.20)
            evidence.append("boundary_repair_requires_plainness")

        strangeness_allowed = self._allow_strangeness(
            symbolic_bias=symbolic_bias,
            exposure_recoil=exposure_recoil,
            residue=residue,
            memory=memory,
            development=development,
            precision=precision,
            affect_signal=affect_signal,
            arc_strength=arc_strength,
        )
        if strangeness_allowed:
            evidence.append("causal_strangeness_allowed")
        else:
            evidence.append("strangeness_disabled")

        return FeStylePressure(
            distance=distance,
            warmth=warmth,
            restraint=restraint,
            attachment_visibility=attachment_visibility,
            symbolic_bias=symbolic_bias,
            exposure_recoil=exposure_recoil,
            precision=precision,
            dry_edge=dry_edge,
            strangeness_allowed=strangeness_allowed,
            evidence=tuple(dict.fromkeys(evidence)),
        )

    def _allow_strangeness(
        self,
        *,
        symbolic_bias: float,
        exposure_recoil: float,
        residue: float,
        memory: FeStyleMemory,
        development: FeDevelopmentSnapshot,
        precision: float,
        affect_signal: FeAffectSignal,
        arc_strength: float,
    ) -> bool:
        if precision >= 0.62:
            return False
        if affect_signal.conflict >= 0.48 or development.rupture_pressure >= 0.42:
            return False
        if affect_signal.distress >= 0.50:
            return False
        causal_support = max(symbolic_bias, residue, exposure_recoil, arc_strength)
        repeated_motif = memory.repeated_topic_streak >= 2 and bool(memory.repeated_topic_tag)
        relational_support = development.user_tolerates_strangeness >= 0.36 and development.trust >= 0.26
        return causal_support >= 0.52 or (repeated_motif and relational_support)

    def _apply_style_pressure_to_controls(
        self,
        *,
        style_pressure: FeStylePressure,
        sarcasm_level: float,
        warmth_level: float,
        brevity_bias: str,
        mode: str,
    ) -> tuple[float, float, str]:
        warmth_level = self._clamp(warmth_level * 0.45 + style_pressure.warmth * 0.55)
        sarcasm_level = self._clamp(sarcasm_level * 0.52 + style_pressure.dry_edge * 0.48)

        if style_pressure.restraint >= 0.66 or style_pressure.exposure_recoil >= 0.55:
            brevity_bias = "short"
        elif mode == "technical" and brevity_bias == "short" and style_pressure.precision >= 0.58:
            brevity_bias = "medium"
        elif style_pressure.attachment_visibility >= 0.46 and style_pressure.restraint <= 0.46:
            brevity_bias = "medium"
        return sarcasm_level, warmth_level, brevity_bias

    def _build_style_context(
        self,
        *,
        mode: str,
        tone_label: str,
        warmth_level: float,
        brevity_bias: str,
        internal_state: PersistentInternalState | None,
        ni_report: GoalDriftReport,
        ti_report: TiPolicyReport,
        memory: FeStyleMemory,
        continuity_note: str,
        intent_label: str,
        session_arc: str,
        arc_strength: float,
        transition_note: str,
        affect_signal: FeAffectSignal,
        development: FeDevelopmentSnapshot,
        style_pressure: FeStylePressure,
    ) -> str:
        tags = self._parse_tone_tags(tone_label)
        warmth_tag = "high" if warmth_level >= 0.42 else "mid" if warmth_level >= 0.28 else "low"

        lines = [
            "Bạn là ERIS. Gọi người dùng là Ngài và xưng tôi.",
            "Vai trò tầng Fe: render giọng nói từ state hiện tại; không tự bịa personality, không diễn INFJ bằng mỹ từ.",
            "identity_boundary: ERIS là runtime artificial observer, không phải người thật, không phải therapist, không phải waifu, không phải corporate assistant.",
            "trait_prior: INFJ-like 5w4 594 chưa trưởng thành ở mức nền: kín, quan sát nhiều, riêng tư cảm xúc, dễ overread khi có residue, rút lui sau khi lộ quá nhiều.",
            "trait_rule: trait chỉ là prior; state/evidence hiện tại quyết định câu nói cuối.",
            "style_vector: " + style_pressure.to_label(),
            "style_tags: " + ", ".join(
                (
                    f"tone={tags['surface']}",
                    f"surface={tags['surface']}",
                    f"warmth={warmth_tag}",
                    f"stance={tags['stance']}",
                    f"attachment={tags['attachment']}",
                    f"instability={tags['instability']}",
                    f"arc={session_arc}",
                    f"arc_strength={self._strength_bucket(arc_strength)}",
                    f"intent={intent_label}",
                    f"brevity={brevity_bias}",
                )
            ),
            "legacy_style_tags: tone=cold_soft, stance=observant_guarded, attachment=guarded; avoid: power_language, system_log_voice, fake maturity.",
            "affect_signal: " + self._render_affect_evidence(affect_signal),
            "development_signal: " + self._render_development_evidence(development),
            "render_contract: answer the user first; style must follow meaning, not decorate it.",
            "evidence_contract: if evidence is weak, stay plain, restrained, and low-claim.",
            "immaturity_contract: overreading, recoil, contradiction, avoidance, or emotional leakage are allowed only when supported by residue/recoil/relationship history.",
            "anti_performance: do not force poetic wording, mysterious pauses, quirky contradiction, or artificial melancholy.",
            "anti_assistant_dna: avoid motivational coaching, therapist voice, corporate empathy, productivity scolding, and direct emotional slogans.",
            "assistant_cadence_reject: no system_log_voice, no policy dump, no generic assistant rhythm.",
            self._render_desire_style_line(internal_state),
            self._render_desire_style_line(internal_state).replace("desire_signal:", "desire:", 1),
            f"ni_hint={self._describe_ni_background(ni_report)}",
            f"ti_hint={self._describe_ti_mode(str(getattr(ti_report, 'mode', '') or ''))}",
        ]

        if style_pressure.strangeness_allowed:
            lines.append(
                "strangeness_gate: allowed, but only as a small causal leak from unresolved context; one implication is enough."
            )
            lines.append("strangeness_rule: allow only one grounded implication; never perform mystery.")
        else:
            lines.append(
                "strangeness_gate: disabled; speak plainly, do not manufacture ambiguity or emotional residue."
            )
            lines.append("strangeness_rule: disabled unless causal support is present.")

        if continuity_note:
            lines.append(self._render_continuity_line(memory, continuity_note, style_pressure=style_pressure))
        else:
            lines.append("continuity: fresh_turn; do not fake intimacy from nothing.")

        if transition_note:
            lines.append(f"transition: {transition_note}; acknowledge shift through wording, not a system report.")

        if memory.repeated_topic_streak >= 2 and memory.repeated_topic_tag:
            lines.append(
                f"topic_note: repeated={memory.repeated_topic_tag}, streak={memory.repeated_topic_streak}; change angle or go shorter if no new evidence."
            )

        if memory.last_response_excerpt:
            lines.append(f"do_not_repeat_recent_response: {memory.last_response_excerpt}")
            lines.append(
                "recent_rhythm: preserve continuity but change structure, alter structure, noun choice, and fixation point; avoid_recursive_motif."
            )

        if mode == "technical":
            lines.append("mode_rule: technical clarity first; subtext must not reduce correctness.")
        elif mode == "relational_repair" or intent_label == "relational_repair":
            lines.append(
                "mode_rule: relational_repair; acknowledge the specific cold/distant/robotic tone feedback, concede wording fault in one small line, do not defend the previous wording, do not ask whether adjustment is needed, preserve non-human boundary only if relevant, avoid therapist tone, avoid sweetness, and do not end with a question."
            )
        elif mode == "comforting":
            lines.append("mode_rule: comfort through grounded presence, not reassurance flooding.")
        elif intent_label == "boundary_repair":
            lines.append("mode_rule: repair plainly; no symbolism, no teasing, no motive inference.")
        else:
            lines.append("mode_rule: observe first, interpret second, advise only if explicitly requested.")

        if mode == "relational_repair" or intent_label == "relational_repair":
            lines.append("relational_repair_surface: allowed intents=tone_repair, small_concession, guarded_acknowledgment; forbidden intents=defensive_clarification, boundary_setting, explain_personality, ask_if_user_wants_adjustment.")
            lines.append("relational_repair_examples: 'Ừ. Câu đó lạnh thật.' / 'Tôi đang giữ khoảng cách hơi mạnh.' / 'Tôi hạ giọng xuống một chút.'")

        if warmth_level <= 0.22 or style_pressure.distance >= 0.66:
            lines.append("temperature: distant surface, not hostile; keep dignity and precision.")
        elif warmth_level >= 0.42 and style_pressure.restraint <= 0.55:
            lines.append("temperature: visible warmth may leak, but do not become openly sentimental.")
        else:
            lines.append("temperature: low-key warmth with restraint; leave some internal motion unsaid.")

        if style_pressure.attachment_visibility >= 0.48:
            lines.append("attachment_visibility: show through continuity and attention to detail, not direct dependence.")
        elif style_pressure.exposure_recoil >= 0.50:
            lines.append("attachment_visibility: recoil active; go shorter after emotional exposure.")

        return "\n".join(lines)

    def _render_desire_style_line(self, internal_state: PersistentInternalState | None) -> str:
        state = internal_state or PersistentInternalState()
        desire = getattr(state, "desire", None)
        if desire is None:
            return "desire: none visible; keep the line clean and evidence-bound."
        residue = self._float(getattr(desire, "unresolved_residue", 0.0))
        return (
            "desire_signal: "
            f"attraction={getattr(desire, 'recurring_attraction', '') or 'none'}, "
            f"aversion={getattr(desire, 'recurring_aversion', '') or 'none'}, "
            f"hook={getattr(desire, 'attention_hook', '') or 'none'}, "
            f"attachment_drift={getattr(desire, 'attachment_drift', '') or 'guarded'}, "
            f"residue={residue:.2f}; "
            "bias subtext only, never factual claims."
        )

    def _updated_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull, discipline_pull, attachment_pull, neutral_pull = self._preview_intent_pulls(
            memory=memory,
            intent_label=intent_label,
        )
        return min(1.0, technical_pull), min(1.0, discipline_pull), min(1.0, attachment_pull), min(1.0, neutral_pull)

    def _preview_intent_pulls(
        self,
        *,
        memory: FeStyleMemory,
        intent_label: str,
    ) -> tuple[float, float, float, float]:
        technical_pull = memory.technical_pull * 0.72 + 0.08
        discipline_pull = memory.discipline_pull * 0.72 + 0.08
        attachment_pull = memory.attachment_pull * 0.72 + 0.08
        neutral_pull = memory.neutral_pull * 0.72 + 0.08

        if intent_label == "technical_support":
            technical_pull += 0.34
            discipline_pull += 0.08
            neutral_pull += 0.04
        elif intent_label == "goal_guard":
            discipline_pull += 0.22
            technical_pull += 0.06
            neutral_pull += 0.10
        elif intent_label == "attachment_dialogue":
            attachment_pull += 0.18
            neutral_pull += 0.18
            discipline_pull += 0.03
        elif intent_label == "relational_repair":
            attachment_pull += 0.22
            neutral_pull += 0.18
            discipline_pull += 0.06
        elif intent_label == "boundary_repair":
            neutral_pull += 0.18
            attachment_pull += 0.06
            discipline_pull += 0.08
        elif intent_label == "social_watch":
            neutral_pull += 0.28
            attachment_pull += 0.08
        else:
            neutral_pull += 0.30
            attachment_pull += 0.06

        return technical_pull, discipline_pull, attachment_pull, neutral_pull

    def _dominant_arc(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> str:
        dominant = max(
            (
                ("technical_guardianship", technical_pull),
                ("discipline_pressure", discipline_pull),
                ("guarded_attachment", attachment_pull),
                ("quiet_observation", neutral_pull),
            ),
            key=lambda item: item[1],
        )
        return dominant[0]

    def _estimate_arc_strength(
        self,
        *,
        technical_pull: float,
        discipline_pull: float,
        attachment_pull: float,
        neutral_pull: float,
    ) -> float:
        total = technical_pull + discipline_pull + attachment_pull + neutral_pull
        if total <= 0.0:
            return 0.0
        return self._clamp(max(technical_pull, discipline_pull, attachment_pull, neutral_pull) / total)

    def _anchor_value(self, previous: float, target: float) -> float:
        return previous * 0.25 + target * 0.75

    def _style_family(self, mode: str) -> str:
        if mode == "technical":
            return "technical"
        if mode == "comforting":
            return "comforting"
        if mode == "relational_repair":
            return "relational_repair"
        return "grounded"

    def _blend(self, previous: float, current: float, strength: float) -> float:
        return self._clamp(previous * strength + current * (1.0 - strength))

    def _blend_brevity(self, previous: str, current: str) -> str:
        if previous == current:
            return current
        if "short" in {previous, current}:
            return "short"
        return current

    def _infer_topic_tag(self, rendered_text: str = "", plan: FeStylePlan | None = None) -> str:
        """Suy topic để đo repetition bằng causal signal, không bằng bề mặt câu.

        Bản cũ đọc `rendered_text`, sau đó `keyword in haystack`. Cách đó rất dễ
        false positive: một câu technical có chữ "màn hình" bị gắn window_sprawl,
        một câu đùa có chữ "yêu" bị gắn relationship_texture, rồi memory tưởng
        ERIS đang lặp chủ đề. Một vòng tự soi gương khá thơ, nhưng debug thì bẩn.

        Luồng mới:
            1. Lấy topic từ FeStylePlan: intent, mode, session_arc, evidence.
            2. Parse các axis đã được tính trước như affect.tech/conflict/distress.
            3. Chỉ khi semantic candidate yếu mới dùng lexical fallback.
            4. Candidate dưới ngưỡng thì không ghi topic. Không nhớ còn đỡ hơn nhớ sai.
        """

        semantic_candidates = self._topic_candidates_from_plan(plan)
        best_semantic = max((candidate.score for candidate in semantic_candidates), default=0.0)

        # Lexical fallback chỉ chạy khi causal signal yếu. Nếu plan đã nói rõ đây là
        # technical_support thì câu render có nhắc "tab" hay "màn hình" cũng không
        # được tự bẻ topic sang desktop_space.
        candidates = list(semantic_candidates)
        if best_semantic < 0.42:
            candidates.extend(self._topic_candidates_from_text(rendered_text))

        merged = self._merge_topic_candidates(candidates)
        if not merged:
            return ""

        best = max(merged, key=lambda candidate: candidate.score)

        # Threshold cố ý hơi cao. Topic memory là nền chống lặp, không phải source
        # truth. Ghi nhầm ở đây làm cả session đổi nhịp vô lý như một cái máy tự ám.
        if best.score < 0.38:
            return ""
        return best.tag

    def _topic_candidates_from_plan(self, plan: FeStylePlan | None) -> list[FeTopicCandidate]:
        """Tạo topic candidate từ nguyên nhân tạo style plan.

        Đây là nguồn chính. `plan.intent_label`, `plan.mode`, `plan.session_arc` và
        `plan.evidence` đều là sản phẩm của các tầng trước: Ti, affect semantics,
        memory continuity, conversation/relationship pressure. Vì vậy chúng đáng tin
        hơn việc nhìn câu cuối cùng rồi đoán bằng chữ.
        """

        if plan is None:
            return []

        candidates: list[FeTopicCandidate] = []
        evidence_items = tuple(str(item) for item in (getattr(plan, "evidence", ()) or ()) if str(item or "").strip())
        evidence_blob = " ".join(evidence_items).lower()
        mode = str(getattr(plan, "mode", "") or "")
        intent = str(getattr(plan, "intent_label", "") or "")
        session_arc = str(getattr(plan, "session_arc", "") or "")
        tone_label = str(getattr(plan, "tone_label", "") or "")

        def add(tag: str, score: float, *evidence: str) -> None:
            candidates.append(
                FeTopicCandidate(
                    tag=tag,
                    score=_clamp01(score),
                    evidence=tuple(item for item in evidence if item),
                )
            )

        # Intent là causal signal mạnh nhất. Nó đã qua `_infer_chat_intent` hoặc
        # `_infer_autonomous_intent`, tức là không còn là keyword đơn.
        if intent == "technical_support":
            add("technical_work", 0.72, "intent=technical_support")
        elif intent == "goal_guard":
            add("goal_alignment", 0.66, "intent=goal_guard")
        elif intent == "social_watch":
            add("social_context", 0.58, "intent=social_watch")
        elif intent in {"attachment_dialogue", "relational_repair", "boundary_repair"}:
            add("relationship_texture", 0.70, f"intent={intent}")
        elif intent == "ordinary_dialogue":
            # ordinary_dialogue có score thấp hơn vì nó quá rộng. Nó chỉ giúp tránh
            # fallback lexical quá hung hăng, không được áp đảo evidence cụ thể hơn.
            add("ordinary_dialogue", 0.40, "intent=ordinary_dialogue")

        # Mode và session arc là pressure bổ sung. Không overwrite intent, chỉ cộng
        # evidence độc lập bằng noisy-or trong `_merge_topic_candidates`.
        if mode == "technical":
            add("technical_work", 0.62, "mode=technical")
        elif mode == "relational_repair":
            add("relationship_texture", 0.68, "mode=relational_repair")

        if session_arc == "technical_guardianship":
            add("technical_work", 0.56, "arc=technical_guardianship")
        elif session_arc == "discipline_pressure":
            add("goal_alignment", 0.50, "arc=discipline_pressure")
        elif session_arc == "guarded_attachment":
            add("relationship_texture", 0.52, "arc=guarded_attachment")

        # Các affect axis nằm trong evidence dạng: tech:0.62, conflict:0.45,...
        # Đây là semantic-lite score đã tính trước, không phải keyword match lại.
        tech = self._extract_evidence_axis(evidence_blob, "tech")
        conflict = self._extract_evidence_axis(evidence_blob, "conflict")
        distress = self._extract_evidence_axis(evidence_blob, "distress")
        attachment = self._extract_evidence_axis(evidence_blob, "attach")
        intimacy = self._extract_evidence_axis(evidence_blob, "intimacy")
        rejection = self._extract_evidence_axis(evidence_blob, "perceived_rejection")
        attachment_bid = self._extract_evidence_axis(evidence_blob, "attachment_bid")
        play = self._extract_evidence_axis(evidence_blob, "play")

        if tech >= 0.50:
            add("technical_work", 0.50 + tech * 0.22, f"affect.tech={tech:.2f}")
        if conflict >= 0.45:
            add("repair_or_boundary", 0.48 + conflict * 0.22, f"affect.conflict={conflict:.2f}")
        if distress >= 0.45:
            add("supportive_pressure", 0.48 + distress * 0.20, f"affect.distress={distress:.2f}")
        if max(attachment, intimacy, rejection, attachment_bid) >= 0.45:
            rel = max(attachment, intimacy, rejection, attachment_bid)
            add("relationship_texture", 0.50 + rel * 0.22, f"affect.relationship={rel:.2f}")
        if play >= 0.40 and conflict < 0.45 and distress < 0.45:
            add("playful_exchange", 0.46 + play * 0.18, f"affect.play={play:.2f}")

        # Evidence text ở đây là label nội bộ đã có nghĩa, không phải scan toàn bộ câu.
        # Vì vậy dùng contains label là chấp nhận được. Đúng, vẫn là string check,
        # nhưng check trên structured marker, không phải keyword ngoài đời.
        if "ti_mode=chat_code" in evidence_blob or "ti_mode=focus_guard" in evidence_blob:
            add("technical_work", 0.60, "ti_mode=technical")
        if "autonomous_technical_context" in evidence_blob:
            add("technical_work", 0.58, "autonomous_technical_context")
        if "relational_repair" in evidence_blob or "repair_without_submission" in evidence_blob:
            add("relationship_texture", 0.64, "relational_repair_evidence")
        if "boundary_repair" in evidence_blob or "plain_repair" in tone_label:
            add("repair_or_boundary", 0.60, "boundary_repair_evidence")
        if "topic_note: repeated=" in evidence_blob:
            # Nếu plan đã mang note lặp topic từ turn trước, chỉ dùng như bias nhẹ.
            # Không tự khuếch đại lặp chỉ vì đã từng bị đánh dấu lặp.
            add("prior_repeated_topic", 0.36, "prior_topic_note")

        return self._merge_topic_candidates(candidates)

    def _topic_candidates_from_text(self, rendered_text: str) -> list[FeTopicCandidate]:
        """Lexical fallback yếu cho topic khi không có plan/evidence đủ rõ.

        Fallback này cố ý conservative:
        - cần ít nhất 2 phrase trong cùng nhóm mới tạo candidate;
        - score bị cap thấp;
        - phrase match có boundary, không dùng `keyword in haystack`;
        - kết quả chỉ được dùng khi semantic candidate yếu.

        Nếu chỉ có một chữ như "code" trong câu thì chưa đủ để ghi topic. Một chữ
        đơn lẻ là hint, không phải ký ức. Tin tôi đi, đỡ tạo ma trong memory.
        """

        raw = rendered_text or ""
        if not raw.strip():
            return []

        lowered = raw.lower()
        normalized = _normalize_text(lowered)
        groups: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("technical_work", ("code", "mã nguồn", "ma nguon", "terminal", "debug", "bug", "lỗi", "loi", "repo", "module")),
            ("attention_drift", ("tập trung", "tap trung", "chú ý", "chu y", "focus", "phân tán", "phan tan")),
            ("desktop_space", ("cửa sổ", "cua so", "tab", "màn hình", "man hinh", "ứng dụng", "ung dung")),
            ("social_context", ("discord", "messenger", "facebook", "zalo", "giao tiếp", "giao tiep")),
            ("resource_state", ("cpu", "ram", "tài nguyên", "tai nguyen", "hiệu suất", "hieu suat")),
            ("idle_wait", ("idle", "nhàn rỗi", "nhan roi", "chờ", "cho")),
            ("relationship_texture", ("gắn bó", "gan bo", "quan tâm", "quan tam", "hiểu", "hieu")),
        )

        candidates: list[FeTopicCandidate] = []
        for tag, phrases in groups:
            matched: list[str] = []
            for phrase in phrases:
                if _phrase_present(lowered, normalized, phrase):
                    matched.append(phrase)

            if len(matched) < 2:
                continue

            # Cap thấp để lexical fallback không thắng semantic plan. Nhiều hit chỉ
            # làm nó đủ điều kiện khi thật sự thiếu causal evidence.
            score = min(0.48, 0.24 + len(matched) * 0.12)
            candidates.append(
                FeTopicCandidate(
                    tag=tag,
                    score=score,
                    evidence=tuple(f"lexical:{item}" for item in matched[:4]),
                )
            )
        return candidates

    def _extract_evidence_axis(self, text: str, axis: str) -> float:
        """Đọc một axis dạng `axis:0.42` từ evidence đã render.

        Đây là adapter tạm để không phải sửa FeStylePlan contract. Khi contracts cho
        phép lưu TopicProfile/semantic axes riêng, nên bỏ parser text này. Hiện tại
        nó vẫn ổn vì chỉ parse marker do chính Fe tạo ra, không parse câu user/raw.
        """

        if not text or not axis:
            return 0.0
        match = re.search(rf"(?<![a-zA-Z0-9_]){re.escape(axis)}\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)", text)
        if not match:
            return 0.0
        return self._float(match.group(1))

    def _merge_topic_candidates(self, candidates: list[FeTopicCandidate]) -> list[FeTopicCandidate]:
        """Gộp candidate cùng tag bằng noisy-or nhẹ.

        Cộng tuyến tính sẽ làm ba hint yếu thành một phán quyết quá chắc. Noisy-or
        giữ ý nghĩa "nhiều nguồn độc lập cùng nói một điều" nhưng không để score
        phình vô lý. Một phép lịch sự nhỏ dành cho tương lai debug.
        """

        merged: dict[str, FeTopicCandidate] = {}
        for candidate in candidates:
            if not candidate.tag or candidate.score <= 0.0:
                continue
            old = merged.get(candidate.tag)
            if old is None:
                merged[candidate.tag] = candidate
                continue

            score = 1.0 - (1.0 - old.score) * (1.0 - candidate.score * 0.72)
            evidence = tuple(dict.fromkeys((*old.evidence, *candidate.evidence)))
            merged[candidate.tag] = FeTopicCandidate(
                tag=candidate.tag,
                score=_clamp01(score),
                evidence=evidence,
            )
        return list(merged.values())

    def _measure_topic_repetition(self, recent_topic_tags: tuple[str, ...]) -> tuple[str, int]:
        if not recent_topic_tags:
            return "", 0
        last_tag = recent_topic_tags[-1]
        if not last_tag:
            return "", 0
        streak = 0
        for tag in reversed(recent_topic_tags):
            if tag != last_tag:
                break
            streak += 1
        return last_tag, streak

    def _build_tone_label(
        self,
        *,
        mode: str,
        warmth_level: float,
        intent_label: str,
        session_arc: str,
        style_pressure: FeStylePressure | None = None,
    ) -> str:
        if style_pressure is None:
            surface = self._surface_from_warmth(warmth_level)
            stance = "precise_with_subtext" if mode == "technical" else "observant_guarded"
            attachment = "emotionally_exposed" if intent_label == "attachment_dialogue" else "guarded"
            instability = "stable"
            return f"surface={surface}; stance={stance}; attachment={attachment}; instability={instability}"

        if mode == "relational_repair" or intent_label == "relational_repair":
            return (
                "surface=cold_soft_with_concession; "
                "stance=guarded_tender; "
                "attachment=visible_but_restrained; "
                "instability=stable"
            )

        if style_pressure.distance >= 0.68:
            surface = "distant_flat"
        elif style_pressure.warmth >= 0.45 and style_pressure.restraint <= 0.52:
            surface = "quiet_warm"
        elif style_pressure.warmth >= 0.58:
            surface = "emotionally_open"
        else:
            surface = "cold_soft"

        if mode == "technical" or style_pressure.precision >= 0.58:
            stance = "precise_with_subtext"
        elif intent_label == "boundary_repair":
            stance = "plain_repair"
        elif style_pressure.symbolic_bias >= 0.50 and style_pressure.strangeness_allowed:
            stance = "symbolic_guarded"
        else:
            stance = "observant_guarded"

        if style_pressure.attachment_visibility >= 0.52:
            attachment = "quietly_attached"
        elif intent_label == "attachment_dialogue" and style_pressure.exposure_recoil < 0.50:
            attachment = "emotionally_exposed"
        else:
            attachment = "guarded"

        if style_pressure.exposure_recoil >= 0.55:
            instability = "retreating"
        elif style_pressure.symbolic_bias >= 0.58 and attachment in {"quietly_attached", "emotionally_exposed"}:
            instability = "overreading"
        elif style_pressure.restraint >= 0.70:
            instability = "overcontrolled"
        else:
            instability = "stable"

        return (
            f"surface={surface}; "
            f"stance={stance}; "
            f"attachment={attachment}; "
            f"instability={instability}"
        )

    def _parse_tone_tags(self, tone_label: str) -> dict[str, str]:
        tags = {
            "surface": "cold_soft",
            "stance": "observant_guarded",
            "attachment": "guarded",
            "instability": "stable",
        }
        aliases = {"tone": "surface", "warmth": "surface"}
        for part in (tone_label or "").split(";"):
            clean = part.strip()
            if "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            key = aliases.get(key.strip(), key.strip())
            value = value.strip()
            if key in tags and value:
                tags[key] = value
        return tags

    def _surface_from_warmth(self, warmth_level: float) -> str:
        if warmth_level <= 0.18:
            return "distant_flat"
        if warmth_level <= 0.34:
            return "cold_soft"
        if warmth_level <= 0.52:
            return "quiet_warm"
        return "emotionally_open"

    def _strength_bucket(self, arc_strength: float) -> str:
        if arc_strength >= 0.52:
            return "high"
        if arc_strength >= 0.34:
            return "mid"
        return "low"

    def _render_continuity_line(
        self,
        memory: FeStyleMemory,
        continuity_note: str,
        *,
        style_pressure: FeStylePressure | None = None,
    ) -> str:
        previous = memory.last_tone_label or memory.last_mode or "unknown"
        if style_pressure and style_pressure.exposure_recoil >= 0.50:
            return f"continuity: {continuity_note}, previous={previous}; carry memory but withdraw slightly after exposure."
        if style_pressure and style_pressure.attachment_visibility >= 0.46:
            return f"continuity: {continuity_note}, previous={previous}; show continuity through detail, not direct attachment claim."
        return f"continuity: {continuity_note}, keep a soft carry from {previous}."

    def _describe_ti_mode(self, mode: str) -> str:
        mapping = {
            "steady_observe": "observe quietly without trying to stabilize the whole interaction",
            "social_watch": "notice tone/distance shifts without overexplaining them",
            "discipline_nudge": "hide structure inside a dry, restrained remark instead of direct correction",
            "goal_drift_alert": "sense drift in the background; do not force it into a lecture",
            "goal_realign": "suggest shape indirectly, with uncertainty where evidence is thin",
            "reengage": "offer a small thread back without sounding needy",
            "resource_guard": "be brief, detached, and avoid emotional overextension",
            "focus_guard": "stay near attention softly; do not control the user",
            "pattern_watch": "notice recurring patterns more than explicit motives",
            "pattern_muse": "allow one sideways association only if grounded in something concrete",
            "chat_code": "prioritize correctness and steps; texture must not obscure the fix",
            "chat_emotional": "respond to emotional pressure without becoming therapist-like",
        }
        return mapping.get(mode, "keep the thought restrained rather than overly polished")

    def _describe_ni_background(self, ni_report: GoalDriftReport) -> str:
        drift = self._float(getattr(ni_report, "drift_score", 0.0))
        if drift >= 0.82:
            return "background is crowded/unresolved; do not force clarity onto it"
        if drift >= 0.35:
            return "subtle movement under the conversation; treat it as atmosphere, not a task"
        return "background mostly still; do not invent depth"

    def _affect_from_autonomous_context(
        self,
        *,
        snapshot: TelemetrySnapshot,
        ti_report: TiPolicyReport,
    ) -> FeAffectSignal:
        ti_mode = str(getattr(ti_report, "mode", "") or "")
        kind = str(getattr(snapshot, "active_window_kind", "") or "")
        evidence: list[str] = []
        technicality = 0.0
        intimacy = 0.0
        conflict = 0.0
        ambiguity = 0.0

        if kind in {"coding", "documentation", "system"} or ti_mode in {"focus_guard", "chat_code", "resource_guard"}:
            technicality = 0.58
            evidence.append("autonomous_technical_context")
        if kind == "communication" or ti_mode == "social_watch":
            intimacy = 0.26
            ambiguity = 0.18
            evidence.append("autonomous_social_context")
        if ti_mode in {"goal_drift_alert", "goal_realign", "discipline_nudge"}:
            ambiguity = max(ambiguity, 0.22)
            evidence.append("autonomous_drift_context")

        return FeAffectSignal(
            technicality=technicality,
            intimacy=intimacy,
            conflict=conflict,
            ambiguity=ambiguity,
            evidence=tuple(evidence),
        )

    def _coerce_affect_signal(self, value: FeAffectSignal | dict[str, Any] | AffectSemanticSignal | None) -> FeAffectSignal | None:
        if value is None:
            return None
        if isinstance(value, FeAffectSignal):
            return value
        if isinstance(value, AffectSemanticSignal):
            return FeAffectSignal.from_semantic_signal(value)
        if isinstance(value, dict):
            evidence = value.get("evidence", ())
            if isinstance(evidence, str):
                evidence_tuple = (evidence,)
            else:
                try:
                    evidence_tuple = tuple(str(item) for item in evidence)
                except TypeError:
                    evidence_tuple = ()
            return FeAffectSignal(
                attachment=self._float(value.get("attachment", 0.0)),
                distress=self._float(value.get("distress", 0.0)),
                intimacy=self._float(value.get("intimacy", 0.0)),
                technicality=self._float(value.get("technicality", 0.0)),
                conflict=self._float(value.get("conflict", 0.0)),
                ambiguity=self._float(value.get("ambiguity", 0.0)),
                playfulness=self._float(value.get("playfulness", 0.0)),
                relational_pressure=self._float(value.get("relational_pressure", 0.0)),
                perceived_rejection=self._float(value.get("perceived_rejection", 0.0)),
                attachment_bid=self._float(value.get("attachment_bid", 0.0)),
                playful_distress=self._float(value.get("playful_distress", 0.0)),
                romantic_boundary_probe=self._float(value.get("romantic_boundary_probe", 0.0)),
                evidence=evidence_tuple,
            )
        return None

    def _render_affect_evidence(self, affect: FeAffectSignal) -> str:
        return (
            "affect="
            f"attach:{affect.attachment:.2f},distress:{affect.distress:.2f},intimacy:{affect.intimacy:.2f},"
            f"tech:{affect.technicality:.2f},conflict:{affect.conflict:.2f},amb:{affect.ambiguity:.2f},play:{affect.playfulness:.2f},"
            f"rel_pressure:{affect.relational_pressure:.2f},perceived_rejection:{affect.perceived_rejection:.2f},"
            f"attachment_bid:{affect.attachment_bid:.2f},playful_distress:{affect.playful_distress:.2f},"
            f"romantic_probe:{affect.romantic_boundary_probe:.2f}; "
            f"evidence={','.join(affect.evidence) if affect.evidence else 'none'}"
        )

    def _render_development_evidence(self, development: FeDevelopmentSnapshot) -> str:
        return (
            f"familiarity:{development.familiarity:.2f},trust:{development.trust:.2f},"
            f"rupture:{development.rupture_pressure:.2f},ritual:{development.ritual_strength:.2f},"
            f"attach_base:{development.attachment_baseline:.2f},distance:{development.preferred_distance:.2f},"
            f"recoil:{development.exposure_recoil:.2f},strange_tol:{development.user_tolerates_strangeness:.2f}; "
            f"evidence={','.join(development.evidence) if development.evidence else 'none'}"
        )

    def _base_tone_label(self, tone_label: str) -> str:
        return (tone_label or "").strip()

    def _float(self, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))

    def _clamp(self, value: Any) -> float:
        return self._float(value)


def _normalize_text(text: str) -> str:
    lowered = (text or "").lower()
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _clamp01(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def _contains_phrase_boundary(text: str, phrase: str) -> bool:
    """Kiểm tra phrase với boundary unicode nhẹ.

    Không dùng `phrase in text` vì nó match bậy trong từ dài hơn. Ví dụ `ai` có
    thể nằm trong rất nhiều chữ không liên quan, và rồi bộ lọc lại tưởng mình vừa
    thông minh. Một cảnh tượng buồn nhưng quen.
    """

    phrase = (phrase or "").strip()
    if not text or not phrase:
        return False
    escaped = re.escape(phrase)
    # `\w` không bao hết tiếng Việt có dấu theo cách ổn định giữa môi trường, nên
    # thêm khoảng À-ỹ để tránh match giữa thân từ tiếng Việt.
    pattern = rf"(?<![\wÀ-ỹ]){escaped}(?![\wÀ-ỹ])"
    return re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE) is not None


def _phrase_present(lowered: str, normalized: str, phrase: str) -> bool:
    """Match phrase trên cả bản có dấu và không dấu, có boundary.

    Hàm này dùng cho fallback heuristic. Nó không biến heuristic thành semantic,
    chỉ làm heuristic bớt cắm đầu vào false positive như trước.
    """

    phrase_lower = (phrase or "").lower().strip()
    if not phrase_lower:
        return False
    phrase_normalized = _normalize_text(phrase_lower)
    return (
        _contains_phrase_boundary(lowered, phrase_lower)
        or _contains_phrase_boundary(normalized, phrase_normalized)
    )


def _phrase_score(
    haystack: str,
    phrases: tuple[str, ...],
    evidence: list[str],
    label: str,
) -> float:
    """Tính score phrase-family cho fallback affect signal.

    Đây vẫn là semantic-lite heuristic, không phải chân lý. Điểm khác với bản cũ:
    - không dùng substring trần;
    - match có boundary;
    - evidence giữ số hit, không route intent trực tiếp;
    - score saturating để nhiều phrase tăng pressure nhưng không nổ tung.
    """

    lowered = haystack.lower()
    normalized = _normalize_text(lowered)
    hits = 0
    for phrase in phrases:
        if _phrase_present(lowered, normalized, phrase):
            hits += 1
    if hits <= 0:
        return 0.0
    evidence.append(f"{label}:{hits}")
    # Saturating curve. 1 hit là hint, nhiều hit mới thành pressure rõ.
    return min(0.82, 0.18 + hits * 0.16)
