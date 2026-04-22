import re


class ActionRouter:
    def route_chat(self, user_text: str, *, last_action: str = "") -> tuple[str, str] | None:
        lowered = (user_text or "").strip().lower()
        if not lowered:
            return None

        url_match = re.search(
            r"(?:mở|mo|open)\s+(https?://\S+|www\.\S+|[\w.-]+\.(?:com|vn|net|org|io|me|app)(?:/\S*)?)",
            lowered,
        )
        if url_match:
            return "open_url", url_match.group(1)

        if self._looks_like_now_playing(lowered):
            return "get_now_playing", ""
        if self._looks_like_now_playing_follow_up(lowered, last_action=last_action):
            return "get_now_playing", ""

        if any(token in lowered for token in ("play pause", "play/pause", "tạm dừng nhạc", "tam dung nhac", "pause nhạc", "pause nhac", "phát nhạc tiếp", "phat nhac tiep", "tiếp tục nhạc", "tiep tuc nhac")):
            return "play_pause_media", ""

        if "âm lượng" in lowered or "am luong" in lowered or "volume" in lowered:
            volume_match = re.search(r"(\d{1,3}|mute|silent|tat am|tat tieng)", lowered)
            if volume_match:
                return "set_volume", volume_match.group(1)

        copy_match = re.search(r"^(?:copy|sao chép|sao chep|chép|chep)\s+(.+)$", (user_text or "").strip(), flags=re.IGNORECASE)
        if copy_match:
            return "copy_text", copy_match.group(1).strip()

        focus_match = re.search(
            r"(?:focus|chuyển qua cửa sổ|chuyen qua cua so|đưa lên cửa sổ|dua len cua so)\s+(.+)$",
            (user_text or "").strip(),
            flags=re.IGNORECASE,
        )
        if focus_match:
            return "focus_window", focus_match.group(1).strip()

        app_match = re.search(
            r"(?:mở app|mo app|chạy app|chay app|launch app|launch)\s+(.+)$",
            (user_text or "").strip(),
            flags=re.IGNORECASE,
        )
        if app_match:
            return "launch_app", app_match.group(1).strip()
        
        # search web
        search_match = re.search(
            r"(?:tìm kiếm|tim kiem|search for|search)\s+(.+)$",
            (user_text or "").strip(),
            flags=re.IGNORECASE, # Thêm cờ IGNORECASE để không phân biệt chữ hoa thường
        )
        if search_match:
            query = search_match.group(1).strip() # Lấy phần truy vấn tìm kiếm và loại bỏ khoảng trắng thừa
            if query:
                return "search_web", query
            
        # get weather
        lowered_no_tone = lowered
        if "thoi tiet" in lowered_no_tone or "thời tiết" in lowered:
            raw = (user_text or "").strip()
            if raw:
                return "get_weather", raw

        return None

    def _looks_like_now_playing(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "youtube",
                "spotify",
                "đang nghe gì",
                "dang nghe gi",
                "mở nhạc",
                "mo nhac",
                "thấy nhạc",
                "thay nhac",
                "nhạc gì",
                "nhac gi",
                "bài gì",
                "bai gi",
                "tên nhạc",
                "ten nhac",
                "tên bài",
                "ten bai",
                "song name",
                "now playing",
            )
        )

    def _looks_like_now_playing_follow_up(self, lowered: str, *, last_action: str) -> bool:
        if last_action != "get_now_playing":
            return False
        if len(lowered) > 48:
            return False
        return any(
            token in lowered
            for token in (
                "youtube",
                "spotify",
                "nhạc",
                "nhac",
                "bài",
                "bai",
                "ấy",
                "ay",
                "đó",
                "do",
                "kia",
            )
        )
