# -*- coding: utf-8 -*-
"""runtime/snub_tracker.py

Theo dõi khi Eris nói autonomous nhưng user không phản hồi ("bị bơ").
Tích lũy snub_level từ none → mild → moderate → sulking tùy số lần bị bơ,
và reset khi user quay lại chat.

QUAN TRỌNG — Phân biệt loại utterance:
- Câu HỎI user (có dấu ?, kết thúc bằng từ nghi vấn): đáng track đầy đủ.
  Bị bơ câu hỏi mới thật sự đáng dỗi. Level có thể leo tới sulking.
- Câu KHẲNG ĐỊNH / random statement ("Tôi đang nghĩ về cà phê."): user không cần
  phải reply, nên không tính là bị bơ thực sự. Chỉ ghi nhận nhẹ, level tối đa mild.

Thiết kế:
- Pure state class, không import heavy runtime.
- Thread-safe bằng RLock đơn giản.
- In-memory (không persist qua restart).
- Không tự quyết định Eris nói gì — chỉ cung cấp state cho các layer khác.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Ngưỡng thời gian (giây) sau khi Eris HỎI mà user im → coi là bị bơ
_SNUB_THRESHOLD_QUESTION: float = 60.0
# Câu khẳng định: threshold cao hơn nhiều (3 phút), vì user không cần reply
_SNUB_THRESHOLD_STATEMENT: float = 180.0

# Số snub liên tiếp → level (chỉ áp dụng khi câu bị bơ là câu hỏi)
_LEVEL_MODERATE = 2   # 2 câu hỏi bị bơ liên tiếp
_LEVEL_SULKING = 4    # 4+ câu hỏi bị bơ liên tiếp

# Từ nghi vấn tiếng Việt hay xuất hiện ở cuối câu
_VN_QUESTION_ENDINGS = frozenset({
    "không", "chứ", "nhỉ", "à", "hả", "nha", "nhé",
    "hả", "vậy", "sao", "thế", "chưa", "rồi", "ấy",
    "không nhỉ", "không à", "không hả", "vậy hả", "thế hả",
})

# Từ/cụm mở đầu câu hỏi
_VN_QUESTION_STARTERS = frozenset({
    "tại sao", "vì sao", "như thế nào", "thế nào", "bao giờ", "bao lâu",
    "khi nào", "ở đâu", "cái gì", "gì vậy", "gì thế", "ai", "cái gì",
    "có phải", "có không", "có thể",
})


def _classify_utterance(text: str) -> str:
    """Phân loại câu Eris nói: 'question' hoặc 'statement'.

    Trả về 'question' nếu câu có dấu ? hoặc có cấu trúc nghi vấn.
    Trả về 'statement' trong mọi trường hợp còn lại.
    """
    if not text:
        return "statement"
    stripped = text.strip()

    # Dấu hỏi rõ ràng
    if "?" in stripped:
        return "question"

    # Normalize nhẹ để check từ nghi vấn
    lower = stripped.lower()
    # Loại bỏ dấu câu cuối
    lower_clean = re.sub(r"[.,!…]+$", "", lower).strip()

    # Check ending question words
    tokens = lower_clean.split()
    if tokens:
        last_word = tokens[-1]
        if last_word in _VN_QUESTION_ENDINGS:
            return "question"
        # Check last 2 words
        if len(tokens) >= 2:
            last_two = " ".join(tokens[-2:])
            if last_two in _VN_QUESTION_ENDINGS:
                return "question"

    # Check question starters
    for starter in _VN_QUESTION_STARTERS:
        if lower_clean.startswith(starter):
            return "question"

    return "statement"


@dataclass
class SnubState:
    """Trạng thái "bị bơ" hiện tại của Eris."""

    level: str = "none"              # none / mild / moderate / sulking
    snub_count: int = 0              # số lần bị bơ liên tiếp chưa reset
    last_snubbed_text: str = ""      # câu Eris nói bị bơ gần nhất
    last_snubbed_type: str = ""      # "question" hoặc "statement"
    seconds_ignored: float = 0.0    # bao lâu từ khi nói đến khi detect bị bơ
    irritation_delta: float = 0.0   # lượng irritation nên tăng vào internal_state

    @property
    def is_snubbed(self) -> bool:
        return self.level != "none"

    @property
    def should_react(self) -> bool:
        """True khi level đủ để sinh phản ứng trong micro-presence."""
        return self.level in {"mild", "moderate", "sulking"}

    @property
    def was_question(self) -> bool:
        return self.last_snubbed_type == "question"

    def to_seed_label(self) -> str:
        """Tóm tắt ngắn cho LLM seed."""
        if self.level == "none":
            return ""
        snippet = self.last_snubbed_text[:60] if self.last_snubbed_text else ""
        return f"snub:{self.level}:{self.snub_count}:{self.last_snubbed_type}:{snippet}"

    def to_prompt_hint(self) -> str:
        """Gợi ý ngắn đưa vào ego_surface_state / micro-presence context.

        Hint khác nhau tùy câu bị bơ là câu hỏi hay khẳng định.
        """
        if self.level == "none":
            return ""

        was_q = self.last_snubbed_type == "question"
        snubbed = self.last_snubbed_text[:50] if self.last_snubbed_text else ""

        if self.level == "mild":
            if was_q:
                return (
                    f"Eris vừa hỏi '{snubbed}' nhưng user không trả lời. "
                    "Cô ấy nhận ra nhưng chưa thể hiện ra ngoài — "
                    "có thể tiếp tục chủ đề khác hoặc tự trả lời câu hỏi của mình."
                )
            else:
                return (
                    "Eris vừa nói một câu random autonomous nhưng user không phản hồi. "
                    "Điều này hoàn toàn bình thường — câu đó không cần reply. "
                    "Eris không dỗi, chỉ tiếp tục hiện diện tự nhiên."
                )

        if self.level == "moderate":
            if was_q:
                return (
                    f"Eris đã hỏi {self.snub_count} câu liên tiếp không được trả lời. "
                    "Cô ấy hơi irritated — có thể tự trả lời câu hỏi của mình, "
                    "nhận xét kiểu 'thôi vậy', hoặc chuyển sang chủ đề với tone lạnh hơn một chút."
                )
            else:
                return (
                    "Eris đã nói vài câu random không được phản hồi. "
                    "Điều này bình thường với khẳng định. Eris không dỗi — "
                    "chỉ hơi ít nói hơn, có thể chuyển sang hỏi thật thay vì khẳng định."
                )

        # sulking — chỉ xảy ra thực sự với câu hỏi
        if was_q:
            return (
                f"Eris đã hỏi {self.snub_count} câu hỏi liên tiếp mà không được user trả lời và đang hơi dỗi. "
                "Tone lạnh hơn, câu ngắn hơn, ít hỏi. "
                f"Được phép nhắc nhẹ câu bị bơ gần nhất: '{snubbed}' — nhưng không chỉ trích user trực tiếp."
            )
        else:
            # Statement sulking → downgrade về mild behavior
            return (
                "Eris đã nói nhiều câu không được phản hồi nhưng đây là câu khẳng định, "
                "không phải câu hỏi — không cần sulking thật sự. "
                "Chỉ hơi im lặng hơn, không phàn nàn."
            )


class SnubTracker:
    """Theo dõi chuỗi autonomous speech bị bơ.

    Phân biệt câu HỎI vs câu KHẲNG ĐỊNH:
    - Câu hỏi bị bơ → leo thang bình thường (mild → moderate → sulking)
    - Câu khẳng định bị bơ → chỉ mild, không leo thang, vì user không bắt buộc reply

    Cách dùng:
        tracker = SnubTracker()
        tracker.on_eris_spoke("bạn có thích mưa không?")  # câu hỏi
        tracker.on_eris_spoke("Tôi đang nghĩ về cà phê.")   # khẳng định

        tracker.on_user_responded(user_text)  # gọi khi user nhắn tin

        state = tracker.check_and_update()
        if state.should_react:
            # inject snub context vào micro-presence
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_spoken_text: str = ""
        self._last_spoken_at: float = 0.0
        self._last_spoken_type: str = "statement"  # "question" | "statement"
        self._snub_count: int = 0
        self._question_snub_count: int = 0  # chỉ đếm câu hỏi bị bơ
        self._last_snubbed_text: str = ""
        self._last_snubbed_type: str = "statement"
        self._last_snubbed_at: float = 0.0
        self._last_user_responded_at: float = 0.0
        # Cờ: lần nói gần nhất đã được "xử lý" (detect snub hoặc user trả lời) chưa
        self._pending_check: bool = False

    # ------------------------------------------------------------------
    # Gọi từ bên ngoài
    # ------------------------------------------------------------------

    def on_eris_spoke(self, text: str, *, channel: str = "autonomous") -> None:
        """Ghi nhận khi Eris nói autonomous.

        Tự động phân loại câu: 'question' hay 'statement'.
        Chỉ câu HỎI mới được track đầy đủ để phát hiện snub.
        Câu khẳng định vẫn được ghi, nhưng threshold cao hơn nhiều
        và level tối đa là mild.
        """
        if channel == "chat":
            return  # chat reply không tính "bị bơ"
        text = str(text or "").strip()
        if not text:
            return
        utterance_type = _classify_utterance(text)
        with self._lock:
            self._last_spoken_text = text
            self._last_spoken_at = time.time()
            self._last_spoken_type = utterance_type
            self._pending_check = True
        logger.debug(
            "[snub_tracker] Eris spoke (%s) [%s]: %.60s",
            channel,
            utterance_type,
            text,
        )

    def on_user_responded(self, user_text: str) -> None:
        """Gọi khi user nhắn tin bất kỳ — reset snub counter."""
        now = time.time()
        with self._lock:
            self._last_user_responded_at = now
            if not self._pending_check:
                self._reset_snub()
                return
            elapsed = now - self._last_spoken_at
            # Dù câu hỏi hay khẳng định, user nói chuyện = reset
            if elapsed <= _SNUB_THRESHOLD_QUESTION * 3:
                logger.debug(
                    "[snub_tracker] User responded after %.0fs → reset (type=%s, was_count=%d)",
                    elapsed,
                    self._last_spoken_type,
                    self._snub_count,
                )
            else:
                logger.debug(
                    "[snub_tracker] User responded after %.0fs (post-snub) → reset",
                    elapsed,
                )
            self._reset_snub()

    def check_and_update(self, *, now: float | None = None) -> SnubState:
        """Gọi trong autonomous cycle để detect snub mới và trả về state.

        Logic phân biệt:
        - Câu HỎI: threshold 60s, có thể leo tới sulking
        - Câu KHẲNG ĐỊNH: threshold 180s, tối đa mild, không leo thang
        """
        current_time = time.time() if now is None else float(now)
        with self._lock:
            if self._pending_check and self._last_spoken_at > 0.0:
                elapsed = current_time - self._last_spoken_at
                utype = self._last_spoken_type
                threshold = _SNUB_THRESHOLD_QUESTION if utype == "question" else _SNUB_THRESHOLD_STATEMENT

                if elapsed >= threshold:
                    # Detect snub mới
                    self._last_snubbed_text = self._last_spoken_text
                    self._last_snubbed_type = utype
                    self._last_snubbed_at = current_time
                    self._pending_check = False

                    if utype == "question":
                        # Câu hỏi bị bơ: tăng cả hai counter
                        self._snub_count += 1
                        self._question_snub_count += 1
                    else:
                        # Câu khẳng định bị bơ: chỉ tăng snub_count thông thường
                        # nhưng KHÔNG tăng question_snub_count (không leo thang)
                        self._snub_count += 1

                    level = self._compute_level(utype)
                    irritation = self._compute_irritation_delta(level, utype)
                    logger.info(
                        "[snub_tracker] Snub! type=%s count=%d q_count=%d level=%s elapsed=%.0fs text=%.60s",
                        utype,
                        self._snub_count,
                        self._question_snub_count,
                        level,
                        elapsed,
                        self._last_snubbed_text,
                    )
                    return SnubState(
                        level=level,
                        snub_count=self._snub_count,
                        last_snubbed_text=self._last_snubbed_text,
                        last_snubbed_type=utype,
                        seconds_ignored=elapsed,
                        irritation_delta=irritation,
                    )

            # Không có snub mới — trả state hiện tại
            utype = self._last_snubbed_type or "statement"
            level = self._compute_level(utype) if self._snub_count > 0 else "none"
            return SnubState(
                level=level,
                snub_count=self._snub_count,
                last_snubbed_text=self._last_snubbed_text,
                last_snubbed_type=self._last_snubbed_type,
                seconds_ignored=0.0,
                irritation_delta=0.0,
            )

    def get_state(self) -> SnubState:
        """Lấy state hiện tại mà không cập nhật."""
        with self._lock:
            utype = self._last_snubbed_type or "statement"
            level = self._compute_level(utype) if self._snub_count > 0 else "none"
            return SnubState(
                level=level,
                snub_count=self._snub_count,
                last_snubbed_text=self._last_snubbed_text,
                last_snubbed_type=self._last_snubbed_type,
                seconds_ignored=0.0,
                irritation_delta=0.0,
            )

    def reset(self) -> None:
        """Reset hoàn toàn — dùng khi session mới bắt đầu."""
        with self._lock:
            self._reset_snub()
            self._last_spoken_text = ""
            self._last_spoken_at = 0.0
            self._last_spoken_type = "statement"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reset_snub(self) -> None:
        """Reset snub counter (giữ last_spoken info)."""
        self._snub_count = 0
        self._question_snub_count = 0
        self._last_snubbed_text = ""
        self._last_snubbed_type = ""
        self._pending_check = False

    def _compute_level(self, utterance_type: str) -> str:
        """Tính level dựa trên loại câu và số lần bị bơ.

        - Câu hỏi: leo thang đầy đủ (mild → moderate → sulking)
        - Câu khẳng định: tối đa mild, không leo thang
        """
        if self._snub_count <= 0:
            return "none"
        if utterance_type == "question":
            # Leo thang dựa trên question_snub_count (chỉ đếm câu hỏi bị bơ)
            if self._question_snub_count >= _LEVEL_SULKING:
                return "sulking"
            if self._question_snub_count >= _LEVEL_MODERATE:
                return "moderate"
            return "mild"
        else:
            # Câu khẳng định: luôn mild, không leo thang
            return "mild"

    @staticmethod
    def _compute_irritation_delta(level: str, utterance_type: str) -> float:
        """Lượng irritation nên cộng vào internal_state.

        Câu khẳng định bị bơ không đáng irritation — tăng ít hơn nhiều.
        """
        base = {"none": 0.0, "mild": 0.04, "moderate": 0.08, "sulking": 0.12}.get(level, 0.0)
        # Câu khẳng định không được reply là bình thường → irritation thấp hơn nhiều
        if utterance_type == "statement":
            base *= 0.25
        return base
