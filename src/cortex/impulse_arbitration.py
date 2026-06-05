# -*- coding: utf-8 -*-
"""Impulse competition for ERIS.

Thay vì hardcode "đủ 5 phút thì nói", module này tạo nhiều impulse cùng lúc
và chấm điểm bằng belief + need + preference + trait + affordance + habit.
Nó không viết câu cuối. Nó chỉ chọn lực nào thắng. Hóa ra một hội đồng nhỏ vẫn
đỡ hơn một if-chain tự tin quá mức.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .agent_state_stack import AgentStateStack, _clamp01, _text


@dataclass(slots=True)
class ImpulseCandidate:
    name: str
    impulse_type: str
    speech_act: str
    topic_seed: str
    family: str = ""
    base_score: float = 0.0
    evidence_fit: float = 0.0
    belief_support: float = 0.0
    need_pressure: float = 0.0
    preference_fit: float = 0.0
    trait_bias: float = 0.0
    affordance_allowance: float = 0.0
    risk: float = 0.0
    repetition_penalty: float = 0.0
    habit_bias: float = 0.0
    interrupt_cost: float = 0.0
    resource_cost: float = 0.0
    metabolic_adjustment: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""
    requires_scene_evidence: bool = False

    @property
    def total(self) -> float:
        return _clamp01(
            self.base_score
            + self.evidence_fit
            + self.belief_support
            + self.need_pressure
            + self.preference_fit
            + self.trait_bias
            + self.affordance_allowance
            + self.habit_bias
            - self.risk
            - self.repetition_penalty
            - self.interrupt_cost
            - self.resource_cost
            + self.metabolic_adjustment
        )

    def score_note(self) -> str:
        return f"impulse.{self.name}={self.total:.2f}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "impulse_type": self.impulse_type,
            "speech_act": self.speech_act,
            "topic_seed": self.topic_seed,
            "family": self.family,
            "total": round(self.total, 3),
            "base_score": round(self.base_score, 3),
            "evidence_fit": round(self.evidence_fit, 3),
            "belief_support": round(self.belief_support, 3),
            "need_pressure": round(self.need_pressure, 3),
            "preference_fit": round(self.preference_fit, 3),
            "trait_bias": round(self.trait_bias, 3),
            "affordance_allowance": round(self.affordance_allowance, 3),
            "risk": round(self.risk, 3),
            "repetition_penalty": round(self.repetition_penalty, 3),
            "habit_bias": round(self.habit_bias, 3),
            "interrupt_cost": round(self.interrupt_cost, 3),
            "resource_cost": round(self.resource_cost, 3),
            "metabolic_adjustment": round(self.metabolic_adjustment, 3),
            "evidence": list(self.evidence),
            "reason": self.reason,
            "requires_scene_evidence": bool(self.requires_scene_evidence),
        }


@dataclass(slots=True)
class ArbitrationReport:
    selected: ImpulseCandidate = field(default_factory=lambda: ImpulseCandidate("silence_impulse", "silence", "no_speech", "silence"))
    candidates: tuple[ImpulseCandidate, ...] = ()
    suppressed: tuple[ImpulseCandidate, ...] = ()
    reason: str = ""

    def evidence_notes(self, limit: int = 8) -> tuple[str, ...]:
        notes = [self.selected.score_note(), f"arbitration={self.reason or self.selected.name}"]
        notes.extend(item.score_note() for item in self.candidates[:limit] if item.name != self.selected.name)
        return tuple(notes[:limit])

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "suppressed": [item.name for item in self.suppressed],
            "reason": self.reason,
        }


class ImpulseArbitrator:
    """Chọn impulse thắng bằng score, không viết output public."""

    def select(self, candidates: tuple[ImpulseCandidate, ...]) -> ArbitrationReport:
        if not candidates:
            selected = ImpulseCandidate("silence_impulse", "silence", "no_speech", "silence", base_score=0.5)
            return ArbitrationReport(selected=selected, candidates=(selected,), reason="empty_candidates")
        ordered = tuple(sorted(candidates, key=lambda item: (item.total, _priority(item.name)), reverse=True))
        selected = ordered[0]
        suppressed = tuple(item for item in ordered[1:] if selected.total - item.total >= 0.18)[:6]
        return ArbitrationReport(selected=selected, candidates=ordered, suppressed=suppressed, reason=f"{selected.name}_wins")


def _priority(name: str) -> float:
    # Tie-break nhẹ: task thật > scene > companionship > whim > silence. Nếu cứ để
    # silence thắng mọi tie thì ERIS thành tranh nền có UDP, một tiến hóa đáng buồn.
    return {
        "technical_help_impulse": 0.74,
        "scene_curiosity_impulse": 0.68,
        "reengagement_impulse": 0.64,
        "curious_question_impulse": 0.60,
        "memory_resonance_impulse": 0.57,
        "random_chatter_impulse": 0.55,
        "companionship_impulse": 0.52,
        "micro_story_impulse": 0.50,
        "inner_whim_impulse": 0.48,
        "body_only_impulse": 0.42,
        "silence_impulse": 0.30,
    }.get(str(name or ""), 0.0)


def build_default_impulse_candidates(stack: AgentStateStack, *, thought_surface: Any = None) -> tuple[ImpulseCandidate, ...]:
    """Tạo bộ impulse mặc định cho spontaneous/autonomous path."""

    ev = stack.evidence
    needs = stack.needs
    beliefs = stack.beliefs
    prefs = stack.preferences
    traits = stack.traits
    habits = stack.habits
    aff = stack.affordances

    # P0/P1: requested_presence và interrupt_cost đi vào đúng tầng phân xử.
    # - force_speak không có screen evidence là explicit pull, không phải ngữ cảnh rỗng.
    # - code/docs tăng ma sát cho xung nói nhảm. Media/game giảm ma sát để ERIS
    #   được khịa nhẹ khi user đang xả hơi.
    requested_presence = _clamp01(getattr(needs, "requested_presence_need", 0.0))
    explicit_no_screen_pull = ev.channel == "force_speak" and requested_presence >= 0.50 and not ev.concrete_signals
    dynamic_interrupt_cost = _clamp01(getattr(aff, "endogenous_interrupt_cost", 0.35), 0.35)
    media_relief = 0.18 if ev.focus_kind in {"media", "game"} or ev.has_tag("media_scene") or ev.has_tag("game_scene") else 0.0
    internal_pull_boost = requested_presence * (0.42 if explicit_no_screen_pull else 0.18)
    micro_presence_demote = requested_presence * 0.30 if explicit_no_screen_pull else 0.0

    # INFJ 5w4 prior: silence is not a broken pipe. Presence pings must fight
    # worldview friction; inner thought and pattern observation should be the
    # natural outlet when boredom/curiosity rises.
    ambient_copresence = beliefs.confidence("silence.ambient_copresence", 0.74)
    status_ping_low_value = beliefs.confidence("presence.status_ping_low_value", 0.72)
    pattern_observation_belief = beliefs.confidence("eris.prefers_pattern_observation", 0.70)
    cognitive_stimulation = _clamp01(getattr(needs, "cognitive_stimulation_need", 0.0))
    social_presence_need = _clamp01(getattr(needs, "social_presence_need", needs.relation_need))
    vital_pressure = _clamp01(getattr(needs, "vital_pressure", 0.0))
    metabolic_pressure = _clamp01(getattr(needs, "metabolic_pressure", vital_pressure))
    silence_pressure = _clamp01(getattr(needs, "silence_pressure", 0.0))
    thought_pressure = _clamp01(getattr(needs, "thought_pressure", 0.0))
    memory_residue_pressure = _clamp01(getattr(needs, "memory_residue_pressure", 0.0))
    boredom_pressure = _clamp01(getattr(needs, "boredom_pressure", 0.0))

    # Metabolic adjustment xuyên suốt arbitration. Đây là điểm "tim đập":
    # im lặng vẫn là ứng viên hợp lệ, nhưng càng nén lâu thì silence càng mất giá.
    vital_speech_bonus = min(0.32, vital_pressure * 0.34)
    vital_silence_discount = min(0.48, vital_pressure * 0.52 + requested_presence * 0.20)

    scene_anchor = _scene_anchor(ev)
    thought_topic = _text(getattr(thought_surface, "topic_seed", "") if thought_surface is not None else "", limit=80)
    has_internal_content = bool(thought_topic)
    has_scene_or_internal_context = bool(ev.has_scene_anchor or scene_anchor or has_internal_content or memory_residue_pressure >= 0.42)
    empty_context_presence_penalty = status_ping_low_value * (0.34 if not has_scene_or_internal_context else 0.18)
    vital_body_release = vital_pressure * (0.30 if not has_scene_or_internal_context else 0.14)
    family_scene = "scene_curiosity:" + _family_key(scene_anchor)
    family_whim = "inner_whim:" + _family_key(thought_topic or "quiet_whim")
    family_story = "micro_story:" + _family_key(thought_topic or "memory_dust")

    candidates: list[ImpulseCandidate] = []

    # 1. Silence is always a real candidate, not merely the absence of speech.
    candidates.append(
        ImpulseCandidate(
            name="silence_impulse",
            impulse_type="silence",
            speech_act="no_speech",
            topic_seed="intentional_silence",
            family="silence:intentional",
            base_score=0.20,
            belief_support=ambient_copresence * 0.16 + status_ping_low_value * 0.06,
            need_pressure=needs.rest_need * 0.28 + needs.competence_need * 0.18 + cognitive_stimulation * 0.03,
            preference_fit=prefs.fit_for("silence_impulse") * 0.10,
            trait_bias=traits.bias_for("silence_impulse"),
            affordance_allowance=0.10 if aff.silence_allowed else 0.0,
            risk=needs.expression_need * 0.08 + requested_presence * 0.24 + vital_silence_discount,
            habit_bias=habits.semantic_bias(action="no_speech", impulse_name="silence_impulse", family="silence:intentional"),
            metabolic_adjustment=-vital_silence_discount,
            evidence=(*needs.notes(), f"metabolic.vital={vital_pressure:.2f}", f"silence_discount={vital_silence_discount:.2f}", "silence_is_candidate"),
            reason="Silence is valid, but metabolic pressure discounts it when ERIS has been compressed too long.",
        )
    )

    # 2. Current scene curiosity, only when the scene itself affords a casual line.
    scene_allowed = aff.casual_comment_allowed and ev.has_scene_anchor
    scene_need = needs.curiosity_need * 0.22 + cognitive_stimulation * 0.24 + needs.expression_need * 0.12
    if ev.has_tag("food_scene"):
        scene_need += 0.12
    if ev.has_tag("game_scene"):
        scene_need += 0.10
    candidates.append(
        ImpulseCandidate(
            name="scene_curiosity_impulse",
            impulse_type="scene_curiosity",
            speech_act="micro_observation",
            topic_seed=scene_anchor or "casual_scene",
            family=family_scene,
            base_score=0.10,
            evidence_fit=0.22 if scene_allowed else 0.0,
            belief_support=max(beliefs.confidence("scene.low_risk_casual"), beliefs.confidence("scene.systemic_interest"), pattern_observation_belief) * 0.20,
            need_pressure=scene_need + requested_presence * 0.12 + media_relief * 0.10 + vital_speech_bonus * 0.52,
            preference_fit=prefs.fit_for("scene_curiosity_impulse") * 0.20,
            trait_bias=traits.bias_for("scene_curiosity_impulse"),
            affordance_allowance=0.18 if scene_allowed else -0.10,
            risk=aff.intrusive_question_risk * 0.10 + needs.rest_need * 0.10,
            repetition_penalty=habits.repetition_penalty(action="micro_observation", family=family_scene),
            habit_bias=habits.semantic_bias(action="micro_observation", impulse_name="scene_curiosity_impulse", family=family_scene),
            interrupt_cost=max(0.0, needs.competence_need * 0.18 + dynamic_interrupt_cost * 0.22 - requested_presence * 0.18 - media_relief),
            resource_cost=0.02,
            metabolic_adjustment=vital_speech_bonus if ev.has_scene_anchor else 0.0,
            evidence=(*ev.evidence_ids, *ev.tags, "belief.scene_low_risk", "pref.absurd_mundane", f"metabolic.vital={vital_pressure:.2f}"),
            reason="Scene curiosity can surface as a small grounded observation.",
            requires_scene_evidence=True,
        )
    )

    # 3. Inner whim from thought stream. No screen claim, just internal residue.
    candidates.append(
        ImpulseCandidate(
            name="inner_whim_impulse",
            impulse_type="inner_whim",
            speech_act="inner_whim",
            topic_seed=thought_topic or "quiet_whim",
            family=family_whim,
            base_score=0.10 + internal_pull_boost,
            evidence_fit=(0.10 if thought_topic else 0.03) + requested_presence * 0.10,
            belief_support=max(beliefs.confidence("eris.should_not_sound_like_camera", 0.50), pattern_observation_belief) * 0.12,
            need_pressure=needs.expression_need * 0.24 + needs.curiosity_need * 0.10 + cognitive_stimulation * 0.28 + requested_presence * 0.18 + vital_speech_bonus,
            preference_fit=prefs.fit_for("inner_whim_impulse") * 0.20,
            trait_bias=traits.bias_for("inner_whim_impulse"),
            affordance_allowance=0.06,
            risk=needs.rest_need * 0.12 + needs.competence_need * 0.16,
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.46 - requested_presence * 0.36 - media_relief),
            repetition_penalty=habits.repetition_penalty(action="inner_whim", family=family_whim),
            habit_bias=habits.semantic_bias(action="inner_whim", impulse_name="inner_whim_impulse", family=family_whim),
            metabolic_adjustment=vital_speech_bonus * 0.82,
            evidence=(*stack.debug_notes()[:5], f"metabolic.vital={vital_pressure:.2f}", "source=thought_or_internal_state"),
            reason="Internal residue wants a short low-claim line.",
        )
    )

    # 4. Curious question từ nội sinh. Khác scene_curiosity ở chỗ nó không
    # được phép bịa screen claim; nó chỉ hỏi nhỏ từ pressure/requested presence.
    candidates.append(
        ImpulseCandidate(
            name="curious_question_impulse",
            impulse_type="curious_question",
            speech_act="curious_question",
            topic_seed=thought_topic or scene_anchor or "requested_presence",
            family="curious_question:" + _family_key(thought_topic or scene_anchor or "requested_presence"),
            base_score=0.06 + requested_presence * 0.34 + media_relief * 0.06,
            evidence_fit=0.08 if (thought_topic or scene_anchor) else 0.02,
            belief_support=beliefs.confidence("eris.should_not_sound_like_camera", 0.50) * 0.06,
            need_pressure=needs.curiosity_need * 0.26 + needs.expression_need * 0.16 + requested_presence * 0.20 + vital_speech_bonus * 0.72,
            preference_fit=prefs.fit_for("inner_whim_impulse") * 0.10,
            trait_bias=traits.bias_for("scene_curiosity_impulse") * 0.42,
            affordance_allowance=0.06 + (0.08 if explicit_no_screen_pull else 0.0),
            risk=aff.intrusive_question_risk * 0.12 + needs.rest_need * 0.10,
            repetition_penalty=habits.repetition_penalty(action="curious_question", family="curious_question:" + _family_key(thought_topic or scene_anchor or "requested_presence")),
            habit_bias=habits.semantic_bias(action="curious_question", impulse_name="curious_question_impulse", family="curious_question:" + _family_key(thought_topic or scene_anchor or "requested_presence")),
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.38 - requested_presence * 0.30 - media_relief),
            metabolic_adjustment=vital_speech_bonus * 0.60,
            evidence=("requested_presence" if requested_presence else "curiosity_pressure", f"metabolic.vital={vital_pressure:.2f}", *stack.debug_notes()[:5]),
            reason="Explicit pull or low-risk curiosity can surface as one small question without screen claims.",
        )
    )

    # 5. Micro story, mostly when memory/thought residue is stronger than raw boredom.
    candidates.append(
        ImpulseCandidate(
            name="micro_story_impulse",
            impulse_type="micro_story",
            speech_act="light_muse",
            topic_seed=thought_topic or "memory_dust",
            family=family_story,
            base_score=0.07 + requested_presence * 0.28,
            evidence_fit=(0.10 if thought_topic else 0.04) + requested_presence * 0.06,
            belief_support=pattern_observation_belief * 0.10,
            need_pressure=needs.expression_need * 0.18 + cognitive_stimulation * 0.22 + requested_presence * 0.14 + vital_speech_bonus * 0.86,
            preference_fit=prefs.fit_for("micro_story_impulse") * 0.16,
            trait_bias=traits.bias_for("micro_story_impulse"),
            affordance_allowance=0.05,
            risk=needs.rest_need * 0.14 + needs.competence_need * 0.16,
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.44 - requested_presence * 0.32 - media_relief),
            repetition_penalty=habits.repetition_penalty(action="light_muse", family=family_story),
            habit_bias=habits.semantic_bias(action="light_muse", impulse_name="micro_story_impulse", family=family_story),
            metabolic_adjustment=vital_speech_bonus * 0.72,
            evidence=("source=memory_or_thought_residue", f"metabolic.vital={vital_pressure:.2f}", *needs.notes()[:3]),
            reason="A tiny memory/thought residue is competing for surface.",
        )
    )

    # 5. Companionship ping. Kept weaker because ERIS should not become a notification demon.
    candidates.append(
        ImpulseCandidate(
            name="companionship_impulse",
            impulse_type="companionship_ping",
            speech_act="micro_presence",
            topic_seed="quiet_co_presence",
            family="companionship:quiet_co_presence",
            base_score=0.025 + vital_pressure * 0.025,
            belief_support=max(0.0, beliefs.confidence("presence.silence_can_decay", 0.0) * 0.04 - ambient_copresence * 0.20 - status_ping_low_value * 0.32),
            need_pressure=social_presence_need * 0.10 + needs.continuity_need * 0.08 + requested_presence * 0.02 + vital_speech_bonus * 0.24,
            preference_fit=prefs.fit_for("companionship_impulse") * 0.10,
            trait_bias=traits.bias_for("companionship_impulse"),
            affordance_allowance=0.02 if aff.body_only_allowed and has_scene_or_internal_context else -0.04,
            risk=aff.intrusive_question_risk * 0.12 + needs.rest_need * 0.18 + micro_presence_demote + empty_context_presence_penalty + max(0.0, status_ping_low_value * 0.26 - vital_pressure * 0.05),
            repetition_penalty=habits.repetition_penalty(action="micro_presence", family="companionship:quiet_co_presence"),
            habit_bias=habits.semantic_bias(action="micro_presence", impulse_name="companionship_impulse", family="companionship:quiet_co_presence"),
            metabolic_adjustment=max(0.0, vital_speech_bonus * 0.18 - empty_context_presence_penalty * 0.35),
            evidence=("need.relation", "need.continuity", f"metabolic.vital={vital_pressure:.2f}", f"belief.status_ping_low_value={status_ping_low_value:.2f}", "low_claim_presence"),
            reason="Co-presence ping is strongly demoted by the belief that empty status pings have low value.",
        )
    )

    # 6. Random chatter: nói nhảm có kiểm soát khi boredom/silence nén đủ lâu.
    # Không claim màn hình; nó là mẩu nội sinh thấp rủi ro, dùng để ERIS bớt hóa tượng.
    random_family = "random_chatter:" + _family_key(thought_topic or scene_anchor or "ambient_runtime")
    candidates.append(
        ImpulseCandidate(
            name="random_chatter_impulse",
            impulse_type="random_chatter",
            speech_act="random_chatter",
            topic_seed=thought_topic or "ambient_runtime",
            family=random_family,
            base_score=0.045 + boredom_pressure * 0.08 + requested_presence * 0.08,
            evidence_fit=0.06 if thought_topic else 0.02,
            belief_support=max(beliefs.confidence("eris.should_not_sound_like_camera", 0.50), pattern_observation_belief) * 0.08,
            need_pressure=boredom_pressure * 0.22 + needs.expression_need * 0.18 + cognitive_stimulation * 0.18 + vital_speech_bonus * 0.80,
            preference_fit=prefs.fit_for("random_chatter_impulse") * 0.14,
            trait_bias=traits.bias_for("random_chatter_impulse"),
            affordance_allowance=0.09 if aff.random_chatter_allowed else -0.04,
            risk=needs.rest_need * 0.12 + aff.intrusive_question_risk * 0.08,
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.34 - requested_presence * 0.24 - media_relief - vital_pressure * 0.18),
            repetition_penalty=habits.repetition_penalty(action="random_chatter", family=random_family),
            habit_bias=habits.semantic_bias(action="random_chatter", impulse_name="random_chatter_impulse", family=random_family),
            metabolic_adjustment=vital_speech_bonus * 0.64,
            evidence=("source=endogenous_boredom", f"metabolic.vital={vital_pressure:.2f}", f"boredom={boredom_pressure:.2f}"),
            reason="Compressed boredom/silence can surface as one tiny no-claim chatter fragment.",
        )
    )

    # 7. Memory resonance: ký ức/pattern cũ nổi lên, nhưng vẫn phải nói thấp-claim.
    memory_family = "memory_resonance:" + _family_key(thought_topic or "pattern_residue")
    candidates.append(
        ImpulseCandidate(
            name="memory_resonance_impulse",
            impulse_type="memory_resonance",
            speech_act="light_muse",
            topic_seed=thought_topic or "pattern_residue",
            family=memory_family,
            base_score=0.05 + memory_residue_pressure * 0.10,
            evidence_fit=0.12 if thought_topic else 0.04,
            belief_support=pattern_observation_belief * 0.18,
            need_pressure=memory_residue_pressure * 0.28 + thought_pressure * 0.18 + vital_speech_bonus * 0.62,
            preference_fit=prefs.fit_for("memory_resonance_impulse") * 0.16,
            trait_bias=traits.bias_for("memory_resonance_impulse"),
            affordance_allowance=0.06,
            risk=needs.rest_need * 0.10 + needs.competence_need * 0.08,
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.32 - vital_pressure * 0.16 - requested_presence * 0.18),
            repetition_penalty=habits.repetition_penalty(action="light_muse", family=memory_family),
            habit_bias=habits.semantic_bias(action="light_muse", impulse_name="memory_resonance_impulse", family=memory_family),
            metabolic_adjustment=vital_speech_bonus * 0.54,
            evidence=("source=memory_residue", f"memory_residue={memory_residue_pressure:.2f}", f"metabolic.vital={vital_pressure:.2f}"),
            reason="A remembered pattern/residue wants a short surface trace.",
        )
    )

    # 8. Re-engagement: sau im lâu, không chỉ 'tôi ở đây' mà kéo nhịp lại thật nhẹ.
    reengagement_family = "reengagement:quiet_return"
    candidates.append(
        ImpulseCandidate(
            name="reengagement_impulse",
            impulse_type="reengagement",
            speech_act="reengagement",
            topic_seed=scene_anchor or thought_topic or "quiet_return",
            family=reengagement_family,
            base_score=0.035 + min(0.14, silence_pressure * 0.12),
            evidence_fit=0.08 if ev.has_scene_anchor else 0.02,
            belief_support=max(0.0, beliefs.confidence("presence.silence_can_decay", 0.0) * 0.08 - ambient_copresence * 0.10 - status_ping_low_value * 0.10),
            need_pressure=needs.continuity_need * 0.16 + social_presence_need * 0.08 + vital_speech_bonus * (0.52 if has_scene_or_internal_context else 0.24),
            preference_fit=prefs.fit_for("reengagement_impulse") * 0.14,
            trait_bias=traits.bias_for("reengagement_impulse"),
            affordance_allowance=0.08 if aff.body_only_allowed else -0.04,
            risk=aff.intrusive_question_risk * 0.10 + needs.rest_need * 0.12 + empty_context_presence_penalty * 0.65,
            interrupt_cost=max(0.0, dynamic_interrupt_cost * 0.30 - vital_pressure * 0.22 - requested_presence * 0.20),
            repetition_penalty=habits.repetition_penalty(action="reengagement", family=reengagement_family),
            habit_bias=habits.semantic_bias(action="reengagement", impulse_name="reengagement_impulse", family=reengagement_family),
            metabolic_adjustment=vital_speech_bonus * (0.40 if has_scene_or_internal_context else 0.12),
            evidence=(f"silence_pressure={silence_pressure:.2f}", f"metabolic.vital={vital_pressure:.2f}", f"belief.status_ping_low_value={status_ping_low_value:.2f}", "low_claim_reengagement"),
            reason="Long compressed silence can ask for one restrained re-engagement line.",
        )
    )

    # 6. Technical help. In spontaneous path this usually loses unless task pressure is real.
    candidates.append(
        ImpulseCandidate(
            name="technical_help_impulse",
            impulse_type="technical_help",
            speech_act="practical_help",
            topic_seed="task_assistance",
            family="technical:task_assistance",
            base_score=0.05,
            evidence_fit=0.24 if aff.technical_help_relevant else 0.0,
            belief_support=beliefs.confidence("task.competence_needed", 0.0) * 0.22,
            need_pressure=needs.competence_need * 0.42,
            preference_fit=prefs.fit_for("technical_help_impulse") * 0.12,
            trait_bias=traits.bias_for("technical_help_impulse"),
            affordance_allowance=0.12 if aff.technical_help_relevant else -0.08,
            risk=needs.rest_need * 0.10,
            interrupt_cost=0.02 if aff.technical_help_relevant else dynamic_interrupt_cost * 0.18,
            habit_bias=habits.semantic_bias(action="practical_help", impulse_name="technical_help_impulse", family="technical:practical_help"),
            evidence=(*ev.evidence_ids, "competence_need"),
            reason="Task pressure may require usefulness instead of personality mist.",
            requires_scene_evidence=True,
        )
    )

    # 7. Body-only impulse. Useful when expression exists but speech is too intrusive.
    candidates.append(
        ImpulseCandidate(
            name="body_only_impulse",
            impulse_type="body_only",
            speech_act="no_speech",
            topic_seed="body_bias_only",
            family="body:quiet_adjustment",
            base_score=0.12 + vital_body_release * 0.25,
            need_pressure=needs.continuity_need * 0.18 + needs.curiosity_need * 0.08 + vital_pressure * 0.20 + empty_context_presence_penalty * 0.38,
            preference_fit=prefs.fit_for("body_only_impulse") * 0.10,
            trait_bias=traits.bias_for("body_only_impulse"),
            affordance_allowance=(0.16 + vital_body_release) if aff.body_only_allowed else -0.04,
            risk=0.04,
            habit_bias=habits.semantic_bias(action="no_speech", impulse_name="body_only_impulse", family="body:quiet_adjustment"),
            metabolic_adjustment=vital_pressure * 0.12 + vital_body_release * 0.22,
            evidence=("body_only_affordance", f"metabolic.vital={vital_pressure:.2f}", f"belief.status_ping_low_value={status_ping_low_value:.2f}", *needs.notes()[:2]),
            reason="When there is no real context, vital pressure should discharge through body rhythm instead of empty presence speech.",
        )
    )

    return tuple(candidates)


def _scene_anchor(ev) -> str:
    if ev.has_tag("food_scene"):
        return ev.active_window or ev.ocr_excerpt or "food_scene"
    if ev.has_tag("game_scene"):
        return ev.active_window or ev.active_app or "game_scene"
    if ev.has_tag("media_scene"):
        return ev.active_window or ev.active_app or "media_scene"
    return ev.active_window or ev.active_app or ev.ocr_excerpt or ""


def _family_key(value: str) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = re.sub(r"[^a-z0-9_\s-]", " ", text)
    words = [w for w in text.split() if len(w) >= 2]
    return "_".join(words[:5])[:80] or "unanchored"
