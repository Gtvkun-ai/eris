# -*- coding: utf-8 -*-
"""
runtime/cognitive_pipeline.py

Xương sống Phase 1 của ERIS V3.

Mục tiêu của file này là biến mớ module rời rạc thành MỘT đường chạy có thật:

    RawSignal
      -> EvidenceItem            (EvidenceNormalizer)        # Phase: contract
      -> CognitiveFrame          (core.cognitive_frame)      # Phase: xương sống
      -> AttentionSalience       (cái gì đáng chú ý)
      -> CognitiveBudget         (fast/normal/deep/reflection)
      -> WorkingMemory           (cái gì được giữ lại)
      -> GlobalWorkspace         (cái gì được broadcast)
      -> DebugTrace              (vì sao nó chọn như vậy)

Vì sao orchestrator tự ghi slot thay vì để engine tự gắn:
    Các engine (attention/working_memory/global_workspace) gọi
    frame.set_slot(..., writer=...) / set_slot(..., module_name=...) — đó là API
    của một CognitiveFrame ĐỜI KHÁC. CognitiveFrame core dùng set_slot(actor=...).
    Vì engine bọc attach trong try/except, chúng FAIL ÂM THẦM khi gắn slot vào
    frame core. Nếu tin vào attach của engine, salience/working_memory sẽ rỗng mà
    không ai báo. Một cái bug rất kiên nhẫn.

    Nên ở đây orchestrator gọi phần TÍNH của engine rồi tự set_slot với đúng API
    core. Engine đổi cách attach cũng không phá pipeline.

Đây là backbone tối giản nhưng THẬT. Meaning, ToM, Arbitration sẽ nối tiếp sau,
đọc workspace/evidence từ chính frame này, không được đọc raw world nữa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from core.cognitive_frame import CognitiveFrame
from core.evidence import ModuleReport, RawSignal
from core.evidence_normalizer import EvidenceNormalizer, EvidenceNormalizerConfig

from cortex.attention_salience import AttentionSalienceEngine
from cortex.working_memory import WorkingMemoryEngine, WorkingMemoryConfig
from cortex.global_workspace import GlobalWorkspaceEngine
from runtime.cognitive_budget import CognitiveBudgetEngine, BudgetDecision
from runtime.debug_trace import attach_trace_to_frame


@dataclass(slots=True)
class PipelineResult:
    """Kết quả một lần chạy pipeline.

    Giữ cả frame lẫn vài tham chiếu nhanh để caller/test khỏi phải đào lại frame.
    """

    frame: CognitiveFrame
    budget_decision: Optional[BudgetDecision] = None
    debug_trace: dict[str, Any] = field(default_factory=dict)

    @property
    def budget_mode(self) -> str:
        return str(getattr(self.frame, "budget_mode", "unknown"))


class CognitivePipeline:
    """Chạy Phase 1 trên CognitiveFrame core.

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
    ) -> None:
        self.normalizer = normalizer or EvidenceNormalizer(EvidenceNormalizerConfig())
        self.attention = attention or AttentionSalienceEngine()
        self.budget = budget or CognitiveBudgetEngine()
        # Tắt attach của WM: orchestrator tự set slot bằng API core.
        wm_config = WorkingMemoryConfig()
        try:
            wm_config.attach_to_frame = False
        except Exception:
            pass
        self.working_memory = working_memory or WorkingMemoryEngine(wm_config)
        self.workspace = workspace or GlobalWorkspaceEngine()

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
    ) -> PipelineResult:
        """Tạo frame từ raw signals rồi chạy toàn bộ Phase 1."""

        frame = CognitiveFrame.start(
            raw_signals=list(raw_signals),
            channel=channel,  # type: ignore[arg-type]
            session_id=session_id,
            user_text=user_text or self._infer_user_text(raw_signals),
        )
        return self.run(
            frame,
            channel=channel,
            active_goal=active_goal,
            idle_seconds=idle_seconds,
            force_deep=force_deep,
            force_fast=force_fast,
            force_reflection=force_reflection,
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
    ) -> PipelineResult:
        """Chạy Phase 1 trên một frame đã có raw_signals."""

        channel = channel or str(getattr(frame, "channel", "unknown"))
        user_text = str(getattr(frame, "user_text", "") or "")

        # --- 0. RawSignal -> EvidenceItem -------------------------------------
        frame.set_status("normalizing", actor="cognitive_pipeline")
        self.normalizer.normalize_into_frame(frame)

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

        # --- 3. Working memory: cái gì được giữ -------------------------------
        wm_frame = self.working_memory.select(frame)
        self._set_slot(
            frame,
            "working_memory",
            wm_frame,
            actor="working_memory",
            evidence_used=list(self._safe_call(wm_frame, "evidence_ids") or []),
            confidence=float(getattr(wm_frame, "context_pressure", 0.0) or 0.0),
        )

        # --- 4. Workspace: cái gì được broadcast ------------------------------
        frame.set_status("interpreting", actor="cognitive_pipeline")
        ws_frame = self.workspace.broadcast(frame)
        self._set_slot(
            frame,
            "workspace",
            ws_frame,
            actor="global_workspace",
            evidence_used=list(self._safe_call(ws_frame, "evidence_ids") or []),
            confidence=float(getattr(ws_frame, "confidence", 0.0) or 0.0),
        )

        # --- 5. Debug trace ----------------------------------------------------
        trace = attach_trace_to_frame(frame)
        frame.close(actor="cognitive_pipeline")

        return PipelineResult(frame=frame, budget_decision=decision, debug_trace=trace)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
