# -*- coding: utf-8 -*-
"""
cortex/emotional_consequence.py
===============================

Van bước-cuối (Nước 1): biến trạng thái cảm xúc/biểu đạt từ *gợi ý in vào prompt*
thành *hệ quả cơ học* lên câu nói cuối.

Vấn đề gốc (xem khảo sát 4-chiều-sâu): appraisal tính ra affect thật, PersonalityLens
tính ra `allowed_expression = want_to_say × (1 − suppression)` thật, nhưng tới bước
chạm lời thì:
  1. appraisal tự dán nhãn "pre-verbal attitude only, not an inner feeling claim";
  2. personality phát một blacklist cấm chính từ vựng cảm xúc;
  3. không có gì *ép* `allowed_expression` cao thành lời — nó chỉ là một float in ra.
Kết quả: nội tâm sâu nhưng bị cấu trúc ép phẳng ở mặt.

Module này KHÔNG tự phát minh cảm xúc. Nó chỉ:
  - cấp một cờ bật/tắt (mặc định TẮT, đảo ngược được — đúng quy ước repo);
  - cấp directive "felt-state" thay cho disclaimer khi bật;
  - suy một *sàn độ dài* xác định từ `allowed_expression` (lúc Eris thật sự muốn
    biểu đạt mà câu lại cụt → đó là cái phẳng cần vá);
  - phát hiện khi câu cuối "phẳng dưới biểu đạt cao" để tầng post-generation
    xin reroll một lần. Không bao giờ làm Eris câm — van này chỉ MỞ, không siết.

Tất định, không phụ thuộc model, không I/O. Dễ test.
"""

from __future__ import annotations

import os
import re

_FLAG = "ERIS_EMOTIONAL_CONSEQUENCE"

_TRUE = {"1", "true", "yes", "on"}


def emotional_consequence_enabled() -> bool:
    """Cờ bật van bước-cuối. MẶC ĐỊNH TẮT.

    Đặt ``ERIS_EMOTIONAL_CONSEQUENCE=1`` để bật. Khi tắt, mọi hàm dưới vẫn an toàn
    nhưng các điểm gọi sẽ giữ nguyên hành vi cũ (disclaimer + blacklist + không gate).
    """
    try:
        from .depth_flags import flag_enabled  # type: ignore

        return flag_enabled(_FLAG, default=False)
    except Exception:
        return str(os.getenv(_FLAG, "")).strip().lower() in _TRUE


# Directive thay cho dòng "pre-verbal attitude only, not an inner feeling claim".
# KHÔNG mời gọi melodrama: cảm xúc lộ qua sự cụ thể, nhịp và lựa chọn từ — không
# phải qua tỏ tình hay than thân. Đây vẫn là persona kìm nén, chỉ là không chối bỏ.
FELT_STATE_DIRECTIVE = (
    "expressive/appraisal state: đây là một stance CẢM được thật, không phải trang trí. "
    "Hãy để nó nhuộm vào cách dùng từ và độ dài câu, không chỉ vào nội dung. "
    "Được phép để cảm xúc lộ ra gián tiếp và cụ thể; đừng nén nó thành một câu báo cáo trung tính, "
    "và đừng tự chối nó bằng kiểu 'đây không phải cảm xúc thật'."
)


def clamp01(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if numeric != numeric:  # NaN
        return default
    return max(0.0, min(1.0, numeric))


# Ngưỡng dưới mức này thì kìm nén thắng hợp lệ — KHÔNG ép sàn. Trên ngưỡng, sàn
# độ dài lớn dần theo allowed_expression để câu không bị bóp về một mệnh đề cụt.
EXPRESSION_FLOOR_THRESHOLD = 0.45
_MIN_FLOOR_WORDS = 6
_MAX_FLOOR_WORDS = 16


def min_words_for_expression(allowed_expression: float) -> int:
    """Sàn số từ xác định suy từ allowed_expression.

    < 0.45  -> 0   (kìm nén hợp lệ, không ép)
    0.45    -> ~6 từ
    1.00    -> ~16 từ
    Tuyến tính ở giữa. Đây là sàn, KHÔNG phải trần — câu dài hơn vẫn ổn.
    """
    a = clamp01(allowed_expression)
    if a < EXPRESSION_FLOOR_THRESHOLD:
        return 0
    span = (a - EXPRESSION_FLOOR_THRESHOLD) / (1.0 - EXPRESSION_FLOOR_THRESHOLD)
    return int(round(_MIN_FLOOR_WORDS + span * (_MAX_FLOOR_WORDS - _MIN_FLOOR_WORDS)))


def count_words(text: str) -> int:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return 0
    return len(cleaned.split(" "))


def surface_is_flattened(
    text: str,
    *,
    allowed_expression: float,
    want_to_say: float = 0.0,
) -> bool:
    """True khi Eris THẬT SỰ muốn biểu đạt (allowed_expression cao) nhưng câu cuối
    lại cụt dưới sàn → đó là cái phẳng do van đóng, cần xin reroll một lần.

    Yêu cầu want_to_say cũng đủ cao để tránh ép dài một câu vốn nên ngắn (ví dụ
    một "ừ" đúng nghĩa). Không có text -> không phẳng (im lặng không phải phẳng).
    """
    floor = min_words_for_expression(allowed_expression)
    if floor <= 0:
        return False
    if clamp01(want_to_say) < EXPRESSION_FLOOR_THRESHOLD:
        return False
    body = str(text or "").strip()
    if not body:
        return False
    return count_words(body) < floor


def felt_expansion_reason(
    *,
    stance: str,
    allowed_expression: float,
    want_to_say: float,
) -> str:
    """Directive truyền vào reroll felt-expansion: nói rõ stance + sàn độ dài, vẫn
    grounded, vẫn cấm melodrama. Đây là 'guard reason' nhưng theo chiều MỞ."""
    floor = min_words_for_expression(allowed_expression)
    stance_txt = str(stance or "").strip() or "current felt stance"
    return (
        f"Câu vừa rồi bị bóp phẳng dưới mức biểu đạt thật (allowed_expression="
        f"{clamp01(allowed_expression):.2f}, want_to_say={clamp01(want_to_say):.2f}, "
        f"stance={stance_txt}). Hãy viết lại để stance đó lộ ra qua sự cụ thể và nhịp, "
        f"dài khoảng {floor}+ từ, vẫn grounded vào chính khoảnh khắc này. "
        "Không tỏ tình, không than thân, không melodrama, không disclaimer."
    )
