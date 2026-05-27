from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    from ..memory.memory_models import MemoryKind, RecallAnswer
    from ..memory.memory_recall_policy import MemoryRecallPolicy
    from .session_turn_ledger import SessionTurnLedger
except ImportError:
    from memory.memory_models import MemoryKind, RecallAnswer
    from memory.memory_recall_policy import MemoryRecallPolicy
    from runtime.session_turn_ledger import SessionTurnLedger


SemanticLookupFn = Callable[[MemoryKind], Optional[Any]]
EpisodicLookupFn = Callable[[str], Optional[Any]]


@dataclass
class MemoryRecallAdapter:
    """
    Adapter gọi trước LLM trong chat cycle.

    Nếu user hỏi câu mà ledger/policy trả lời được, dừng ở đây. Không giao cho LLM
    tự đếm câu hỏi hay tự nhớ tên. LLM đếm chữ đã đủ bi kịch rồi.
    """

    recall_policy: MemoryRecallPolicy
    ledger: SessionTurnLedger
    semantic_lookup: SemanticLookupFn | None = None
    episodic_lookup: EpisodicLookupFn | None = None

    def try_answer(self, user_text: str) -> Optional[RecallAnswer]:
        return self.recall_policy.answer(
            user_text,
            ledger=self.ledger,
            semantic_lookup=self.semantic_lookup,
            episodic_lookup=self.episodic_lookup,
        )

    def try_answer_as_decision_payload(self, user_text: str) -> Optional[dict[str, Any]]:
        """
        Dùng khi muốn trả payload dict thay vì dựng Decision trực tiếp.

        Shape này tương thích kiểu JSON decision phổ biến trong ERIS.
        """
        answer = self.try_answer(user_text)
        if answer is None:
            return None

        return {
            "text": answer.text,
            "intent": "memory_recall",
            "action": "answer",
            "animation": "stand",
            "reasoning_tags": [
                "answer_first",
                "memory_policy",
                answer.surface_mode.value,
            ],
            "should_speak": True,
            "confidence": answer.confidence,
            "direction": "neutral",
            "target_x": 0,
            "bounce_action": "none",
            "extracted_fact": "",
            "debug_trace": answer.debug_trace,
            "next_animation": "stand",
            "system_action": "none",
            "action_input": "",
            "memory_source": answer.source,
        }
