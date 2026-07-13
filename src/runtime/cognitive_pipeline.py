# -*- coding: utf-8 -*-
"""
runtime/cognitive_pipeline.py

Xương sống canonical của ERIS V3.

Mục tiêu của file này là biến mớ module rời rạc thành MỘT đường chạy có thật:

    RawSignal
      -> EvidenceItem            (EvidenceNormalizer)        # Phase: contract
      -> CognitiveFrame          (core.cognitive_frame)      # Phase: xương sống
      -> AttentionSalience       (cái gì đáng chú ý)
      -> CognitiveBudget         (fast/normal/deep/reflection)
      -> WorkingMemory           (cái gì được giữ lại)
      -> GlobalWorkspace         (cái gì được broadcast)
      -> Meaning / ToM / Decision / Modality
      -> Wording/Guard/Execution bridge
      -> Outcome/SelfObservation finalizer

Vì sao orchestrator tự ghi slot thay vì để engine tự gắn:
    Các engine (attention/working_memory/global_workspace) gọi
    frame.set_slot(..., writer=...) / set_slot(..., module_name=...) — đó là API
    của một CognitiveFrame ĐỜI KHÁC. CognitiveFrame core dùng set_slot(actor=...).
    Vì engine bọc attach trong try/except, chúng FAIL ÂM THẦM khi gắn slot vào
    frame core. Nếu tin vào attach của engine, salience/working_memory sẽ rỗng mà
    không ai báo. Một cái bug rất kiên nhẫn.

    Nên ở đây orchestrator gọi phần TÍNH của engine rồi tự set_slot với đúng API
    core. Engine đổi cách attach cũng không phá pipeline.

File này từng dừng ở GlobalWorkspace rồi tự gọi mình là pipeline. Một sự tự tin
đáng nể, hơi thiếu dây điện. Bản hiện tại đi hết canonical planning graph; sau khi
runtime cũ thực thi output, ``finalize_from_legacy`` khép vòng wording -> outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from core.cognitive_frame import CognitiveFrame
from core.evidence import ModuleReport, RawSignal
from core.evidence_normalizer import EvidenceNormalizer, EvidenceNormalizerConfig

from cortex.attention_salience import AttentionSalienceEngine
from cortex.situation_model import SituationModel
from cortex.working_memory import WorkingMemoryEngine, WorkingMemoryConfig
from cortex.global_workspace import GlobalWorkspaceEngine
from cortex.meaning import Phase2MeaningPipeline
from cortex.semantic_encoder import LexicalHashingSemanticEncoder
from cortex.semantic_hypothesis import SemanticHypothesisEngine
from cortex.self_observation import SelfObservationEngine
from runtime.cognitive_budget import CognitiveBudgetEngine, BudgetDecision
from runtime.canonical_cognition import CanonicalStageSuite, GroundingReport, ExecutionReport, LLMWordingResult
from runtime.debug_trace import attach_trace_to_frame
from runtime.outcome_observer import OutcomeObserver


class _SituationEmbeddingProvider:
    """Embedding provider lazy cho Situation Model.

    Uỷ thác cho `EmbeddingIndex` singleton dùng chung (MiniLM đa ngôn ngữ) — cùng
    model với memory store và event semantics, nạp lazy một lần. Mọi lỗi (thiếu
    torch/transformers, model không tải được, encode lỗi) đều trả `()` để Situation
    Model tự fallback sang token-overlap thay vì làm vỡ pipeline.
    """

    def embed(self, text: str):
        try:
            from memory.embedding_index import get_shared_embedding_index

            index = get_shared_embedding_index()
        except Exception:
            return ()
        if index is None:
            return ()
        try:
            return index.embed(str(text or ""))
        except Exception:
            return ()


@dataclass(slots=True)
class PipelineResult:
    """Kết quả một lần chạy pipeline.

    Giữ cả frame lẫn vài tham chiếu nhanh để caller/test khỏi phải đào lại frame.
    """

    frame: CognitiveFrame
    budget_decision: Optional[BudgetDecision] = None
    debug_trace: dict[str, Any] = field(default_factory=dict)
    finalized: bool = False

    @property
    def budget_mode(self) -> str:
        return str(getattr(self.frame, "budget_mode", "unknown"))


class CognitivePipeline:
    """Chạy canonical V3 planning graph trên CognitiveFrame core.

    Dùng:
        pipeline = CognitivePipeline()
        result = pipeline.run_from_signals(
            [RawSignal.from_chat("ERIS, build gì tiếp cho V3?")],
            channel="chat",
        )
        print(result.budget_mode)
        print(result.debug_trace)
    """

    def __init__(
        self,
        *,
        normalizer: Optional[EvidenceNormalizer] = None,
        attention: Optional[AttentionSalienceEngine] = None,
        budget: Optional[CognitiveBudgetEngine] = None,
        working_memory: Optional[WorkingMemoryEngine] = None,
        workspace: Optional[GlobalWorkspaceEngine] = None,
        situation_model: Optional[SituationModel] = None,
        meaning_pipeline: Optional[Phase2MeaningPipeline] = None,
        stages: Optional[CanonicalStageSuite] = None,
        outcome_observer: Optional[OutcomeObserver] = None,
        self_observer: Optional[SelfObservationEngine] = None,
    ) -> None:
        self.normalizer = normalizer or EvidenceNormalizer(EvidenceNormalizerConfig())
        # Situation Model bền vững (mặc định BẬT qua config), nối sẵn embedding
        # provider thật để prediction error là khoảng cách ngữ nghĩa, không phải
        # token-overlap. Provider lazy + an toàn: thiếu model -> fallback degraded.
        self.situation_model = situation_model or SituationModel(
            embedding_provider=_SituationEmbeddingProvider(),
        )
        self.attention = attention or AttentionSalienceEngine(situation_model=self.situation_model)
        # Nếu attention được truyền sẵn, vẫn nối Situation Model vào nó.
        try:
            if attention is not None and hasattr(self.attention, "set_situation_model"):
                self.attention.set_situation_model(self.situation_model)
        except Exception:
            pass
        self.budget = budget or CognitiveBudgetEngine()
        # Tắt attach của WM: orchestrator tự set slot bằng API core.
        wm_config = WorkingMemoryConfig()
        try:
            wm_config.attach_to_frame = False
        except Exception:
            pass
        self.working_memory = working_memory or WorkingMemoryEngine(wm_config)
        self.workspace = workspace or GlobalWorkspaceEngine()
        # Dùng semantic engine fallback deterministic đã có sẵn. Không tải model
        # từ mạng trong hot path; khi repo có encoder thật caller có thể inject.
        self.meaning_pipeline = meaning_pipeline or Phase2MeaningPipeline(
            semantic_engine=SemanticHypothesisEngine(LexicalHashingSemanticEncoder())
        )
        self.stages = stages or CanonicalStageSuite()
        self.outcome_observer = outcome_observer or OutcomeObserver()
        self.self_observer = self_observer or SelfObservationEngine()

    # ------------------------------------------------------------------
    # Entrypoints
    # ------------------------------------------------------------------

    def run_from_signals(
        self,
        raw_signals: Sequence[RawSignal],
        *,
        channel: str = "chat",
        user_text: str = "",
        session_id: Optional[str] = None,
        active_goal: Any = None,
        idle_seconds: Optional[float] = None,
        force_deep: bool = False,
        force_fast: bool = False,
        force_reflection: bool = False,
        legacy_frame: Any = None,
        snapshot: Any = None,
    ) -> PipelineResult:
        """Tạo frame từ raw signals rồi chạy toàn bộ canonical planning graph."""

        frame = CognitiveFrame.start(
            raw_signals=list(raw_signals),
            channel=channel,  # type: ignore[arg-type]
            session_id=session_id,
            user_text=user_text or self._infer_user_text(raw_signals),
            turn_id=str(getattr(legacy_frame, "cycle_id", "") or "") or None,
            metadata={
                "legacy_cycle_id": str(getattr(legacy_frame, "cycle_id", "") or ""),
                "has_snapshot": snapshot is not None,
            },
        )
        return self.run(
            frame,
            channel=channel,
            active_goal=active_goal,
            idle_seconds=idle_seconds,
            force_deep=force_deep,
            force_fast=force_fast,
            force_reflection=force_reflection,
            legacy_frame=legacy_frame,
            snapshot=snapshot,
        )

    def run(
        self,
        frame: CognitiveFrame,
        *,
        channel: Optional[str] = None,
        active_goal: Any = None,
        idle_seconds: Optional[float] = None,
        force_deep: bool = False,
        force_fast: bool = False,
        force_reflection: bool = False,
        legacy_frame: Any = None,
        snapshot: Any = None,
    ) -> PipelineResult:
        """Chạy canonical planning graph trên một frame đã có raw_signals."""

        channel = channel or str(getattr(frame, "channel", "unknown"))
        user_text = str(getattr(frame, "user_text", "") or "")

        # --- 0. RawSignal -> EvidenceItem -------------------------------------
        frame.set_status("normalizing", actor="cognitive_pipeline")
        self.normalizer.normalize_into_frame(frame)

        # --- 0b. Situation Model: cập nhật vòng dự đoán -> sai số --------------
        # Chạy TRƯỚC attention để prediction error sẵn sàng cho việc chấm salience.
        # Cô lập lỗi: bất kỳ trục trặc nào cũng để attention tự fallback _novelty_score
        # và chu kỳ vẫn hoàn tất.
        try:
            self.situation_model.observe_and_update(frame)
            frame.metadata["situation"] = self.situation_model.serialize()
        except Exception as exc:
            frame.add_warning(f"situation_model failed: {exc!r}", actor="situation_model")

        # --- 1. Attention: cái gì đáng chú ý ----------------------------------
        frame.set_status("selecting", actor="cognitive_pipeline")
        salience = self.attention.evaluate(
            frame,
            channel=channel,
            active_goal=active_goal,
            write_to_frame=False,
        )
        self._set_slot(
            frame,
            "salience",
            salience,
            actor=self.attention.module_name,
            evidence_used=list(getattr(salience, "selected_evidence_ids", []) or []),
            confidence=self._salience_confidence(salience),
        )

        # --- 2. Budget: chạy nhẹ hay sâu --------------------------------------
        decision = self.budget.choose(
            frame,
            channel=channel,
            user_text=user_text,
            idle_seconds=idle_seconds,
            force_deep=force_deep,
            force_fast=force_fast,
            force_reflection=force_reflection,
            attach_to_frame=False,
        )
        # Budget mode phải có TRƯỚC working_memory (WM đọc frame.budget_mode).
        frame.budget_mode = decision.mode  # type: ignore[assignment]
        frame.metadata["budget_decision"] = decision.to_dict()
        frame.add_report(self._budget_report(decision))

        # --- 3. Time / space / regulation ------------------------------------
        # Các state này phải xuất hiện trước WorkingMemory để downstream không
        # phải mò lại snapshot/raw input bằng cửa sau.
        temporal = self.stages.temporal(frame, idle_seconds=idle_seconds, legacy_frame=legacy_frame)
        self._set_slot(frame, "temporal", temporal, actor="temporal_perception", confidence=0.78)

        spatial = self.stages.spatial(frame, snapshot=snapshot, legacy_frame=legacy_frame)
        self._set_slot(frame, "spatial", spatial, actor="spatial_proprioception", confidence=0.62)

        homeostasis = self.stages.homeostasis(frame, legacy_frame=legacy_frame)
        self._set_slot(frame, "homeostasis", homeostasis, actor="homeostasis", confidence=0.72)

        affect = self.stages.affect(frame, homeostasis, legacy_frame=legacy_frame)
        self._set_slot(frame, "affect", affect, actor="affective_substrate", confidence=0.68)

        # --- 4. Working memory: cái gì được giữ -------------------------------
        wm_frame = self.working_memory.select(frame)
        self._set_slot(
            frame,
            "working_memory",
            wm_frame,
            actor="working_memory",
            evidence_used=list(self._safe_call(wm_frame, "evidence_ids") or []),
            confidence=float(getattr(wm_frame, "context_pressure", 0.0) or 0.0),
        )

        # --- 5. Workspace: cái gì được broadcast ------------------------------
        frame.set_status("interpreting", actor="cognitive_pipeline")
        ws_frame = self.workspace.broadcast(frame)
        ws_evidence = list(self._safe_call(ws_frame, "evidence_ids") or [])
        self._set_slot(
            frame,
            "workspace",
            ws_frame,
            actor="global_workspace",
            evidence_used=ws_evidence,
            confidence=float(getattr(ws_frame, "confidence", 0.0) or 0.0),
        )

        # --- 6. Scene -> Culture -> Meaning -> ToM -----------------------------
        phase2 = self.meaning_pipeline.run(ws_frame)
        frame.metadata["phase2_debug"] = getattr(phase2, "debug", {}) or {}

        self._set_slot(
            frame,
            "world_scene",
            getattr(phase2, "world_scene", None),
            actor="world_scene_builder",
            evidence_used=ws_evidence,
            confidence=self._phase2_stage_confidence(phase2, "WorldSceneBuilder", 0.60),
        )
        self._set_slot(
            frame,
            "interpretation",
            list(getattr(phase2, "observations", []) or []),
            actor="world_interpreter",
            evidence_used=ws_evidence,
            confidence=self._phase2_stage_confidence(phase2, "WorldInterpreter", 0.58),
        )
        self._set_slot(
            frame,
            "sociocultural",
            list(getattr(phase2, "sociocultural_annotations", []) or []),
            actor="sociocultural_context",
            evidence_used=ws_evidence,
            confidence=self._phase2_stage_confidence(phase2, "SocioculturalContext", 0.55),
        )

        meaning = self.stages.meaning(phase2, frame)
        self._set_slot(
            frame,
            "meaning",
            meaning,
            actor="meaning_hypothesis",
            evidence_used=ws_evidence,
            confidence=float(getattr(meaning, "confidence", 0.0) or 0.0),
        )

        tom = self.stages.tom(phase2, ws_frame, frame)
        self._set_slot(
            frame,
            "tom",
            tom,
            actor="theory_of_mind",
            evidence_used=ws_evidence,
            confidence=float(getattr(tom, "global_confidence", 0.0) or 0.0),
        )

        # --- 7. Curiosity / inquiry / memory / belief -------------------------
        epistemic = self.stages.epistemic(frame, meaning, tom)
        self._set_slot(
            frame,
            "epistemic",
            epistemic,
            actor="epistemic_drive",
            evidence_used=ws_evidence,
            confidence=float(getattr(epistemic, "inquiry_urgency", 0.0) or 0.0),
        )

        inquiry = self.stages.inquiry(frame, epistemic, meaning)
        self._set_slot(
            frame,
            "inquiry",
            inquiry,
            actor="inquiry_planner",
            evidence_used=ws_evidence,
            confidence=float(getattr(inquiry, "expected_value", 0.0) or 0.0),
        )

        memory_packet = self.stages.memory_packet(frame, legacy_frame=legacy_frame)
        self._set_slot(
            frame,
            "memory_packet",
            memory_packet,
            actor="memory_cognition",
            evidence_used=ws_evidence,
            confidence=0.70,
        )

        belief = self.stages.belief(frame, meaning)
        belief_conf = max(
            [float(getattr(item, "confidence", 0.0) or 0.0) for item in (belief.active_beliefs + belief.candidate_beliefs)],
            default=0.0,
        )
        self._set_slot(
            frame,
            "belief",
            belief,
            actor="belief_core",
            evidence_used=ws_evidence,
            confidence=belief_conf,
        )

        # --- 8. Values -> simulation -> arbitration -> agency -----------------
        frame.set_status("planning", actor="cognitive_pipeline")
        relation = self.stages.relation(frame, legacy_frame=legacy_frame)
        permission = self.stages.permission(frame, tom, relation, inquiry)
        value_resolution = self.stages.values(frame, inquiry, permission, relation)
        self._set_slot(
            frame,
            "value_resolution",
            value_resolution,
            actor="value_resolution",
            evidence_used=ws_evidence,
            confidence=0.78,
        )

        simulations = self.stages.simulations(frame, inquiry, permission, relation)
        self._set_slot(
            frame,
            "simulations",
            simulations,
            actor="predictive_simulation",
            evidence_used=ws_evidence,
            confidence=max([float(getattr(item, "confidence", 0.0) or 0.0) for item in simulations], default=0.0),
        )

        arbitration = self.stages.arbitration(simulations, inquiry, permission)
        self._set_slot(
            frame,
            "arbitration",
            arbitration,
            actor="cognitive_arbitration",
            evidence_used=ws_evidence,
            confidence=float(getattr(arbitration, "confidence", 0.0) or 0.0),
        )

        agency = self.stages.agency(arbitration, inquiry)
        self._set_slot(
            frame,
            "agency",
            agency,
            actor="agency_engine",
            evidence_used=ws_evidence,
            confidence=float(getattr(agency, "commitment_strength", 0.0) or 0.0),
        )

        # Relation/permission được ghi sau agency đúng canonical order, dù adapter
        # đã tính provisional state để simulation không phải đoán mù.
        self._set_slot(frame, "relation", relation, actor="relational_dynamics", confidence=0.72)
        self._set_slot(
            frame,
            "permission",
            permission,
            actor="permission_engine",
            evidence_used=ws_evidence,
            confidence=float(getattr(permission, "max_intensity", 0.0) or 0.0),
        )

        # --- 9. Speech / body / modality planning -----------------------------
        noise = self.stages.noise(frame)
        self._set_slot(frame, "noise", noise, actor="calculated_noise", confidence=1.0)

        opportunity = self.stages.speech_opportunity(frame, agency, homeostasis, permission)
        self._set_slot(
            frame,
            "speech_opportunity",
            opportunity,
            actor="speech_opportunity",
            confidence=float(getattr(opportunity, "urgency", 0.0) or 0.0),
        )

        speech_plan = self.stages.speech_plan(frame, opportunity, meaning, relation, permission)
        self._set_slot(frame, "speech_plan", speech_plan, actor="speech_core", confidence=0.78)

        body_plan = self.stages.body_plan(frame, opportunity, spatial, permission)
        self._set_slot(frame, "body_plan", body_plan, actor="body_action_planner", confidence=0.68)

        modality = self.stages.modality(speech_plan, body_plan, spatial, permission)
        self._set_slot(
            frame,
            "modality",
            modality,
            actor="modality_sync",
            confidence=float(getattr(modality, "emotional_congruence", 0.0) or 0.0),
        )

        # Wording/guard/execution có placeholder có cấu trúc ngay trong planning
        # frame. Khi runtime cũ sinh text và thực thi xong, finalize_from_legacy sẽ
        # thay chúng bằng kết quả thật rồi mới đóng frame.
        wording = self.stages.deferred_wording()
        self._set_slot(frame, "wording", wording, actor="llm_wording", confidence=0.50)

        grounding = self.stages.baseline_grounding(frame, permission, modality)
        self._set_slot(frame, "grounding", grounding, actor="grounding_guard", confidence=0.72)

        execution = self.stages.planned_execution(agency, modality)
        self._set_slot(frame, "execution", execution, actor="execution_layer", confidence=0.50)

        trace = attach_trace_to_frame(frame)
        frame.metadata["canonical_planning_complete"] = True
        # Không close ở đây. Output thật vẫn chạy qua runtime hiện có; finalizer
        # sẽ điền wording/grounding/execution/outcome và đóng đúng một lần.
        return PipelineResult(frame=frame, budget_decision=decision, debug_trace=trace, finalized=False)

    def render_prompt_context(self, frame: CognitiveFrame) -> str:
        """Projection compact của kế hoạch V3 cho wording layer hiện hữu."""
        try:
            return self.stages.render_prompt_context(frame)
        except Exception as exc:
            frame.add_warning(f"render_prompt_context failed: {exc!r}", actor="cognitive_pipeline")
            return ""

    def finalize_from_legacy(
        self,
        frame_or_result: CognitiveFrame | PipelineResult,
        *,
        legacy_frame: Any = None,
        final_decision: Any = None,
        grounding: Any = None,
        execution: Any = None,
        outcome: Any = None,
        self_observation: Any = None,
    ) -> PipelineResult:
        """Khép vòng canonical sau khi runtime cũ đã wording/guard/execute.

        Đây là cầu chuyển tiếp có chủ đích. Nó không chạy lại cognition và không
        tạo một quyết định thứ hai. Nó chỉ đưa kết quả production đã xảy ra vào
        đúng slot V3, chạy Outcome/SelfObservation nếu caller chưa có report, rồi
        đóng frame. Nhờ vậy V3 là xương sống quan sát được thay vì một bản shadow
        chết ở GlobalWorkspace.
        """
        if isinstance(frame_or_result, PipelineResult):
            result = frame_or_result
            frame = result.frame
        else:
            frame = frame_or_result
            result = PipelineResult(frame=frame, budget_decision=None, debug_trace={})

        if str(getattr(frame, "status", "")) == "closed":
            result.debug_trace = attach_trace_to_frame(frame)
            result.finalized = True
            return result

        legacy_final = final_decision
        if legacy_final is None and legacy_frame is not None:
            legacy_final = getattr(legacy_frame, "final_decision", None)
        text = self._extract_final_text(legacy_final)
        violations = self._extract_violations(grounding if grounding is not None else getattr(legacy_frame, "grounding", None))

        frame.set_status("wording", actor="cognitive_pipeline")
        wording_result = LLMWordingResult(
            raw_text=text,
            parsed_text=text or None,
            parser_ok=not bool(violations),
            violations=violations,
            deferred=False,
        )
        self._set_slot(
            frame,
            "wording",
            wording_result,
            actor="llm_wording",
            confidence=0.92 if text else 0.55,
        )

        frame.set_status("guarding", actor="cognitive_pipeline")
        legacy_grounding = grounding if grounding is not None else getattr(legacy_frame, "grounding", None)
        grounding_result = self._coerce_grounding(legacy_grounding, final_text=text, fallback=frame.grounding)
        self._set_slot(frame, "grounding", grounding_result, actor="grounding_guard", confidence=0.88)

        frame.set_status("executing", actor="cognitive_pipeline")
        legacy_execution = execution if execution is not None else getattr(legacy_frame, "execution", None)
        execution_result = self._coerce_execution(legacy_execution, legacy_final, text=text, fallback=frame.execution)
        self._set_slot(frame, "execution", execution_result, actor="execution_layer", confidence=0.86)

        frame.set_status("observing", actor="cognitive_pipeline")
        outcome_result = outcome if outcome is not None else getattr(legacy_frame, "outcome", None)
        if outcome_result is None:
            outcome_result = self.outcome_observer.observe(
                frame,
                execution_result=execution_result,
                body_result=getattr(frame, "modality", None),
                attach_to_frame=False,
            )
        self._set_slot(frame, "outcome", outcome_result, actor="outcome_observer", confidence=float(getattr(outcome_result, "confidence", 0.60) or 0.60))

        self_obs_result = self_observation if self_observation is not None else getattr(legacy_frame, "self_observation", None)
        if self_obs_result is None:
            self_obs_result = self.self_observer.reflect(frame, outcome=outcome_result, attach_to_frame=False)
        self._set_slot(
            frame,
            "self_observation",
            self_obs_result,
            actor="self_observation",
            confidence=float(getattr(self_obs_result, "confidence", 0.60) or 0.60),
        )
        try:
            self.self_observer.append_repair_commit_request(frame, report=self_obs_result)
        except Exception as exc:
            frame.add_warning(f"repair request bridge failed: {exc!r}", actor="self_observation")

        frame.metadata["canonical_finalized_from_legacy"] = legacy_frame is not None
        frame.close(actor="cognitive_pipeline")
        result.debug_trace = attach_trace_to_frame(frame)
        result.finalized = True
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_final_text(final_decision: Any) -> str:
        if final_decision is None:
            return ""
        if isinstance(final_decision, dict):
            return str(final_decision.get("text", final_decision.get("final_text", "")) or "").strip()
        for name in ("text", "final_text", "parsed_text", "raw_text"):
            value = getattr(final_decision, name, None)
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def _extract_violations(grounding: Any) -> list[str]:
        if grounding is None:
            return []
        if isinstance(grounding, dict):
            values = grounding.get("violations", grounding.get("unsupported_claims", []))
        else:
            values = getattr(grounding, "violations", getattr(grounding, "unsupported_claims", []))
        if isinstance(values, str):
            values = [values]
        return [str(value) for value in (values or []) if str(value).strip()]

    @staticmethod
    def _read_any(obj: Any, name: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _coerce_grounding(self, value: Any, *, final_text: str, fallback: Any = None) -> GroundingReport:
        source = value if value is not None else fallback
        if isinstance(source, GroundingReport):
            source.final_text = final_text or source.final_text
            return source
        unsupported = self._read_any(source, "unsupported_claims", []) or []
        if isinstance(unsupported, str):
            unsupported = [unsupported]
        return GroundingReport(
            factual_risk=float(self._read_any(source, "factual_risk", 0.0) or 0.0),
            unsupported_claims=[str(x) for x in unsupported],
            overcertainty_risk=float(self._read_any(source, "overcertainty_risk", 0.0) or 0.0),
            tone_violation=float(self._read_any(source, "tone_violation", 0.0) or 0.0),
            permission_violation=float(self._read_any(source, "permission_violation", 0.0) or 0.0),
            body_action_mismatch=float(self._read_any(source, "body_action_mismatch", 0.0) or 0.0),
            repair_action=self._read_any(source, "repair_action", None),
            final_text=final_text or self._read_any(source, "final_text", None),
        )

    def _coerce_execution(self, value: Any, final_decision: Any, *, text: str, fallback: Any = None) -> ExecutionReport:
        source = value if value is not None else fallback
        final = final_decision if isinstance(final_decision, dict) else {}
        animation = str(final.get("animation", final.get("motion", "")) or "")
        system_action = final.get("system_action")
        status = str(self._read_any(source, "status", "executed") or "executed")
        success = self._read_any(source, "success", None)
        speech_done = bool(text)
        body_done = bool(animation) or bool(self._read_any(source, "body_executed", False))
        system_done = bool(system_action) or bool(self._read_any(source, "system_action_executed", False))
        if success is False:
            status = "failed"
        return ExecutionReport(
            status=status,
            speech_executed=speech_done or bool(self._read_any(source, "speech_executed", False)),
            body_executed=body_done,
            system_action_executed=system_done,
            memory_commit_deferred=True,
            details={
                "legacy_execution": repr(source)[:500] if source is not None else "",
                "animation": animation,
                "system_action": system_action,
            },
        )

    @staticmethod
    def _phase2_stage_confidence(phase2: Any, stage_name: str, default: float) -> float:
        debug = getattr(phase2, "debug", {}) or {}
        stages = debug.get("stages", debug.get("stage_debugs", [])) if isinstance(debug, dict) else []
        for item in stages or []:
            name = item.get("stage", item.get("module", "")) if isinstance(item, dict) else getattr(item, "stage", getattr(item, "module", ""))
            if str(name) == stage_name:
                if isinstance(item, dict):
                    return float(item.get("confidence", default) or default)
                return float(getattr(item, "confidence", default) or default)
        return default

    def _set_slot(
        self,
        frame: CognitiveFrame,
        slot_name: str,
        value: Any,
        *,
        actor: str,
        evidence_used: Optional[list[str]] = None,
        confidence: Optional[float] = None,
    ) -> None:
        try:
            frame.set_slot(
                slot_name,  # type: ignore[arg-type]
                value,
                actor=actor,
                evidence_used=evidence_used,
                confidence=confidence,
            )
            # Mọi stage để lại ModuleReport chuẩn. Trước đây nhiều module chỉ set
            # slot, khiến debug frame nhìn như có hai module hoạt động dù cả pipeline
            # đã chạy. Một trò ảo thuật không ai yêu cầu.
            if actor not in getattr(frame, "module_reports", {}):
                frame.add_report(ModuleReport(
                    module_name=actor,
                    confidence=float(confidence if confidence is not None else 0.5),
                    pressure=float(confidence if confidence is not None else 0.0),
                    evidence_used=list(evidence_used or []),
                    result=value,
                    warnings=[],
                    debug={"slot": slot_name, "canonical_bridge": True},
                ))
        except Exception as exc:
            # Không để integration làm chết pipeline; ghi cảnh báo để debug_trace thấy.
            frame.add_warning(f"set_slot({slot_name}) failed: {exc!r}", actor=actor)
            try:
                setattr(frame, slot_name, value)
            except Exception:
                pass

    @staticmethod
    def _safe_call(obj: Any, method: str) -> Any:
        fn = getattr(obj, method, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                return None
        return None

    @staticmethod
    def _salience_confidence(salience: Any) -> float:
        vals = [
            float(getattr(salience, name, 0.0) or 0.0)
            for name in ("user_relevance", "goal_relevance", "risk_relevance", "broadcast_priority")
        ]
        return max(vals) if vals else 0.0

    @staticmethod
    def _budget_report(decision: BudgetDecision) -> ModuleReport:
        return ModuleReport(
            module_name="cognitive_budget",
            confidence=float(getattr(decision, "confidence", 0.0) or 0.0),
            pressure=float(getattr(decision.snapshot, "salience_priority", 0.0) or 0.0),
            evidence_used=[],
            result=decision.mode,
            warnings=list(getattr(decision, "warnings", []) or []),
            debug={
                "urgency": decision.urgency,
                "reason": decision.reason,
                "escalation": list(decision.escalation_reasons),
                "downgrade": list(decision.downgrade_reasons),
            },
        )

    @staticmethod
    def _infer_user_text(raw_signals: Sequence[RawSignal]) -> str:
        for signal in raw_signals:
            if getattr(signal, "source", "") == "user_chat":
                content = getattr(signal, "content", "")
                if isinstance(content, str):
                    return content
        return ""


__all__ = [
    "CognitivePipeline",
    "PipelineResult",
]
