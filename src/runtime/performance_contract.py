# -*- coding: utf-8 -*-
"""performance_contract.py - hợp đồng biểu diễn cho Eris.

DirectorContext trả lời câu hỏi: "Đang ở sân khấu nào, được phép claim gì?"
PerformanceContext trả lời câu hỏi kế tiếp: "Nếu mở miệng, Eris nên diễn kiểu gì?"

Module này cố ý không gọi LLM. Nó chỉ tạo contract hẹp để:
- coordinator có metadata biểu diễn ổn định;
- LLM nhỏ sau này sinh 3-5 candidate theo đúng khung;
- StageScorer có thể rerank mà không phải đoán lại ý đồ sân khấu.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, Mapping

from runtime.content_engine import ContentEngine, ContentHook
from runtime.director_context import DirectorContext


PerformanceIntent = Literal[
    "answer",
    "technical_help",
    "tease",
    "react",
    "repair",
    "stall",
    "micro_presence",
    "body_only",
]
Publicity = Literal["private", "audience_safe", "broadcast"]


@dataclass(frozen=True, slots=True)
class PerformanceContext:
    performance_intent: PerformanceIntent
    delivery_style: str
    stage_emotion: str
    stage_motion: str
    tts_style: str
    publicity: Publicity
    content_hook_id: str | None = None
    content_hook: dict[str, Any] | None = None
    body_only_ok: bool = True
    max_words: int = 16
    candidate_count: int = 4
    reasons: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True, slots=True)
class DirectorContract:
    """Contract hẹp đưa cho LLM/candidate generator.

    Đây không phải prompt dài. Nó là JSON nhỏ, đủ để model biết giới hạn:
    scene nào, ý đồ biểu diễn nào, max words bao nhiêu, claim nào bị cấm.
    """

    contract_version: str
    scene_mode: str
    audience_mode: str
    relation_band: str
    performance_intent: str
    delivery_style: str
    stage_emotion: str
    stage_motion: str
    tts_style: str
    publicity: str
    max_words: int
    candidate_count: int
    body_only_ok: bool
    content_hook: dict[str, Any] | None
    content_seed: dict[str, Any] | None
    topic_stack: tuple[dict[str, Any], ...]
    runtime_hints: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    allowed_claim_levels: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    output_schema: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "scene_mode": self.scene_mode,
            "audience_mode": self.audience_mode,
            "relation_band": self.relation_band,
            "performance_intent": self.performance_intent,
            "delivery_style": self.delivery_style,
            "stage_emotion": self.stage_emotion,
            "stage_motion": self.stage_motion,
            "tts_style": self.tts_style,
            "publicity": self.publicity,
            "max_words": self.max_words,
            "candidate_count": self.candidate_count,
            "body_only_ok": self.body_only_ok,
            "content_hook": dict(self.content_hook) if isinstance(self.content_hook, dict) else None,
            "content_seed": dict(self.content_seed) if isinstance(self.content_seed, dict) else None,
            "topic_stack": list(self.topic_stack),
            "runtime_hints": list(self.runtime_hints),
            "evidence": list(self.evidence),
            "allowed_claim_levels": list(self.allowed_claim_levels),
            "forbidden_claims": list(self.forbidden_claims),
            "output_schema": dict(self.output_schema),
        }

    def to_prompt_block(self) -> str:
        """Render contract candidate-generation đầy đủ."""
        return "[DIRECTOR_CONTRACT]\n" + json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":"))

    def to_generation_guard_block(self) -> str:
        """Contract hẹp cho lượt sinh Decision đầu tiên.

        Không gửi ``output_schema=candidates`` vào answer pass vì nó xung đột
        với Decision JSON hiện tại. Director vẫn đi trước model bằng scene, budget
        và evidence gate; pass candidate sau đó mới dùng schema nhiều candidate.
        """

        payload = {
            "contract_version": self.contract_version,
            "scene_mode": self.scene_mode,
            "audience_mode": self.audience_mode,
            "relation_band": self.relation_band,
            "performance_intent": self.performance_intent,
            "delivery_style": self.delivery_style,
            "stage_emotion": self.stage_emotion,
            "stage_motion": self.stage_motion,
            "tts_style": self.tts_style,
            "publicity": self.publicity,
            "max_words": self.max_words,
            "body_only_ok": self.body_only_ok,
            "evidence": list(self.evidence),
            "allowed_claim_levels": list(self.allowed_claim_levels),
            "forbidden_claims": list(self.forbidden_claims),
            "instruction": "Return the normal Decision JSON. Do not add facts outside this evidence contract.",
        }
        return "[DIRECTOR_GENERATION_GUARD]\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _intent_from_payload(payload: Mapping[str, Any]) -> str:
    return _clean(payload.get("intent")).lower()


def _publicity_for(context: DirectorContext) -> Publicity:
    if context.audience_mode == "stream":
        return "broadcast"
    if context.audience_mode == "recording":
        return "audience_safe"
    return "private"


class PerformanceContextBuilder:
    """Dịch DirectorContext + intent thô thành ý đồ biểu diễn.

    Chú ý: cognition chỉ nên nói "tôi định trả lời / trêu / repair".
    Stage mới quyết định emotion/motion/TTS cụ thể. Nhờ vậy LLM không còn phải
    tự viết "(cười nhẹ)" trong text.
    """

    def __init__(self, *, content_engine: ContentEngine | None = None) -> None:
        self.content_engine = content_engine or ContentEngine()

    def build(
        self,
        director: DirectorContext,
        *,
        payload: Mapping[str, Any],
        channel: str | None = None,
    ) -> PerformanceContext:
        channel_name = _clean(channel).lower()
        # Autonomous permit là budget đã được SpeakGate cấp trước cognition. Ép
        # budget này xuống DirectorContext để candidate/scorer phía sau không vô
        # tình nới câu trở lại theo budget scene tổng quát.
        autonomous_budget_applied = False
        autonomous_plan = payload.get("autonomous_plan") if isinstance(payload.get("autonomous_plan"), Mapping) else {}
        permit = autonomous_plan.get("permit") if isinstance(autonomous_plan.get("permit"), Mapping) else {}
        if channel_name == "autonomous" and bool(permit.get("allowed", False)):
            try:
                max_words = max(1, int(permit.get("max_words", director.speak_budget_words) or director.speak_budget_words))
                max_duration_ms = max(300, int(permit.get("max_duration_ms", director.speak_budget_ms) or director.speak_budget_ms))
                director = replace(
                    director,
                    speak_budget_words=min(director.speak_budget_words, max_words),
                    speak_budget_ms=min(director.speak_budget_ms, max_duration_ms),
                )
                autonomous_budget_applied = True
            except (TypeError, ValueError):
                pass

        scene = director.scene_mode.name
        intent = _intent_from_payload(payload)
        selected_opportunity = (
            autonomous_plan.get("selected_opportunity")
            if isinstance(autonomous_plan.get("selected_opportunity"), Mapping)
            else {}
        )
        session_directive = (
            autonomous_plan.get("session_directive")
            if isinstance(autonomous_plan.get("session_directive"), Mapping)
            else {}
        )
        if channel_name == "autonomous" and bool(permit.get("allowed", False)):
            suggested_intent = _clean(selected_opportunity.get("suggested_intent")).lower()
            # Opportunity đã qua evidence + session director. Dùng intent này làm
            # hướng biểu diễn thay vì để một inner_whim cũ kéo new_error về body-only.
            if suggested_intent:
                intent = suggested_intent
        publicity = _publicity_for(director)
        reasons: list[str] = [f"scene={scene}", f"intent={intent or 'unknown'}"]
        if autonomous_budget_applied:
            reasons.append(f"autonomous_budget={director.speak_budget_words}w/{director.speak_budget_ms}ms")
            reasons.append(
                f"session={_clean(session_directive.get('phase')) or 'settled'}/"
                f"{_clean(session_directive.get('cadence')) or 'balanced'}"
            )
        hook = self.content_engine.select_hook(
            director,
            payload=payload,
            channel=channel,
            # Chat commit theo hành vi cũ. Autonomous chỉ commit sau khi output
            # public thật sự được gửi, tránh cooldown cho một câu bị scorer chặn.
            commit_on_select=channel_name != "autonomous",
        )

        if hook.family == "silence" and channel_name != "chat":
            reasons.append("content_cooldown_body_only")
            return PerformanceContext(
                performance_intent="body_only",
                delivery_style="silent_presence",
                stage_emotion="neutral",
                stage_motion="blink_slow",
                tts_style="none",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=True,
                max_words=0,
                candidate_count=1,
                reasons=tuple(reasons),
            )

        if director.interruption_state == "interrupted" or intent in {"interrupt_repair", "format_repair_fallback"}:
            reasons.append("interrupt_or_repair")
            return PerformanceContext(
                performance_intent="repair",
                delivery_style="brief_stop_then_repair",
                stage_emotion="focused",
                stage_motion="listen_snap",
                tts_style="clipped_clear",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=False,
                max_words=min(24, max(12, director.speak_budget_words)),
                candidate_count=3,
                reasons=tuple(reasons),
            )

        if channel_name == "chat":
            if scene == "coding_partner" or intent in {"technical_support", "screen_observation", "curious_question"}:
                reasons.append("chat_technical")
                return PerformanceContext(
                    performance_intent="technical_help",
                    delivery_style="dry_focus",
                    stage_emotion="focused",
                    stage_motion="tilt_head",
                    tts_style="clear_low",
                    publicity=publicity,
                    content_hook_id=hook.id,
                    content_hook=hook.to_payload(),
                    body_only_ok=False,
                    max_words=max(24, min(60, director.speak_budget_words)),
                    candidate_count=4,
                    reasons=tuple(reasons),
                )
            reasons.append("chat_answer")
            return PerformanceContext(
                performance_intent="answer",
                delivery_style="soft_direct",
                stage_emotion="warm_soft",
                stage_motion="lean_in_small",
                tts_style="low_warm",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=False,
                max_words=max(24, min(60, director.speak_budget_words)),
                candidate_count=4,
                reasons=tuple(reasons),
            )

        if scene == "coding_partner":
            reasons.append("protect_focus")
            return PerformanceContext(
                performance_intent="body_only" if intent in {"random_chatter", "inner_whim", ""} else "technical_help",
                delivery_style="quiet_focus",
                stage_emotion="focused",
                stage_motion="blink_slow",
                tts_style="clipped_clear",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=True,
                max_words=min(18, director.speak_budget_words),
                candidate_count=3,
                reasons=tuple(reasons),
            )

        if scene == "private_idle":
            reasons.append("idle_micro_presence")
            return PerformanceContext(
                performance_intent="tease" if intent in {"random_chatter", "inner_whim"} else "micro_presence",
                delivery_style="dry_tease",
                stage_emotion="mischief",
                stage_motion="tilt_head",
                tts_style="low_warm",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=True,
                max_words=min(14, director.speak_budget_words),
                candidate_count=4,
                reasons=tuple(reasons),
            )

        if scene == "stream_host":
            reasons.append("public_safe")
            return PerformanceContext(
                performance_intent="react",
                delivery_style="audience_safe_warm",
                stage_emotion="gentle",
                stage_motion="open_palm",
                tts_style="projected_even",
                publicity=publicity,
                content_hook_id=hook.id,
                content_hook=hook.to_payload(),
                body_only_ok=True,
                max_words=min(22, director.speak_budget_words),
                candidate_count=4,
                reasons=tuple(reasons),
            )

        reasons.append("default_micro_presence")
        return PerformanceContext(
            performance_intent="micro_presence",
            delivery_style="soft_near",
            stage_emotion="neutral_warm",
            stage_motion="blink_slow",
            tts_style="low_warm",
            publicity=publicity,
            content_hook_id=hook.id,
            content_hook=hook.to_payload(),
            body_only_ok=True,
            max_words=director.speak_budget_words,
            candidate_count=4,
            reasons=tuple(reasons),
        )


class DirectorContractBuilder:
    """Tạo JSON contract để LLM sinh candidate theo khung biểu diễn."""

    def build(self, director: DirectorContext, performance: PerformanceContext) -> DirectorContract:
        public_evidence: list[dict[str, Any]] = []
        for claim in director.evidence:
            if not claim.public_ok:
                continue
            public_evidence.append(
                {
                    "key": claim.key,
                    "level": claim.level,
                    "value": claim.value,
                    "confidence": round(float(claim.confidence), 3),
                }
            )
            if len(public_evidence) >= 6:
                break

        return DirectorContract(
            contract_version="director.v1",
            scene_mode=director.scene_mode.name,
            audience_mode=director.audience_mode,
            relation_band=director.relation_band,
            performance_intent=performance.performance_intent,
            delivery_style=performance.delivery_style,
            stage_emotion=performance.stage_emotion,
            stage_motion=performance.stage_motion,
            tts_style=performance.tts_style,
            publicity=performance.publicity,
            max_words=performance.max_words,
            candidate_count=performance.candidate_count,
            body_only_ok=performance.body_only_ok,
            content_hook=dict(performance.content_hook) if isinstance(performance.content_hook, dict) else None,
            content_seed=(
                dict(performance.content_hook.get("content_seed"))
                if isinstance(performance.content_hook, dict) and isinstance(performance.content_hook.get("content_seed"), dict)
                else None
            ),
            topic_stack=tuple(
                dict(item)
                for item in (
                    director.world_state.get("topic_stack", ())
                    if isinstance(director.world_state, dict)
                    else ()
                )
                if isinstance(item, dict)
            ),
            runtime_hints=tuple(
                dict(item)
                for item in (
                    director.world_state.get("runtime_hints", ())
                    if isinstance(director.world_state, dict)
                    else ()
                )
                if isinstance(item, dict)
            )[:4],
            evidence=tuple(public_evidence),
            allowed_claim_levels=tuple(director.allowed_claim_levels),
            forbidden_claims=tuple(director.forbidden_claims),
            output_schema={
                "shape": "candidate_list",
                "json": {
                    "candidates": [
                        {
                            "text": "string",
                            "intent": "string",
                            "should_speak": "boolean",
                            "confidence": "number",
                            "delivery_hint": "string",
                            "nonverbal_cue": "string",
                            "stage_motion": "string",
                            "evidence_refs": ["string"],
                        }
                    ]
                },
                "rules": [
                    "Vietnamese only for public text",
                    "No stage directions inside text",
                    "Use delivery_hint/nonverbal_cue/stage_motion for performance",
                    "Return empty text only when body_only/suppress is better",
                    "Use content_hook as a writing seed, not as a fact claim",
                    "If content_hook.evidence_policy forbids screen claims, obey it strictly",
                    "runtime_hints are private operational data; never mention keys, quota, provider pool, or browser state in public text",
                ],
            },
        )


__all__ = [
    "DirectorContract",
    "DirectorContractBuilder",
    "PerformanceContext",
    "PerformanceContextBuilder",
    "PerformanceIntent",
    "Publicity",
]
