# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from core.cognition import (
    DiscourseProjection,
    EpistemicProjection,
    PreResponseCognitiveBrief,
    ProjectionFailure,
    SemanticProjection,
    SocialProjection,
    StyleProjection,
)
from .frame_builder import CognitiveFrameBuilder
from .specialists import DiscourseCortex, EpistemicCortex, SemanticCortex, SocialCortex, StyleCortex
from .workspace import CognitiveWorkspace


T = TypeVar("T")


class PreResponseCognition:
    """Facade duy nhất Architecture C gọi trước planner.

    Specialist deterministic và read-only. Mỗi specialist có failure boundary
    riêng: một module hỏng chỉ làm projection của nó suy giảm, không xóa sạch
    những kết luận còn hợp lệ của bốn module khác.
    """

    def __init__(
        self,
        *,
        logger: Any | None = None,
        frame_builder: CognitiveFrameBuilder | None = None,
        discourse: Any | None = None,
        semantic: Any | None = None,
        epistemic: Any | None = None,
        social: Any | None = None,
        style: Any | None = None,
        workspace: CognitiveWorkspace | None = None,
    ) -> None:
        self.logger = logger
        self.frame_builder = frame_builder or CognitiveFrameBuilder()
        self.discourse = discourse or DiscourseCortex()
        self.semantic = semantic or SemanticCortex()
        self.epistemic = epistemic or EpistemicCortex()
        self.social = social or SocialCortex()
        self.style = style or StyleCortex()
        self.workspace = workspace or CognitiveWorkspace()

    def analyze(
        self,
        *,
        user_text: str,
        recent_history: Sequence[Mapping[str, Any] | str],
        turn_id: str,
        turn_seq: int,
        grounding_context: str = "",
        relationship_summary: str = "",
        personality_summary: str = "",
        memory_available: bool = False,
        interrupt_context: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PreResponseCognitiveBrief:
        frame = self.frame_builder.build(
            user_text=user_text,
            recent_history=recent_history,
            turn_id=turn_id,
            turn_seq=turn_seq,
            grounding_context=grounding_context,
            relationship_summary=relationship_summary,
            personality_summary=personality_summary,
            memory_available=memory_available,
            interrupt_context=interrupt_context,
            metadata=metadata,
        )
        failures: list[ProjectionFailure] = []

        discourse = self._project(
            "discourse",
            lambda: self.discourse.project(frame),
            DiscourseProjection(confidence=0.18, ambiguity=0.92, evidence_ids=("turn:user_text",)),
            failures,
        )
        semantic = self._project(
            "semantic",
            lambda: self.semantic.project(frame, discourse),
            SemanticProjection(confidence=0.20, ambiguity=0.90, evidence_ids=("turn:user_text",)),
            failures,
        )
        epistemic = self._project(
            "epistemic",
            lambda: self.epistemic.project(frame, discourse, semantic),
            EpistemicProjection(
                grounding_scope=("user_text", "public_history"),
                uncertainty=0.72,
                overread_risk=0.68,
                confidence=0.20,
                evidence_ids=("turn:user_text",),
            ),
            failures,
        )
        social = self._project(
            "social",
            lambda: self.social.project(frame, discourse, semantic),
            SocialProjection(confidence=0.18, ambiguity=0.88, evidence_ids=("turn:user_text",)),
            failures,
        )
        style = self._project(
            "style",
            lambda: self.style.project(frame, discourse, semantic, social),
            StyleProjection(confidence=0.24, evidence_ids=("turn:user_text",)),
            failures,
        )

        try:
            brief = self.workspace.compile(
                frame=frame,
                discourse=discourse,
                semantic=semantic,
                epistemic=epistemic,
                social=social,
                style=style,
                failures=tuple(failures),
            )
        except Exception as exc:  # workspace là failure boundary cuối, không phải chăn phủ mọi specialist
            failure = ProjectionFailure("workspace", type(exc).__name__, str(exc))
            failures.append(failure)
            self._log("error", "[cortex v2] workspace failed: %s", exc)
            return PreResponseCognitiveBrief.neutral(
                frame.trace_id,
                degraded_modules=tuple(item.module for item in failures),
            )

        self._log(
            "info",
            "[cortex v2] turn=%s relation=%s owner=%s move=%s posture=%s delivery=%s "
            "conf=%.2f ambiguity=%.2f margin=%.2f coverage=%.2f deep=%s degraded=%s conflicts=%s",
            turn_seq,
            brief.discourse_relation,
            brief.ambiguity_owner,
            brief.response_move,
            brief.user_posture,
            brief.delivery,
            brief.confidence,
            brief.ambiguity,
            brief.decision_margin,
            brief.evidence_coverage,
            int(brief.needs_deep_inference),
            ",".join(brief.degraded_modules) or "none",
            ",".join(brief.conflicts) or "none",
        )
        return brief

    def _project(
        self,
        module: str,
        call: Callable[[], T],
        fallback: T,
        failures: list[ProjectionFailure],
    ) -> T:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            failures.append(ProjectionFailure(module, type(exc).__name__, str(exc)))
            self._log("warning", "[cortex v2] specialist=%s failed: %s", module, exc)
            return fallback

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass
