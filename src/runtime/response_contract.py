from __future__ import annotations

"""ResponseContract: biến hiểu hội thoại thành nghĩa vụ có thể kiểm tra.

Detector không được viết thay model. Nhưng nếu detector thấy user đang phê bình
"mày nói như trợ lý AI", draft cuối không được phép tự giới thiệu "Tôi là ERIS,
trợ lý cá nhân..." rồi vỗ tay vì JSON sạch. Đây là cái cửa soát vé đó.
"""

from dataclasses import dataclass, field
from typing import Iterable

from actions.capability_registry import capability_surface_keywords, render_capability_registry_prompt
from runtime.social_act import normalize_vi_ascii
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class ResponseObligation:
    kind: str
    priority: int = 50
    must: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    fallback_text: str = ""


@dataclass(frozen=True, slots=True)
class ResponseContract:
    obligations: tuple[ResponseObligation, ...] = ()
    prohibited_markers: tuple[str, ...] = ()
    capability_keywords: tuple[str, ...] = ()
    prompt_notes: tuple[str, ...] = ()
    fallback_text: str = ""

    @property
    def active(self) -> bool:
        return bool(self.obligations or self.prohibited_markers or self.prompt_notes)

    def to_prompt_block(self) -> str:
        if not self.active:
            return ""
        lines = ["RESPONSE_CONTRACT: binding obligations for the public reply."]
        for obligation in sorted(self.obligations, key=lambda o: -o.priority):
            lines.append(f"- obligation={obligation.kind}; priority={obligation.priority}")
            for item in obligation.must:
                lines.append(f"  MUST: {item}")
            for item in obligation.must_not:
                lines.append(f"  MUST_NOT: {item}")
        for note in self.prompt_notes:
            lines.append(f"- {note}")
        if self.prohibited_markers:
            lines.append("- banned_public_surfaces=" + ", ".join(self.prohibited_markers[:16]))
        lines.append("If you cannot satisfy the contract, produce a short direct repair line rather than a generic assistant answer.")
        return "\n".join(lines)


def build_response_contract(frame: TurnFrame, *, capability_action_ids: Iterable[str] | None = None) -> ResponseContract:
    obligations: list[ResponseObligation] = []
    prohibited: list[str] = []
    notes: list[str] = []
    fallback = ""
    cap_keywords: tuple[str, ...] = ()

    if frame.has_relation("META_STYLE_FEEDBACK"):
        obligations.append(ResponseObligation(
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
            fallback_text="Ừ, đúng. Câu đó nghe như bot tổng đài. Tôi chỉnh lại: Ngài ném việc cụ thể sang đây, tôi xử lý thẳng, khỏi màn 'sẵn sàng hỗ trợ' phèn đó.",
        ))
        prohibited.extend(("toi la eris", "tro ly ca nhan", "san sang ho tro", "toi co the giup", "hay cho toi biet", "dat cau hoi"))
        fallback = obligations[-1].fallback_text

    if frame.has_relation("CAPABILITY_INQUIRY"):
        cap_prompt = render_capability_registry_prompt(capability_action_ids)
        cap_keywords = capability_surface_keywords(capability_action_ids)
        obligations.append(ResponseObligation(
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
            fallback_text=_capability_fallback(),
        ))
        notes.append(cap_prompt)
        prohibited.extend(("tu van y te", "tu van phap ly", "khong thay the chuyen gia", "hay dat cau hoi", "toi co the ho tro nhieu linh vuc"))
        fallback = obligations[-1].fallback_text if not fallback else fallback

    if frame.has_relation("REASSERT_AFTER_MISREAD") or frame.has_relation("REASSERT_AFTER_INTERRUPTION"):
        obligations.append(ResponseObligation(
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
            fallback_text="À, tôi né sai nhịp rồi. Ý Ngài là đang nhắc lại cú chọc đó, không phải mở hồ sơ gia phả của tôi.",
        ))
        prohibited.extend(("toi khong co me", "toi khong co gia dinh", "toi la mot ai", "toi la eris", "san sang ho tro"))
        fallback = obligations[-1].fallback_text if not fallback else fallback

    if frame.has_relation("PROVOCATION"):
        obligations.append(ResponseObligation(
            kind="HANDLE_PROVOCATION_WITH_DRY_BOUNDARY",
            priority=80,
            must=(
                "Recognize the provocation/chọc, answer with dry boundary or light tease.",
            ),
            must_not=(
                "Do not literalize family insults as factual family questions.",
                "Do not reset into helper mode.",
            ),
            fallback_text="Cú đó hơi thiếu trí tưởng tượng, thưa Ngài. Nhưng được, tôi hiểu: Ngài đang chọc chứ không hỏi tôi làm giấy khai sinh.",
        ))
        prohibited.extend(("toi khong co me", "toi khong co bo", "toi khong co gia dinh", "la ai", "san sang ho tro"))
        fallback = obligations[-1].fallback_text if not fallback else fallback

    if frame.has_relation("CHALLENGE_PREVIOUS_WORDING") and not frame.has_relation("CAPABILITY_INQUIRY"):
        obligations.append(ResponseObligation(
            kind="ANSWER_WORDING_CHALLENGE",
            priority=70,
            must=("Acknowledge that the previous helper wording was vague or hollow.",),
            must_not=("Do not ask the user to restate the problem as if nothing happened.",),
            fallback_text="Ý Ngài là câu 'hỗ trợ' của tôi rỗng quá chứ gì. Đúng, nó nghe như nút help màu xám. Tôi nói cụ thể hơn.",
        ))
        prohibited.extend(("ban dang gap van de gi", "ngai can ho tro gi", "hay mo ta van de"))
        fallback = obligations[-1].fallback_text if not fallback else fallback

    return ResponseContract(
        obligations=tuple(obligations),
        prohibited_markers=tuple(dict.fromkeys(prohibited)),
        capability_keywords=cap_keywords,
        prompt_notes=tuple(notes),
        fallback_text=fallback,
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


def _capability_fallback() -> str:
    return (
        "Tôi làm được mấy việc thật trong runtime: mở hoặc focus ứng dụng, mở URL, chỉnh âm lượng, "
        "play/pause media, copy text, tìm web và xem thời tiết nếu tool đang bật. Nói tên việc cụ thể, "
        "tôi sẽ xử lý thẳng, khỏi màn quảng cáo trợ lý đa năng nghe phát mệt."
    )


def normalize_public_text(text: str) -> str:
    return normalize_vi_ascii(text)
