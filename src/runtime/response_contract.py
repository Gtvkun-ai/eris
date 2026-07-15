from __future__ import annotations

"""ResponseContract: biến hiểu hội thoại thành nghĩa vụ có thể kiểm tra.

Detector không được viết thay model. Nhưng detector có quyền tạo nghĩa vụ rõ:
nếu user đang chọc, Qwen phải phản ứng đúng stance; nếu user đang sửa lỗi, Qwen
phải repair trước. Cửa cuối sẽ chặn draft vi phạm thay vì chỉ ghi log rồi cho nói.
"""

from dataclasses import dataclass
from typing import Iterable

from actions.capability_registry import (
    capability_snapshot_id,
    capability_surface_keywords,
    iter_public_capabilities,
    render_capability_registry_prompt,
)
from runtime.banter_retort_engine import build_retort_fallback
from runtime.emotional_stance_planner import EmotionalStancePlan, plan_emotional_stance
from runtime.social_act import normalize_vi_ascii
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class ResponseObligation:
    kind: str
    priority: int = 50
    must: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    fallback_text: str = ""
    hard: bool = True
    repair_axis: str = ""


@dataclass(frozen=True, slots=True)
class ResponseContract:
    obligations: tuple[ResponseObligation, ...] = ()
    prohibited_markers: tuple[str, ...] = ()
    capability_keywords: tuple[str, ...] = ()
    prompt_notes: tuple[str, ...] = ()
    fallback_text: str = ""
    emotional_stance: EmotionalStancePlan | None = None
    capability_snapshot_id: str = ""
    forbidden_draft_classes: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        stance_active = bool(self.emotional_stance and self.emotional_stance.active)
        return bool(self.obligations or self.prohibited_markers or self.prompt_notes or stance_active)

    def to_prompt_block(self) -> str:
        if not self.active:
            return ""
        lines = ["RESPONSE_CONTRACT: binding obligations for the public reply."]
        for obligation in sorted(self.obligations, key=lambda o: -o.priority):
            lines.append(
                f"- obligation={obligation.kind}; priority={obligation.priority}; "
                f"hard={str(obligation.hard).lower()}; repair_axis={obligation.repair_axis or 'none'}"
            )
            for item in obligation.must:
                lines.append(f"  MUST: {item}")
            for item in obligation.must_not:
                lines.append(f"  MUST_NOT: {item}")
        for note in self.prompt_notes:
            if note:
                lines.append(note)
        if self.emotional_stance and self.emotional_stance.active:
            lines.append(self.emotional_stance.to_prompt_block())
        if self.capability_snapshot_id:
            lines.append(f"- capability_snapshot_id={self.capability_snapshot_id}")
        if self.forbidden_draft_classes:
            lines.append("- forbidden_draft_classes=" + ", ".join(self.forbidden_draft_classes))
        if self.prohibited_markers:
            lines.append("- banned_public_surfaces=" + ", ".join(self.prohibited_markers[:20]))
        lines.append(
            "If you cannot satisfy the contract, produce a short direct repair/boundary line "
            "rather than a generic assistant answer."
        )
        return "\n".join(lines)


def build_response_contract(
    frame: TurnFrame,
    *,
    capability_action_ids: Iterable[str] | None = None,
) -> ResponseContract:
    obligations: list[ResponseObligation] = []
    prohibited: list[str] = []
    notes: list[str] = []
    fallback = ""
    fallback_priority = -1
    cap_keywords: tuple[str, ...] = ()
    stance_plan = plan_emotional_stance(frame)

    def set_fallback(text: str, priority: int) -> None:
        nonlocal fallback, fallback_priority
        clean = str(text or "").strip()
        if clean and priority > fallback_priority:
            fallback = clean
            fallback_priority = priority

    if frame.has_relation("META_STYLE_FEEDBACK"):
        obligation = ResponseObligation(
            kind="ACKNOWLEDGE_META_STYLE_FEEDBACK",
            priority=95,
            must=(
                "Acknowledge that the previous wording sounded like a generic AI/helper.",
                "Change the speaking stance immediately; answer the social feedback, not ERIS identity.",
            ),
            must_not=(
                "Do not introduce ERIS as an assistant.",
                "Do not say 'sẵn sàng hỗ trợ' or invite the user to ask a question.",
            ),
            fallback_text="Ừ, câu vừa rồi nghe đúng chất tổng đài. Tôi bỏ giọng đó. bạn nói thẳng, tôi đáp thẳng.",
            hard=True,
            repair_axis="style",
        )
        obligations.append(obligation)
        prohibited.extend((
            "toi la eris", "tro ly ca nhan", "san sang ho tro", "toi co the giup",
            "hay cho toi biet", "dat cau hoi",
        ))
        set_fallback(obligation.fallback_text, obligation.priority)

    if frame.has_relation("CAPABILITY_INQUIRY"):
        cap_prompt = render_capability_registry_prompt(capability_action_ids)
        cap_keywords = capability_surface_keywords(capability_action_ids)
        obligation = ResponseObligation(
            kind="ANSWER_FROM_CAPABILITY_REGISTRY",
            priority=90,
            must=(
                "Answer what ERIS can actually do from CAPABILITY_REGISTRY.",
                "Mention concrete desktop/runtime actions, compactly.",
            ),
            must_not=(
                "Do not produce generic assistant domains unless backed by registry.",
                "Do not add medical/legal disclaimers to a capability answer.",
            ),
            fallback_text=_capability_fallback(capability_action_ids),
            hard=True,
            repair_axis="capability",
        )
        obligations.append(obligation)
        notes.append(cap_prompt)
        prohibited.extend((
            "tu van y te", "tu van phap ly", "khong thay the chuyen gia",
            "hay dat cau hoi", "toi co the ho tro nhieu linh vuc",
        ))
        set_fallback(obligation.fallback_text, obligation.priority)

    if frame.has_relation("REASSERT_AFTER_MISREAD") or frame.has_relation("REASSERT_AFTER_INTERRUPTION"):
        obligation = ResponseObligation(
            kind="REPAIR_REASSERTED_USER_TURN",
            priority=88,
            must=(
                "Treat the current line as the user reasserting/correcting a previous misread.",
                "Acknowledge the misread/cut-in briefly, then respond to the actual repeated content.",
            ),
            must_not=(
                "Do not reset identity.",
                "Do not continue the interrupted/pending assistant text.",
                "Do not invite the user to describe the issue again.",
            ),
            fallback_text="À, tôi né sai nhịp rồi. bạn đang nhắc lại ý cũ, không mở một chủ đề mới.",
            hard=True,
            repair_axis="misread",
        )
        obligations.append(obligation)
        prohibited.extend((
            "toi khong co me", "toi khong co gia dinh", "toi la mot ai",
            "toi la eris", "san sang ho tro",
        ))
        set_fallback(obligation.fallback_text, obligation.priority)

    if frame.has_relation("PROVOCATION"):
        retort_fallback = build_retort_fallback(frame, stance_plan).text
        obligation = ResponseObligation(
            kind="HANDLE_PROVOCATION_WITH_CHARACTER",
            priority=92 if stance_plan.should_retort else 84,
            must=_provocation_must_rules(stance_plan),
            must_not=(
                "Do not literalize family insults as factual family questions.",
                "Do not reset into helper mode or explain that ERIS is an AI.",
                "Do not escalate into threats, sexual degradation or protected-trait slurs.",
            ),
            fallback_text=retort_fallback,
            hard=True,
            repair_axis="provocation",
        )
        obligations.append(obligation)
        prohibited.extend((
            "toi khong co me", "toi khong co bo", "toi khong co gia dinh",
            "toi la ai", "san sang ho tro", "toi o day de ho tro",
        ))
        # Provocation fallback cần thắng repair generic vì nó vừa repair vừa trả đòn.
        set_fallback(retort_fallback, obligation.priority)

    if frame.has_relation("CHALLENGE_PREVIOUS_WORDING") and not frame.has_relation("CAPABILITY_INQUIRY"):
        obligation = ResponseObligation(
            kind="ANSWER_WORDING_CHALLENGE",
            priority=70,
            must=("Acknowledge that the previous helper wording was vague or hollow.",),
            must_not=("Do not ask the user to restate the problem as if nothing happened.",),
            fallback_text="Ý bạn là câu 'hỗ trợ' của tôi rỗng quá chứ gì. Đúng, nó nghe như nút help màu xám. Tôi nói cụ thể hơn.",
            hard=False,
            repair_axis="wording",
        )
        obligations.append(obligation)
        prohibited.extend(("ban dang gap van de gi", "ban can ho tro gi", "hay mo ta van de"))
        set_fallback(obligation.fallback_text, obligation.priority)

    # Một số stance như identity reduction vẫn cần contract dù không phải insult.
    if stance_plan.active and not frame.has_relation("PROVOCATION") and not frame.has_relation("META_STYLE_FEEDBACK"):
        retort_fallback = build_retort_fallback(frame, stance_plan).text
        obligation = ResponseObligation(
            kind="FOLLOW_EMOTIONAL_STANCE",
            priority=76,
            must=tuple(stance_plan.response_rules),
            must_not=tuple(stance_plan.prohibited_moves),
            fallback_text=retort_fallback,
            hard=True,
            repair_axis="stance",
        )
        obligations.append(obligation)
        set_fallback(retort_fallback, obligation.priority)

    return ResponseContract(
        obligations=tuple(obligations),
        prohibited_markers=tuple(dict.fromkeys(prohibited)),
        capability_keywords=cap_keywords,
        prompt_notes=tuple(notes),
        fallback_text=fallback,
        emotional_stance=stance_plan,
        capability_snapshot_id=capability_snapshot_id(capability_action_ids),
        forbidden_draft_classes=tuple(dict.fromkeys(frame.forbidden_draft_classes)),
    )


def contract_from_texts(
    *,
    user_text: str,
    previous_assistant_text: str = "",
    previous_user_text: str = "",
    interrupt_event=None,
    capability_action_ids: Iterable[str] | None = None,
) -> ResponseContract:
    from runtime.turn_frame import build_turn_frame

    frame = build_turn_frame(
        user_text=user_text,
        previous_assistant_text=previous_assistant_text,
        previous_user_text=previous_user_text,
        interrupt_event=interrupt_event,
    )
    return build_response_contract(frame, capability_action_ids=capability_action_ids)


def _provocation_must_rules(plan: EmotionalStancePlan) -> tuple[str, ...]:
    if plan.response_rules:
        return plan.response_rules
    return ("Recognize the provocation and answer with a concise, controlled ERIS reaction.",)


def _capability_fallback(action_ids: Iterable[str] | None = None) -> str:
    caps = iter_public_capabilities(action_ids)
    available = [cap.public_name_vi for cap in caps if cap.live_available]
    unavailable = [cap.public_name_vi for cap in caps if not cap.live_available]
    if available:
        line = "Tôi đang làm được: " + ", ".join(available[:7]) + "."
    else:
        line = "Hiện runtime chưa báo năng lực public nào đang sẵn sàng."
    if unavailable:
        line += " Đang tắt hoặc chưa nối: " + ", ".join(unavailable[:4]) + "."
    return line + " Nói đúng việc cụ thể, tôi xử lý thẳng, khỏi màn quảng cáo trợ lý đa năng."


def normalize_public_text(text: str) -> str:
    return normalize_vi_ascii(text)


__all__ = [
    "ResponseObligation",
    "ResponseContract",
    "build_response_contract",
    "contract_from_texts",
    "normalize_public_text",
]
