# -*- coding: utf-8 -*-
"""Authoritative end-to-end runtime facade for ERIS Cognitive Pipeline V3.

Production integrations may keep their existing LLM, tool, TTS and renderer
implementations. They are adapters invoked around this runtime; they no longer
own attention, meaning, permission, agency, grounding or learning policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from core.evidence import RawSignal
from domain import Decision
from runtime.cognitive_pipeline import CognitivePipeline, PipelineResult
from runtime.v3_authority import V3AuthorityController


@dataclass(slots=True)
class RuntimeCycleResult:
    pipeline_result: PipelineResult
    decision: Decision
    commit_report: Any = None

    @property
    def frame(self):
        return self.pipeline_result.frame


class CognitiveRuntime:
    """Canonical runtime with injectable edge adapters.

    `wording_adapter(frame, prompt_context) -> Decision`
    `execution_adapter(decision, frame) -> execution result`

    The adapter signatures are deliberately small. A provider swap should not
    require a spiritual crisis across fourteen modules.
    """

    def __init__(
        self,
        *,
        pipeline: CognitivePipeline | None = None,
        authority: V3AuthorityController | None = None,
        state_committer: Any = None,
    ) -> None:
        self.pipeline = pipeline or CognitivePipeline()
        self.authority = authority or V3AuthorityController()
        self.state_committer = state_committer

    def plan(
        self,
        raw_signals: Sequence[RawSignal],
        *,
        channel: str = "chat",
        user_text: str = "",
        session_id: str | None = None,
        active_goal: Any = None,
        idle_seconds: float | None = None,
        snapshot: Any = None,
        runtime_owner: Any = None,
    ) -> PipelineResult:
        return self.pipeline.run_from_signals(
            raw_signals,
            channel=channel,
            user_text=user_text,
            session_id=session_id,
            active_goal=active_goal,
            idle_seconds=idle_seconds,
            snapshot=snapshot,
            runtime_owner=runtime_owner,
        )

    def govern(self, result: PipelineResult, decision: Decision, *, channel: str = "") -> Decision:
        frame = result.frame
        governed = self.authority.apply_to_decision(decision, v3_frame=frame, channel=channel or str(frame.channel))
        governed, report = self.pipeline.grounding_guard.check(frame, governed)
        frame.grounding = report
        return governed

    def finalize(
        self,
        result: PipelineResult,
        decision: Decision,
        *,
        execution_result: Any = None,
        commit: bool = True,
    ) -> RuntimeCycleResult:
        finalized = self.pipeline.finalize_from_production(
            result,
            final_decision=decision,
            execution=execution_result,
        )
        commit_report = None
        if commit and self.state_committer is not None:
            commit_report = self.state_committer.commit_frame(finalized.frame)
        return RuntimeCycleResult(finalized, decision, commit_report)

    def run_cycle(
        self,
        raw_signals: Sequence[RawSignal],
        *,
        wording_adapter: Callable[[Any, str], Decision],
        execution_adapter: Callable[[Decision, Any], Any] | None = None,
        channel: str = "chat",
        user_text: str = "",
        session_id: str | None = None,
        active_goal: Any = None,
        idle_seconds: float | None = None,
        snapshot: Any = None,
        runtime_owner: Any = None,
        commit: bool = True,
    ) -> RuntimeCycleResult:
        result = self.plan(
            raw_signals,
            channel=channel,
            user_text=user_text,
            session_id=session_id,
            active_goal=active_goal,
            idle_seconds=idle_seconds,
            snapshot=snapshot,
            runtime_owner=runtime_owner,
        )
        prompt_context = self.pipeline.render_prompt_context(result.frame)
        decision = wording_adapter(result.frame, prompt_context)
        if not isinstance(decision, Decision):
            raise TypeError("wording_adapter must return domain.Decision")
        decision = self.govern(result, decision, channel=channel)
        execution_result = execution_adapter(decision, result.frame) if execution_adapter is not None else None
        return self.finalize(result, decision, execution_result=execution_result, commit=commit)


__all__ = ["CognitiveRuntime", "RuntimeCycleResult"]
