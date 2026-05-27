from __future__ import annotations

"""
orientation_semantics.py
========================

Tầng hybrid semantic cho Orientation/Ni/GoalPersistence.

Vì sao file này tồn tại?
------------------------
`orientation_context.py` hiện làm tốt phần lexical-semantic nhẹ:
- normalize tiếng Việt không dấu
- bắt file/module/code anchor
- bắt closure có negation
- tách task/casual/recovery bằng phrase groups
- tính goal relation/intervention pressure mềm

Nhưng nó vẫn là heuristic lexical. File này thêm một tầng semantic thật hơn:
    lexical anchors + semantic prototype hypotheses + goal context + temporal context

Quy tắc thiết kế
----------------
1. Lexical giữ quyền veto cho thứ chính xác:
   negation, closure, filename, explicit error, task verb, pasted code anchor.
2. Semantic chỉ sinh top-k hypothesis, không tự phán quyết.
3. Permission/intervention vẫn dựa vào active goal strength + intervention_permission.
4. Nếu semantic mơ hồ, hạ confidence, không bơm drift.
5. Nếu chỉ có hashing fallback, cap confidence để ERIS không thành nhà tiên tri
   làm từ token. Một viễn cảnh rất công nghệ và rất đáng sợ.

Cách nối vào Ni
---------------
Thay vì gọi trực tiếp:
    OrientationInterpreter().estimate_orientation(probe)

Có thể gọi:
    HybridOrientationInterpreter(semantic_engine=engine).estimate_orientation(probe)

Nếu không có semantic_engine hoặc encoder không sẵn sàng, nó tự fallback về
OrientationInterpreter hiện tại.
"""

from dataclasses import dataclass, field
from typing import Mapping, Sequence

try:
    from .orientation_context import (
        ActivityIntent,
        ActivityIntentLabel,
        GoalRelation,
        GoalRelationLabel,
        OrientationInterpreter,
        OrientationSignal,
        SemanticContextProbe,
        TECHNICAL_TERMS,
        LEARNING_TERMS,
        MEDIA_TERMS,
        SHORT_FORM_TERMS,
        PLAY_TERMS,
        COMMUNICATION_TERMS,
        RECOVERY_TERMS,
        AVOIDANCE_TERMS,
        SYSTEM_WAIT_TERMS,
        DESIGN_TERMS,
        FILE_OR_MODULE_RE,
        clamp,
        clamp01,
        extract_anchors,
        has_any,
        normalize,
    )
    from .semantic_hypothesis import SemanticHypothesisReport, SemanticHypothesisEngine
    from .semantic_prototypes import DOMAIN_ACTIVITY_INTENT, DOMAIN_GOAL_RELATION
except ImportError:  # Cho phép chạy lẻ khi copy file ra ngoài package.
    from orientation_context import (  # type: ignore
        ActivityIntent,
        ActivityIntentLabel,
        GoalRelation,
        GoalRelationLabel,
        OrientationInterpreter,
        OrientationSignal,
        SemanticContextProbe,
        TECHNICAL_TERMS,
        LEARNING_TERMS,
        MEDIA_TERMS,
        SHORT_FORM_TERMS,
        PLAY_TERMS,
        COMMUNICATION_TERMS,
        RECOVERY_TERMS,
        AVOIDANCE_TERMS,
        SYSTEM_WAIT_TERMS,
        DESIGN_TERMS,
        FILE_OR_MODULE_RE,
        clamp,
        clamp01,
        extract_anchors,
        has_any,
        normalize,
    )
    from semantic_hypothesis import SemanticHypothesisReport, SemanticHypothesisEngine  # type: ignore
    from semantic_prototypes import DOMAIN_ACTIVITY_INTENT, DOMAIN_GOAL_RELATION  # type: ignore


@dataclass(frozen=True, slots=True)
class HybridOrientationConfig:
    """Tham số điều phối lexical + semantic.

    semantic_weight:
        Mức semantic được quyền kéo label khi đủ chắc.
    lexical_weight:
        Mức lexical baseline được giữ lại.
    semantic_takeover_confidence:
        Semantic chỉ được thắng lexical nếu confidence vượt ngưỡng này và
        ambiguity thấp.
    ambiguity_block:
        Nếu ambiguity cao hơn ngưỡng này, semantic chỉ thêm evidence, không
        đổi label.
    fallback_semantic_cap:
        Cap confidence khi semantic engine dùng fallback vector.
    """

    semantic_weight: float = 0.46
    lexical_weight: float = 0.54
    semantic_takeover_confidence: float = 0.62
    ambiguity_block: float = 0.56
    fallback_semantic_cap: float = 0.55
    min_active_goal_for_conflict: float = 0.35
    min_intervention_for_conflict: float = 0.35
    max_unknown_confidence: float = 0.42


@dataclass(frozen=True, slots=True)
class LexicalVetoReport:
    """Các neo/veto lexical mà semantic không được lấn qua."""

    technical_anchor: bool = False
    file_anchor: bool = False
    learning_anchor: bool = False
    media_anchor: bool = False
    short_form_anchor: bool = False
    recovery_anchor: bool = False
    explicit_avoidance_anchor: bool = False
    system_wait_anchor: bool = False
    communication_anchor: bool = False
    design_anchor: bool = False
    evidence: tuple[str, ...] = ()

    @property
    def hard_work_anchor(self) -> bool:
        return self.technical_anchor or self.file_anchor or self.design_anchor

    @property
    def research_media_anchor(self) -> bool:
        return self.media_anchor and (self.learning_anchor or self.technical_anchor or self.design_anchor)


@dataclass(frozen=True, slots=True)
class HybridOrientationDebug:
    """Debug bundle để log/audit khi cần."""

    lexical_intent: str
    lexical_relation: str
    semantic_intent: str = ""
    semantic_relation: str = ""
    semantic_intent_confidence: float = 0.0
    semantic_relation_confidence: float = 0.0
    semantic_ambiguity: float = 1.0
    relation_ambiguity: float = 1.0
    blend_reason: str = ""
    veto_evidence: tuple[str, ...] = ()


class HybridOrientationInterpreter:
    """Orientation interpreter dùng lexical hiện tại + semantic hypothesis.

    Đây là adapter để nâng cấp dần. Nếu semantic chưa sẵn sàng, nó trả đúng
    output của `OrientationInterpreter` cũ và chỉ thêm channel báo fallback.
    """

    def __init__(
        self,
        *,
        semantic_engine: SemanticHypothesisEngine | None = None,
        lexical_interpreter: OrientationInterpreter | None = None,
        config: HybridOrientationConfig | None = None,
    ) -> None:
        self.semantic_engine = semantic_engine
        self.lexical = lexical_interpreter or OrientationInterpreter()
        self.config = config or HybridOrientationConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_orientation(self, probe: SemanticContextProbe) -> OrientationSignal:
        """Ước lượng orientation bằng hybrid lexical + semantic.

        Output vẫn là `OrientationSignal` để Ni hiện tại có thể dùng mà không
        phải đổi contract ngay. Thêm thông tin semantic nằm trong `channels`
        và `evidence`.
        """

        lexical_signal = self.lexical.estimate_orientation(probe)
        if self.semantic_engine is None:
            return self._with_fallback_channels(lexical_signal, reason="semantic_engine_missing")

        context_text = self._semantic_context_text(probe)
        anchors = extract_anchors(context_text)
        veto = self._lexical_veto(context_text)

        intent_report = self.semantic_engine.compare(DOMAIN_ACTIVITY_INTENT, context_text, anchors=anchors)
        relation_text = self._relation_context_text(probe, context_text)
        relation_report = self.semantic_engine.compare(DOMAIN_GOAL_RELATION, relation_text, anchors=anchors)

        # Nếu semantic thực sự không có tín hiệu, giữ lexical. Không có gì đáng
        # xấu hổ ở đây; đáng xấu hổ là đoán bừa rồi log confidence 0.91.
        if not intent_report.dominant:
            return self._with_semantic_channels(
                lexical_signal,
                intent_report=intent_report,
                relation_report=relation_report,
                debug=HybridOrientationDebug(
                    lexical_intent=lexical_signal.intent.label,
                    lexical_relation=lexical_signal.relation.label,
                    blend_reason="semantic_no_dominant_intent",
                    veto_evidence=veto.evidence,
                ),
            )

        blended_intent = self._blend_intent(lexical_signal.intent, intent_report, veto, probe)
        blended_relation = self._blend_relation(lexical_signal.relation, relation_report, blended_intent, veto, probe)

        coherence = self._estimate_coherence(
            intent=blended_intent,
            relation=blended_relation,
            lexical_signal=lexical_signal,
            intent_report=intent_report,
            relation_report=relation_report,
            probe=probe,
        )
        conflict = self._estimate_conflict(
            intent=blended_intent,
            relation=blended_relation,
            lexical_signal=lexical_signal,
            intent_report=intent_report,
            relation_report=relation_report,
            probe=probe,
            veto=veto,
        )
        intervention = self._estimate_intervention_pressure(
            relation=blended_relation,
            conflict=conflict,
            lexical_signal=lexical_signal,
            intent_report=intent_report,
            relation_report=relation_report,
            probe=probe,
        )
        confidence = self._estimate_confidence(
            blended_intent=blended_intent,
            blended_relation=blended_relation,
            lexical_signal=lexical_signal,
            intent_report=intent_report,
            relation_report=relation_report,
            veto=veto,
        )

        reason = (
            f"hybrid:{probe.focus_kind}:intent={blended_intent.label}:relation={blended_relation.label}:"
            f"coh={coherence:.2f}:conflict={conflict:.2f}:intervene={intervention:.2f}"
        )

        debug = HybridOrientationDebug(
            lexical_intent=lexical_signal.intent.label,
            lexical_relation=lexical_signal.relation.label,
            semantic_intent=intent_report.dominant.label if intent_report.dominant else "",
            semantic_relation=relation_report.dominant.label if relation_report.dominant else "",
            semantic_intent_confidence=intent_report.confidence,
            semantic_relation_confidence=relation_report.confidence,
            semantic_ambiguity=intent_report.ambiguity,
            relation_ambiguity=relation_report.ambiguity,
            blend_reason=self._blend_reason(lexical_signal.intent, blended_intent, intent_report, veto),
            veto_evidence=veto.evidence,
        )

        evidence = list(lexical_signal.evidence)
        evidence.extend(veto.evidence)
        evidence.extend(f"semantic_intent:{item}" for item in intent_report.evidence)
        evidence.extend(f"semantic_relation:{item}" for item in relation_report.evidence)
        evidence.extend(
            (
                f"hybrid_intent={blended_intent.label}:{blended_intent.confidence:.2f}",
                f"hybrid_relation={blended_relation.label}:{blended_relation.confidence:.2f}",
                f"hybrid_coherence={coherence:.2f}",
                f"hybrid_conflict={conflict:.2f}",
                f"hybrid_intervention={intervention:.2f}",
                f"hybrid_confidence={confidence:.2f}",
                f"blend_reason={debug.blend_reason}",
            )
        )

        channels = dict(lexical_signal.channels or {})
        channels.update(
            {
                "semantic_available": 1.0 if intent_report.semantic_available else 0.0,
                "semantic_fallback_used": 1.0 if intent_report.fallback_used else 0.0,
                "semantic_intent_confidence": intent_report.confidence,
                "semantic_intent_ambiguity": intent_report.ambiguity,
                "semantic_relation_confidence": relation_report.confidence,
                "semantic_relation_ambiguity": relation_report.ambiguity,
                "hybrid_confidence": confidence,
                "hybrid_coherence": coherence,
                "hybrid_conflict": conflict,
                "hybrid_intervention": intervention,
                "lexical_intent_confidence": lexical_signal.intent.confidence,
                "lexical_relation_confidence": lexical_signal.relation.confidence,
            }
        )

        return OrientationSignal(
            intent=blended_intent,
            relation=blended_relation,
            orientation_coherence=coherence,
            goal_conflict_score=conflict,
            intervention_pressure=intervention,
            confidence=confidence,
            reason_span=reason,
            evidence=tuple(evidence),
            channels=channels,
        )

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------

    def _semantic_context_text(self, probe: SemanticContextProbe) -> str:
        """Dựng text semantic gọn từ probe.

        Không nhét raw world vô hạn. Semantic cần context đủ nghĩa, không cần
        cả nghĩa trang telemetry.
        """

        parts = [
            f"focus kind: {probe.focus_kind}",
            f"focus: {probe.focus_text}",
            f"window: {probe.window_text}",
            f"browser: {probe.browsing_text}",
            f"current user text: {probe.current_text}",
        ]
        if probe.active_goal_summary:
            parts.append(f"active goal: {probe.active_goal_summary}")
        if probe.memory_text:
            # Memory chỉ đưa gist ngắn. Nó không phải evidence hiện tại.
            parts.append(f"memory context gist: {probe.memory_text[:220]}")
        parts.append(f"idle seconds: {float(probe.idle_seconds or 0.0):.0f}")
        parts.append(f"open windows: {int(probe.open_window_count or 0)}")
        return "\n".join(part for part in parts if part and not part.endswith(": "))

    def _relation_context_text(self, probe: SemanticContextProbe, context_text: str) -> str:
        return "\n".join(
            part
            for part in (
                context_text,
                f"active goal strength: {probe.active_goal_strength:.2f}",
                f"active goal intervention permission: {probe.active_goal_intervention_permission:.2f}",
                f"active goal type: {probe.active_goal_type}",
                "Decide whether current activity supports, is adjacent to, is neutral to, or conflicts with the active goal.",
            )
            if part
        )

    def _lexical_veto(self, text: str) -> LexicalVetoReport:
        norm = normalize(text)
        evidence: list[str] = []

        file_anchor = bool(FILE_OR_MODULE_RE.search(str(text or "")))
        technical = has_any(norm, TECHNICAL_TERMS)
        learning = has_any(norm, LEARNING_TERMS)
        media = has_any(norm, MEDIA_TERMS)
        short_form = has_any(norm, SHORT_FORM_TERMS)
        recovery = has_any(norm, RECOVERY_TERMS)
        explicit_avoidance = has_any(norm, AVOIDANCE_TERMS)
        system_wait = has_any(norm, SYSTEM_WAIT_TERMS)
        communication = has_any(norm, COMMUNICATION_TERMS)
        design = has_any(norm, DESIGN_TERMS)

        if file_anchor:
            evidence.append("lexical:file_or_module_anchor")
        if technical:
            evidence.append("lexical:technical_anchor")
        if learning:
            evidence.append("lexical:learning_anchor")
        if media:
            evidence.append("lexical:media_anchor")
        if short_form:
            evidence.append("lexical:short_form_anchor")
        if recovery:
            evidence.append("lexical:recovery_anchor")
        if explicit_avoidance:
            evidence.append("lexical:explicit_avoidance_anchor")
        if system_wait:
            evidence.append("lexical:system_wait_anchor")
        if communication:
            evidence.append("lexical:communication_anchor")
        if design:
            evidence.append("lexical:design_anchor")

        return LexicalVetoReport(
            technical_anchor=technical,
            file_anchor=file_anchor,
            learning_anchor=learning,
            media_anchor=media,
            short_form_anchor=short_form,
            recovery_anchor=recovery,
            explicit_avoidance_anchor=explicit_avoidance,
            system_wait_anchor=system_wait,
            communication_anchor=communication,
            design_anchor=design,
            evidence=tuple(evidence),
        )

    # ------------------------------------------------------------------
    # Blend intent / relation
    # ------------------------------------------------------------------

    def _blend_intent(
        self,
        lexical_intent: ActivityIntent,
        semantic_report: SemanticHypothesisReport,
        veto: LexicalVetoReport,
        probe: SemanticContextProbe,
    ) -> ActivityIntent:
        dominant = semantic_report.dominant
        if dominant is None:
            return lexical_intent

        semantic_label = dominant.label
        semantic_conf = semantic_report.confidence
        semantic_usable = semantic_conf >= self.config.semantic_takeover_confidence and semantic_report.ambiguity <= self.config.ambiguity_block

        # Hard lexical cases: explicit avoidance nên giữ, nhưng vẫn cần goal permission
        # ở tầng conflict/intervention. Không cho semantic "research" tẩy trắng câu
        # user tự nói đang né việc. Con người đã đủ giỏi tự lừa mình rồi.
        if veto.explicit_avoidance_anchor:
            return ActivityIntent(
                ActivityIntentLabel.POSSIBLE_AVOIDANCE.value,
                max(lexical_intent.confidence, min(0.78, semantic_conf + 0.08)),
                tuple(lexical_intent.evidence) + ("hybrid:explicit_avoidance_veto",),
            )

        # Media + learning/code/design là research, kể cả lexical cũ hơi phân vân.
        if veto.research_media_anchor:
            confidence = max(lexical_intent.confidence, semantic_conf, 0.68)
            return ActivityIntent(
                ActivityIntentLabel.RESEARCH.value,
                clamp01(confidence),
                tuple(lexical_intent.evidence) + ("hybrid:media_learning_research_veto",),
            )

        # File/code/design anchor đủ mạnh thì không để semantic kéo sang play/recovery.
        if veto.hard_work_anchor and semantic_label in {"play_or_recovery", "recovery", "possible_avoidance"}:
            if lexical_intent.label in {ActivityIntentLabel.TECHNICAL_FOCUS.value, ActivityIntentLabel.RESEARCH.value}:
                return ActivityIntent(
                    lexical_intent.label,
                    max(lexical_intent.confidence, 0.62),
                    tuple(lexical_intent.evidence) + ("hybrid:hard_work_anchor_blocks_semantic_leisure",),
                )

        # System wait là trạng thái hợp lệ: build/install/loading không phải lười.
        if veto.system_wait_anchor and lexical_intent.label == ActivityIntentLabel.SYSTEM_WAITING.value:
            return ActivityIntent(
                lexical_intent.label,
                max(lexical_intent.confidence, semantic_conf, 0.62),
                tuple(lexical_intent.evidence) + ("hybrid:system_wait_veto",),
            )

        # Nếu semantic mơ hồ hoặc yếu, giữ lexical.
        if not semantic_usable:
            return ActivityIntent(
                lexical_intent.label,
                self._blend_confidence(lexical_intent.confidence, semantic_conf, semantic_report.ambiguity, favor_lexical=True),
                tuple(lexical_intent.evidence) + (f"hybrid:semantic_not_strong_enough:{semantic_label}",),
            )

        # Nếu semantic và lexical cùng hướng, tăng confidence vừa phải.
        if semantic_label == lexical_intent.label:
            return ActivityIntent(
                lexical_intent.label,
                self._blend_confidence(lexical_intent.confidence, semantic_conf, semantic_report.ambiguity),
                tuple(lexical_intent.evidence) + (f"hybrid:semantic_confirms:{semantic_label}",),
            )

        # Semantic được đổi label khi đủ chắc và không đụng veto.
        return ActivityIntent(
            semantic_label,
            self._blend_confidence(lexical_intent.confidence, semantic_conf, semantic_report.ambiguity, favor_semantic=True),
            tuple(lexical_intent.evidence) + (f"hybrid:semantic_relabels:{lexical_intent.label}->{semantic_label}",),
        )

    def _blend_relation(
        self,
        lexical_relation: GoalRelation,
        semantic_report: SemanticHypothesisReport,
        blended_intent: ActivityIntent,
        veto: LexicalVetoReport,
        probe: SemanticContextProbe,
    ) -> GoalRelation:
        dominant = semantic_report.dominant
        if dominant is None:
            return lexical_relation

        semantic_label = dominant.label
        semantic_conf = semantic_report.confidence
        active_goal_strength = clamp01(probe.active_goal_strength)
        intervention_perm = clamp01(probe.active_goal_intervention_permission)

        # Conflict bị gate rất chặt. Không có active goal và permission thì semantic
        # không được la "xung đột" chỉ vì thấy entertainment. Rất tiếc cho cảnh sát.
        if semantic_label == GoalRelationLabel.CONFLICTING.value:
            if active_goal_strength < self.config.min_active_goal_for_conflict or intervention_perm < self.config.min_intervention_for_conflict:
                return GoalRelation(
                    GoalRelationLabel.NEUTRAL.value if lexical_relation.label == GoalRelationLabel.UNKNOWN.value else lexical_relation.label,
                    min(max(lexical_relation.confidence, 0.42), 0.56),
                    tuple(lexical_relation.evidence) + ("hybrid:conflict_blocked_by_goal_permission",),
                )

        # Technical/research intent thường aligned/adjacent với technical goal.
        if blended_intent.label in {ActivityIntentLabel.TECHNICAL_FOCUS.value, ActivityIntentLabel.RESEARCH.value, ActivityIntentLabel.SYSTEM_WAITING.value}:
            if active_goal_strength >= 0.25 and semantic_label in {GoalRelationLabel.CONFLICTING.value, GoalRelationLabel.UNKNOWN.value}:
                return GoalRelation(
                    GoalRelationLabel.ALIGNED.value,
                    max(lexical_relation.confidence, 0.58),
                    tuple(lexical_relation.evidence) + ("hybrid:work_intent_blocks_conflict_relation",),
                )

        semantic_usable = semantic_conf >= self.config.semantic_takeover_confidence and semantic_report.ambiguity <= self.config.ambiguity_block
        if not semantic_usable:
            return GoalRelation(
                lexical_relation.label,
                self._blend_confidence(lexical_relation.confidence, semantic_conf, semantic_report.ambiguity, favor_lexical=True),
                tuple(lexical_relation.evidence) + (f"hybrid:semantic_relation_not_strong:{semantic_label}",),
            )

        if semantic_label == lexical_relation.label:
            return GoalRelation(
                lexical_relation.label,
                self._blend_confidence(lexical_relation.confidence, semantic_conf, semantic_report.ambiguity),
                tuple(lexical_relation.evidence) + (f"hybrid:semantic_relation_confirms:{semantic_label}",),
            )

        return GoalRelation(
            semantic_label,
            self._blend_confidence(lexical_relation.confidence, semantic_conf, semantic_report.ambiguity, favor_semantic=True),
            tuple(lexical_relation.evidence) + (f"hybrid:semantic_relation_relabels:{lexical_relation.label}->{semantic_label}",),
        )

    def _blend_confidence(
        self,
        lexical_conf: float,
        semantic_conf: float,
        ambiguity: float,
        *,
        favor_lexical: bool = False,
        favor_semantic: bool = False,
    ) -> float:
        lexical_weight = self.config.lexical_weight + (0.16 if favor_lexical else 0.0) - (0.10 if favor_semantic else 0.0)
        semantic_weight = self.config.semantic_weight + (0.16 if favor_semantic else 0.0) - (0.10 if favor_lexical else 0.0)
        lexical_weight = max(0.05, lexical_weight)
        semantic_weight = max(0.05, semantic_weight)
        total = lexical_weight + semantic_weight
        blended = (clamp01(lexical_conf) * lexical_weight + clamp01(semantic_conf) * semantic_weight) / total
        blended *= 1.0 - 0.32 * clamp01(ambiguity)
        return clamp01(blended)

    # ------------------------------------------------------------------
    # Score cuối
    # ------------------------------------------------------------------

    def _estimate_coherence(
        self,
        *,
        intent: ActivityIntent,
        relation: GoalRelation,
        lexical_signal: OrientationSignal,
        intent_report: SemanticHypothesisReport,
        relation_report: SemanticHypothesisReport,
        probe: SemanticContextProbe,
    ) -> float:
        coherence = lexical_signal.orientation_coherence

        # Relation aligned/adjacent tăng coherence; conflict giảm. Semantic chỉ
        # kéo nhẹ, vì coherence là state tổng hợp, không phải cosine score.
        if relation.label == GoalRelationLabel.ALIGNED.value:
            coherence += 0.08 * relation.confidence
        elif relation.label == GoalRelationLabel.ADJACENT.value:
            coherence += 0.04 * relation.confidence
        elif relation.label == GoalRelationLabel.CONFLICTING.value:
            coherence -= 0.12 * relation.confidence

        if intent.label in {ActivityIntentLabel.TECHNICAL_FOCUS.value, ActivityIntentLabel.RESEARCH.value, ActivityIntentLabel.SYSTEM_WAITING.value}:
            coherence += 0.05 * intent.confidence
        elif intent.label == ActivityIntentLabel.POSSIBLE_AVOIDANCE.value:
            coherence -= 0.08 * intent.confidence

        # Semantic mơ hồ thì coherence không được quá cao.
        ambiguity = max(intent_report.ambiguity, relation_report.ambiguity * 0.65)
        coherence -= 0.06 * ambiguity
        if intent_report.fallback_used:
            coherence -= 0.03
        return clamp01(coherence)

    def _estimate_conflict(
        self,
        *,
        intent: ActivityIntent,
        relation: GoalRelation,
        lexical_signal: OrientationSignal,
        intent_report: SemanticHypothesisReport,
        relation_report: SemanticHypothesisReport,
        probe: SemanticContextProbe,
        veto: LexicalVetoReport,
    ) -> float:
        conflict = lexical_signal.goal_conflict_score
        active_goal_strength = clamp01(probe.active_goal_strength)
        intervention_perm = clamp01(probe.active_goal_intervention_permission)

        if relation.label == GoalRelationLabel.CONFLICTING.value:
            conflict += 0.22 * relation.confidence
        elif relation.label in {GoalRelationLabel.ALIGNED.value, GoalRelationLabel.ADJACENT.value}:
            conflict -= 0.10 * relation.confidence

        if intent.label == ActivityIntentLabel.POSSIBLE_AVOIDANCE.value:
            conflict += 0.16 * intent.confidence
        elif intent.label in {ActivityIntentLabel.RESEARCH.value, ActivityIntentLabel.TECHNICAL_FOCUS.value, ActivityIntentLabel.SYSTEM_WAITING.value}:
            conflict -= 0.10 * intent.confidence
        elif intent.label == ActivityIntentLabel.RECOVERY.value and active_goal_strength < 0.55:
            conflict -= 0.04

        if veto.research_media_anchor or veto.system_wait_anchor:
            conflict -= 0.10
        if veto.short_form_anchor and active_goal_strength >= 0.45 and intervention_perm >= 0.45:
            conflict += 0.06

        # Không cho conflict vượt cao nếu permission thấp.
        if intervention_perm < self.config.min_intervention_for_conflict:
            conflict = min(conflict, 0.46)
        if active_goal_strength < self.config.min_active_goal_for_conflict:
            conflict = min(conflict, 0.42)

        # Semantic fallback/mơ hồ không được bơm conflict.
        if intent_report.fallback_used or intent_report.ambiguity > self.config.ambiguity_block:
            conflict = min(conflict, lexical_signal.goal_conflict_score + 0.06)
        return clamp01(conflict)

    def _estimate_intervention_pressure(
        self,
        *,
        relation: GoalRelation,
        conflict: float,
        lexical_signal: OrientationSignal,
        intent_report: SemanticHypothesisReport,
        relation_report: SemanticHypothesisReport,
        probe: SemanticContextProbe,
    ) -> float:
        active_goal_strength = clamp01(probe.active_goal_strength)
        intervention_perm = clamp01(probe.active_goal_intervention_permission)
        pressure = lexical_signal.intervention_pressure

        if relation.label == GoalRelationLabel.CONFLICTING.value:
            pressure += conflict * 0.25
        elif relation.label in {GoalRelationLabel.ALIGNED.value, GoalRelationLabel.ADJACENT.value}:
            pressure -= 0.06

        pressure *= 0.55 + active_goal_strength * 0.25 + intervention_perm * 0.20

        # Ambiguity cao thì intervention tụt. Đây là phanh chính chống "Ni police".
        ambiguity = max(intent_report.ambiguity, relation_report.ambiguity)
        pressure *= 1.0 - 0.42 * ambiguity

        if intervention_perm < self.config.min_intervention_for_conflict:
            pressure = min(pressure, 0.36)
        if intent_report.fallback_used or relation_report.fallback_used:
            pressure = min(pressure, self.config.fallback_semantic_cap)
        return clamp01(pressure)

    def _estimate_confidence(
        self,
        *,
        blended_intent: ActivityIntent,
        blended_relation: GoalRelation,
        lexical_signal: OrientationSignal,
        intent_report: SemanticHypothesisReport,
        relation_report: SemanticHypothesisReport,
        veto: LexicalVetoReport,
    ) -> float:
        semantic_conf = max(intent_report.confidence, relation_report.confidence * 0.85)
        confidence = (
            lexical_signal.confidence * 0.44
            + blended_intent.confidence * 0.22
            + blended_relation.confidence * 0.16
            + semantic_conf * 0.18
        )
        ambiguity = max(intent_report.ambiguity, relation_report.ambiguity * 0.80)
        confidence *= 1.0 - 0.30 * ambiguity

        if blended_intent.label == ActivityIntentLabel.UNKNOWN.value:
            confidence = min(confidence, self.config.max_unknown_confidence)
        if intent_report.fallback_used or relation_report.fallback_used:
            confidence = min(confidence, self.config.fallback_semantic_cap)
        if veto.evidence:
            confidence += 0.03
        return clamp01(confidence)

    # ------------------------------------------------------------------
    # Helpers trả fallback / channels
    # ------------------------------------------------------------------

    def _with_fallback_channels(self, signal: OrientationSignal, *, reason: str) -> OrientationSignal:
        channels = dict(signal.channels or {})
        channels.update({"semantic_available": 0.0, "semantic_fallback_reason": 1.0, "hybrid_confidence": signal.confidence})
        evidence = tuple(signal.evidence) + (f"hybrid:{reason}",)
        return OrientationSignal(
            intent=signal.intent,
            relation=signal.relation,
            orientation_coherence=signal.orientation_coherence,
            goal_conflict_score=signal.goal_conflict_score,
            intervention_pressure=signal.intervention_pressure,
            confidence=signal.confidence,
            reason_span=signal.reason_span,
            evidence=evidence,
            channels=channels,
        )

    def _with_semantic_channels(
        self,
        signal: OrientationSignal,
        *,
        intent_report: SemanticHypothesisReport,
        relation_report: SemanticHypothesisReport,
        debug: HybridOrientationDebug,
    ) -> OrientationSignal:
        channels = dict(signal.channels or {})
        channels.update(
            {
                "semantic_available": 1.0 if intent_report.semantic_available else 0.0,
                "semantic_fallback_used": 1.0 if intent_report.fallback_used else 0.0,
                "semantic_intent_confidence": intent_report.confidence,
                "semantic_intent_ambiguity": intent_report.ambiguity,
                "semantic_relation_confidence": relation_report.confidence,
                "semantic_relation_ambiguity": relation_report.ambiguity,
                "hybrid_confidence": signal.confidence,
            }
        )
        evidence = tuple(signal.evidence) + tuple(debug.veto_evidence) + tuple(intent_report.evidence) + (f"hybrid:{debug.blend_reason}",)
        return OrientationSignal(
            intent=signal.intent,
            relation=signal.relation,
            orientation_coherence=signal.orientation_coherence,
            goal_conflict_score=signal.goal_conflict_score,
            intervention_pressure=signal.intervention_pressure,
            confidence=signal.confidence,
            reason_span=signal.reason_span,
            evidence=evidence,
            channels=channels,
        )

    def _blend_reason(
        self,
        lexical_intent: ActivityIntent,
        blended_intent: ActivityIntent,
        semantic_report: SemanticHypothesisReport,
        veto: LexicalVetoReport,
    ) -> str:
        semantic_label = semantic_report.dominant.label if semantic_report.dominant else "none"
        if lexical_intent.label == blended_intent.label == semantic_label:
            return "semantic_confirms_lexical"
        if lexical_intent.label != blended_intent.label:
            return f"semantic_or_veto_relabel:{lexical_intent.label}->{blended_intent.label}"
        if semantic_report.ambiguity > self.config.ambiguity_block:
            return "semantic_ambiguous_keep_lexical"
        if veto.evidence:
            return "lexical_veto_keep_or_shape_label"
        return "hybrid_keep_lexical"


# ---------------------------------------------------------------------------
# Factory tiện dụng
# ---------------------------------------------------------------------------


def build_hybrid_orientation_interpreter(
    semantic_engine: SemanticHypothesisEngine | None = None,
    *,
    config: HybridOrientationConfig | None = None,
) -> HybridOrientationInterpreter:
    """Factory nhỏ để coordinator/Ni nối nhanh."""

    return HybridOrientationInterpreter(semantic_engine=semantic_engine, config=config)
