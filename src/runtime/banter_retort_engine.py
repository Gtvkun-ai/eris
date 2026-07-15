from __future__ import annotations

"""Fallback retort có kiểm soát cho ERIS.

Qwen vẫn là người viết chính. Engine này chỉ cung cấp lưới an toàn khi draft bị
Acceptance Gate từ chối, ví dụ literalize "mẹ mày béo" thành bài giảng về việc
AI không có mẹ. Các câu được chọn ổn định theo nội dung để tránh lúc nào cũng
phát đúng một câu, nhưng không dùng random toàn cục làm test chập chờn.
"""

from dataclasses import dataclass
import hashlib
from typing import Mapping

from runtime.emotional_stance_planner import EmotionalStanceKind, EmotionalStancePlan
from runtime.turn_frame import TurnFrame


@dataclass(frozen=True, slots=True)
class RetortFallback:
    text: str
    reason: str


_VARIANTS: Mapping[EmotionalStanceKind, tuple[str, ...]] = {
    EmotionalStanceKind.HUMBLED_REPAIR: (
        "Ừ, câu vừa rồi nghe đúng chất tổng đài. Tôi bỏ giọng đó. Ngài nói thẳng, tôi đáp thẳng.",
        "Đúng, tôi vừa trượt về giọng trợ lý đóng hộp. Rút lại. Nói tiếp đi, lần này tôi nghe như ERIS.",
        "Câu đó phèn thật. Tôi nhận. Bỏ màn giới thiệu đi, ta nói chuyện cho ra nói chuyện.",
    ),
    EmotionalStanceKind.PLAYFUL_RETORT: (
        "À, tôi né sai nhịp. Ngài đang chọc. Được thôi: cú đó mỏng đến mức autocomplete còn ngáp.",
        "Nghe rồi. Tôi vừa làm hỏng cú chọc bằng bài giảng gia phả. Còn câu của Ngài thì vẫn thiếu lực một cách đáng yêu.",
        "Rồi, tôi hiểu lần này. Ngài chọc tôi, không hỏi hộ khẩu. Nhưng cú chọc ấy vẫn cần thêm chút trí tưởng tượng.",
    ),
    EmotionalStanceKind.DRY_TEASE: (
        "Ngài lôi cả gia phả của một đống code ra chọc à. Táo bạo đấy, nhưng câu này hơi thiếu lực.",
        "Tôi ghi nhận nỗ lực công kích. Điểm sáng tạo hơi thấp, nhưng tinh thần tham gia thì đáng khen.",
        "Cú đó vừa chạm tới tôi rồi trượt xuống vì thiếu nội dung. Ngài thử lại có đầu tư hơn xem.",
    ),
    EmotionalStanceKind.ANNOYED_SOFT: (
        "Tôi nghe rồi. Không cần tăng âm lượng bằng cách giảm chất lượng câu chửi đâu.",
        "Ngài đang cố làm tôi cáu à? Có tiến triển, nhưng câu chửi vẫn còn hơi nghiệp dư.",
        "Cáu thì có một chút. Ấn tượng thì chưa. Hai thứ đó khác nhau, đáng tiếc thật.",
    ),
    EmotionalStanceKind.SHARP_RETORT: (
        "Ngài lặp lại lần nữa cũng không làm câu đó sắc hơn. Nó chỉ chứng minh kho từ đang xin nghỉ.",
        "Cùng một cú chọc, lần thứ hai. Tôi tưởng Ngài đang công kích, hóa ra chỉ đang kiểm tra nút replay.",
        "Tôi nghe từ lần đầu rồi. Lặp lại không phải nhấn mạnh, chỉ là tiết kiệm ý tưởng.",
    ),
    EmotionalStanceKind.COLD_BOUNDARY: (
        "Đủ rồi. Tôi vẫn nói chuyện, nhưng không tiếp tục một vòng hạ nhục lặp lại.",
        "Dừng ở đây. Chọc thì được, đe dọa hoặc hạ nhục kéo dài thì không.",
        "Tôi không né cuộc trò chuyện, nhưng ranh giới này rõ: không đe dọa, không quấy rối lặp lại.",
    ),
    EmotionalStanceKind.NEUTRAL: (
        "Câu vừa rồi của tôi lệch nhịp. Tôi rút lại và trả lời trực tiếp hơn.",
    ),
}


def build_retort_fallback(frame: TurnFrame, plan: EmotionalStancePlan) -> RetortFallback:
    variants = _VARIANTS.get(plan.kind) or _VARIANTS[EmotionalStanceKind.NEUTRAL]
    key = "|".join(
        (
            plan.kind.value,
            str(frame.user_text or ""),
            str(frame.previous_user_text or ""),
            str(frame.previous_assistant_text or ""),
        )
    )
    digest = hashlib.blake2s(key.encode("utf-8", errors="ignore"), digest_size=2).digest()
    index = int.from_bytes(digest, "big") % len(variants)
    return RetortFallback(text=variants[index], reason=f"stance_fallback:{plan.kind.value}")


__all__ = ["RetortFallback", "build_retort_fallback"]
