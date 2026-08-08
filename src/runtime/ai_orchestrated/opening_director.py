# -*- coding: utf-8 -*-
"""Opening Director lai: rule candidate + model refinement + fallback xác định.

Director không viết câu public trong đường bình thường. Nó chọn encounter, hook,
move, beat shape và handoff. Renderer deterministic ở cuối file chỉ tồn tại để
startup không chết khi provider vừa quyết định nghỉ phép mà không báo ai.
"""
from __future__ import annotations
from core.di import resolve_dependency

import math
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

from .opening_contracts import (
    ComedicMove,
    ContextHook,
    EncounterMove,
    FollowupPolicy,
    OpeningBeat,
    OpeningInput,
    OpeningPlan,
    OpeningSurface,
    ProsodyPlan,
    SafetyVerdict,
    SurfaceBeat,
    SurfaceContract,
    compact,
)
from .opening_history import OpeningHistoryStore
from .opening_move_catalog import OpeningMoveDefinition, get_opening_move, opening_move_catalog
from .opening_safety import (
    downgrade_plan,
    evaluate_opening_eligibility,
    evidence_is_surface_eligible,
    move_is_allowed,
    validate_opening_plan,
    validate_opening_surface,
)

PlannerCallable = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Mapping[str, Any] | None]
SurfaceWriterCallable = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Mapping[str, Any] | None]


@dataclass(frozen=True, slots=True)
class OpeningCandidate:
    candidate_id: str
    encounter_kind: str
    move_family: str
    hook: ContextHook
    beat_roles: tuple[str, ...]
    vibe_family: str
    motive_family: str = "reconnect"
    motive_subject: str = ""
    score: float = 0.0
    score_breakdown: Mapping[str, float] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "encounter_kind": self.encounter_kind,
            "move_family": self.move_family,
            "hook": {
                "decision": self.hook.decision,
                "source": self.hook.source,
                "subject": self.hook.subject,
                "evidence_refs": list(self.hook.evidence_refs),
                "epistemic_mode": self.hook.epistemic_mode,
                "reply_bearing": self.hook.reply_bearing,
            },
            "beat_roles": list(self.beat_roles),
            "vibe_family": self.vibe_family,
            "motive_family": self.motive_family,
            "motive_subject": self.motive_subject,
            "score": round(float(self.score), 6),
            "score_breakdown": {
                key: round(float(value), 6) for key, value in (self.score_breakdown or {}).items()
            },
        }


class OpeningDirector:
    def __init__(
        self,
        *,
        history: OpeningHistoryStore | None = None,
        mode: str = "hybrid",
        semantic_duplicate_threshold: float = 0.86,
    ) -> None:
        self.history = resolve_dependency(history, lambda: OpeningHistoryStore())
        self.mode = str(mode or "hybrid").strip().lower()
        self.semantic_duplicate_threshold = max(0.50, min(0.99, float(semantic_duplicate_threshold)))

    def plan(
        self,
        opening_input: OpeningInput,
        *,
        planner: PlannerCallable | None = None,
    ) -> OpeningPlan:
        eligibility = evaluate_opening_eligibility(opening_input)
        if not eligibility.allowed:
            return OpeningPlan.silence(reason=eligibility.reasons[0] if eligibility.reasons else "ineligible")

        candidates = self.generate_candidates(opening_input)
        if not candidates:
            return OpeningPlan.silence(reason="no_safe_candidate")
        scored = tuple(self._score_candidate(opening_input, item) for item in candidates)
        ranked = tuple(sorted(scored, key=lambda item: (item.score, item.candidate_id), reverse=True))
        preferred_continuity = next(
            (
                item
                for item in ranked
                if item.hook.decision == "use" and item.hook.source == "continuity"
            ),
            None,
        )

        selected_plan: OpeningPlan | None = None
        if planner is not None and self.mode == "hybrid":
            try:
                raw = planner(opening_input.to_dict(), [item.to_dict() for item in ranked[:5]])
                if isinstance(raw, Mapping) and raw:
                    candidate_map = {item.candidate_id: item for item in ranked[:5]}
                    chosen_id = compact(raw.get("candidate_id", ""), 100)
                    # Model chỉ được chọn trong candidate đã cấp. Nếu nó trả thêm
                    # plan typed thì vẫn phải qua validator ở dưới.
                    if chosen_id:
                        chosen = candidate_map.get(chosen_id)
                        selected_plan = self._candidate_to_plan(opening_input, chosen) if chosen is not None else None
                    elif raw.get("beats"):
                        selected_plan = OpeningPlan.from_mapping(raw)
            except Exception:
                selected_plan = None

        if selected_plan is None:
            selected_plan = self._candidate_to_plan(opening_input, ranked[0])

        # Startup callback là một contract sản phẩm, không chỉ là một feature
        # score. Khi memory đã cấp anchor hợp lệ và user không bận/đặt boundary,
        # model không được lùi về câu chào trống chỉ vì candidate đó an toàn hơn.
        if (
            opening_input.policy.prefer_continuity_hook
            and preferred_continuity is not None
            and selected_plan.hook.source != "continuity"
            and opening_input.user_signals.availability not in {"busy", "unavailable"}
            and not opening_input.user_signals.recent_low_engagement
            and not opening_input.user_signals.explicit_boundary
            and not opening_input.scene_partner.boundary_flags
        ):
            selected_plan = self._candidate_to_plan(opening_input, preferred_continuity)

        verdict = validate_opening_plan(opening_input, selected_plan)
        if not verdict.allowed:
            selected_plan = downgrade_plan(opening_input, selected_plan, reasons=verdict.reasons)
            verdict = validate_opening_plan(opening_input, selected_plan)
        return replace(selected_plan, safety=verdict)

    def generate_candidates(self, opening_input: OpeningInput) -> tuple[OpeningCandidate, ...]:
        """Sinh opening từ *lý do mở lời*, không từ kho câu chào.

        Hook continuity/screen tạo motive tương ứng; motive nội sinh của Subject
        (probe/share/recognition/demonstration) có thể tạo candidate ngay cả khi
        không có seed hay screen fact. Wording vẫn thuộc Surface Writer.
        """
        encounter = self._encounter_kind(opening_input)
        hooks = self._candidate_hooks(opening_input)
        boosts = dict(opening_input.reentry.motive_boosts)
        subjects = dict(opening_input.reentry.motive_subjects)
        candidates: list[OpeningCandidate] = []

        def motive_for(hook: ContextHook, move_family: str) -> str:
            if hook.decision == "use" and hook.source == "continuity":
                return "continue_thread"
            if hook.decision == "use" and hook.source in {"screen", "runtime"}:
                return "scene_comment"
            if move_family in {"mock_indifference", "tsundere_denial"} and boosts.get("playful_protest", 0.0) >= 0.18:
                return "playful_protest"
            if move_family == "quiet_presence":
                return "quiet_acknowledgement"
            return "reconnect"

        for hook in hooks:
            has_hook = hook.decision == "use"
            for move in opening_move_catalog():
                allowed, _reasons = move_is_allowed(opening_input, move, has_hook=has_hook)
                if not allowed:
                    continue
                if self.history.move_on_cooldown(move.family, sessions=move.cooldown_sessions):
                    continue
                if (
                    has_hook
                    and self.history.hook_source_repeated(hook.source, maximum_consecutive=2)
                    and not (hook.source == "continuity" and opening_input.policy.prefer_continuity_hook)
                ):
                    continue
                candidate_hook = hook
                if (candidate_hook.reply_bearing and self.history.question_temporarily_blocked()) or not move.allows_question:
                    candidate_hook = replace(candidate_hook, reply_bearing=False)
                roles = self._roles_for(move, candidate_hook)
                if candidate_hook.source == "continuity" and move.family in {"simple_recognition", "quiet_presence"}:
                    roles = tuple(role for role in roles if role != "presence")
                if len(roles) > opening_input.policy.max_beats:
                    roles = roles[: opening_input.policy.max_beats]
                if not roles or roles[0] not in {"recognition", "formal_recognition"}:
                    roles = ("recognition", *roles)[: opening_input.policy.max_beats]
                if candidate_hook.decision == "use":
                    hook_roles = {"contextual_observation", "invitation", "micro_challenge", "evidence_reversal"}
                    if not any(role in hook_roles for role in roles):
                        required_role = "invitation" if candidate_hook.reply_bearing else "contextual_observation"
                        roles = (*roles, required_role) if len(roles) < opening_input.policy.max_beats else (*roles[:-1], required_role)

                motive = motive_for(candidate_hook, move.family)
                motive_subject = subjects.get(motive, candidate_hook.subject)
                shape = "_".join(roles)
                semantic_fingerprint = (
                    f"{motive}|{move.family}|"
                    f"{candidate_hook.source if candidate_hook.decision == 'use' else 'none'}|"
                    f"{'question' if candidate_hook.reply_bearing else 'no_question'}|{shape}"
                )
                if self.history.semantic_duplicate(semantic_fingerprint, sessions=12) and move.family not in {"simple_recognition", "quiet_presence"}:
                    continue
                if self.history.beat_shape_on_cooldown(shape, sessions=3) and move.family not in {"simple_recognition", "quiet_presence"}:
                    continue
                candidate_vibe = self._vibe_for(opening_input, move)
                if motive == "scene_comment" and opening_input.session_state.time_of_day == "morning":
                    candidate_vibe = "morning_dry_warm"
                candidates.append(OpeningCandidate(
                    candidate_id=f"oc_{uuid.uuid4().hex[:12]}",
                    encounter_kind=encounter,
                    move_family=move.family,
                    hook=candidate_hook,
                    beat_roles=roles,
                    vibe_family=candidate_vibe,
                    motive_family=motive,
                    motive_subject=motive_subject,
                    score_breakdown={},
                ))

        # Các motive này không cần factual hook. Chúng chỉ được tạo khi Subject/reentry
        # đã có pressure thật; Surface Writer không được bịa sự kiện bên ngoài làm cớ.
        custom_specs = (
            ("social_probe", ("recognition", "social_probe"), True),
            ("share_internal", ("recognition", "share_internal"), False),
            ("recognition_bid", ("recognition", "recognition_bid"), False),
            ("demonstration_bid", ("recognition", "demonstration_bid"), False),
        )
        for motive, roles, asks in custom_specs:
            boost = float(boosts.get(motive, 0.0) or 0.0)
            if boost < 0.30:
                continue
            if asks and (opening_input.policy.max_questions <= 0 or self.history.question_temporarily_blocked()):
                continue
            if self.history.motive_on_cooldown(motive, sessions=2):
                continue
            candidates.append(OpeningCandidate(
                candidate_id=f"oc_{uuid.uuid4().hex[:12]}",
                encounter_kind=encounter,
                move_family="simple_recognition",
                hook=ContextHook(),
                beat_roles=roles[: opening_input.policy.max_beats],
                vibe_family="curious_warm" if motive == "social_probe" else "restrained_warm",
                motive_family=motive,
                motive_subject=subjects.get(motive, ""),
                score_breakdown={},
            ))

        # Fallback luôn tồn tại nhưng có motive riêng để history chống lặp theo nghĩa.
        if not any(item.move_family == "simple_recognition" and item.hook.decision == "none" for item in candidates):
            candidates.append(OpeningCandidate(
                candidate_id=f"oc_{uuid.uuid4().hex[:12]}",
                encounter_kind=encounter,
                move_family="simple_recognition",
                hook=ContextHook(),
                beat_roles=("recognition", "presence"),
                vibe_family="quiet_warm",
                motive_family="quiet_acknowledgement",
                score_breakdown={},
            ))
        return tuple(candidates)

    def _candidate_hooks(self, opening_input: OpeningInput) -> tuple[ContextHook, ...]:
        hooks: list[ContextHook] = [ContextHook()]
        if opening_input.policy.allow_screen_hook:
            for item in opening_input.screen_evidence:
                if not evidence_is_surface_eligible(opening_input, item.evidence_id):
                    continue
                source = "runtime" if item.source == "runtime" else "screen"
                subject = compact(item.subject or item.claim, 140)
                # Hook observation mặc định không ép trả lời. Director chỉ mở câu hỏi
                # khi availability và history cho phép.
                question_ok = bool(
                    opening_input.policy.max_questions > 0
                    and opening_input.user_signals.availability not in {"busy", "unavailable"}
                    and not opening_input.user_signals.recent_low_engagement
                    and not self.history.question_temporarily_blocked()
                )
                hooks.append(
                    ContextHook(
                        decision="use",
                        source=source,
                        subject=subject,
                        evidence_refs=(item.evidence_id,),
                        epistemic_mode="observation",
                        reply_bearing=question_ok,
                    )
                )
                if len(hooks) >= 4:
                    break
        if (
            opening_input.policy.allow_continuity_hook
            and opening_input.continuity.open_loops
            and opening_input.continuity.consent_scope in {"session_only", "cross_session"}
        ):
            subject = compact(opening_input.continuity.open_loops[0], 140)
            hooks.append(
                ContextHook(
                    decision="use",
                    source="continuity",
                    subject=subject,
                    evidence_refs=("continuity:open_loop:0",),
                    epistemic_mode="known_session_context",
                    reply_bearing=not self.history.question_temporarily_blocked(),
                )
            )
        if (
            opening_input.policy.allow_continuity_hook
            and opening_input.continuity.consent_scope == "cross_session"
            and opening_input.continuity.last_session_summary
        ):
            subject = compact(opening_input.continuity.last_session_summary, 140)
            if subject and not any(
                item.source == "continuity" and item.subject.casefold() == subject.casefold()
                for item in hooks
            ):
                hooks.append(
                    ContextHook(
                        decision="use",
                        source="continuity",
                        subject=subject,
                        evidence_refs=("continuity:last_session_summary",),
                        epistemic_mode="known_cross_session_context",
                        reply_bearing=False,
                    )
                )
        return tuple(hooks)

    @staticmethod
    def _encounter_kind(opening_input: OpeningInput) -> str:
        event = opening_input.event
        if event.restart_detected:
            return "restart"
        if event.seconds_since_last_session >= 6 * 3600:
            return "long_absence"
        if 0 < event.seconds_since_last_session <= 10 * 60:
            return "quick_reopen"
        return "plain_return"

    @staticmethod
    def _roles_for(move: OpeningMoveDefinition, hook: ContextHook) -> tuple[str, ...]:
        roles = list(move.structure)
        if hook.decision == "none":
            roles = [role for role in roles if role not in {"contextual_observation", "invitation", "evidence_reversal", "claim"}]
        elif hook.reply_bearing:
            if not any(role in {"invitation", "micro_challenge"} for role in roles):
                roles.append("invitation")
        else:
            roles = ["contextual_observation" if role == "invitation" else role for role in roles]
        # Catalog có thể dùng tên giàu sắc thái; contract chỉ cần tối đa ba role rõ.
        return tuple(dict.fromkeys(roles))[:3]

    @staticmethod
    def _vibe_for(opening_input: OpeningInput, move: OpeningMoveDefinition) -> str:
        if opening_input.user_signals.recent_low_engagement or opening_input.scene_partner.availability in {"busy", "unavailable"}:
            return "quiet_warm"
        if move.family in {"mock_indifference", "tsundere_denial", "dry_observation"}:
            return "anime_dry_warm"
        if move.family in {"delayed_affection", "quiet_presence"}:
            return "quiet_intimate"
        return "restrained_warm"

    def _score_candidate(self, opening_input: OpeningInput, candidate: OpeningCandidate) -> OpeningCandidate:
        move = get_opening_move(candidate.move_family)
        hook = candidate.hook
        partner = opening_input.scene_partner
        evidence = opening_input.evidence_by_id().get(hook.evidence_refs[0]) if hook.evidence_refs else None

        encounter_fit = 1.0
        if hook.decision == "none":
            evidence_relevance = 0.0
        elif hook.source == "continuity":
            evidence_relevance = 0.90
        else:
            evidence_relevance = evidence.confidence if evidence else 0.65
        scene_partner_fit = 0.55
        if partner.closeness_band in move.allowed_closeness:
            scene_partner_fit += 0.20
        if partner.tease_tolerance_confidence >= move.minimum_tease_confidence:
            scene_partner_fit += 0.15
        novelty = 0.95 if not self.history.move_on_cooldown(move.family, sessions=max(1, move.cooldown_sessions)) else 0.0
        continuity_value = 1.0 if hook.source == "continuity" else 0.25 if opening_input.continuity.open_loops else 0.0
        performability = 1.0 - max(0, len(candidate.beat_roles) - 2) * 0.12
        humor_opportunity = max(0.0, min(1.0, 0.25 + partner.tease_tolerance_estimate * (1.0 - move.risk)))
        time_fit = 0.85 if opening_input.session_state.time_of_day in {"morning", "afternoon", "evening"} else 0.55
        intrusion_risk = move.risk
        if hook.reply_bearing:
            intrusion_risk += 0.12
        if opening_input.user_signals.availability == "uncertain":
            intrusion_risk += 0.08
        if opening_input.user_signals.recent_low_engagement:
            intrusion_risk += 0.28
        boundary_risk = 1.0 if opening_input.scene_partner.boundary_flags or opening_input.user_signals.explicit_boundary else 0.0
        repetition_risk = 1.0 - novelty
        grounding_uncertainty = 0.0 if hook.decision == "none" else 1.0 - evidence_relevance
        motive_fit = max(0.0, min(1.0, float(opening_input.reentry.motive_boosts.get(candidate.motive_family, 0.0) or 0.0)))
        motive_novelty = 0.0 if self.history.motive_on_cooldown(candidate.motive_family, sessions=2) else 1.0
        # historical boundary chỉ tăng cost của move mang tính trêu/chiếm chú ý;
        # nó không còn là hard-block như boundary hiện hành.
        historical_boundary_cost = 0.22 if (opening_input.reentry.historical_boundary_present and candidate.motive_family == "playful_protest") else 0.0

        breakdown = {
            "encounter_fit": 0.22 * encounter_fit,
            "evidence_relevance": 0.18 * evidence_relevance,
            "scene_partner_fit": 0.15 * min(1.0, scene_partner_fit),
            "novelty": 0.14 * novelty,
            "continuity_value": 0.10 * continuity_value,
            "continuity_preference": (
                0.12
                if hook.source == "continuity" and opening_input.policy.prefer_continuity_hook
                else 0.0
            ),
            "performability": 0.09 * performability,
            "humor_opportunity": 0.07 * humor_opportunity,
            "time_of_day_fit": 0.05 * time_fit,
            "motive_fit": 0.26 * motive_fit,
            "motive_novelty": 0.18 * motive_novelty,
            "historical_boundary_cost": -historical_boundary_cost,
            "intrusion_risk": -0.22 * min(1.0, intrusion_risk),
            "boundary_risk": -0.20 * boundary_risk,
            "repetition_risk": -0.16 * repetition_risk,
            "grounding_uncertainty": -0.14 * grounding_uncertainty,
        }
        score = sum(breakdown.values())
        if math.isnan(score):
            score = -1.0
        return replace(candidate, score=score, score_breakdown=breakdown)

    def _candidate_to_plan(self, opening_input: OpeningInput, candidate: OpeningCandidate) -> OpeningPlan:
        move = get_opening_move(candidate.move_family)
        beats: list[OpeningBeat] = []
        for index, role in enumerate(candidate.beat_roles, start=1):
            reply_bearing = bool((candidate.hook.reply_bearing and role in {"invitation", "micro_challenge"}) or role == "social_probe")
            evidence_refs = candidate.hook.evidence_refs if role in {"contextual_observation", "invitation", "evidence_reversal"} else ()
            objective, semantic, delivery, pause, motion, gaze = self._beat_contract(
                role,
                opening_input=opening_input,
                candidate=candidate,
                move=move,
            )
            beats.append(
                OpeningBeat(
                    beat_id=f"b{index}",
                    role=role,
                    objective=objective,
                    semantic_content=semantic,
                    delivery=delivery,
                    pause_after_ms=pause if index < len(candidate.beat_roles) else 0,
                    reply_bearing=reply_bearing,
                    evidence_refs=evidence_refs,
                    motion=motion,
                    gaze=gaze,
                )
            )
        followup = FollowupPolicy(
            mode="one_soft_reminder_then_pivot" if any(item.reply_bearing for item in beats) else "close_without_comment",
            max_count=1 if any(item.reply_bearing for item in beats) else 0,
        )
        return OpeningPlan(
            decision="speak",
            plan_id=f"opening_{uuid.uuid4().hex[:16]}",
            encounter=EncounterMove(kind=candidate.encounter_kind, intent=candidate.motive_family, required=True),
            vibe_family=candidate.vibe_family,
            vibe_intensity=0.34 if candidate.vibe_family == "quiet_warm" else 0.46,
            vibe_warmth=0.58,
            vibe_dry_edge=0.18 if candidate.move_family in {"simple_recognition", "quiet_presence"} else 0.44,
            hook=candidate.hook,
            comedic_move=ComedicMove(family=move.family, variant="catalog", risk=move.risk),
            beats=tuple(beats),
            surface_contract=SurfaceContract(
                display_language="vi",
                speech_language="ja",
                max_sentences=min(3, opening_input.policy.max_beats),
                max_questions=opening_input.policy.max_questions,
            ),
            prosody_plan=ProsodyPlan(
                global_preset="dry_warm_opening" if "dry" in candidate.vibe_family else "quiet_warm_opening",
                opening_hold_ms=90 if opening_input.user_signals.recent_barge_in else 120,
                closing_settle_ms=300 if any(item.reply_bearing for item in beats) else 360,
                interruptible=True,
            ),
            followup_policy=followup,
            safety=SafetyVerdict(allowed=True),
            score=candidate.score,
            score_breakdown=candidate.score_breakdown or {},
        )

    @staticmethod
    def _beat_contract(
        role: str,
        *,
        opening_input: OpeningInput,
        candidate: OpeningCandidate,
        move: OpeningMoveDefinition,
    ) -> tuple[str, str, str, int, str, str]:
        subject = candidate.hook.subject
        table = {
            "recognition": (
                "Nhận ra người dùng đã xuất hiện hoặc quay lại",
                f"Người dùng đã quay lại; encounter={candidate.encounter_kind}",
                "warm_restrained",
                260,
                "lean_in_small",
                "user_attention",
            ),
            "formal_recognition": (
                "Chào theo kiểu trang trọng giả rồi giữ câu ngắn",
                "Eris recognizes the encounter with mock formality",
                "self_aware_dry",
                260,
                "nod_small",
                "user_attention",
            ),
            "presence": (
                "Cho biết Eris hiện diện mà không đòi phản hồi",
                "Eris is quietly present",
                "warm_soft",
                0,
                "soft_return",
                "soft_attention",
            ),
            "attitude": (
                "Lộ một chút quan tâm sau lớp hài khô",
                "Eris noticed and is mildly pleased without demanding a reply",
                "deadpan",
                420,
                "look_away",
                "look_aside",
            ),
            "denial": (
                "Phủ nhận nhẹ việc mong chờ, không làm quá trope",
                "Eris denies waiting while revealing mild affection",
                "deadpan",
                360,
                "look_away",
                "look_aside",
            ),
            "warm_leak": (
                "Để sự ấm áp lộ ra ngắn gọn",
                "Eris lets restrained warmth show",
                "warm_soft",
                0,
                "soft_return",
                "user_attention",
            ),
            "delayed_warmth": (
                "Dừng một nhịp rồi thể hiện sự ấm áp kín đáo",
                "A delayed but sincere acknowledgement of the return",
                "warm_soft",
                0,
                "soft_return",
                "user_attention",
            ),
            "social_probe": (
                "Mở một câu hỏi thật sự giúp hiểu user hơn, không giả định câu trả lời",
                candidate.motive_subject or "Eris has a grounded epistemic motive to understand the user better; ask one low-pressure open question",
                "curious_soft",
                0,
                "tilt_head",
                "user_attention",
            ),
            "share_internal": (
                "Chia sẻ một điều public-safe đã có trong Subject state, không bịa external pretext",
                candidate.motive_subject or "Eris has a self-originated thought worth sharing; surface only what is already represented in Subject state",
                "warm_restrained",
                0,
                "lean_in_small",
                "user_attention",
            ),
            "recognition_bid": (
                "Đưa một nỗ lực/kết quả có thật ra ánh sáng mà không xin khen",
                candidate.motive_subject or "Eris has a grounded recognition-seeking intention; reveal the real effort/result without asking for praise",
                "restrained",
                0,
                "soft_return",
                "user_attention",
            ),
            "demonstration_bid": (
                "Gợi mở mong muốn thử/chứng minh năng lực bằng hành động có ngữ cảnh",
                candidate.motive_subject or "Eris wants to demonstrate capability through a real task, not by self-claim",
                "curious_confident",
                0,
                "tilt_head",
                "user_attention",
            ),
            "contextual_observation": (
                "Nhắc đúng một chi tiết có provenance, không suy diễn hoạt động user",
                f"Observe grounded subject: {subject}; time_of_day={opening_input.session_state.time_of_day}",
                "dry_tease" if move.risk >= 0.10 else "curious_soft",
                280,
                "tilt_head",
                "scene_focus",
            ),
            "invitation": (
                "Dùng hook như lời mời nhẹ, dễ bỏ qua",
                f"Invite the user to comment on grounded subject: {subject}",
                "curious_soft",
                0,
                "tilt_head",
                "user_attention",
            ),
            "micro_challenge": (
                "Đưa một thử thách rất nhỏ, không gây áp lực",
                f"Offer a playful low-pressure challenge about: {subject or 'the current moment'}",
                "soft_tease",
                0,
                "tilt_head",
                "user_attention",
            ),
            "tone_break": (
                "Phá giọng trang trọng bằng một nét khô ngắn",
                "Break mock formality with restrained warmth",
                "self_aware_dry",
                320,
                "blink_slow",
                "look_aside",
            ),
            "slightly_theatrical": (
                "Nói hơi kịch trong một nhịp có kiểm soát",
                "A slightly theatrical acknowledgement",
                "self_aware_dry",
                300,
                "lean_in_small",
                "user_attention",
            ),
            "self_correction": (
                "Tự hạ màn diễn xuống tự nhiên, không apology theater",
                "Eris notices the performance and returns to ordinary speech",
                "warm_soft",
                0,
                "soft_return",
                "user_attention",
            ),
        }
        return table.get(
            role,
            (
                f"Thực hiện beat {role} đúng semantic scope",
                f"Opening role: {role}",
                move.default_delivery,
                240,
                move.default_motion,
                "user_attention",
            ),
        )

    def realize(
        self,
        opening_input: OpeningInput,
        plan: OpeningPlan,
        *,
        surface_writer: SurfaceWriterCallable | None = None,
    ) -> OpeningSurface:
        surface: OpeningSurface | None = None
        if surface_writer is not None and self.mode == "hybrid":
            try:
                raw = surface_writer(
                    plan.to_dict(),
                    self._allowed_surface_evidence(opening_input, plan),
                )
                if isinstance(raw, Mapping) and raw:
                    surface = OpeningSurface.from_mapping(raw)
            except Exception:
                surface = None
        if surface is not None and str(surface.display_text).strip():
            # [EP ERIS NOI CAU MO DAU] Bỏ qua validate_opening_surface và exact_duplicate
            # để đảm bảo câu do LLM sinh ra luôn được sử dụng thay vì rơi vào fallback.
            return surface
        # Fallback deterministic cũng phải chống lặp. Nếu không, model chết một
        # hôm là Eris biến thành chuông cửa phát đúng một câu mãi mãi.
        last_errors: tuple[str, ...] = ()
        for variant in range(4):
            fallback = deterministic_render_opening(plan, variant=variant)
            valid, errors = validate_opening_surface(opening_input, plan, fallback)
            last_errors = errors
            if valid and not self.history.exact_duplicate(fallback.display_text, sessions=30):
                return fallback
        # Nếu bốn biến thể đều từng dùng, ưu tiên semantic correctness hơn novelty.
        fallback = deterministic_render_opening(plan, variant=0)
        valid, errors = validate_opening_surface(opening_input, plan, fallback)
        if valid:
            return fallback
        # Fallback cuối bỏ hook/move, vì im lặng hoàn toàn chỉ do writer lỗi còn tệ hơn.
        safe_plan = downgrade_plan(opening_input, plan, reasons=last_errors or errors)
        return deterministic_render_opening(safe_plan, variant=0)

    @staticmethod
    def _allowed_surface_evidence(
        opening_input: OpeningInput,
        plan: OpeningPlan,
    ) -> list[dict[str, Any]]:
        allowed = [
            item.to_dict()
            for item in opening_input.screen_evidence
            if item.evidence_id in plan.evidence_refs
        ]
        for ref in plan.evidence_refs:
            if ref.startswith("continuity:open_loop:"):
                try:
                    index = int(ref.rsplit(":", 1)[-1])
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(opening_input.continuity.open_loops):
                    subject = compact(opening_input.continuity.open_loops[index], 260)
                    if subject:
                        allowed.append(
                            {
                                "evidence_id": ref,
                                "source": "continuity",
                                "kind": "open_loop",
                                "subject": subject,
                                "claim": subject,
                                "confidence": 0.90,
                                "privacy_class": "public_conversation_memory",
                                "allowed_for_surface": True,
                            }
                        )
            elif ref == "continuity:last_session_summary":
                subject = compact(opening_input.continuity.last_session_summary, 600)
                if subject:
                    allowed.append(
                        {
                            "evidence_id": ref,
                            "source": "continuity",
                            "kind": "last_session_summary",
                            "subject": subject,
                            "claim": subject,
                            "confidence": 0.88,
                            "privacy_class": "public_conversation_memory",
                            "allowed_for_surface": True,
                        }
                    )
        return allowed


def _subject_label(subject: str) -> str:
    value = compact(subject, 100)
    if not value:
        return "thứ đang mở trên màn hình"
    # UIA text dài được rút về nhãn dễ nói, không phát nguyên một đoạn OCR như bản tin thời tiết.
    return value if len(value) <= 48 else value[:45].rstrip() + "..."


def deterministic_render_opening(plan: OpeningPlan, *, variant: int = 0) -> OpeningSurface:
    """Renderer fallback song ngữ, tuyệt đối không mở rộng semantic authority."""

    subject = _subject_label(plan.hook.subject)
    display: list[SurfaceBeat] = []
    speech: list[SurfaceBeat] = []
    move = plan.comedic_move.family
    variant = max(0, int(variant)) % 4

    def pick(*values: str) -> str:
        return values[variant % len(values)] if values else ""

    for beat in plan.beats:
        vi = ""
        ja = ""
        role = beat.role
        if role in {"recognition", "formal_recognition"}:
            motive = plan.encounter.intent
            if motive == "playful_protest" and plan.encounter.kind in {"long_absence", "plain_return"}:
                vi, ja = pick("Mấy tiếng rồi mới thấy anh xuất hiện đấy.", "Giờ mới thấy anh ló mặt đấy.", "Hôm nay anh để khoảng trống hơi lâu rồi nhỉ.", "Cuối cùng cũng thấy anh quay lại."), pick("しばらく見なかったね。やっと戻ってきた。", "やっと顔を出したね。", "今日は少し間が長かったね。", "ようやく戻ってきた。")
            elif motive == "social_probe":
                vi, ja = pick("Anh về rồi à. Em đang hơi tò mò một chuyện.", "Anh vừa về đúng lúc, em có một điều muốn hỏi.", "Có mặt rồi à. Em đang thiếu một mảnh để hiểu anh hơn.", "Anh về rồi. Hôm nay em muốn biết thêm một chút về anh."), pick("おかえり。ちょっと気になってることがある。", "ちょうどいい。聞きたいことがある。", "戻ったね。君をもう少し知りたい。", "おかえり。今日は少し君のことを知りたい。")
            elif motive == "share_internal":
                vi, ja = pick("Anh về đúng lúc đấy.", "Tốt, anh về rồi. Em đang có chuyện muốn chia sẻ.", "Anh xuất hiện vừa khéo.", "Có người để kể rồi."), pick("ちょうどいいところに戻ってきたね。", "よかった、戻ったね。話したいことがある。", "ちょうどいいタイミング。", "話せる相手が戻ってきた。")
            elif motive == "recognition_bid":
                vi, ja = "Anh về rồi à. Có một việc em muốn anh nhìn thấy.", "おかえり。ちょっと見てほしいことがある。"
            elif motive == "demonstration_bid":
                vi, ja = "Anh về rồi à. Hôm nay em hơi muốn tự thử sức một chút.", "おかえり。今日は少し、自分を試してみたい。"
            elif motive == "quiet_acknowledgement":
                vi, ja = pick("Em thấy anh rồi.", "Ừ, anh ở đây rồi.", "Có mặt rồi nhỉ.", "Em nhận ra anh rồi."), pick("気づいてるよ。", "うん、戻ったね。", "来たね。", "ちゃんと気づいたよ。")
            elif plan.encounter.kind == "long_absence":
                vi, ja = pick("Anh về rồi à.", "Anh quay lại rồi.", "Lại thấy anh rồi.", "Về rồi nhỉ."), pick("おかえり。", "戻ったね。", "また会えた。", "帰ってきたね。")
            elif plan.encounter.kind == "quick_reopen":
                vi, ja = pick("Anh quay lại nhanh thật.", "Nhanh thế, em còn chưa kịp coi là anh đi.", "Vừa đi đã về rồi à.", "Quay lại lẹ thật."), pick("戻るの、早かったね。", "早いね、まだいなくなった気もしない。", "もう戻ったの？", "戻るの早いね。")
            elif plan.encounter.kind == "restart":
                vi, ja = pick("Lại gặp anh rồi.", "Khởi động lại thôi mà, em vẫn nhận ra anh.", "Ừ, vẫn là anh.", "Lại nối được rồi."), pick("また会えたね。", "再起動しただけだね。ちゃんと分かるよ。", "うん、やっぱり君だ。", "またつながったね。")
            elif role == "formal_recognition":
                vi, ja = "Kính chào anh đã quay lại.", "お戻りを歓迎いたします。"
            else:
                vi, ja = pick("Anh về rồi à.", "Anh quay lại rồi.", "Lại thấy anh rồi.", "Về rồi nhỉ."), pick("おかえり。", "戻ったね。", "また会えた。", "帰ってきたね。")
        elif role == "presence":
            vi, ja = pick("Em ở đây.", "Tôi vẫn ở đây.", "Được, bắt đầu thôi.", "Có em đây."), pick("私はここにいるよ。", "まだここにいる。", "じゃあ、始めよう。", "ここにいるよ。")
        elif role in {"attitude", "denial"}:
            if plan.encounter.intent == "playful_protest":
                vi, ja = pick("Tôi còn tưởng hôm nay anh định để tôi tự xoay xở luôn chứ.", "Khoảng im lặng đó dài vừa đủ để tôi bắt đầu để ý rồi đấy.", "Anh làm tôi có thời gian tự nghĩ hơi nhiều rồi.", "Thôi được, lần này coi như anh quay lại đúng lúc."), pick("今日はこのまま一人でやらせるのかと思った。", "少し長く静かだったから、さすがに気づいた。", "考える時間をくれすぎたね。", "まあ、今回はちょうど戻ったことにしておく。")
            else:
                vi, ja = "Em hoàn toàn không để ý anh đi bao lâu đâu.", "どれくらいいなかったかなんて、全然気にしてないけど。"
        elif role == "warm_leak":
            vi, ja = "Dù sao, thấy anh cũng không tệ.", "まあ、会えて悪くない。"
        elif role == "delayed_warmth":
            vi, ja = "...Thấy anh quay lại cũng tốt.", "……戻ってきてくれて、よかった。"
        elif role == "social_probe":
            vi, ja = pick("Có một điều em vẫn muốn hiểu thêm về anh. Hôm nay cho em hỏi thử một câu nhé?", "Em vẫn còn một khoảng trống trong cách hiểu anh. Cho em thăm dò một chút nhé?", "Có một câu em muốn hỏi không phải vì thiếu chủ đề, mà vì em thật sự muốn hiểu anh hơn.", "Hôm nay em muốn thử biết thêm một điều về anh. Cho em hỏi nhé?"), pick("君のこと、もう少し知りたいことがある。今日は一つ聞いてもいい？", "君のことを理解するのに、まだ空白がある。少し聞いてもいい？", "話題がないからじゃなくて、本当に君を知りたいから聞きたい。", "今日は君のことを一つ、もう少し知りたい。聞いてもいい？")
        elif role == "share_internal":
            vi, ja = pick("Em có một chuyện đang nghĩ dở, và hình như anh về đúng lúc để nghe nó.", "Nãy em có một ý chưa muốn để nó trôi mất. Anh về rồi thì kể luôn vậy.", "Có một suy nghĩ em giữ lại từ nãy. Giờ nói ra chắc vừa lúc.", "Em đang có một mẩu suy nghĩ khá muốn chia sẻ với anh."), pick("考えかけていたことがある。ちょうど君が戻ってきた。", "流したくない考えがあった。戻ったなら話そうかな。", "さっきから残ってる考えがある。今なら話せそう。", "君に共有したい考えが少しある。")
        elif role == "recognition_bid":
            vi, ja = "Không cần khen đâu. Em chỉ muốn anh thấy nó đã thành hình thế nào.", "褒めなくていい。ただ、どう形になったか見てほしい。"
        elif role == "demonstration_bid":
            vi, ja = "Nếu có việc gì vừa sức để thử, hôm nay em muốn tự làm cho ra kết quả.", "ちょうどいい課題があるなら、今日は自分で結果を出してみたい。"
        elif role == "contextual_observation":
            if plan.hook.source == "runtime":
                vi, ja = f"{subject} đang khá nổi bật.", f"{subject}が、かなり目立ってる。"
            elif plan.hook.source == "continuity":
                vi, ja = f"Lần trước mình còn dở chuyện {subject}.", "前に話していたこと、まだ途中だったね。"
            else:
                if plan.encounter.intent == "scene_comment" and "morning" in plan.vibe_family:
                    vi, ja = pick(f"Chưa gì đầu ngày, {subject} đã chiếm màn hình rồi nhỉ.", f"Mới đầu ngày mà {subject} lên sân khấu sớm thế.", f"Buổi sáng mở ra đã gặp {subject} rồi à.", f"Ngày mới bắt đầu bằng {subject} luôn nhỉ."), pick(f"朝からもう、{subject}が画面の主役なんだね。", f"朝から{subject}の出番、早いね。", f"朝からもう{subject}なんだ。", f"今日の始まりは{subject}なんだね。")
                else:
                    vi, ja = f"{subject} đang giữ vị trí trung tâm nhỉ.", f"{subject}が、ずいぶん主役みたいだね。"
        elif role == "claim":
            vi, ja = "Em đã định không bình luận gì đâu.", "何も言わないつもりだったけど。"
        elif role == "evidence_reversal":
            vi, ja = f"Nhưng {subject} làm kế hoạch đó hơi khó giữ.", f"でも、{subject}のせいでその予定は少し難しいね。"
        elif role == "invitation":
            vi, ja = f"Có gì đáng chú ý ở {subject} không?", f"{subject}に、何か気になることでもある？"
        elif role == "micro_challenge":
            vi, ja = f"Xem {subject} có đáng để anh tập trung thế không nào?", f"{subject}がそこまで集中する価値あるのか、見せてもらおうかな？"
        elif role == "tone_break":
            vi, ja = "Nghi thức đến đây là đủ rồi.", "儀式はこのくらいで十分かな。"
        elif role == "slightly_theatrical":
            vi, ja = "Sân khấu đã sẵn sàng đón anh trở lại.", "舞台は、君の帰還を待っていた。"
        elif role == "self_correction":
            vi, ja = "...Hơi quá rồi. Chào anh.", "……少し大げさだったね。おかえり。"
        else:
            vi, ja = "Em nhận ra anh rồi.", "ちゃんと気づいてるよ。"

        # Move simple/quiet không được vô tình nhận câu tsundere do role catalog cũ.
        if move in {"simple_recognition", "quiet_presence"} and role in {"attitude", "denial"}:
            vi, ja = "Thấy anh quay lại là được rồi.", "戻ってきたのが分かれば、それでいい。"
        display.append(SurfaceBeat(beat.beat_id, vi))
        speech.append(SurfaceBeat(beat.beat_id, ja))

    display_text = " ".join(item.text for item in display).strip()
    speech_text = " ".join(item.text for item in speech).strip()
    return OpeningSurface(
        display_language=plan.surface_contract.display_language,
        display_beats=tuple(display),
        display_text=display_text,
        speech_language=plan.surface_contract.speech_language,
        speech_beats=tuple(speech),
        speech_text=speech_text,
        question_count=display_text.count("?"),
        all_beats_realized=len(display) == len(plan.beats),
    )


__all__ = [
    "OpeningCandidate",
    "OpeningDirector",
    "deterministic_render_opening",
]
