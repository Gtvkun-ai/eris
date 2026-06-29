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
from dataclasses import asdict, dataclass
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
            "evidence": list(self.evidence),
            "allowed_claim_levels": list(self.allowed_claim_levels),
            "forbidden_claims": list(self.forbidden_claims),
            "output_schema": dict(self.output_schema),
        }

    def to_prompt_block(self) -> str:
        """Render thành block JSON compact để nhét vào prompt khi cần."""
        return "[DIRECTOR_CONTRACT]\n" + json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":"))


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
        scene = director.scene_mode.name
        intent = _intent_from_payload(payload)
        channel_name = _clean(channel).lower()
        publicity = _publicity_for(director)
        reasons: list[str] = [f"scene={scene}", f"intent={intent or 'unknown'}"]
        hook = self.content_engine.select_hook(director, payload=payload, channel=channel)

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
