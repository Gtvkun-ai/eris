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
            self._route_project_operation(raw, norm),
            self._route_internal_cognition(raw, norm),
            self._route_environment_read(raw, norm),
            self._route_open_url(raw, norm),
            self._route_local_time(raw, norm),
            self._route_now_playing(raw, norm),
            self._route_now_playing_follow_up(raw, norm, last_action=last_action),
            self._route_play_pause_media(raw, norm),
            self._route_volume(raw, norm),
            self._route_copy_text(raw, norm),
            self._route_focus_window(raw, norm),
            self._route_launch_app(raw, norm),
            self._route_weather(raw, norm),
        ]

        valid = [c for c in candidates if c.allowed]
        if not valid:
            return None

        # Nếu nhiều candidate hợp lệ, chọn candidate chắc nhất. Thứ tự list phía trên
        # vẫn là tie-breaker vì max giữ phần tử đầu khi bằng điểm.
        winner = max(valid, key=lambda c: c.confidence)
        return winner.action, winner.value

    def _route_project_operation(self, raw: str, norm: str) -> RouteCandidate:
        """Route lệnh project rõ ràng sang executor thật.

        Lệnh sửa/làm project được chuyển cho ``project_execute_task`` để runtime
        tự inspect -> edit -> test -> verify. Câu hỏi kiểu "nên sửa sao" vẫn đi
        qua chat; không phải thấy chữ test là vồ lấy repo như một con mèo thiếu ngủ.
        """
        if self._starts_with_negation(norm):
            return self._blocked("project_execute_task", "negated")

        # Workspace là repo được người dùng giao, không phải source Eris suy ra từ
        # vị trí runtime. Lệnh có link/path rõ ràng được xử lý trước open_url.
        source_match = re.search(
            r"(?:https?://\S+|git@\S+|[A-Za-z]:[\\/][^\r\n<>\"|?*]+|[^\s\"]+\.zip)",
            raw, flags=re.I,
        )
        source = source_match.group(0).rstrip(".,;)") if source_match else ""
        edit_shape = bool(re.search(r"\b(?:sửa|sua|fix|làm|lam|triển khai|trien khai|refactor|patch|thêm|them|xóa|xoa)\b", raw, flags=re.I))
        join_shape = bool(re.search(r"\b(?:vào|vao|gia nhập|gia nhap|join|clone|mở repo|mo repo|xem repo)\b", raw, flags=re.I))
        if source and edit_shape:
            return RouteCandidate("project_execute_task", raw, 0.98, ("workspace_source_and_code_task",))
        if source and join_shape:
            return RouteCandidate("workspace_join", source, 0.98, ("explicit_workspace_join",))

        if re.search(r"^(?:eris\s+)?(?:liệt kê|liet ke|list|xem)\s+(?:các\s+|cac\s+)?workspace(?:\s+đã gia nhập|\s+da gia nhap)?\s*$", raw, flags=re.I):
            return RouteCandidate("workspace_list", "", 0.97, ("explicit_workspace_list",))
        switch_match = re.search(r"^(?:eris\s+)?(?:chuyển|chuyen|switch)\s+(?:sang\s+)?workspace\s+(.+?)\s*$", raw, flags=re.I)
        if switch_match:
            return RouteCandidate("workspace_switch", switch_match.group(1).strip(), 0.97, ("explicit_workspace_switch",))
        leave_match = re.search(r"^(?:eris\s+)?(?:rời|roi|leave|gỡ|go)\s+workspace(?:\s+(.+?))?\s*$", raw, flags=re.I)
        if leave_match:
            return RouteCandidate("workspace_leave", (leave_match.group(1) or "").strip(), 0.96, ("explicit_workspace_leave",))

        read_match = re.search(r"^(?:eris\s+)?(?:doc|xem)\s+(?:file|tep)\s+([^?]+)$", norm)
        if read_match and not any(token in norm for token in ("dang mo", "dang chon", "hien tai")):
            path = raw[read_match.start(1):].strip().strip("\"'")
            return RouteCandidate("project_read_file", path, 0.95, ("explicit_project_file_read",))

        symbol_match = re.search(r"^(?:eris\s+)?(?:tim|find)\s+(?:symbol|class|ham|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", norm)
        if symbol_match:
            raw_symbol = re.search(r"(?:symbol|class|hàm|ham|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", raw, flags=re.I)
            symbol = raw_symbol.group(1) if raw_symbol else symbol_match.group(1)
            return RouteCandidate("project_find_symbol", symbol, 0.96, ("explicit_symbol_search",))

        text_match = re.search(r"^(?:eris\s+)?(?:tim|search)\s+(.+?)\s+(?:trong|o)\s+(?:project|repo|source)\s*$", norm)
        if text_match:
            return RouteCandidate("project_search_text", text_match.group(1).strip(), 0.93, ("explicit_project_search",))

        if re.search(r"^(?:eris\s+)?(?:xem|doc|kiem)\s+(?:git\s+)?diff(?:\s+project|\s+repo)?\s*$", norm):
            return RouteCandidate("project_git_diff", "current", 0.96, ("explicit_project_diff",))
        if re.search(r"^(?:eris\s+)?(?:chay|run)\s+(?:lai\s+)?(?:test|pytest)(?:\s+.*)?$", norm):
            target = re.sub(r"^(?:eris\s+)?(?:chay|run)\s+(?:lai\s+)?", "", raw, flags=re.I).strip()
            return RouteCandidate("project_run_tests", target or "auto", 0.96, ("explicit_project_test",))
        if re.search(r"^(?:eris\s+)?(?:rollback|hoan tac|khoi phuc)\s+(?:thay doi|patch|operation)?(?:\s+.*)?$", norm):
            return RouteCandidate("project_rollback", "latest", 0.96, ("explicit_project_rollback",))
        if re.search(r"^(?:eris\s+)?(?:dong goi|tao)\s+(?:patch\s+)?(?:zip|patch zip)(?:\s+.*)?$", norm):
            return RouteCandidate("project_package_patch", "latest", 0.96, ("explicit_project_package",))
        if re.search(r"^(?:eris\s+)?(?:liet ke|list)\s+(?:file|tep)(?:\s+trong)?\s+(?:project|repo|source)\s*$", norm):
            return RouteCandidate("project_list_files", "", 0.95, ("explicit_project_list",))

        # Toàn quyền project: khi user ra lệnh sửa/làm/hoàn thành rõ ràng, runtime
        # tự tiếp tục kể cả không nhận được phản hồi duyệt tiếp theo.
        command_shape = re.search(
            r"^(?:eris\s+)?(?:sua|fix|lam|trien khai|hoan thanh|noi|them|xoa|refactor|viet lai|va|patch)\b",
            norm,
        )
        project_anchor = any(token in norm for token in (
            "project", "repo", "source", "src", "file", ".py", "runtime", "test", "patch", "code",
        ))
        advisory = any(token in norm for token in ("nen ", "co nen", "theo ban", "cach nao", "lam sao", "nhu the nao"))
        if command_shape and project_anchor and not advisory:
            return RouteCandidate("project_execute_task", raw, 0.91, ("explicit_autonomous_project_task",))
        return self._no_candidate("project_operation")

    def _route_internal_cognition(self, raw: str, norm: str) -> RouteCandidate:
        """Chỉ route câu lệnh tự kiểm tra có động từ rõ ràng.

        Câu hỏi xã hội tự nhiên như "em hiểu sai gì?" vẫn đi qua chat repair;
        chỉ "kiểm/rà/xem lại" mới biến thành action. Không cướp miệng của social
        cognition chỉ vì regex nhìn thấy chữ "sai" rồi phấn khích.
        """
        if self._starts_with_negation(norm):
            return self._blocked("review_discourse_claim", "negated")
        patterns = (
            ("review_discourse_claim", r"^(?:eris\s+)?(?:kiem tra|kiem|ra|xem lai|doi chieu)\s+(?:lai\s+)?(?:cho|cau|claim|loi)\s+(?:vua\s+)?(?:hieu sai|noi sai|bi sua|vua roi).*$", "latest_challenged"),
            ("inspect_unresolved_questions", r"^(?:eris\s+)?(?:kiem tra|kiem|xem|liet ke)\s+(?:lai\s+)?(?:cau hoi|correction)\s+(?:con\s+)?(?:bo ngo|chua tra loi|dang do).*$", "current"),
            ("inspect_memory_candidates", r"^(?:eris\s+)?(?:kiem tra|kiem|ra|xem|dem)\s+(?:lai\s+)?(?:memory candidate|manh ky uc|ky uc|manh nho)(?:\s+con sot|\s+chua xu ly|\s+di)?.*$", "summary_only"),
            ("compare_recent_turns", r"^(?:eris\s+)?(?:so sanh|doi chieu|kiem tra|kiem)\s+(?:hai|2)?\s*(?:cau|luot noi|phan hoi)\s+(?:gan nhat|vua roi|vua noi).*$", "recent"),
            ("inspect_social_state", r"^(?:eris\s+)?(?:kiem tra|kiem|xem|doc)\s+(?:social state|trang thai xa hoi|muc cau|muc buc)(?:\s+cua em|\s+hien tai)?.*$", "current"),
            ("detect_internal_contradictions", r"^(?:eris\s+)?(?:kiem tra|kiem|tim|xem)\s+(?:lai\s+)?(?:em co\s+)?(?:tu\s+)?mau thuan(?:\s+khong|\s+gi)?.*$", "recent"),
            ("summarize_open_loops", r"^(?:eris\s+)?(?:tong ket|kiem tra|kiem|xem|ra)\s+(?:lai\s+)?(?:open loop|viec nhan thuc|nhung gi)\s*(?:con dang do|con sot|bo ngo|chua xu ly)?.*$", "summary_only"),
            ("inspect_capability_health", r"^(?:eris\s+)?(?:kiem tra|kiem|xem|doc)\s+(?:lai\s+)?(?:capability|nang luc)(?:\s+health|\s+nao dang chet|\s+nao chua san sang|\s+hien tai)?.*$", "current"),
        )
        for action, pattern, value in patterns:
            if re.search(pattern, norm, flags=re.IGNORECASE):
                return RouteCandidate(action, value, 0.95, ("explicit_internal_cognitive_command",))
        return self._no_candidate("internal_cognition")

    def _route_environment_read(self, raw: str, norm: str) -> RouteCandidate:
        """Route sáu năng lực đọc môi trường, không route câu bàn về code API."""
        if self._starts_with_negation(norm):
            return self._blocked("environment_read", "negated")

        # Các câu này là truy vấn trạng thái thật, nên dạng hỏi tự nhiên vẫn được route.
        patterns = (
            ("get_active_application", r"^(?:eris\s+)?(?:(?:app|ung dung|cua so)\s+nao\s+(?:dang\s+)?(?:active|focus|mo)|dang\s+(?:active|focus)\s+(?:app|cua so)\s+gi|xem\s+(?:app|ung dung|cua so)\s+(?:dang\s+)?(?:active|focus)).*$", "current"),
            ("read_visible_ui_text", r"^(?:eris\s+)?(?:doc|xem|kiem)\s+(?:chu|text|uia|ocr|giao dien)(?:\s+(?:tren man hinh|dang hien|hien tai|nay))?.*$", "current"),
            ("inspect_runtime_log", r"^(?:eris\s+)?(?:doc|xem|kiem|ra)\s+(?:lai\s+)?(?:log runtime|log chay|log eris|runtime log)(?:\s+.*)?$", "latest"),
            ("read_current_error", r"^(?:eris\s+)?(?:(?:doc|xem|kiem|tim)\s+(?:loi|traceback|exception)(?:\s+(?:hien tai|dang hien|gan nhat))?|loi\s+(?:hien tai|dang hien)\s+la\s+gi).*$", "current"),
            ("inspect_selected_file", r"^(?:eris\s+)?(?:(?:file|tep)\s+nao\s+(?:dang\s+)?(?:mo|chon)|(?:doc|xem|kiem)\s+(?:file|tep)\s+(?:dang\s+)?(?:mo|chon|hien tai))(?:\s+.*)?$", "content" if any(token in norm for token in ("doc file", "doc tep", "noi dung", "preview")) else "metadata"),
            ("get_project_status", r"^(?:eris\s+)?(?:git status|project status|repo status|(?:xem|kiem)\s+(?:trang thai\s+)?(?:project|repo)|repo\s+(?:dang\s+)?ban\s+khong|co\s+file\s+nao\s+thay\s+doi).*$", "current"),
        )
        for action, pattern, value in patterns:
            if re.search(pattern, norm, flags=re.IGNORECASE):
                return RouteCandidate(action, value, 0.95, ("explicit_environment_read",))
        return self._no_candidate("environment_read")

    def _route_local_time(self, raw: str, norm: str) -> RouteCandidate:
        if self._looks_like_meta_question(norm):
            return self._blocked("get_local_time", "meta_question")
        patterns = (
            r"^\s*(?:bay gio|hien tai|bây giờ|hiện tại)?\s*(?:la\s*)?(?:may gio|mấy giờ)\s*(?:roi|rồi)?\s*\??\s*$",
            r"^\s*(?:xem|cho biet|cho biết|noi|nói)?\s*(?:gio|giờ)\s*(?:hien tai|hiện tại|bay gio|bây giờ)?\s*\??\s*$",
            r"^\s*what time is it\s*\??\s*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in patterns):
            return RouteCandidate("get_local_time", "", 0.94, ("local_time_query",))
        return self._no_candidate("get_local_time")

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
        "mo nhac",
        "bat nhac",
        "nghe nhac",
        "mo bai",
        "bat bai",
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

        max_patterns = (
            rf"^\s*{self._COMMAND_PREFIX}(?:set|dat|đặt|chinh|chỉnh|tang|tăng|day|đẩy|dua|đưa|bat|bật)?\s*(?:volume|am luong|âm lượng)?\s*(?:len|lên|toi|tới|ve|về)?\s*(?:max|maximum|full|100|toi da|tối đa|het co|hết cỡ|to nhat|to nhất)\s*%?\s*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in max_patterns):
            return RouteCandidate("set_volume", "100", 0.94, ("explicit_volume_max_command",))

        min_patterns = (
            rf"^\s*{self._COMMAND_PREFIX}(?:set|dat|đặt|chinh|chỉnh|giam|giảm|dua|đưa)?\s*(?:volume|am luong|âm lượng)?\s*(?:xuong|xuống|ve|về)?\s*(?:min|minimum|0|nho nhat|nhỏ nhất)\s*%?\s*$",
        )
        if any(re.search(p, norm, flags=re.IGNORECASE) for p in min_patterns):
            return RouteCandidate("set_volume", "0", 0.94, ("explicit_volume_min_command",))

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
