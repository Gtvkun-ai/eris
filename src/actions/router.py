"""High-confidence action router for ERIS.

Router này chỉ nên bắt các lệnh hệ thống thật sự rõ ràng.
Nếu câu user có vẻ là câu hỏi, meta-discussion, code/debug, hoặc chỉ nhắc đến
một từ khóa như "youtube/search/volume/copy" thì trả None để chat/LLM xử lý.

Nguyên tắc:
- False negative chấp nhận được: user có thể nói rõ hơn hoặc LLM hỏi lại.
- False positive nguy hiểm hơn: route sai có thể mở app, đổi volume, search web...
- Vì vậy mọi nhánh action đều phải có command shape + target hợp lệ + blocker kiểm tra.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class RouteCandidate:
    """Ứng viên route nội bộ.

    confidence không dùng để làm màu. Nó là cổng cuối: chỉ action đủ chắc mới được
    trả ra ngoài. Các blocker có thể hạ confidence hoặc hủy candidate.
    """

    action: str
    value: str = ""
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    blocked_reason: str = ""

    @property
    def allowed(self) -> bool:
        return not self.blocked_reason and self.confidence >= 0.82


class ActionRouter:
    """Route chat text thành direct system action.

    Public API giữ nguyên bản cũ:
        route_chat(user_text, last_action="") -> tuple[action, value] | None

    Router này không cố hiểu toàn bộ intent. Nó chỉ nhận các lệnh có hình dạng rõ.
    Những câu còn mơ hồ phải đi qua tầng chat/cognition thay vì bị regex bắn nhầm.
    """

    # Các marker cho thấy user đang hỏi về khái niệm/code/debug, không ra lệnh.
    _META_MARKERS = (
        " la gi",
        " la cai gi",
        " nghia la gi",
        " cach ",
        " lam sao",
        " tai sao",
        " vi sao",
        " nhu the nao",
        " trong python",
        " trong c#",
        " trong csharp",
        " trong javascript",
        " api",
        " regex",
        " bug",
        " loi",
        " ham ",
        " class ",
        " function",
        " method",
        " constructor",
        " docker",
        " test ",
        " unit test",
        " source",
        " code",
    )

    # Marker phủ định ở đầu câu hoặc ngay trước command. Không dùng "khong" chung chung
    # trong toàn câu vì query như "tim kiem khong dau tieng viet" vẫn là lệnh hợp lệ.
    _NEGATION_PREFIXES = (
        "dung ",
        "đung ",
        "đừng ",
        "khong ",
        "không ",
        "chua ",
        "chưa ",
        "don't ",
        "do not ",
        "not ",
    )

    _COMMAND_PREFIX = r"(?:eris\s+|ê\s+eris\s+|này\s+eris\s+)?"

    _URL_TARGET_RE = r"(https?://\S+|www\.\S+|[\w.-]+\.(?:com|vn|net|org|io|me|app)(?:/\S*)?)"

    def route_chat(self, user_text: str, *, last_action: str = "") -> tuple[str, str] | None:
        raw = (user_text or "").strip()
        if not raw:
            return None

        norm = self._normalize_vi(raw)

        candidates: list[RouteCandidate] = [
            self._route_open_url(raw, norm),
            self._route_now_playing(raw, norm),
            self._route_now_playing_follow_up(raw, norm, last_action=last_action),
            self._route_play_pause_media(raw, norm),
            self._route_volume(raw, norm),
            self._route_copy_text(raw, norm),
            self._route_focus_window(raw, norm),
            self._route_launch_app(raw, norm),
            self._route_search_web(raw, norm),
            self._route_weather(raw, norm),
        ]

        valid = [c for c in candidates if c.allowed]
        if not valid:
            return None

        # Nếu nhiều candidate hợp lệ, chọn candidate chắc nhất. Thứ tự list phía trên
        # vẫn là tie-breaker vì max giữ phần tử đầu khi bằng điểm.
        winner = max(valid, key=lambda c: c.confidence)
        return winner.action, winner.value

    # ---------------------------------------------------------------------
    # Route candidates
    # ---------------------------------------------------------------------

    def _route_open_url(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm):
            return self._blocked("open_url", "meta_question")
        if self._starts_with_negation(norm):
            return self._blocked("open_url", "negated")

        pattern = rf"^\s*{self._COMMAND_PREFIX}(?:mo|open|vao|truy cap|di den|go to)\s+{self._URL_TARGET_RE}\s*$"
        match = re.search(pattern, norm, flags=re.IGNORECASE)
        if match:
            # Lấy target từ raw để giữ nguyên chữ hoa/path nếu có.
            raw_match = re.search(self._URL_TARGET_RE, raw, flags=re.IGNORECASE)
            target = raw_match.group(1).strip() if raw_match else match.group(1).strip()
            return RouteCandidate("open_url", target, 0.96, ("explicit_url_command",))

        # Người dùng dán nguyên một URL/domain (không kèm động từ) => mở luôn.
        bare = re.search(rf"^\s*{self._URL_TARGET_RE}\s*$", norm, flags=re.IGNORECASE)
        if bare:
            raw_match = re.search(self._URL_TARGET_RE, raw, flags=re.IGNORECASE)
            target = raw_match.group(1).strip() if raw_match else bare.group(1).strip()
            return RouteCandidate("open_url", target, 0.9, ("bare_url",))

        return self._no_candidate("open_url")

    # Từ vựng intent cho now-playing. Tách thành nhóm để rule dựa trên ý nghĩa
    # thay vì khớp nguyên câu. Mỗi nhóm là một "facet" của câu hỏi đang-phát-gì.
    _NOW_PLAYING_MEDIA = (
        "nhac",
        "bai hat",
        "bai",
        "ban nhac",
        "song",
        "track",
        "music",
    )
    _NOW_PLAYING_CONTEXT = (
        "dang nghe",
        "dang phat",
        "dang mo",
        "dang choi",
        "dang bat",
        "dang chay",
        "mo o youtube",
        "mo o spotify",
        "mo tren youtube",
        "mo tren spotify",
        "tren youtube",
        "tren spotify",
        "nghe tren",
        "phat tren",
        "playing",
    )
    _NOW_PLAYING_QUESTION = (
        "la gi",
        "ten gi",
        "ten la gi",
        "ten bai gi",
        "bai gi",
        "nhac gi",
        "gi vay",
        "gi the",
        "gi day",
        "hay khong",
        "phai khong",
        "dung khong",
    )

    def _route_now_playing(self, raw: str, norm: str) -> RouteCandidate:
        # English explicit form, không cần thêm facet.
        if re.search(r"^\s*(?:now playing|what'?s playing|what is playing)\b", norm, flags=re.IGNORECASE):
            return RouteCandidate("get_now_playing", "", 0.94, ("explicit_now_playing_en",))

        if self._starts_with_negation(norm):
            return self._blocked("get_now_playing", "negated")
        # Chỉ chặn meta khi là câu hỏi code/lập trình, KHÔNG chặn chỉ vì có "la gi".
        if self._now_playing_is_meta(norm):
            return self._blocked("get_now_playing", "meta_code_question")

        has_media = self._contains_any(norm, self._NOW_PLAYING_MEDIA)
        has_context = self._contains_any(norm, self._NOW_PLAYING_CONTEXT)
        has_question = self._contains_any(norm, self._NOW_PLAYING_QUESTION) or raw.strip().endswith("?")

        # Cần đủ 3 facet: đối tượng (nhạc/bài) + ngữ cảnh đang phát + dạng hỏi.
        # Đây là điều khiến rule tổng quát theo ý chứ không khớp cứng câu chữ.
        if has_media and has_context and has_question:
            return RouteCandidate("get_now_playing", "", 0.94, ("now_playing_intent",))
        return self._no_candidate("get_now_playing")

    def _route_now_playing_follow_up(self, raw: str, norm: str, *, last_action: str) -> RouteCandidate:
        if last_action != "get_now_playing":
            return self._no_candidate("get_now_playing")
        if len(norm) > 80:
            return self._no_candidate("get_now_playing")
        if self._looks_like_correction(norm) or self._starts_with_negation(norm):
            return self._blocked("get_now_playing", "correction_or_negated_followup")
        if self._now_playing_is_meta(norm):
            return self._blocked("get_now_playing", "meta_followup")

        # Sau khi vừa trả lời đang-phát-gì, một follow-up ngắn vẫn nhắc tới
        # bài/nhạc/song hoặc nền tảng (youtube/spotify) thì hiểu là hỏi tiếp về
        # bài đó. Đại từ trần ("đó/ấy") đứng một mình thì không route, tránh nhầm
        # câu nói chuyện phiếm.
        has_media = self._contains_any(norm, self._NOW_PLAYING_MEDIA)
        has_platform = self._contains_any(norm, ("youtube", "spotify"))
        if has_media or has_platform:
            return RouteCandidate("get_now_playing", "", 0.86, ("now_playing_followup",))
        return self._no_candidate("get_now_playing")

    def _route_play_pause_media(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm) or self._starts_with_negation(norm):
            return self._blocked("play_pause_media", "meta_or_negated")

        patterns = (
            r"^\s*(?:play pause|play/pause)\s*$",
            r"^\s*(?:tam dung|pause)\s+(?:nhac|media|bai hat)\s*$",
            r"^\s*(?:phat tiep|tiep tuc|resume)\s+(?:nhac|media|bai hat)\s*$",
            r"^\s*(?:pause|resume)\s*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in patterns):
            return RouteCandidate("play_pause_media", "", 0.93, ("explicit_media_command",))
        return self._no_candidate("play_pause_media")

    def _route_volume(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm):
            return self._blocked("set_volume", "meta_question")
        if self._starts_with_negation(norm):
            return self._blocked("set_volume", "negated")

        mute_patterns = (
            r"^\s*(?:mute|silent)\s*$",
            r"^\s*(?:tat tieng|tat am|tat volume|tat loa)\s*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in mute_patterns):
            return RouteCandidate("set_volume", "mute", 0.96, ("explicit_mute_command",))

        patterns = (
            rf"^\s*{self._COMMAND_PREFIX}(?:set|dat|chinh)\s+(?:volume|am luong)\s*(?:to|len|xuong|=|:)?\s*(\d{{1,3}})\s*%?\s*$",
            rf"^\s*{self._COMMAND_PREFIX}(?:volume|am luong)\s*(?:to|len|xuong|=|:)?\s*(\d{{1,3}})\s*%?\s*$",
            rf"^\s*{self._COMMAND_PREFIX}(?:tang|giam)\s+(?:volume|am luong)\s*(?:len|xuong|to)?\s*(\d{{1,3}})\s*%?\s*$",
        )
        for pattern in patterns:
            match = re.search(pattern, norm, flags=re.IGNORECASE)
            if not match:
                continue
            value = int(match.group(1))
            if not 0 <= value <= 100:
                return self._blocked("set_volume", "volume_out_of_range")
            return RouteCandidate("set_volume", str(value), 0.92, ("explicit_volume_command",))

        return self._no_candidate("set_volume")

    def _route_copy_text(self, raw: str, norm: str) -> RouteCandidate:
        if self._starts_with_negation(norm):
            return self._blocked("copy_text", "negated")

        match = re.search(r"^\s*(?:copy|sao chep|chep)\s+(.+?)\s*$", raw, flags=re.IGNORECASE)
        if not match:
            return self._no_candidate("copy_text")

        rest_raw = match.group(1).strip()
        rest_norm = self._normalize_vi(rest_raw)

        if not rest_raw:
            return self._no_candidate("copy_text")
        if self._copy_rest_is_meta(rest_norm):
            return self._blocked("copy_text", "copy_meta_topic")

        # Quote/backtick là bằng chứng mạnh nhất: user muốn copy literal text.
        quoted = self._extract_single_quoted_payload(rest_raw)
        if quoted is not None:
            return RouteCandidate("copy_text", quoted, 0.97, ("quoted_copy_payload",))

        # Dạng chỉ định nội dung hiện tại/đoạn này. Executor phía sau quyết định có
        # clipboard source thật không; router chỉ chuyển intent.
        if re.search(r"^(?:doan nay|noi dung nay|text nay|cai nay|phan nay)(?:\s*[:：-]\s*.+)?$", rest_norm):
            return RouteCandidate("copy_text", rest_raw, 0.88, ("deictic_copy_payload",))

        # Cho phép copy literal ngắn nếu không giống câu hỏi/meta code.
        if self._looks_like_meta_question(rest_norm) or "?" in rest_raw:
            return self._blocked("copy_text", "copy_question")
        if len(rest_raw) <= 240:
            return RouteCandidate("copy_text", rest_raw, 0.84, ("literal_copy_payload",))

        return self._blocked("copy_text", "copy_payload_too_long_or_unclear")

    def _route_focus_window(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm) or self._starts_with_negation(norm):
            return self._blocked("focus_window", "meta_or_negated")

        pattern = rf"^\s*{self._COMMAND_PREFIX}(?:focus|chuyen qua cua so|dua len cua so|dua cua so)\s+(.+?)\s*$"
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            return self._no_candidate("focus_window")

        target = match.group(1).strip()
        if self._target_is_meta_or_empty(target):
            return self._blocked("focus_window", "bad_target")
        return RouteCandidate("focus_window", target, 0.88, ("explicit_focus_command",))

    def _route_launch_app(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm) or self._starts_with_negation(norm):
            return self._blocked("launch_app", "meta_or_negated")

        # Không bắt "mở youtube" trần để tránh nhầm hỏi/nhạc. Yêu cầu app/chạy/launch rõ.
        pattern = rf"^\s*{self._COMMAND_PREFIX}(?:mo app|chay app|launch app|launch|open app)\s+(.+?)\s*$"
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            return self._no_candidate("launch_app")

        target = match.group(1).strip()
        if self._target_is_meta_or_empty(target):
            return self._blocked("launch_app", "bad_target")
        return RouteCandidate("launch_app", target, 0.90, ("explicit_launch_command",))

    def _route_search_web(self, raw: str, norm: str) -> RouteCandidate:
        if self._starts_with_negation(norm):
            return self._blocked("search_web", "negated")

        # Anchor đầu câu. Không bắt "cách search ..." hay "hàm search ...".
        pattern = rf"^\s*{self._COMMAND_PREFIX}(?:tim kiem|search(?: for)?)\s+(.+?)\s*$"
        match_norm = re.search(pattern, norm, flags=re.IGNORECASE)
        if not match_norm:
            return self._no_candidate("search_web")
        if self._looks_like_meta_question(norm):
            return self._blocked("search_web", "meta_question")

        # Lấy query từ raw bằng pattern tương đương để giữ dấu tiếng Việt.
        raw_pattern = rf"^\s*{self._COMMAND_PREFIX}(?:tìm kiếm|tim kiem|search(?: for)?)\s+(.+?)\s*$"
        match_raw = re.search(raw_pattern, raw, flags=re.IGNORECASE)
        query = (match_raw.group(1) if match_raw else match_norm.group(1)).strip()
        if not query:
            return self._no_candidate("search_web")
        return RouteCandidate("search_web", query, 0.92, ("explicit_search_command",))

    def _route_weather(self, raw: str, norm: str) -> RouteCandidate:
        if self._starts_with_negation(norm):
            return self._blocked("get_weather", "negated")
        # Chặn câu hỏi kiểu "cách làm app thời tiết bằng python" trước khi match.
        if self._weather_is_meta(norm):
            return self._blocked("get_weather", "weather_meta_topic")

        patterns = (
            rf"^\s*{self._COMMAND_PREFIX}(?:xem|coi|kiem tra)?\s*(?:thoi tiet|weather)\b.*$",
            rf"^\s*{self._COMMAND_PREFIX}(?:du bao thoi tiet|weather forecast)\b.*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in patterns):
            return RouteCandidate("get_weather", raw, 0.88, ("explicit_weather_query",))
        if re.search(r"\bthoi tiet\b", norm, flags=re.IGNORECASE):
            return RouteCandidate("get_weather", raw, 0.84, ("implicit_weather_query",))
        if self._weather_is_meta(norm):
            return self._blocked("get_weather", "weather_meta_topic")
        return self._no_candidate("get_weather")

    # ---------------------------------------------------------------------
    # Backward-compatible helpers used by older tests/imports.
    # ---------------------------------------------------------------------

    def _looks_like_now_playing(self, lowered: str) -> bool:
        norm = self._normalize_vi(lowered)
        return self._route_now_playing(lowered, norm).allowed

    def _looks_like_now_playing_follow_up(self, lowered: str, *, last_action: str) -> bool:
        norm = self._normalize_vi(lowered)
        return self._route_now_playing_follow_up(lowered, norm, last_action=last_action).allowed

    # ---------------------------------------------------------------------
    # Blockers / utilities
    # ---------------------------------------------------------------------

    @staticmethod
    def _normalize_vi(text: str) -> str:
        """Lowercase + bỏ dấu tiếng Việt để rule ít phải nhân đôi.

        Giữ lại ký tự URL cơ bản. Normalize whitespace để regex ổn định hơn.
        """

        text = (text or "").strip().lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = text.replace("đ", "d")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _pad(cls, text: str) -> str:
        return f" {text.strip()} "

    @classmethod
    def _starts_with_negation(cls, norm: str) -> bool:
        stripped = norm.strip()
        return any(stripped.startswith(prefix) for prefix in cls._NEGATION_PREFIXES)

    @classmethod
    def _looks_like_meta_question(cls, norm: str) -> bool:
        padded = cls._pad(norm)
        return any(marker in padded for marker in cls._META_MARKERS)

    @staticmethod
    def _contains_any(norm: str, needles: tuple[str, ...]) -> bool:
        """True nếu norm chứa bất kỳ cụm nào. Dùng cho intent dạng facet."""

        return any(needle in norm for needle in needles)

    @classmethod
    def _now_playing_is_meta(cls, norm: str) -> bool:
        """Chỉ chặn now-playing khi câu rõ ràng là hỏi code/lập trình.

        Khác với _looks_like_meta_question chung: ở đây KHÔNG coi " la gi" là meta,
        vì "tên nhạc đang nghe là gì" là câu hỏi now-playing hợp lệ.
        """

        padded = cls._pad(norm)
        meta = (
            " python ",
            " c# ",
            " csharp ",
            " javascript ",
            " api ",
            " regex ",
            " code ",
            " function ",
            " ham ",
            " class ",
            " method ",
            " bug ",
            " debug ",
            " source ",
            " thuat toan ",
        )
        return any(marker in padded for marker in meta)

    @classmethod
    def _looks_like_correction(cls, norm: str) -> bool:
        padded = cls._pad(norm)
        markers = (
            " sai ",
            " sai roi ",
            " khong phai ",
            " ko phai ",
            " nham ",
            " nham roi ",
            " thieu ",
            " chua dung ",
            " khong dung ",
            " fix ",
            " sua ",
        )
        return any(marker in padded for marker in markers)

    @classmethod
    def _copy_rest_is_meta(cls, rest_norm: str) -> bool:
        padded = cls._pad(rest_norm)
        hard_meta = (
            " constructor ",
            " copy constructor ",
            " copy on write ",
            " copy-on-write ",
            " copywriting ",
            " deep copy ",
            " shallow copy ",
            " trong python ",
            " trong c# ",
            " la gi ",
            " cach ",
            " api ",
            " regex ",
        )
        return any(marker in padded for marker in hard_meta)

    @classmethod
    def _weather_is_meta(cls, norm: str) -> bool:
        padded = cls._pad(norm)
        meta = (
            " api ",
            " code ",
            " python ",
            " app ",
            " source ",
            " regex ",
            " bug ",
            " loi ",
            " lam app ",
            " cach ",
            " la gi ",
        )
        return any(marker in padded for marker in meta)

    @classmethod
    def _target_is_meta_or_empty(cls, target: str) -> bool:
        target_norm = cls._normalize_vi(target)
        if not target_norm:
            return True
        if len(target_norm) > 120:
            return True
        return cls._looks_like_meta_question(target_norm)

    @staticmethod
    def _extract_single_quoted_payload(text: str) -> str | None:
        text = text.strip()
        patterns = (
            r'^"(.+)"$',
            r"^'(.+)'$",
            r"^`(.+)`$",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.DOTALL)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _no_candidate(action: str) -> RouteCandidate:
        return RouteCandidate(action=action, blocked_reason="no_candidate")

    @staticmethod
    def _blocked(action: str, reason: str) -> RouteCandidate:
        return RouteCandidate(action=action, blocked_reason=reason)
