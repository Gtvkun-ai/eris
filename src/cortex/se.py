import json
import os

from .contracts import TelemetrySnapshot


class SeLens:
    _CODING_KEYWORDS = (
        "visual studio code",
        "vscode",
        "visual studio",
        "rider",
        "pycharm",
        "intellij",
        "godot",
        "terminal",
        "powershell",
        "cmd.exe",
        "github",
        "git bash",
    )
    _DOC_KEYWORDS = (
        "docs",
        "documentation",
        "readme",
        "stackoverflow",
        "stack overflow",
        "developer.mozilla",
        "learn.microsoft",
        "python.org",
    )
    _COMMUNICATION_KEYWORDS = (
        "discord",
        "telegram",
        "slack",
        "messenger",
        "mail",
        "gmail",
        "outlook",
        "zalo",
        "facebook",
    )
    _ENTERTAINMENT_KEYWORDS = (
        "youtube",
        "netflix",
        "spotify",
        "steam",
        "game",
        "twitch",
        "instagram",
        "tiktok",
        "reddit",
    )

    def __init__(self):
        self._context_overrides = self._load_context_overrides()

    def build_snapshot(self, raw: dict) -> TelemetrySnapshot:
        active_window = str(raw.get("active_window", "") or "Desktop")
        browser_url = str(raw.get("browser_url", "") or "")
        browser_tabs = tuple(str(tab) for tab in raw.get("browser_tabs", ()) if str(tab).strip())
        open_windows = tuple(str(window) for window in raw.get("open_windows", ()) if str(window).strip())
        active_window_kind = self._classify_window_kind(active_window, browser_url, browser_tabs)

        return TelemetrySnapshot(
            captured_at=str(raw.get("captured_at", "")),
            active_window=active_window,
            active_window_kind=active_window_kind,
            focus_summary=self._build_focus_summary(active_window_kind, active_window, browser_url),
            browser_url=browser_url,
            browser_tabs=browser_tabs,
            open_windows=open_windows,
            cpu_percent=float(raw.get("cpu_percent", 0.0) or 0.0),
            ram_percent=float(raw.get("ram_percent", 0.0) or 0.0),
            mood_score=int(raw.get("mood_score", 50) or 50),
            mood_label=self._label_mood(int(raw.get("mood_score", 50) or 50)),
            inferred_pos_x=float(raw.get("inferred_pos_x", 0.5) or 0.5),
            position_label=self._label_position(float(raw.get("inferred_pos_x", 0.5) or 0.5)),
            idle_seconds=float(raw.get("idle_seconds", 0.0) or 0.0),
            idle_label=self._label_idle(float(raw.get("idle_seconds", 0.0) or 0.0)),
        )

    def _load_context_overrides(self) -> dict[str, tuple[str, ...]]:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        config_path = os.path.join(project_root, "focus_context_config.json")
        defaults = {
            "force_communication": (),
            "focus_aid_media": (),
        }
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return defaults

        if not isinstance(data, dict):
            return defaults

        normalized: dict[str, tuple[str, ...]] = {}
        for key, fallback in defaults.items():
            raw_values = data.get(key, ())
            if not isinstance(raw_values, (list, tuple)):
                normalized[key] = fallback
                continue
            normalized[key] = tuple(
                str(value).strip().lower()
                for value in raw_values
                if str(value).strip()
            )
        return normalized

    def _contains_override(self, haystack: str, key: str) -> bool:
        keywords = self._context_overrides.get(key, ())
        return any(keyword in haystack for keyword in keywords)

    def format_snapshot(self, snapshot: TelemetrySnapshot) -> str:
        tabs_str = ", ".join(snapshot.browser_tabs[:6]) if snapshot.browser_tabs else "không rõ"
        other_windows = ", ".join(snapshot.open_windows[:12]) if snapshot.open_windows else "không có"
        browser_segment = ""
        if snapshot.browser_url:
            browser_segment = (
                f" URL trình duyệt: [{snapshot.browser_url}]."
                f" Các tab đang mở: [{tabs_str}]."
            )

        return (
            f"Thời gian: {snapshot.captured_at}. "
            f"Loại focus: {snapshot.active_window_kind}. "
            f"Tóm tắt focus: {snapshot.focus_summary}. "
            f"Cửa sổ đang focus: [{snapshot.active_window}]."
            f"{browser_segment} "
            f"Các cửa sổ khác: [{other_windows}]. "
            f"CPU: {snapshot.cpu_percent:.1f}%. "
            f"RAM: {snapshot.ram_percent:.1f}%. "
            f"Tâm trạng: {snapshot.mood_label} ({snapshot.mood_score}/100). "
            f"Vị trí ERIS: {snapshot.position_label}. "
            f"Trạng thái nhàn rỗi: {snapshot.idle_label} ({int(snapshot.idle_seconds)}s)."
        )

    def _classify_window_kind(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...]) -> str:
        active_haystack = " | ".join((active_window, browser_url)).lower()
        tabs_haystack = " | ".join(browser_tabs).lower()
        combined_haystack = f"{active_haystack} | {tabs_haystack}"

        if any(keyword in active_haystack for keyword in self._CODING_KEYWORDS):
            return "coding"
        if any(keyword in active_haystack for keyword in self._DOC_KEYWORDS):
            return "documentation"
        if self._contains_override(combined_haystack, "force_communication"):
            return "communication"
        if self._contains_override(combined_haystack, "focus_aid_media"):
            return "general"
        if any(keyword in active_haystack for keyword in self._COMMUNICATION_KEYWORDS):
            return "communication"
        if any(keyword in active_haystack for keyword in self._ENTERTAINMENT_KEYWORDS):
            return "entertainment"
        if any(keyword in tabs_haystack for keyword in self._CODING_KEYWORDS):
            return "coding"
        if any(keyword in tabs_haystack for keyword in self._DOC_KEYWORDS):
            return "documentation"
        if self._contains_override(combined_haystack, "force_communication"):
            return "communication"
        if self._contains_override(combined_haystack, "focus_aid_media"):
            return "general"
        if any(keyword in tabs_haystack for keyword in self._COMMUNICATION_KEYWORDS):
            return "communication"
        if any(keyword in tabs_haystack for keyword in self._ENTERTAINMENT_KEYWORDS):
            return "entertainment"
        haystack = combined_haystack
        if "settings" in haystack or "task manager" in haystack or "file explorer" in haystack:
            return "system"
        return "general"

    def _build_focus_summary(self, active_window_kind: str, active_window: str, browser_url: str) -> str:
        if active_window_kind == "coding":
            return f"Ngài đang ở bối cảnh code hoặc project: {active_window}"
        if active_window_kind == "documentation":
            return f"Ngài đang đọc tài liệu hoặc reference: {browser_url or active_window}"
        if active_window_kind == "communication":
            return f"Ngài đang ở bối cảnh giao tiếp: {active_window}"
        if active_window_kind == "entertainment":
            return f"Ngài đang nghiêng sang giải trí: {active_window}"
        if active_window_kind == "system":
            return f"Ngài đang thao tác hệ thống: {active_window}"
        return f"Ngài đang ở bối cảnh tổng quát: {active_window}"

    def _label_mood(self, mood_score: int) -> str:
        if mood_score >= 80:
            return "hài lòng ngầm"
        if mood_score <= 30:
            return "bực dọc"
        return "trung tính"

    def _label_position(self, inferred_pos_x: float) -> str:
        if inferred_pos_x <= 0.15:
            return "mép trái"
        if inferred_pos_x >= 0.85:
            return "mép phải"
        if 0.4 <= inferred_pos_x <= 0.6:
            return "giữa màn hình"
        return "lệch tâm"

    def _label_idle(self, idle_seconds: float) -> str:
        if idle_seconds >= 600:
            return "rất lâu không tương tác"
        if idle_seconds >= 180:
            return "đang nhàn rỗi"
        if idle_seconds >= 45:
            return "đang chậm lại"
        return "đang hoạt động"
