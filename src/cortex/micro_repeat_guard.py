from __future__ import annotations

from collections import deque
import time

from .micro_contracts import (
    SemanticRepeatResult,
    clean_family,
    clamp01,
    family_source_is_trusted,
    lexical_fingerprint,
    normalize_text,
    phrase_in_normalized,
)


class SemanticRepeatGuard:
    """Chặn lặp semantic family, nhưng không để keyword fallback cầm lái.

    Luật mới:
    1. Nếu tầng trên truyền semantic_family đáng tin, repeat guard được quyền
       block trong cửa sổ gần.
    2. Nếu không có semantic_family, fallback keyword chỉ tạo hint yếu.
    3. Exact lexical fingerprint lặp quá gần có thể block, vì đó là lặp câu bề
       mặt chứ không phải suy diễn meaning.

    Nói cách khác: MeaningLayer được nói "đây là cùng family". Keyword fallback
    chỉ được ho nhẹ ở góc phòng. Một trật tự xã hội hiếm hoi có lý.
    """

    FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
        "code_stalled": (
            "code", "debug", "loi", "traceback", "terminal", "python", "vscode",
            "visual studio", "mach code",
        ),
        "screen_still": (
            "man hinh", "screen", "cua so", "window", "tab", "khung",
        ),
        "quiet_still": (
            "im", "yen", "dung", "nam", "treo", "cho", "nhap nhay",
        ),
        "awake_presence": (
            "thuc", "khuya", "dem", "mat ngu",
        ),
        "chat_idle": (
            "chat", "tin nhan", "nhan tin", "khung chat",
        ),
        "meeting_idle": (
            "meet", "meeting", "cuoc goi", "phong hop",
        ),
        "log_meta": (
            "log", "dong log",
        ),
        "ambient_residue": (
            "nhip", "du am", "lang lai", "yen xuong", "doi nhip",
        ),
    }

    SYNONYMS: tuple[tuple[str, str], ...] = (
        ("ma nguon", "code"),
        ("lap trinh", "code"),
        ("monitor", "man hinh"),
        ("dung im", "im"),
        ("nam im", "im"),
        ("treo may", "treo"),
        ("van mo", "treo"),
        ("con thuc", "thuc"),
        ("thuc khuya", "thuc"),
        ("nhan message", "tin nhan"),
    )

    def __init__(
        self,
        *,
        max_items: int = 20,
        window_seconds: float = 240.0,
        exact_repeat_seconds: float = 90.0,
    ):
        self.max_items = max(10, min(40, int(max_items or 20)))
        self.window_seconds = max(90.0, min(600.0, float(window_seconds or 240.0)))
        self.exact_repeat_seconds = max(20.0, min(self.window_seconds, float(exact_repeat_seconds or 90.0)))
        self._items: deque[tuple[float, str, str, str, float, str]] = deque(maxlen=self.max_items)

    def remember(
        self,
        text: str,
        *,
        timestamp: float | None = None,
        semantic_family: str = "",
        family_source: str = "",
        confidence: float = 1.0,
    ) -> None:
        """Lưu family/fingerprint của câu vừa nói.

        semantic_family từ tầng trên được lưu là trusted nếu source hợp lệ. Nếu
        không có, ta chỉ lưu fallback_keyword + fingerprint để phát hiện câu lặp
        bề mặt, không tạo quyền block meaning.
        """

        family, source, score = self._resolve_family(
            text,
            semantic_family=semantic_family,
            family_source=family_source,
            confidence=confidence,
        )
        fingerprint = lexical_fingerprint(text)
        if not family and not fingerprint:
            return
        self._items.append((
            time.time() if timestamp is None else float(timestamp),
            str(text or ""),
            family,
            source,
            score,
            fingerprint,
        ))

    def check(
        self,
        text: str,
        *,
        now: float | None = None,
        recent_lines: tuple[tuple[float, str], ...] = (),
        semantic_family: str = "",
        meaning_family: str = "",
        family_source: str = "",
        semantic_confidence: float = 1.0,
    ) -> SemanticRepeatResult:
        """Kiểm tra lặp.

        Backward compatible: call-site cũ chỉ truyền text vẫn chạy. Nhưng khi chỉ
        có fallback keyword, hàm trả weak hint thay vì rejected=True.
        """

        family, source, score = self._resolve_family(
            text,
            semantic_family=semantic_family or meaning_family,
            family_source=family_source or ("meaning_layer" if meaning_family else ""),
            confidence=semantic_confidence,
        )
        fingerprint = lexical_fingerprint(text)
        current_time = time.time() if now is None else float(now)
        trusted_current = family_source_is_trusted(source) and score >= 0.45

        weak_family_seen = False
        for timestamp, _line, recent_family, recent_source, recent_confidence, recent_fingerprint in self._iter_recent(recent_lines):
            age = current_time - timestamp
            if age > self.window_seconds:
                continue

            # Exact/gần exact repeat là vấn đề bề mặt, không phải suy diễn meaning.
            if fingerprint and recent_fingerprint == fingerprint and age <= self.exact_repeat_seconds:
                return SemanticRepeatResult(
                    rejected=True,
                    family=family or recent_family,
                    reason="exact_micro_line_repeat",
                    family_source="lexical_fingerprint",
                    confidence=0.72,
                    weak=False,
                    fingerprint=fingerprint,
                )

            if family and recent_family == family:
                trusted_recent = family_source_is_trusted(recent_source) and recent_confidence >= 0.45
                if trusted_current and trusted_recent:
                    return SemanticRepeatResult(
                        rejected=True,
                        family=family,
                        reason=f"semantic_repeat_family={family}",
                        family_source=source,
                        confidence=min(score, recent_confidence),
                        weak=False,
                        fingerprint=fingerprint,
                    )
                if age <= self.window_seconds:
                    return SemanticRepeatResult(
                        rejected=True,
                        family=family,
                        reason=f"semantic_repeat_family={family}",
                        family_source=source or recent_source or "fallback_keyword",
                        confidence=min(max(score, recent_confidence), 0.42),
                        weak=True,
                        fingerprint=fingerprint,
                    )
                weak_family_seen = True

        if family:
            return SemanticRepeatResult(
                rejected=False,
                family=family,
                reason="weak_keyword_family_only" if weak_family_seen or source == "fallback_keyword" else "",
                family_source=source,
                confidence=score,
                weak=not trusted_current,
                fingerprint=fingerprint,
            )
        return SemanticRepeatResult(fingerprint=fingerprint)

    def family_for_text(self, text: str) -> str:
        """Backward compatible fallback family.

        Hàm này vẫn tồn tại cho code cũ/test cũ, nhưng đừng dùng nó làm chân lý.
        Muốn biết nguồn yếu/mạnh, dùng family_for_text_with_source().
        """

        family, _source, _confidence = self.family_for_text_with_source(text)
        return family

    def family_for_text_with_source(self, text: str) -> tuple[str, str, float]:
        normalized = self.normalize(text)
        if not normalized:
            return "", "unknown", 0.0
        for source, target in self.SYNONYMS:
            if phrase_in_normalized(normalized, source):
                normalized = normalized.replace(source, target)
        for family, markers in self.FAMILY_MARKERS.items():
            hits = sum(1 for marker in markers if phrase_in_normalized(normalized, marker))
            if hits:
                # Fallback marker luôn confidence thấp. Nó là khói, không phải lửa.
                return family, "fallback_keyword", min(0.42, 0.22 + hits * 0.08)
        return "", "unknown", 0.0

    def normalize(self, text: str) -> str:
        return normalize_text(text)

    def _resolve_family(
        self,
        text: str,
        *,
        semantic_family: str = "",
        family_source: str = "",
        confidence: float = 1.0,
    ) -> tuple[str, str, float]:
        family = clean_family(semantic_family)
        source = str(family_source or "").strip().lower()
        score = clamp01(confidence)
        if family:
            if not source:
                source = "manual"
            if family_source_is_trusted(source):
                return family, source, max(score, 0.55)
            return family, source or "unknown", min(score, 0.44)
        return self.family_for_text_with_source(text)

    def _iter_recent(self, recent_lines: tuple[tuple[float, str], ...]):
        for item in tuple(self._items):
            yield item
        for timestamp, line in tuple(recent_lines or ()):  # external history từ coordinator nếu có.
            family, source, confidence = self.family_for_text_with_source(line)
            yield float(timestamp), str(line or ""), family, source, confidence, lexical_fingerprint(line)

    def _clean_family(self, family: str) -> str:
        # Giữ wrapper cũ để code ngoài nếu lỡ gọi private vẫn ít vỡ hơn. Tuyệt vời,
        # giờ ta bảo vệ cả private API, vì con người rất thích dùng nhầm đồ riêng.
        return clean_family(family)
