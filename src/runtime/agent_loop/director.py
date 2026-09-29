# -*- coding: utf-8 -*-
"""ConversationDirector V7 — projection thuần, KHÔNG sở hữu disclosure policy.

Từ V7, quyền quyết định *ý nào được nói ở lượt hiện tại* thuộc hoàn toàn về
``TurnAgentLoop`` / root executive.

Director không còn được phép:
- tự chọn 1/2/N DialogueBeat dựa trên voice/text mode;
- tự chuyển beat sang deferred;
- tự dedupe rồi làm mất một claim mà executive đã chủ động muốn nói;
- tự tạo fallback proposition khi executive quên lập public plan;
- dùng word/time/max_beats để giới hạn public semantic content.

Director chỉ còn là boundary adapter cơ học:
1) nhận snapshot discourse mà agent đã quyết;
2) project chính xác các beat có ``say_now=True`` cho public writer;
3) giữ nguyên continuation/deferred mà agent đã quyết;
4) validate contract và phản hồi lỗi trở lại agent loop để agent tự re-plan.

Nói ngắn gọn: **agent quyết định; runtime thi hành**.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import ConversationSpeechPlan, DiscoursePlan, SpeechContinuationMode


@dataclass(frozen=True, slots=True)
class DisclosureValidation:
    """Kết quả kiểm tra contract, không chứa quyết định thay agent."""

    valid: bool
    reason: str = ""


class ConversationDirector:
    """Adapter/projection cho discourse plan do root agent sở hữu.

    Tên class được giữ để không phá caller cũ. Từ V7 class này **không còn là
    owner của pacing/disclosure**. Mọi semantic choice phải có nguồn gốc từ
    ``TurnDecision.discourse`` do agent loop sinh ra.
    """

    DEFAULT_STYLE_NOTES = (
        "Nói tự nhiên như hội thoại; không đọc tên DialogueBeat ra ngoài.",
        "Không public chain-of-thought; chỉ nói kết luận, bằng chứng, ví dụ và lý do giải thích được.",
        "Không tự xổ continuation.deferred_threads vào lượt hiện tại.",
    )

    def accept_agent_snapshot(self, current: DiscoursePlan, incoming: DiscoursePlan) -> DiscoursePlan:
        """Nhận nguyên snapshot discourse mới nhất của executive.

        ``current`` chỉ còn trong signature để tương thích API. Ta cố ý KHÔNG
        merge beat/continuation theo heuristic vì merge semantic cũng là một dạng
        runtime tự quyết định nội dung. Executive đã nhìn thấy state vòng trước;
        vì vậy mỗi iteration phải trả lại *toàn bộ public/disclosure plan hiện tại*.
        """
        del current
        return incoming

    # Compatibility alias cho code/test cũ. ``max_beats`` bị bỏ qua có chủ ý.
    def merge(self, current: DiscoursePlan, incoming: DiscoursePlan, *, max_beats: int = 8) -> DiscoursePlan:
        del max_beats
        return self.accept_agent_snapshot(current, incoming)

    def project_for_writer(self, plan: DiscoursePlan) -> DiscoursePlan:
        """Project đúng quyết định ``say_now`` của agent sang public writer.

        Đây là phép chiếu cơ học, không phải lựa chọn của runtime:
        - ``say_now=True``  -> writer được nói;
        - ``say_now=False`` -> writer không được nói ở turn này.

        Runtime KHÔNG tự thêm beat ``say_now=False`` vào deferred. Nếu agent muốn
        giữ nó cho lượt sau, chính agent phải ghi vào ``continuation.deferred_threads``.
        """
        public_beats = tuple(beat for beat in plan.beats if beat.say_now)
        return type(plan)(
            response_mode=plan.response_mode,
            disclosure_mode=plan.disclosure_mode,
            beats=public_beats,
            style_notes=plan.style_notes,
            user_response_required=plan.user_response_required,
            speech_budget=plan.speech_budget,
            continuation=plan.continuation,
            speech_plan=plan.speech_plan,
        )

    def validate_agent_plan(
        self,
        plan: DiscoursePlan,
        *,
        speech_plan: ConversationSpeechPlan | None = None,
        completion_candidate: bool,
        waiting_for_user: bool,
    ) -> DisclosureValidation:
        """Chỉ *phát hiện* plan lỗi; tuyệt đối không tự sửa thay agent.

        Nếu lỗi, ``TurnAgentRuntime`` đưa reason này vào context vòng kế tiếp để
        executive tự tạo plan mới. Đây là khác biệt quan trọng giữa validation
        và policy ownership.
        """
        public_count = sum(1 for beat in plan.beats if beat.say_now and beat.proposition)
        long_plan = speech_plan or ConversationSpeechPlan()

        # Runtime chỉ kiểm tra consistency. Nó không được tự đổi mode/next_intent.
        if long_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE:
            if not (long_plan.next_intent or long_plan.planned_threads):
                return DisclosureValidation(False, "auto_continue_requires_agent_authored_next_intent_or_thread")
            if long_plan.resume_trigger not in {"auto_after_audio", "after_audio", "timer"}:
                return DisclosureValidation(False, "auto_continue_requires_audio_resume_trigger")

        if long_plan.continuation_mode == SpeechContinuationMode.YIELD_USER:
            if long_plan.resume_trigger not in {"user_reply", "user_turn", "user_response"}:
                return DisclosureValidation(False, "yield_user_requires_user_resume_trigger")

        if waiting_for_user and long_plan.continuation_mode == SpeechContinuationMode.AUTO_CONTINUE:
            return DisclosureValidation(False, "tutor_wait_cannot_auto_continue")

        if waiting_for_user:
            if public_count != 1:
                return DisclosureValidation(False, "waiting_user_requires_exactly_one_agent_selected_public_beat")
            if not plan.user_response_required:
                return DisclosureValidation(False, "waiting_user_requires_user_response_flag")
            return DisclosureValidation(True, "")

        if completion_candidate and public_count == 0:
            return DisclosureValidation(False, "completion_requires_agent_selected_public_beat")

        return DisclosureValidation(True, "")

    # V6 compatibility: các method cũ trở thành no-op/projection thuần.
    def apply_turn_pacing(
        self,
        plan: DiscoursePlan,
        *,
        voice_mode: bool,
        explicit_exhaustive_request: bool = False,
        tts_speed: float = 1.0,
    ) -> DiscoursePlan:
        del voice_mode, explicit_exhaustive_request, tts_speed
        return self.project_for_writer(plan)

    def ensure_speakable(self, plan: DiscoursePlan, *, objective: str) -> DiscoursePlan:
        del objective
        return plan

    @staticmethod
    def _dedupe(values: Iterable[str], limit: int) -> tuple[str, ...]:
        """Giữ helper legacy cho import cũ; không dùng trong disclosure V7."""
        out: list[str] = []
        for value in values:
            text = " ".join(str(value or "").strip().split())
            if text and text not in out:
                out.append(text)
            if len(out) >= limit:
                break
        return tuple(out)


__all__ = ["ConversationDirector", "DisclosureValidation"]
