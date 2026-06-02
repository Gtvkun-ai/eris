"""Utility competition for ERIS actions.

File này thay lõi "if intent == X -> return Y" bằng cạnh tranh utility.
Không phải ML. Không giả vờ thông minh. Chỉ là scoring minh bạch, có memory,
có risk penalty, có rhythm, có pressure thật. Ít nhất nó không ngu theo cách
cũ nữa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .action_memory import ActionMemoryState, build_action_family


ACTION_SPACE: tuple[str, ...] = (
    "no_speech",
    "observe",
    "tease",
    "protect",
    "withdraw",
    "ask",
    "reassure",
    "react",
    "hesitate",
    "suppress",
    "indirect_presence",
    "guarded_reply",
    "refuse",
    "mirror",
    "meta_reply",
    "telemetry_comment",
    "vision_comment",
    "micro_observation",
    "micro_presence",
    "reengagement",
    "random_chatter",
    "inner_whim",
    "curious_question",
    "relational_checkin",
    "light_muse",
    "practical_help",
    "soft_boundary",
    "system_action",
)

SCREEN_CLAIM_ACTIONS = {
    "observe",
    "tease",
    "telemetry_comment",
    "vision_comment",
    "micro_observation",
}

FREEFORM_SOCIAL_ACTIONS = {
    "random_chatter",
    "inner_whim",
    "curious_question",
    "relational_checkin",
    "light_muse",
    "reengagement",
    "tease",
}

LOW_SIGNAL_SAFE_ACTIONS = {
    "no_speech",
    "withdraw",
    "suppress",
    "micro_presence",
    "indirect_presence",
    "hesitate",
}

# Soft cooldown. Không hard block, vì hard block lại đẻ rule-based trá hình.
ACTION_COOLDOWN_SECONDS: dict[str, float] = {
    "tease": 90.0,
    "inner_whim": 140.0,
    "curious_question": 150.0,
    "relational_checkin": 300.0,
    "random_chatter": 120.0,
    "light_muse": 120.0,
    "micro_presence": 40.0,
    "reengagement": 180.0,
    "ask": 45.0,
}


@dataclass(slots=True)
class ActionContext:
    """Context đã normalize cho scorer.

    Planner build object này từ coordinator inputs. Dùng dataclass để debug rõ,
    thay vì truyền 20 tham số vào từng hàm như một nghi thức triệu hồi bug.
    """

    channel: str
    user_text: str = ""
    force_speak: bool = False
    proposed_intent: str = ""
    proposed_speech_act: str = ""
    proposed_reason: str = ""
    system_action: str = ""
    concrete_signals: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    snapshot: Any = None
    ti_report: Any = None
    fe_plan: Any = None
    appraisal: Any = None
    broadcast: Any = None
    self_state: Any = None
    speech_core: Any = None
    conversation_dynamics: Any = None
    relationship_dynamics: Any = None
    goal_state: Any = None
    action_memory: ActionMemoryState | None = None

    # Full impulse report from SpontaneousLife/AgentStateStack. This is optional
    # so old call-sites still run, but when present it lets ActionUtility choose
    # from the actual winning motive instead of staring at proposed_speech_act
    # like a clerk who only received page 10 of a court file.
    impulse_arbitration: Mapping[str, Any] | None = None
    body_bias_hint: Mapping[str, Any] | None = None

    has_broadcast_signal: bool = False
    now: float = 0.0

    @property
    def explicit_user_pull(self) -> bool:
        return self.channel in {"chat", "force_speak"} or self.force_speak

    @property
    def has_concrete_signal(self) -> bool:
        return bool(self.concrete_signals or self.has_broadcast_signal)

    @property
    def family(self) -> str:
        return build_action_family(
            proposed_intent=self.proposed_intent,
            speech_act=self.proposed_speech_act,
            notes=self.notes,
        )


@dataclass(slots=True)
class ActionScore:
    """Chi tiết điểm của một action.

    total = base + bias + pressure + rhythm - risk - repetition - fatigue.
    reasons để debug. Đừng xóa. Không có reason là lại ngồi bói log.
    """

    action: str
    total: float = 0.0
    base: float = 0.0
    bias: float = 0.0
    pressure: float = 0.0
    rhythm: float = 0.0
    risk: float = 0.0
    repetition: float = 0.0
    fatigue: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, amount: float, reason: str, bucket: str = "bias") -> None:
        amount = float(amount or 0.0)
        self.total += amount
        if bucket == "base":
            self.base += amount
        elif bucket == "pressure":
            self.pressure += amount
        elif bucket == "rhythm":
            self.rhythm += amount
        elif bucket == "risk":
            self.risk += -amount if amount < 0 else amount
        elif bucket == "repetition":
            self.repetition += -amount if amount < 0 else amount
        elif bucket == "fatigue":
            self.fatigue += -amount if amount < 0 else amount
        else:
            self.bias += amount
        if reason:
            sign = "+" if amount >= 0 else ""
            self.reasons.append(f"{sign}{amount:.2f}:{reason}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "total": round(self.total, 4),
            "base": round(self.base, 4),
            "bias": round(self.bias, 4),
            "pressure": round(self.pressure, 4),
            "rhythm": round(self.rhythm, 4),
            "risk": round(self.risk, 4),
            "repetition": round(self.repetition, 4),
            "fatigue": round(self.fatigue, 4),
            "reasons": tuple(self.reasons[:8]),
        }


@dataclass(slots=True)
class ActionUtilityReport:
    selected_action: str
    selected_utility: float
    scores: dict[str, ActionScore]
    suppressed_actions: tuple[str, ...] = ()
    rhythm_phase: str = "settled"
    transition_reason: str = ""
    memory_pressure: tuple[str, ...] = ()
    hard_override: bool = False
    selected_impulse: str = ""
    impulse_scores: tuple[str, ...] = ()
    impulse_arbitration: dict[str, Any] = field(default_factory=dict)
    body_bias_hint: dict[str, Any] = field(default_factory=dict)

    def utility_scores(self) -> dict[str, float]:
        return {action: round(score.total, 4) for action, score in self.scores.items()}

    def top_reasons(self, limit: int = 4) -> tuple[str, ...]:
        ordered = sorted(self.scores.values(), key=lambda item: item.total, reverse=True)
        result: list[str] = []
        for item in ordered[:limit]:
            result.append(f"{item.action}={item.total:.2f}({'|'.join(item.reasons[:3])})")
        return tuple(result)

    def to_debug_notes(self) -> tuple[str, ...]:
        return (
            f"action_selected={self.selected_action}",
            f"action_utility={self.selected_utility:.2f}",
            f"rhythm_phase={self.rhythm_phase}",
            f"transition={self.transition_reason}",
            "action_scores=" + "; ".join(self.top_reasons(5)),
            *self.memory_pressure,
            f"selected_impulse={self.selected_impulse}" if self.selected_impulse else "selected_impulse=none",
            "impulse_scores=" + "; ".join(self.impulse_scores[:6]) if self.impulse_scores else "impulse_scores=none",
        )


class ActionUtilityScorer:
    """Chấm điểm cạnh tranh cho ACTION_SPACE.

    Hard override chỉ dành cho case thật sự không nên tranh luận:
    - system_action: user yêu cầu tool/action cụ thể
    - proposed_speech_act=refuse: tầng safety đã quyết
    - proposed_intent=no_speech và không explicit pull: giữ im

    Còn lại proposed_speech_act/proposed_intent chỉ là bias.
    """

    def score(self, ctx: ActionContext) -> ActionUtilityReport:
        override = self._hard_override(ctx)
        if override:
            score = ActionScore(action=override, total=999.0)
            score.add(999.0, "hard_override", "base")
            return ActionUtilityReport(
                selected_action=override,
                selected_utility=score.total,
                scores={override: score},
                suppressed_actions=(),
                rhythm_phase=self._memory(ctx).rhythm_phase,
                transition_reason="hard override from system/safety/no_speech contract",
                memory_pressure=(*self._memory_pressure_notes(ctx), *self._goal_pressure_notes(ctx), *self._impulse_pressure_notes(ctx)),
                hard_override=True,
                selected_impulse=self._selected_impulse_name(ctx),
                impulse_scores=self._impulse_score_notes(ctx),
                impulse_arbitration=self._impulse_report(ctx),
                body_bias_hint=self._body_bias_hint(ctx),
            )

        candidates = self._candidate_actions(ctx)
        scores = {action: ActionScore(action=action) for action in candidates}

        for action, score in scores.items():
            self._apply_base(score, ctx)
            self._apply_intent_bias(score, ctx)
            self._apply_channel_pressure(score, ctx)
            self._apply_appraisal_pressure(score, ctx)
            self._apply_conversation_pressure(score, ctx)
            self._apply_relationship_pressure(score, ctx)
            self._apply_goal_persistence_pressure(score, ctx)
            self._apply_memory_pressure(score, ctx)
            self._apply_impulse_arbitration_pressure(score, ctx)
            self._apply_rhythm(score, ctx)
            self._apply_risk_penalty(score, ctx)
            self._apply_repetition_penalty(score, ctx)
            self._apply_fatigue_penalty(score, ctx)

        selected = max(scores.values(), key=lambda item: (item.total, self._tie_break_priority(item.action)))
        suppressed = tuple(
            action for action, score in sorted(scores.items(), key=lambda pair: pair[1].total)
            if score.total <= -0.35
        )[:8]
        memory = self._memory(ctx)
        return ActionUtilityReport(
            selected_action=selected.action,
            selected_utility=selected.total,
            scores=scores,
            suppressed_actions=suppressed,
            rhythm_phase=memory.rhythm_phase,
            transition_reason=self._transition_reason(selected, ctx),
            memory_pressure=(*self._memory_pressure_notes(ctx), *self._goal_pressure_notes(ctx), *self._impulse_pressure_notes(ctx)),
            hard_override=False,
            selected_impulse=self._selected_impulse_name(ctx),
            impulse_scores=self._impulse_score_notes(ctx),
            impulse_arbitration=self._impulse_report(ctx),
            body_bias_hint=self._body_bias_hint(ctx),
        )

    def _hard_override(self, ctx: ActionContext) -> str:
        proposed = _clean(ctx.proposed_speech_act)
        intent = _clean(ctx.proposed_intent)
        if ctx.system_action:
            return "system_action"
        if proposed == "refuse":
            return "refuse"
        if intent == "no_speech" and not proposed and not ctx.explicit_user_pull:
            return "no_speech"
        return ""

    def _candidate_actions(self, ctx: ActionContext) -> tuple[str, ...]:
        """Chọn tập candidate nhỏ để score rõ, không phải action nào cũng lôi vào."""
        if ctx.channel == "chat":
            base = {
                "mirror",
                "ask",
                "react",
                "guarded_reply",
                "soft_boundary",
                "protect",
                "refuse",
                "meta_reply",
                "hesitate",
            }
            mode = _clean(getattr(ctx.conversation_dynamics, "mode", ""))
            if mode in {"repair", "execute", "compress"}:
                base.update({"mirror", "react", "meta_reply", "hesitate"})
            if self._looks_like_technical_request(ctx.user_text):
                base.update({"mirror", "react", "meta_reply", "practical_help"})
            return self._with_proposed(base, ctx)

        if ctx.channel == "force_speak" or ctx.force_speak:
            base = {
                "observe",
                "micro_presence",
                "indirect_presence",
                "withdraw",
                "hesitate",
                "curious_question",
                "inner_whim",
                "react",
                "practical_help",
            }
            return self._with_proposed(base, ctx)

        # Autonomous: mặc định rất ít social action. ERIS không phải loa phường.
        base = {
            "no_speech",
            "observe",
            "micro_observation",
            "micro_presence",
            "indirect_presence",
            "withdraw",
            "suppress",
            "protect",
            "inner_whim",
            "random_chatter",
            "light_muse",
            "tease",
            "reengagement",
            "practical_help",
        }
        if self._goal_can_intervene(ctx):
            base.update({"guarded_reply", "soft_boundary", "reengagement"})
        return self._with_proposed(base, ctx)

    def _with_proposed(self, base: set[str], ctx: ActionContext) -> tuple[str, ...]:
        proposed = _clean(ctx.proposed_speech_act)
        intent_action = self._intent_to_action(ctx.proposed_intent)
        if proposed in ACTION_SPACE:
            base.add(proposed)
        if intent_action in ACTION_SPACE:
            base.add(intent_action)
        return tuple(action for action in ACTION_SPACE if action in base)

    def _intent_to_action(self, intent: str) -> str:
        intent = _clean(intent)
        return {
            "system_warning": "protect",
            "screen_observation": "observe",
            "playful_aside": "tease",
            "brief_ack": "mirror",
            "curious_question": "curious_question",
            "social_presence": "micro_presence",
            "presence_maintenance": "micro_presence",
            "re_engagement": "reengagement",
            "micro_observation": "micro_observation",
            "inner_whim": "inner_whim",
            "random_chatter": "random_chatter",
            "light_muse": "light_muse",
            "ambient_comment": "micro_presence",
            "companionship_ping": "micro_presence",
            "micro_story": "light_muse",
            "practical_help": "practical_help",
            "technical_help": "practical_help",
        }.get(intent, "")

    def _apply_base(self, score: ActionScore, ctx: ActionContext) -> None:
        # Base cực nhẹ. Phần lớn quyết định đến từ context.
        if score.action == "no_speech":
            score.add(0.05, "silence_is_valid", "base")
        if score.action in {"mirror", "react"} and ctx.channel == "chat":
            score.add(0.22, "chat_needs_direct_response", "base")
        if score.action == "observe" and ctx.has_concrete_signal:
            score.add(0.22, "grounded_signal_available", "base")
        if score.action == "practical_help":
            score.add(0.08, "practical_help_available", "base")
        if score.action in {"withdraw", "suppress", "hesitate"}:
            score.add(0.04, "restraint_is_allowed", "base")

    def _apply_intent_bias(self, score: ActionScore, ctx: ActionContext) -> None:
        proposed = _clean(ctx.proposed_speech_act)
        intent_action = self._intent_to_action(ctx.proposed_intent)
        if proposed == score.action:
            score.add(0.42, "proposed_speech_act_bias")
        elif proposed in SCREEN_CLAIM_ACTIONS and score.action in SCREEN_CLAIM_ACTIONS:
            score.add(-0.20, "prefer_specific_screen_speech_act", "risk")
        if intent_action == score.action and not (
            proposed in SCREEN_CLAIM_ACTIONS and proposed != "observe" and score.action == "observe"
        ):
            score.add(0.34, "proposed_intent_bias")

    def _apply_channel_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        if ctx.channel == "chat":
            if self._looks_like_question(ctx.user_text):
                if self._is_vague_question(ctx.user_text):
                    if score.action == "ask":
                        score.add(0.42, "vague_question_needs_clarification", "pressure")
                    if score.action == "mirror":
                        score.add(-0.16, "vague_question_not_enough_to_answer", "risk")
                else:
                    if score.action in {"mirror", "react"}:
                        score.add(0.36, "answer_first_question", "pressure")
                    if score.action == "ask":
                        score.add(-0.22, "do_not_answer_question_with_question", "risk")
            else:
                if score.action in {"mirror", "react"}:
                    score.add(0.24, "chat_turn_needs_grounded_reply", "pressure")

        if ctx.channel == "force_speak" or ctx.force_speak:
            if ctx.has_concrete_signal and score.action in {"observe", "telemetry_comment", "vision_comment", "micro_observation"}:
                score.add(0.46, "force_speak_with_signal", "pressure")
            if not ctx.has_concrete_signal:
                if score.action in {"micro_presence", "indirect_presence", "hesitate", "withdraw"}:
                    score.add(0.34, "force_speak_low_signal_presence", "pressure")
                if score.action == "observe":
                    score.add(-0.55, "low_signal_observe_would_fabricate", "risk")

        if ctx.channel == "autonomous":
            if self._has_note(ctx, "speech_source=meaning") and self._has_note(ctx, "meaning_reaction=quiet_observe"):
                if score.action == "inner_whim":
                    score.add(0.74, "meaning_quiet_observe_surfaces_as_inner_whim", "pressure")
                if score.action == "micro_presence":
                    score.add(-0.12, "meaning_quiet_observe_not_plain_presence", "risk")
            meaning_shift = self._meaning_shift(ctx)
            if not meaning_shift:
                if score.action == "no_speech":
                    score.add(0.34, "no_meaning_shift", "pressure")
                if score.action in FREEFORM_SOCIAL_ACTIONS | SCREEN_CLAIM_ACTIONS and _clean(ctx.proposed_speech_act) != score.action:
                    score.add(-0.28, "autonomous_needs_meaning_shift", "risk")
            else:
                if score.action in {"observe", "micro_observation", "micro_presence"}:
                    score.add(0.24, "meaning_shift_allows_small_surface", "pressure")

    def _apply_appraisal_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        threat = _num(getattr(ctx.appraisal, "threat", 0.0))
        certainty = _num(getattr(ctx.appraisal, "certainty", 0.5), 0.5)
        tenderness = _num(getattr(ctx.appraisal, "tenderness", 0.0))
        protectiveness = _num(getattr(ctx.appraisal, "protectiveness", 0.0))
        amusement = _num(getattr(ctx.appraisal, "amusement", 0.0))
        fatigue = _num(getattr(ctx.appraisal, "fatigue", 0.0))

        if threat >= 0.60 or protectiveness >= 0.66:
            if score.action in {"protect", "soft_boundary"}:
                score.add(0.42, "threat_or_protectiveness", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS:
                score.add(-0.32, "threat_reduces_chatter", "risk")

        if certainty <= 0.32:
            if score.action in {"hesitate", "ask", "withdraw", "micro_presence"}:
                score.add(0.20, "low_certainty", "pressure")
            if score.action in SCREEN_CLAIM_ACTIONS:
                score.add(-0.30, "low_certainty_screen_claim", "risk")

        if tenderness >= 0.52:
            if score.action in {"guarded_reply", "indirect_presence", "reassure"}:
                score.add(0.24, "tenderness_needs_restrained_warmth", "pressure")
            if score.action in {"random_chatter", "tease"}:
                score.add(-0.16, "tenderness_not_play_noise", "risk")

        if amusement >= 0.45 and score.action == "tease":
            score.add(0.20, "amusement_supports_dry_tease", "pressure")

        if fatigue >= 0.55:
            if score.action in {"no_speech", "withdraw", "suppress"}:
                score.add(0.24, "fatigue_prefers_low_output", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS:
                score.add(-0.24, "fatigue_reduces_expressive_action", "fatigue")

    def _apply_conversation_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        mode = _clean(getattr(ctx.conversation_dynamics, "mode", ""))
        pressure = _num(getattr(ctx.conversation_dynamics, "conversation_pressure", 0.0))
        tension = _num(getattr(ctx.conversation_dynamics, "semantic_tension", 0.0))
        last_failure = getattr(ctx.conversation_dynamics, "last_failure", None)
        failure_type = _clean(getattr(last_failure, "type", ""))

        if mode == "repair":
            if score.action in {"mirror", "react", "hesitate", "meta_reply"}:
                score.add(0.30 + 0.20 * pressure, "repair_mode_answer_directly", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS or score.action in {"reassure", "relational_checkin"}:
                score.add(-0.45, "repair_mode_no_performance", "risk")
            if failure_type == "underacted" and score.action in {"mirror", "react"}:
                score.add(0.18, "previous_underacted_do_the_work", "pressure")

        if mode == "compress":
            if score.action in {"mirror", "react"}:
                score.add(0.22, "compress_mode_direct_reply", "pressure")
            if score.action in {"ask", "meta_reply", "inner_whim", "light_muse"}:
                score.add(-0.25, "compress_mode_reduce_extra", "risk")

        if mode == "execute":
            if score.action in {"mirror", "react"}:
                score.add(0.28, "execute_mode_do_task", "pressure")
            if score.action in {"ask", "curious_question", "inner_whim"}:
                score.add(-0.22, "execute_mode_no_detour", "risk")

        if tension >= 0.55:
            if score.action in {"hesitate", "guarded_reply", "soft_boundary"}:
                score.add(0.16, "semantic_tension_needs_care", "pressure")

    def _apply_relationship_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        rel = ctx.relationship_dynamics
        dignity = _num(getattr(rel, "dignity_defense", 0.0))
        overread = _num(getattr(rel, "overread_correction", 0.0))
        technical_respect = _num(getattr(rel, "technical_respect", 0.0))
        attachment_visibility = _num(getattr(rel, "attachment_visibility", 0.0))
        preferred_distance = _num(getattr(rel, "preferred_distance", 0.0))

        if dignity >= 0.45 or preferred_distance >= 0.60:
            if score.action in {"guarded_reply", "soft_boundary", "withdraw"}:
                score.add(0.22, "dignity_or_distance_pressure", "pressure")
            if score.action in {"reassure", "relational_checkin", "inner_whim"}:
                score.add(-0.28, "distance_reduces_attachment_surface", "risk")

        if overread >= 0.35:
            if score.action in {"inner_whim", "relational_checkin", "curious_question"}:
                score.add(-0.30, "overread_correction_reduces_symbolic_guess", "risk")
            if score.action in {"mirror", "react", "ask"}:
                score.add(0.12, "overread_correction_prefers_grounded_response", "pressure")

        if technical_respect >= 0.35 and ctx.channel == "chat":
            if score.action in {"mirror", "react"}:
                score.add(0.18, "technical_respect_directness", "pressure")
            if score.action in {"inner_whim", "tease", "random_chatter"}:
                score.add(-0.25, "technical_thread_no_noise", "risk")

        if attachment_visibility >= 0.50:
            if score.action in {"guarded_reply", "indirect_presence"}:
                score.add(0.14, "attachment_visibility_but_restrained", "pressure")

    def _apply_goal_persistence_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        goal = ctx.goal_state
        if not bool(getattr(goal, "active", False)):
            return

        strength = _num(getattr(goal, "strength", 0.0))
        urgency = _num(getattr(goal, "urgency", 0.0))
        confidence = _num(getattr(goal, "confidence", 0.0))
        actionability = _num(getattr(goal, "actionability", 0.0))
        intervention = _num(getattr(goal, "intervention_permission", 0.0))
        can_intervene = bool(getattr(goal, "can_intervene", False))
        goal_type = _clean(getattr(goal, "goal_type", ""))

        continuity = strength * max(0.25, confidence)
        if score.action in {"micro_presence", "indirect_presence", "observe"}:
            score.add(0.10 * continuity, "goal_continuity_background", "pressure")

        if ctx.channel == "chat" and goal_type in {"concrete_task", "debug_thread", "correction_thread", "review_request"}:
            if score.action in {"mirror", "react"}:
                score.add(0.12 * continuity, "active_goal_direct_work_context", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS:
                score.add(-0.10 * continuity, "active_goal_reduces_social_detour", "risk")

        if ctx.channel == "autonomous":
            if can_intervene:
                permission = max(intervention, actionability) * max(urgency, 0.35)
                if score.action in {"reengagement", "guarded_reply", "soft_boundary"}:
                    score.add(0.16 * permission, "goal_can_intervene_gently", "pressure")
                if score.action == "no_speech" and urgency >= 0.58 and confidence >= 0.50:
                    score.add(-0.08 * permission, "goal_intervention_permission_reduces_silence", "risk")
            else:
                if score.action in {"reengagement", "curious_question", "relational_checkin"}:
                    score.add(-0.18 * continuity, "goal_background_only_no_proactive_pull", "risk")
                if score.action in {"no_speech", "withdraw", "suppress"}:
                    score.add(0.08 * (1.0 - intervention), "goal_background_prefers_quiet_continuity", "pressure")

    def _apply_memory_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        mem = self._memory(ctx)
        if score.action in {"micro_presence", "indirect_presence", "observe"}:
            score.add(0.20 * mem.continuity_pressure, "continuity_pressure", "pressure")
        if score.action in {"inner_whim", "light_muse", "random_chatter"}:
            score.add(0.18 * mem.boredom_pressure, "boredom_seeks_small_shift", "pressure")
        if score.action in {"no_speech", "withdraw", "suppress"}:
            score.add(0.18 * mem.exposure_recoil, "exposure_recoil", "pressure")
        if score.action in FREEFORM_SOCIAL_ACTIONS:
            score.add(-0.28 * mem.social_fatigue, "social_fatigue", "fatigue")

    def _apply_impulse_arbitration_pressure(self, score: ActionScore, ctx: ActionContext) -> None:
        """Bias action utility bằng full ArbitrationReport.

        Đây là bước "nối sâu": ActionUtility không chỉ nghe
        proposed_speech_act nữa, mà đọc được impulse nào thắng và các impulse thua
        sát nút. Nhờ vậy scene_curiosity tạo micro_observation ngắn, technical_help
        tạo practical_help, body_only giữ im + body bias, còn silence không bị biến
        thành câu social vô cớ. Nếu không có báo cáo thì hàm này im, giữ tương thích.
        """
        report = self._impulse_report(ctx)
        if not report:
            return
        selected_name = self._selected_impulse_name(ctx)
        selected_total = self._selected_impulse_total(ctx)
        selected_action = self._impulse_to_action(selected_name)
        silence_total = self._candidate_impulse_total(ctx, "silence_impulse")
        body_total = self._candidate_impulse_total(ctx, "body_only_impulse")

        if selected_action and score.action == selected_action:
            score.add(0.18 + selected_total * 0.34, f"impulse_winner:{selected_name}", "pressure")

        # Nếu silence sát nút, giảm các hành vi kéo chú ý. Đây là cách mềm hơn
        # nhiều so với hard cooldown kiểu đồng hồ báo thức mặc váy cognitive.
        if silence_total and selected_total - silence_total <= 0.10:
            if score.action in {"curious_question", "reengagement", "random_chatter", "relational_checkin"}:
                score.add(-0.26, "silence_close_runner_up_reduce_pull", "risk")
            if score.action in {"micro_observation", "micro_presence", "inner_whim", "light_muse"}:
                score.add(-0.08, "silence_close_runner_up_keep_tiny", "risk")

        if selected_name == "silence_impulse":
            if score.action == "no_speech":
                score.add(0.34 + selected_total * 0.20, "intentional_silence_winner", "pressure")
            elif score.action in FREEFORM_SOCIAL_ACTIONS | SCREEN_CLAIM_ACTIONS | {"micro_presence", "reengagement"}:
                score.add(-0.30, "silence_winner_blocks_surface_noise", "risk")

        elif selected_name == "body_only_impulse":
            if score.action == "no_speech":
                score.add(0.26 + body_total * 0.16, "body_only_prefers_no_bubble", "pressure")
            if score.action in {"indirect_presence", "micro_presence"}:
                score.add(0.08, "body_only_allows_low_presence_if_forced", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS | SCREEN_CLAIM_ACTIONS:
                score.add(-0.24, "body_only_not_verbal_surface", "risk")

        elif selected_name == "scene_curiosity_impulse":
            if score.action == "micro_observation":
                score.add(0.20, "scene_curiosity_wants_grounded_micro_line", "pressure")
            if score.action == "curious_question":
                score.add(-0.24, "scene_curiosity_no_intrusive_question", "risk")
            if score.action in {"random_chatter", "light_muse", "inner_whim"}:
                score.add(-0.10, "scene_curiosity_prefers_scene_anchor", "risk")

        elif selected_name == "technical_help_impulse":
            if score.action == "practical_help":
                score.add(0.30 + selected_total * 0.24, "technical_impulse_competence_wins", "pressure")
            if score.action in FREEFORM_SOCIAL_ACTIONS | {"tease", "micro_presence", "reengagement"}:
                score.add(-0.34, "technical_impulse_no_personality_noise", "risk")
            if score.action == "no_speech" and selected_total >= 0.62:
                score.add(-0.18, "technical_impulse_reduces_silence", "risk")

        elif selected_name in {"inner_whim_impulse", "micro_story_impulse", "companionship_impulse"}:
            if selected_name == "inner_whim_impulse" and score.action == "inner_whim":
                score.add(0.18, "inner_whim_winner", "pressure")
            if selected_name == "micro_story_impulse" and score.action == "light_muse":
                score.add(0.18, "micro_story_winner", "pressure")
            if selected_name == "companionship_impulse" and score.action == "micro_presence":
                score.add(0.16, "companionship_winner", "pressure")
            if score.action == "curious_question":
                score.add(-0.16, "internal_impulse_no_question_pull", "risk")

    def _impulse_report(self, ctx: ActionContext) -> dict[str, Any]:
        report = getattr(ctx, "impulse_arbitration", None) or None
        if isinstance(report, Mapping):
            return dict(report)
        core = getattr(ctx, "speech_core", None)
        impulse = getattr(core, "speech_impulse", None)
        report = getattr(impulse, "arbitration_report", None) if impulse is not None else None
        return dict(report) if isinstance(report, Mapping) else {}

    def _body_bias_hint(self, ctx: ActionContext) -> dict[str, Any]:
        hint = getattr(ctx, "body_bias_hint", None) or None
        if isinstance(hint, Mapping):
            return dict(hint)
        core = getattr(ctx, "speech_core", None)
        impulse = getattr(core, "speech_impulse", None)
        hint = getattr(impulse, "body_bias_hint", None) if impulse is not None else None
        return dict(hint) if isinstance(hint, Mapping) else {}

    def _selected_impulse_name(self, ctx: ActionContext) -> str:
        report = self._impulse_report(ctx)
        selected = report.get("selected") if isinstance(report, Mapping) else None
        if isinstance(selected, Mapping):
            return str(selected.get("name") or "")
        core = getattr(ctx, "speech_core", None)
        impulse = getattr(core, "speech_impulse", None)
        return str(getattr(impulse, "selected_impulse", "") or "") if impulse is not None else ""

    def _selected_impulse_total(self, ctx: ActionContext) -> float:
        report = self._impulse_report(ctx)
        selected = report.get("selected") if isinstance(report, Mapping) else None
        if isinstance(selected, Mapping):
            return _num(selected.get("total", 0.0))
        return 0.0

    def _selected_impulse_has_evidence(self, ctx: ActionContext) -> bool:
        report = self._impulse_report(ctx)
        selected = report.get("selected") if isinstance(report, Mapping) else None
        evidence = selected.get("evidence", ()) if isinstance(selected, Mapping) else ()
        return bool(evidence)

    def _candidate_impulse_total(self, ctx: ActionContext, name: str) -> float:
        report = self._impulse_report(ctx)
        candidates = report.get("candidates", ()) if isinstance(report, Mapping) else ()
        if not isinstance(candidates, (list, tuple)):
            return 0.0
        for item in candidates:
            if isinstance(item, Mapping) and str(item.get("name") or "") == name:
                return _num(item.get("total", 0.0))
        return 0.0

    def _impulse_score_notes(self, ctx: ActionContext) -> tuple[str, ...]:
        report = self._impulse_report(ctx)
        candidates = report.get("candidates", ()) if isinstance(report, Mapping) else ()
        notes: list[str] = []
        if isinstance(candidates, (list, tuple)):
            for item in candidates[:8]:
                if isinstance(item, Mapping):
                    notes.append(f"impulse.{item.get('name', 'unknown')}={_num(item.get('total', 0.0)):.2f}")
        return tuple(notes)

    def _impulse_pressure_notes(self, ctx: ActionContext) -> tuple[str, ...]:
        selected = self._selected_impulse_name(ctx) or "none"
        scores = self._impulse_score_notes(ctx)
        hint = self._body_bias_hint(ctx)
        body = "body_bias_hint=" + ",".join(f"{k}:{v}" for k, v in list(hint.items())[:5]) if hint else "body_bias_hint=none"
        return (f"selected_impulse={selected}", *(scores[:6]), body)

    def _impulse_to_action(self, name: str) -> str:
        return {
            "silence_impulse": "no_speech",
            "body_only_impulse": "no_speech",
            "scene_curiosity_impulse": "micro_observation",
            "technical_help_impulse": "practical_help",
            "inner_whim_impulse": "inner_whim",
            "micro_story_impulse": "light_muse",
            "companionship_impulse": "micro_presence",
        }.get(str(name or ""), "")

    def _apply_rhythm(self, score: ActionScore, ctx: ActionContext) -> None:
        phase = self._memory(ctx).rhythm_phase
        action = score.action
        if phase == "watching":
            if action in {"observe", "micro_presence", "indirect_presence", "no_speech"}:
                score.add(0.18, "watching_phase_low_pressure", "rhythm")
            if action in {"random_chatter", "reengagement", "curious_question"}:
                score.add(-0.18, "watching_phase_no_pull", "rhythm")
        elif phase == "touch":
            if action in {"micro_presence", "indirect_presence", "hesitate", "observe"}:
                score.add(0.22, "touch_phase_small_response", "rhythm")
        elif phase == "exposure":
            if action in {"withdraw", "suppress", "no_speech", "hesitate"}:
                score.add(0.24, "after_exposure_recoil", "rhythm")
            if action in {"reassure", "relational_checkin", "inner_whim"}:
                score.add(-0.30, "do_not_chain_exposure", "rhythm")
        elif phase == "recoil":
            if action in {"withdraw", "suppress", "no_speech", "guarded_reply"}:
                score.add(0.26, "recoil_phase", "rhythm")
            if action in FREEFORM_SOCIAL_ACTIONS:
                score.add(-0.36, "recoil_no_social_push", "rhythm")
        elif phase == "withdrawn":
            if action in {"no_speech", "observe", "micro_presence"}:
                score.add(0.16, "withdrawn_phase_minimal", "rhythm")
        elif phase == "dormant":
            if action in {"no_speech", "micro_presence", "light_muse"}:
                score.add(0.20, "dormant_small_shift", "rhythm")
            if action in {"reengagement", "random_chatter"}:
                score.add(-0.18, "dormant_no_attention_grab", "rhythm")
        elif phase == "execute":
            if action in {"mirror", "react", "protect", "soft_boundary"}:
                score.add(0.12, "execute_phase_direct", "rhythm")

    def _apply_risk_penalty(self, score: ActionScore, ctx: ActionContext) -> None:
        action = score.action
        if action in SCREEN_CLAIM_ACTIONS and not ctx.has_concrete_signal:
            # Một ngoại lệ nhỏ: micro_observation từ scene_curiosity có evidence nằm
            # trong impulse report, không nhất thiết nằm trong concrete_signals cũ.
            if action == "micro_observation" and self._selected_impulse_name(ctx) == "scene_curiosity_impulse" and self._selected_impulse_has_evidence(ctx):
                score.add(0.10, "scene_impulse_supplies_grounding", "pressure")
            else:
                score.add(-0.60, "screen_action_without_evidence", "risk")
        if action == "practical_help" and not (ctx.explicit_user_pull or ctx.has_concrete_signal or self._selected_impulse_name(ctx) == "technical_help_impulse"):
            score.add(-0.45, "practical_help_without_task_evidence", "risk")
        if action in FREEFORM_SOCIAL_ACTIONS and ctx.channel == "autonomous" and not self._meaning_shift(ctx):
            if self._has_internal_impulse(ctx):
                score.add(0.18, "endogenous_impulse_can_surface_without_external_shift", "pressure")
            else:
                score.add(-0.34, "freeform_without_shift", "risk")
        if action in {"reassure", "relational_checkin"} and ctx.channel != "chat":
            score.add(-0.18, "relational_checkin_needs_user_context", "risk")
        if action == "ask" and ctx.channel == "chat" and self._looks_like_question(ctx.user_text) and not self._is_vague_question(ctx.user_text):
            score.add(-0.22, "unneeded_clarification", "risk")
        if action == "no_speech" and ctx.explicit_user_pull:
            score.add(-0.70, "explicit_user_pull_requires_surface", "risk")

    def _apply_repetition_penalty(self, score: ActionScore, ctx: ActionContext) -> None:
        mem = self._memory(ctx)
        count = mem.action_count(score.action, window=8)
        if count:
            weight = 0.18
            if score.action in FREEFORM_SOCIAL_ACTIONS:
                weight = 0.25
            if score.action in {"no_speech", "observe"}:
                weight = 0.10
            score.add(-min(0.70, count * weight), f"recent_action_repeat:{count}", "repetition")

        family = ctx.family
        if family:
            f_count = mem.family_count(family, window=8)
            if f_count >= 2 and score.action not in {"no_speech", "withdraw", "suppress"}:
                score.add(-min(0.42, f_count * 0.12), f"recent_family_repeat:{family}:{f_count}", "repetition")

        habituation = mem.habituation.get(score.action, 0.0)
        if habituation > 0:
            score.add(-0.38 * habituation, f"habituation:{habituation:.2f}", "repetition")

        elapsed = mem.seconds_since_action(ctx.now)
        cooldown = ACTION_COOLDOWN_SECONDS.get(score.action, 0.0)
        if cooldown > 0 and elapsed < cooldown:
            # Penalty mềm theo tỉ lệ còn lại của cooldown.
            remaining_ratio = 1.0 - max(0.0, elapsed / cooldown)
            score.add(-0.30 * remaining_ratio, f"soft_cooldown:{elapsed:.0f}/{cooldown:.0f}s", "repetition")

    def _apply_fatigue_penalty(self, score: ActionScore, ctx: ActionContext) -> None:
        state_label = _clean(getattr(ctx.self_state, "state_label", ""))
        if state_label == "overloaded":
            if score.action in FREEFORM_SOCIAL_ACTIONS | {"reassure", "ask"}:
                score.add(-0.32, "self_overloaded", "fatigue")
            if score.action in {"no_speech", "withdraw", "suppress", "micro_presence"}:
                score.add(0.16, "overloaded_prefers_low_output", "pressure")

    def _memory(self, ctx: ActionContext) -> ActionMemoryState:
        return ctx.action_memory or ActionMemoryState()

    def _memory_pressure_notes(self, ctx: ActionContext) -> tuple[str, ...]:
        mem = self._memory(ctx)
        return (
            f"action_memory_phase={mem.rhythm_phase}",
            f"action_memory_fatigue={mem.social_fatigue:.2f}",
            f"action_memory_boredom={mem.boredom_pressure:.2f}",
            f"action_memory_recoil={mem.exposure_recoil:.2f}",
            f"action_memory_continuity={mem.continuity_pressure:.2f}",
        )

    def _goal_pressure_notes(self, ctx: ActionContext) -> tuple[str, ...]:
        goal = ctx.goal_state
        if not bool(getattr(goal, "active", False)):
            return ()
        return (
            "goal_active=1",
            f"goal_type={_clean(getattr(goal, 'goal_type', '')) or 'unknown'}",
            f"goal_strength={_num(getattr(goal, 'strength', 0.0)):.2f}",
            f"goal_urgency={_num(getattr(goal, 'urgency', 0.0)):.2f}",
            f"goal_intervention={_num(getattr(goal, 'intervention_permission', 0.0)):.2f}",
            f"goal_can_intervene={1 if bool(getattr(goal, 'can_intervene', False)) else 0}",
        )

    def _goal_can_intervene(self, ctx: ActionContext) -> bool:
        goal = ctx.goal_state
        return bool(getattr(goal, "active", False)) and bool(getattr(goal, "can_intervene", False))

    def _transition_reason(self, selected: ActionScore, ctx: ActionContext) -> str:
        mem = self._memory(ctx)
        reason = selected.reasons[0] if selected.reasons else "highest utility"
        return f"{mem.rhythm_phase}: {reason}"

    def _meaning_shift(self, ctx: ActionContext) -> bool:
        # Ưu tiên speech_core/notes nếu có. Không assume schema.
        for note in ctx.notes or ():
            text = str(note or "").lower()
            if "meaning_shift=true" in text:
                return True
            if "meaning_shift=false" in text:
                return False
        value = getattr(ctx.speech_core, "meaning_shift", None)
        if value is not None:
            return bool(value)
        value = getattr(ctx.broadcast, "meaning_shift", None)
        if value is not None:
            return bool(value)
        return bool(ctx.has_concrete_signal)

    def _has_note(self, ctx: ActionContext, marker: str) -> bool:
        needle = str(marker or "").strip().lower()
        if not needle:
            return False
        return any(needle in str(note or "").lower() for note in ctx.notes or ())

    def _has_internal_impulse(self, ctx: ActionContext) -> bool:
        # SpeechCore exposes endogenous impulses through speech_impulse. Notes are
        # kept as a fallback for older call-sites. This prevents autonomous inner
        # life from being punished as an ungrounded screen claim merely because
        # MeaningLayer did not report an external semantic shift.
        for note in ctx.notes or ():
            lowered = str(note or "").lower()
            if "spontaneous_life" in lowered or "endogenous" in lowered:
                return True
        core = getattr(ctx, "speech_core", None)
        impulse = getattr(core, "speech_impulse", None)
        if impulse is None:
            return False
        source = str(getattr(impulse, "source", "") or "").lower()
        layer = str(getattr(impulse, "source_layer", "") or "").lower()
        act = str(getattr(impulse, "suggested_speech_act", "") or "").lower()
        pressure = _num(getattr(impulse, "surface_pressure", 0.0))
        needs_external = bool(getattr(impulse, "needs_external_evidence", False))
        return (source == "endogenous" or layer == "spontaneous_life") and not needs_external and act not in {"", "no_speech"} and pressure >= 0.35

    def _looks_like_question(self, text: str) -> bool:
        text = _normalize_text(text)
        if not text:
            return False
        if "?" in text:
            return True
        tokens = set(text.split())
        # Token-based để tránh match bẩn kiểu "giai đoạn" chứa "gi".
        vi = {"sao", "gi", "gì", "nao", "nào", "ai", "dau", "đâu", "khong", "không", "chua", "chưa"}
        en = {"why", "what", "how", "where", "when", "who"}
        return bool(tokens & (vi | en))

    def _is_vague_question(self, text: str) -> bool:
        text_norm = _normalize_text(text)
        tokens = [token for token in text_norm.replace("?", " ").split() if token]
        if not tokens:
            return True
        # Các câu 2 token nhưng rất rõ về hành động thì không coi là vague.
        action_terms = {"fix", "sua", "sửa", "tao", "tạo", "viet", "viết", "gui", "gửi", "doc", "đọc"}
        if len(tokens) <= 2 and not (set(tokens) & action_terms):
            return True
        return False

    def _looks_like_technical_request(self, text: str) -> bool:
        text_norm = _normalize_text(text)
        technical_terms = {
            "code", "file", "fix", "bug", "class", "dataclass", "python", "c#", "godot",
            "ham", "hàm", "loi", "lỗi", "runtime", "planner", "memory", "utility",
        }
        return bool(set(text_norm.split()) & technical_terms)

    def _tie_break_priority(self, action: str) -> int:
        # Khi bằng điểm, ưu tiên hành vi thấp áp lực hơn. Trật tự này cố ý bảo thủ.
        priority = {
            "system_action": 100,
            "refuse": 95,
            "protect": 90,
            "mirror": 80,
            "react": 78,
            "ask": 70,
            "observe": 65,
            "micro_observation": 62,
            "micro_presence": 60,
            "inner_whim": 59,
            "light_muse": 58,
            "random_chatter": 57,
            "indirect_presence": 58,
            "hesitate": 55,
            "withdraw": 52,
            "suppress": 50,
            "no_speech": 48,
        }
        return priority.get(action, 40)


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric:
        return default
    return max(0.0, min(1.0, numeric))


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())
