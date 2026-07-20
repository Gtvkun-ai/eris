# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.cognition import PreResponseCognitiveBrief
from .frame_builder import CognitiveFrameBuilder
from .specialists import DiscourseCortex, EpistemicCortex, SemanticCortex, SocialCortex, StyleCortex
from .workspace import CognitiveWorkspace


class PreResponseCognition:
    """Facade duy nhất được Architecture C gọi trước planner.

    Tất cả specialist đều deterministic/read-only. Một specialist lỗi không được
    làm chết lượt chat; engine hạ về brief trung tính và ghi log, thay vì kéo cả
    runtime về fallback hỏi lại người dùng như một cái máy bán vé hết giấy.
    """

    def __init__(self, *, logger: Any | None = None) -> None:
        self.logger = logger
        self.frame_builder = CognitiveFrameBuilder()
        self.discourse = DiscourseCortex()
        self.semantic = SemanticCortex()
        self.epistemic = EpistemicCortex()
        self.social = SocialCortex()
        self.style = StyleCortex()
        self.workspace = CognitiveWorkspace()

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
        try:
            discourse = self.discourse.project(frame)
            semantic = self.semantic.project(frame, discourse)
            epistemic = self.epistemic.project(frame, discourse, semantic)
            social = self.social.project(frame, discourse, semantic)
            style = self.style.project(frame, discourse, semantic, social)
            brief = self.workspace.compile(
                trace_id=frame.trace_id,
                discourse=discourse,
                semantic=semantic,
                epistemic=epistemic,
                social=social,
                style=style,
            )
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[cortex v2] projection failed: %s", exc)
            return PreResponseCognitiveBrief.neutral(frame.trace_id)
        self._log(
            "info",
            "[cortex v2] turn=%s relation=%s owner=%s move=%s posture=%s delivery=%s conf=%.2f ambiguity=%.2f",
            turn_seq,
            brief.discourse_relation,
            brief.ambiguity_owner,
            brief.response_move,
            brief.user_posture,
            brief.delivery,
            brief.confidence,
            brief.ambiguity,
        )
        return brief

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass
