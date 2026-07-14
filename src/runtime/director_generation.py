# -*- coding: utf-8 -*-
"""Pipeline duy nhất cho Director -> candidates -> FinalDecision.

File này gom các bước trước đây nằm rải trong chat_cycle, precommit guard và
stage output. Nó không thay cognition hay persona. Nó chỉ bảo đảm một lượt chat
có đúng một DirectorContext, một lần chọn candidate và một kết quả cuối có thể
truy vết.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from domain import Decision
from runtime.adaptive_candidates import AdaptiveCandidateController
from runtime.content_engine import ContentHarvester
from runtime.director_context import DirectorContext, DirectorContextBuilder
from runtime.director_trace import DirectorTrace, DirectorTraceStore
from runtime.final_decision import FinalDecision
from runtime.performance_contract import (
    DirectorContract,
    DirectorContractBuilder,
    PerformanceContext,
    PerformanceContextBuilder,
)
from runtime.stage_scorer import CandidateUtterance, StageScore, StageScorer
from runtime.scene_repair_policy import shorten_text


@dataclass(frozen=True, slots=True)
class PreparedDirectorTurn:
    director_context: DirectorContext
    performance_context: PerformanceContext
    director_contract: DirectorContract
    base_payload: Mapping[str, Any]
    channel: str
    user_text: str


class DirectorGenerationPipeline:
    """Sở hữu toàn bộ quyết định bề mặt của một turn.

    ``prepare`` chỉ được gọi một lần cho turn chính. Content hook được harvest và
    chọn tại đây, vì gọi lại PerformanceContextBuilder nhiều lần có thể tiêu
    cooldown hai lần. Một bug nhỏ, nhưng đủ khiến Eris quên câu đùa vừa dùng sau
    đúng vài mili giây. Rất con người, không cần thiết phải mô phỏng phần đó.
    """

    def __init__(
        self,
        *,
        director_builder: DirectorContextBuilder | None = None,
        performance_builder: PerformanceContextBuilder | None = None,
        contract_builder: DirectorContractBuilder | None = None,
        stage_scorer: StageScorer | None = None,
        content_harvester: ContentHarvester | None = None,
        trace_store: DirectorTraceStore | None = None,
        candidate_controller: AdaptiveCandidateController | None = None,
    ) -> None:
        self.director_builder = director_builder or DirectorContextBuilder()
        self.performance_builder = performance_builder or PerformanceContextBuilder()
        self.contract_builder = contract_builder or DirectorContractBuilder()
        self.stage_scorer = stage_scorer or StageScorer()
        self.content_harvester = content_harvester or ContentHarvester()
        self.trace_store = trace_store or DirectorTraceStore()
        self.candidate_controller = candidate_controller or AdaptiveCandidateController()

    def prepare(
        self,
        *,
        runtime: Any,
        frame: Any,
        payload: Mapping[str, Any],
        user_text: str,
        channel: str = "chat",
        harvest_content: bool = True,
    ) -> PreparedDirectorTurn:
        working = dict(payload or {})
        working["user_text"] = str(user_text or "")
        context = self.director_builder.build(
            payload=working,
            frame=frame,
            channel=channel,
            user_text=user_text,
        )

        if harvest_content:
            harvested = self.content_harvester.payloads(
                runtime=runtime,
                frame=frame,
                payload=working,
                channel=channel,
            )
            working["content_seeds"] = [
                seed for seed in harvested
                if isinstance(seed, dict) and bool(seed.get("public_ok", True))
            ]
            context.world_state["runtime_hints"] = [
                seed for seed in harvested
                if isinstance(seed, dict) and not bool(seed.get("public_ok", True))
            ]

        performance = self.performance_builder.build(context, payload=working, channel=channel)
        try:
            context.world_state["content_hook"] = performance.content_hook or {}
            context.world_state["topic_stack"] = self.performance_builder.content_engine.topic_stack_payload()
        except Exception:
            pass
        contract = self.contract_builder.build(context, performance)
        return PreparedDirectorTurn(
            director_context=context,
            performance_context=performance,
            director_contract=contract,
            base_payload=working,
            channel=channel,
            user_text=str(user_text or ""),
        )

    def finalize(
        self,
        *,
        draft_decision: Decision,
        prepared: PreparedDirectorTurn,
        llm_service: Any | None = None,
        conversation_context: str = "",
        grounding_context: str = "",
        memory_context: str = "",
        generate_candidates: bool = True,
    ) -> FinalDecision:
        started = time.perf_counter()
        base_payload = dict(prepared.base_payload)
        base_payload.update(draft_decision.to_payload())
        base_payload["performance_context"] = prepared.performance_context.to_payload()
        base_payload["director_contract"] = prepared.director_contract.to_payload()
        base_payload["delivery_hint"] = str(
            base_payload.get("delivery_hint") or prepared.performance_context.delivery_style
        )
        base_payload["stage_motion"] = str(
            base_payload.get("stage_motion") or prepared.performance_context.stage_motion
        )

        # Candidate mặc định được tạo deterministic từ cùng draft: giữ nguyên,
        # gắn stage metadata, bản rút gọn và body-only fallback. Nhờ vậy hot path
        # chat chỉ cần MỘT model call (answer pass). Pass model thứ hai vẫn có thể
        # bật thủ công để thử nghiệm chất lượng, nhưng mặc định tắt để key pool
        # khỏi quay như máy giặt hỏng.
        raw_candidates: list[Mapping[str, Any]] = self._deterministic_candidates(
            draft_decision,
            base_payload,
            prepared,
        )
        generation_notes: list[str] = ["deterministic_candidate_set"]

        pressure_snapshot = None
        if llm_service is not None:
            try:
                pressure_client = (
                    getattr(llm_service, "style_client", None)
                    or getattr(llm_service, "fallback_client", None)
                    or getattr(llm_service, "client", None)
                )
                pressure_snapshot = llm_service.token_pressure_snapshot(
                    client=pressure_client,
                    channel="director_candidates",
                )
            except Exception:
                pressure_snapshot = None
        recent_failures = (
            *tuple(getattr(draft_decision, "reasoning_tags", ()) or ()),
            str(getattr(draft_decision, "debug_trace", "") or ""),
            str(getattr(draft_decision, "parse_mode", "") or ""),
        )
        candidate_plan = self.candidate_controller.decide(
            lane=prepared.channel,
            user_text=prepared.user_text,
            draft_confidence=float(getattr(draft_decision, "confidence", 0.0) or 0.0),
            recent_failures=recent_failures,
            token_snapshot=pressure_snapshot,
        )
        generation_notes.append(
            f"adaptive_candidates:{candidate_plan.model_candidates}:{candidate_plan.reason}:"
            f"{candidate_plan.pressure_level}"
        )
        base_payload["adaptive_candidate_plan"] = {
            "model_candidates": candidate_plan.model_candidates,
            "reason": candidate_plan.reason,
            "chat_act": candidate_plan.chat_act.value,
            "act_confidence": round(candidate_plan.act_confidence, 3),
            "token_pressure": round(candidate_plan.token_pressure, 3),
            "pressure_level": candidate_plan.pressure_level,
        }

        can_generate = (
            generate_candidates
            and candidate_plan.use_model_second_pass
            and llm_service is not None
            and bool(str(draft_decision.text or "").strip())
            and bool(getattr(draft_decision, "should_speak", True))
            and self._candidate_generation_enabled()
            and self._model_second_pass_enabled()
            and not self._skip_candidate_generation(draft_decision)
        )
        if can_generate:
            try:
                generated = llm_service.generate_director_candidates(
                    draft_payload=base_payload,
                    user_message=prepared.user_text,
                    director_contract_prompt=prepared.director_contract.to_prompt_block(),
                    conversation_context=conversation_context,
                    grounding_context=grounding_context,
                    memory_context=memory_context,
                    candidate_count=candidate_plan.model_candidates,
                )
                if isinstance(generated, list):
                    raw_candidates.extend(item for item in generated if isinstance(item, Mapping))
            except Exception as exc:  # noqa: BLE001
                generation_notes.append(f"candidate_generation_failed:{type(exc).__name__}")

        candidates = [CandidateUtterance.from_mapping(item) for item in raw_candidates]
        selected, score, selected_index = self._choose(candidates, prepared)
        if selected is None or score is None:
            selected = CandidateUtterance.from_mapping(raw_candidates[0])
            score = self.stage_scorer.score_candidate(
                selected,
                context=prepared.director_context,
                channel=prepared.channel,
            )
            selected_index = 0
            generation_notes.append("candidate_fallback_to_draft")

        finalized_payload = self.stage_scorer.apply_candidate_to_payload(
            dict(base_payload),
            selected,
            score,
            channel=prepared.channel,
            context=prepared.director_context,
        )
        final_decision = self._decision_from_payload(draft_decision, finalized_payload)
        repair_payload = (
            dict(finalized_payload.get("scene_repair") or {})
            if isinstance(finalized_payload.get("scene_repair"), Mapping)
            else {}
        )
        stage_score_payload = (
            dict(finalized_payload.get("stage_score") or {})
            if isinstance(finalized_payload.get("stage_score"), Mapping)
            else score.to_payload()
        )
        generation_latency_ms = int((time.perf_counter() - started) * 1000)
        trace = DirectorTrace(
            trace_id=prepared.director_context.trace_id,
            channel=prepared.channel,
            scene_mode=prepared.director_context.scene_mode.name,
            completed_at_ms=int(time.time() * 1000),
            candidate_count=len(candidates),
            selected_candidate=str(final_decision.text or ""),
            selected_index=selected_index,
            authority_result=tuple(score.policy_tags),
            score=stage_score_payload,
            repair_action=str(repair_payload.get("action", stage_score_payload.get("applied_action", "keep")) or "keep"),
            generation_latency_ms=generation_latency_ms,
            finalized_text=str(final_decision.text or ""),
            should_speak=bool(final_decision.should_speak),
            notes=tuple(generation_notes),
        )
        self.trace_store.put(trace)

        # Gắn metadata compact vào Decision để precommit và stage output không
        # chấm lại. Đây là "con dấu" của FinalDecision, không phải lời mời mở thêm
        # một hội đồng giám khảo ở tầng dưới.
        final_decision.director_finalized = True
        final_decision.director_trace_id = trace.trace_id
        final_decision.reasoning_tags = tuple(
            dict.fromkeys((*tuple(final_decision.reasoning_tags or ()), "director_final_decision"))
        )
        final_decision.debug_trace = self._join_trace(
            final_decision.debug_trace,
            f"director_final={score.decision}:{score.reason}:{trace.repair_action}",
        )

        result = FinalDecision(
            decision=replace(final_decision),
            director_context=prepared.director_context,
            performance_context=prepared.performance_context,
            director_contract=prepared.director_contract,
            selected_candidate=selected,
            stage_score=score,
            repair_payload=repair_payload,
            trace=trace,
        )
        final_decision.director_meta = result.compact_meta()
        result = replace(result, decision=replace(final_decision))
        return result

    def finalize_without_generation(
        self,
        *,
        draft_decision: Decision,
        prepared: PreparedDirectorTurn,
    ) -> FinalDecision:
        return self.finalize(
            draft_decision=draft_decision,
            prepared=prepared,
            llm_service=None,
            generate_candidates=False,
        )

    def _choose(
        self,
        candidates: Sequence[CandidateUtterance],
        prepared: PreparedDirectorTurn,
    ) -> tuple[CandidateUtterance | None, StageScore | None, int]:
        best: CandidateUtterance | None = None
        best_score: StageScore | None = None
        best_index = -1
        best_value = -10_000.0
        for index, candidate in enumerate(candidates):
            score = self.stage_scorer.score_candidate(
                candidate,
                context=prepared.director_context,
                channel=prepared.channel,
            )
            value = self.stage_scorer.ranking_value(candidate, score)
            # Khi điểm bằng nhau, ưu tiên draft (index 0) để tránh đổi câu chỉ vì
            # model sinh một biến thể tương đương. Novelty không đáng đổi lấy drift.
            if value > best_value:
                best = candidate
                best_score = score
                best_index = index
                best_value = value
        return best, best_score, best_index

    def _deterministic_candidates(
        self,
        decision: Decision,
        payload: Mapping[str, Any],
        prepared: PreparedDirectorTurn,
    ) -> list[Mapping[str, Any]]:
        """Tạo candidate không gọi model, chỉ dùng phép biến đổi không đổi nghĩa."""

        original = self._candidate_mapping_from_decision(decision, payload)
        out: list[Mapping[str, Any]] = [original]

        staged = dict(original)
        staged["delivery_hint"] = str(
            staged.get("delivery_hint") or prepared.performance_context.delivery_style
        )
        staged["stage_motion"] = str(
            staged.get("stage_motion") or prepared.performance_context.stage_motion
        )
        if staged != original:
            out.append(staged)

        shortened = shorten_text(
            str(original.get("text", "") or ""),
            prepared.director_context.speak_budget_words,
        )
        if shortened and shortened != str(original.get("text", "") or ""):
            short_candidate = dict(staged)
            short_candidate["text"] = shortened
            # Rút gọn deterministic không làm tăng confidence; nó chỉ giảm tải
            # TTS, không tự phong mình thông minh hơn câu gốc.
            short_candidate["confidence"] = float(original.get("confidence", 0.0) or 0.0)
            out.append(short_candidate)

        if prepared.performance_context.body_only_ok:
            out.append(
                {
                    "text": "",
                    "intent": "body_only",
                    "should_speak": False,
                    "confidence": 0.42,
                    "delivery_hint": "",
                    "nonverbal_cue": str(original.get("nonverbal_cue", "") or ""),
                    "stage_motion": str(
                        original.get("stage_motion")
                        or prepared.performance_context.stage_motion
                        or "blink_slow"
                    ),
                    "evidence_refs": list(original.get("evidence_refs", ()) or ()),
                }
            )
        return out

    def _candidate_mapping_from_decision(self, decision: Decision, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "text": str(decision.text or ""),
            "intent": str(decision.intent or payload.get("intent", "") or ""),
            "should_speak": bool(decision.should_speak),
            "confidence": float(decision.confidence or 0.0),
            "delivery_hint": str(decision.delivery_hint or payload.get("delivery_hint", "") or ""),
            "nonverbal_cue": str(decision.nonverbal_cue or ""),
            "stage_motion": str(decision.stage_motion or payload.get("stage_motion", "") or ""),
            "evidence_refs": list(payload.get("evidence_refs", ()) or ()),
        }

    def _decision_from_payload(self, draft: Decision, payload: Mapping[str, Any]) -> Decision:
        decision = replace(draft)
        decision.text = str(payload.get("text", "") or "")
        decision.should_speak = bool(payload.get("should_speak", False) and decision.text.strip())
        decision.confidence = max(0.0, min(1.0, float(payload.get("confidence", decision.confidence) or 0.0)))
        decision.intent = str(payload.get("intent", decision.intent) or decision.intent)
        decision.delivery_hint = str(payload.get("delivery_hint", decision.delivery_hint) or "")
        decision.nonverbal_cue = str(payload.get("nonverbal_cue", decision.nonverbal_cue) or "")
        decision.stage_motion = str(payload.get("stage_motion", decision.stage_motion) or "")
        if not decision.should_speak or decision.text != str(draft.text or ""):
            # Fact được trích từ draft không tự động sống sót qua rewrite/suppress.
            # Memory commit sẽ tự xét lại từ user fact thật.
            decision.extracted_fact = ""
        return decision

    def _skip_candidate_generation(self, decision: Decision) -> bool:
        parse_mode = str(decision.parse_mode or "")
        intent = str(decision.intent or "")
        return bool(
            decision.system_action
            or intent in {"no_fallback_block", "format_repair_fallback", "service_error"}
            or "no_fallback" in parse_mode
            or "format_repair" in parse_mode
        )

    def _candidate_generation_enabled(self) -> bool:
        return os.environ.get("ERIS_CHAT_DIRECTOR_CANDIDATES", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }

    def _model_second_pass_enabled(self) -> bool:
        """Mặc định dùng chế độ adaptive, không phải bật model pass mọi lượt."""

        raw = os.environ.get("ERIS_CHAT_DIRECTOR_SECOND_PASS", "adaptive").strip().lower()
        return raw not in {"0", "false", "no", "off", "disabled"}

    @staticmethod
    def _join_trace(current: str, marker: str) -> str:
        return " | ".join(part for part in (str(current or "").strip(), str(marker or "").strip()) if part)


__all__ = ["DirectorGenerationPipeline", "PreparedDirectorTurn"]
