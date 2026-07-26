from __future__ import annotations

"""Deterministic continuity for tiny conversational repair and recent-turn recall.

Module này cố ý chỉ xử lý hai trường hợp có bằng chứng trực tiếp trong session:
- user hỏi mình vừa nói gì;
- user nói "hả/ủa/gì cơ" ngay sau khi ERIS trả lời lệch một câu recent-turn recall.

Nó không thay main model và không suy diễn ý mới. Mục tiêu là chặn hai lỗi UX rất
khó chịu: profile-memory bắt nhầm câu hỏi hội thoại, và public surface im lặng khi
user đang yêu cầu sửa hội thoại.
"""

from dataclasses import dataclass
from typing import Any

from core.conversation_intent import (
    is_recent_user_turn_recall,
    is_short_repair_request,
    normalize_conversation_text,
)
from domain import Decision



@dataclass(slots=True)
class ConversationContinuityAdapter:
    """Trả lời deterministic từ session ledger khi có đủ bằng chứng."""

    ledger: Any

    def try_answer(self, user_text: str) -> Decision | None:
        if is_recent_user_turn_recall(user_text):
            return self._answer_recent_user_turn(user_text)

        if is_short_repair_request(user_text):
            repaired = self._repair_recent_recall(user_text)
            if repaired is not None:
                return repaired
        return None

    def repair_fallback_text(self, user_text: str) -> str:
        """Fallback có nghĩa khi model trả payload rỗng cho một repair request."""

        if not is_short_repair_request(user_text):
            return ""
        previous_user = self._previous_user_turns(user_text)
        if previous_user:
            return f"Tôi vừa trả lời chưa rõ. Bạn đang hỏi: “{previous_user[-1].text}”."
        return "Tôi vừa nói chưa rõ. Tôi sẽ bám lại đúng điều bạn đang hỏi."

    def _answer_recent_user_turn(self, user_text: str) -> Decision:
        turns = self._previous_user_turns(user_text)
        if not turns:
            text = "Trong phiên này chưa có câu nào trước đó của bạn để tôi nhắc lại."
            confidence = 0.92
            trace = "continuity_recent_user_turn|missing_previous_user_turn"
        else:
            text = f"Bạn vừa nói: “{turns[-1].text}”."
            confidence = 0.99
            trace = f"continuity_recent_user_turn|turn={getattr(turns[-1], 'index', 0)}"
        return self._decision(text, confidence=confidence, trace=trace, intent="recent_turn_recall")

    def _repair_recent_recall(self, user_text: str) -> Decision | None:
        turns = self._previous_user_turns(user_text)
        if not turns or not is_recent_user_turn_recall(turns[-1].text):
            return None
        # Bỏ câu recent-recall ngay trước đó để lấy đúng câu mà user muốn nhớ lại.
        if len(turns) < 2:
            return self._decision(
                "Tôi trả lời lệch ý rồi. Trong phiên này chưa có câu nào trước đó để nhắc lại.",
                confidence=0.95,
                trace="continuity_repair|recent_recall_without_target",
                intent="conversation_repair",
            )
        target = turns[-2]
        return self._decision(
            f"Tôi trả lời lệch ý rồi. Bạn vừa nói: “{target.text}”.",
            confidence=0.99,
            trace=f"continuity_repair|target_turn={getattr(target, 'index', 0)}",
            intent="conversation_repair",
        )

    def _previous_user_turns(self, current_text: str) -> list[Any]:
        getter = getattr(self.ledger, "user_turns", None)
        turns = list(getter() if callable(getter) else [])
        # Orchestrator ghi current turn vào ledger trước khi gọi adapter. Loại đúng
        # lượt hiện tại, nhưng không xóa hai câu giống nhau thật sự ở trước đó.
        if turns and normalize_conversation_text(getattr(turns[-1], "text", "")) == normalize_conversation_text(current_text):
            turns = turns[:-1]
        return turns

    @staticmethod
    def _decision(text: str, *, confidence: float, trace: str, intent: str) -> Decision:
        return Decision(
            text=text,
            animation="stand",
            intent=intent,
            action="answer",
            reasoning_tags=("answer_first", "session_continuity", intent),
            should_speak=True,
            confidence=confidence,
            direction=0,
            target_x=-1.0,
            bounce_action="",
            debug_trace=trace,
            next_animation="stand",
            parse_mode="conversation_continuity",
            system_action="",
            action_input="",
            delivery_hint="focused",
            performance_hint="focused",
        )
