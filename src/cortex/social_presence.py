from .contracts import SocialPresenceEvent


def _clean(value: object) -> str:
    return str(value or "").strip()


def _clamp(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric != numeric:
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


class SocialPresenceDetector:
    """Detects ambient co-presence without treating it as chat or speech intent."""

    NON_CHAT_CHANNELS = {"autonomous", "background"}
    ACTIVE_TYPING = {"slow", "medium", "fast", "high", "very_fast", "extreme_fluctuation", "low"}
    PRESENT_FOCUS = {
        "attentive_listening",
        "deep",
        "deep_work",
        "distracted_typing",
        "frantic_tweaking",
        "heavy_contemplation",
        "lost_in_thought",
        "perfectionism_paralysis",
        "searching_for_anchor",
        "stable",
        "steady",
        "sustained",
    }
    ABSENT_FOCUS = {"absent", "microsleep_nodding", "passive_consumption"}
    PRESENCE_EVENT_TERMS = (
        "active",
        "click",
        "cursor",
        "editing",
        "highlight",
        "key",
        "mouse",
        "scroll",
        "typing",
        "window_active",
    )

    def detect( # Dựa trên các tín hiệu môi trường và trạng thái người dùng, xác định xem người dùng có đang hiện diện trong cùng một không gian nhận thức hay không, ngay cả khi họ không tham gia vào một kênh trò chuyện hoặc hoạt động nói chuyện rõ ràng nào. Điều này bao gồm việc phân tích tốc độ gõ phím, mô hình chuyển đổi cửa sổ, mẫu tập trung, sự kiện gần đây và các tín hiệu khác để đánh giá khả năng hiện_presence của người dùng.
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state=None,
        user_text: str = "",
        force_speak: bool = False,
        timestamp: str = "",
    ) -> SocialPresenceEvent:
        channel_name = _clean(channel) or "autonomous"
        #Nếu user đang thật sự nói chuyện thì khỏi cần đo presence nền
        if channel_name not in self.NON_CHAT_CHANNELS or force_speak or _clean(user_text):
            return SocialPresenceEvent(timestamp=timestamp)

        user_signals = getattr(snapshot, "user_signals", None)
        typing_speed = _clean(getattr(user_signals, "typing_speed", "")).lower()
        switching = _clean(getattr(user_signals, "window_switching", "")).lower()
        focus_pattern = _clean(getattr(user_signals, "focus_pattern", "")).lower()
        focus_kind = _clean(getattr(snapshot, "active_window_kind", ""))
        previous_focus = _clean(getattr(internal_state, "last_focus_kind", ""))
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())

        score = 0.0
        evidence: list[str] = []
        if idle_seconds <= 12:
            score += 0.30
            evidence.append("recent_activity") #user gần như chắc chắn còn đó
        elif idle_seconds <= 90:
            score += 0.18
            evidence.append(f"short_idle={int(idle_seconds)}s") #vẫn còn hiện diện nhẹ

        if typing_speed in self.ACTIVE_TYPING:
            score += 0.28
            evidence.append(f"typing={typing_speed}")
        elif typing_speed == "zero":
            score -= 0.03

        if switching in {"low", "medium", "high"}:
            score += 0.10 if switching == "low" else 0.14
            evidence.append(f"window_switching={switching}")

        if focus_pattern in self.PRESENT_FOCUS:
            score += 0.18
            evidence.append(f"focus_pattern={focus_pattern}")
        elif focus_pattern in self.ABSENT_FOCUS:
            score -= 0.18
            evidence.append(f"focus_pattern={focus_pattern}")

        matched_event = next((event for event in recent_events[:6] if self._looks_like_presence_event(event)), "")
        if matched_event:
            score += 0.24
            evidence.append(f"recent_event={matched_event[:80]}")

        if focus_kind and previous_focus and focus_kind == previous_focus:
            score += 0.12
            evidence.append(f"same_focus_kind={focus_kind}")
        elif focus_kind in {"coding", "documentation", "communication"}:
            score += 0.06
            evidence.append(f"shared_space={focus_kind}")

        if idle_seconds >= 300 and not matched_event:
            score -= 0.22
            evidence.append(f"long_idle={int(idle_seconds)}s") #bắt đầu xem như rời khỏi shared space
        if idle_seconds >= 900:
            score -= 0.18
            evidence.append(f"very_long_idle={int(idle_seconds)}s") #gần như biến mất khỏi cognitive room.

        confidence = _clamp(score)
        present = confidence >= 0.38
        if not present:
            return SocialPresenceEvent(
                present=False,
                confidence=confidence,
                intensity=0.0,
                kind="ambient_presence_below_threshold",
                reason="Ambient signals were too weak to count as co-presence.",
                evidence=tuple(dict.fromkeys(evidence))[:6],
                timestamp=timestamp,
            )

        return SocialPresenceEvent(
            present=True,
            confidence=confidence,
            intensity=_clamp(0.24 + confidence * 0.56),
            kind="ambient_co_presence",
            reason="Non-chat activity suggests the user remains in the same cognitive space.",
            evidence=tuple(dict.fromkeys(evidence))[:6],
            timestamp=timestamp,
            speech_allowed=False, #“Có mặt không đồng nghĩa được phép lên tiếng.”
        )

    def _looks_like_presence_event(self, event: str) -> bool:
        lowered = event.lower()
        return any(term in lowered for term in self.PRESENCE_EVENT_TERMS)
