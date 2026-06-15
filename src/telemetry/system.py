import ctypes
import datetime
import os
import threading

import psutil
try:
    import uiautomation as auto
except Exception:  # pragma: no cover - Linux/CI hoặc máy chưa cài UIAutomation
    auto = None  # type: ignore

try:
    from .content_metadata import ContentMetadataCollector
except Exception:  # pragma: no cover - fallback nếu chạy file lẻ ngoài package
    ContentMetadataCollector = None  # type: ignore

_com_state = threading.local()


def _self_window_titles() -> set[str]:
    """Tên cửa sổ của chính Eris cần loại khỏi telemetry.

    Cửa sổ overlay của Eris là borderless + transparent + always-on-top phủ toàn
    màn hình, nên GetForegroundWindow rất hay trả về chính nó. Nếu để nguyên,
    Eris sẽ "thấy chính mình" và cứ bình luận về việc bị đè màn hình. Cho phép
    override qua ERIS_SELF_WINDOW_TITLES (ngăn cách bằng dấu phẩy).
    """
    raw = os.environ.get("ERIS_SELF_WINDOW_TITLES", "").strip()
    titles = {"eris"}
    for part in raw.split(","):
        cleaned = part.strip().lower()
        if cleaned:
            titles.add(cleaned)
    return titles


def _is_self_window(title: str) -> bool:
    return title.strip().lower() in _self_window_titles()


def _ensure_com_initialized() -> None:
    if getattr(_com_state, "initialized", False):
        return
    try:
        # UIAutomation is COM-backed. Background telemetry threads must initialize
        # COM for themselves before touching uiautomation.
        ctypes.windll.ole32.CoInitializeEx(None, 0)
    except Exception:
        pass
    _com_state.initialized = True


class TelemetryMixin:
    def _get_content_metadata_collector(self):
        # Collector được lazy-init vì TelemetryMixin không chắc có __init__ riêng.
        # Nếu import/OS không hỗ trợ thì trả None, runtime vẫn sống. Đáng tiếc là
        # phần mềm cần sống trước khi tỏ ra thông minh.
        collector = getattr(self, "_content_metadata_collector", None)
        if collector is not None:
            return collector
        if ContentMetadataCollector is None:
            return None
        try:
            collector = ContentMetadataCollector()
            self._content_metadata_collector = collector
            return collector
        except Exception:
            self._content_metadata_collector = None
            return None

    def _get_browser_telemetry_uia(self) -> dict:
        try:
            if auto is None:
                return {"url": "", "tabs": (), "available": False}
            _ensure_com_initialized()
            window = auto.GetForegroundControl()
            if window.ClassName != "Chrome_WidgetWin_1":
                return {"url": "", "tabs": (), "available": False}

            edit_control = window.EditControl(searchDepth=4)
            url = edit_control.GetValuePattern().Value if edit_control.Exists(0.1, 0) else ""

            tab_names = []
            for tab in auto.WalkTree(window, maxDepth=5):
                if tab[0].ControlType == auto.ControlType.TabItemControl and tab[0].Name:
                    tab_names.append(tab[0].Name)

            unique_tabs = tuple(dict.fromkeys(tab_names))[:10]
            return {"url": url, "tabs": unique_tabs, "available": True}
        except Exception:
            return {"url": "", "tabs": (), "available": False}

    def _enum_visible_titled_windows(self) -> list:
        """Trả danh sách title cửa sổ hiển thị theo thứ tự Z (trên xuống dưới).

        EnumWindows trả theo Z-order nên phần tử đầu là cửa sổ nằm trên cùng.
        Đã loại blacklist hệ thống và cửa sổ của chính Eris.
        """
        titles = []
        wnd_enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        blacklist = [
            "Program Manager",
            "Windows Input Experience",
            "Settings",
            "Taskbar",
            "NVIDIA GeForce Overlay",
            "Microsoft Text Input Application",
        ]

        def _callback(hwnd, _):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    if title and title not in blacklist and not _is_self_window(title):
                        titles.append(title)
            return True

        ctypes.windll.user32.EnumWindows(wnd_enum_proc(_callback), 0)
        return list(dict.fromkeys(titles))

    def _get_all_windows(self) -> list:
        return self._enum_visible_titled_windows()

    def _resolve_active_window(self) -> str:
        """Cửa sổ người dùng thực sự đang nhìn.

        Nếu foreground là chính Eris (hoặc rỗng), bỏ qua nó và lấy cửa sổ thật
        nằm ngay dưới theo Z-order. Nhờ vậy Eris không còn tự soi gương.
        """
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            foreground = buff.value.strip()
        except Exception:
            return "Không xác định"

        if foreground and not _is_self_window(foreground):
            return foreground

        # Foreground là chính Eris hoặc không có title → tìm cửa sổ thật dưới nó.
        try:
            for title in self._enum_visible_titled_windows():
                return title
        except Exception:
            pass
        return "Desktop"

    def _get_idle_seconds(self) -> float:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, millis / 1000.0)

    def capture_raw_telemetry(self, *, mood_score: int, inferred_pos_x: float) -> dict:
        try:
            active_window = self._resolve_active_window()
        except Exception:
            active_window = "Không xác định"

        try:
            browser_info = self._get_browser_telemetry_uia()
        except Exception:
            browser_info = {"url": "", "tabs": (), "available": False}

        try:
            all_windows = self._get_all_windows()
        except Exception:
            all_windows = []

        try:
            collector = self._get_content_metadata_collector()
            if collector is None:
                content_metadata = {}
            else:
                content_metadata = collector.collect(
                    active_window=active_window,
                    browser_url=str(browser_info.get("url", "") or ""),
                    browser_tabs=tuple(browser_info.get("tabs", ()) or ()),
                )
        except Exception:
            # Metadata nội dung là steroid, không phải single point of failure.
            # Để collector làm sập telemetry thì đúng là nâng cấp theo trường phái tự hủy.
            content_metadata = {}

        try:
            cpu = psutil.cpu_percent(interval=0.2)
            ram = psutil.virtual_memory().percent
        except Exception:
            cpu = 0.0
            ram = 0.0

        current_time = datetime.datetime.now().strftime("%H:%M")
        try:
            idle_seconds = self._get_idle_seconds()
        except Exception:
            idle_seconds = 0.0

        return {
            "captured_at": current_time,
            "active_window": active_window,
            "active_app": active_window,
            "browser_url": str(browser_info.get("url", "") or ""),
            "browser_tabs": tuple(browser_info.get("tabs", ()) or ()),
            "content_metadata": content_metadata,
            "open_windows": tuple(all_windows),
            "cpu_percent": cpu,
            "ram_percent": ram,
            "mood_score": mood_score,
            "inferred_pos_x": inferred_pos_x,
            "idle_seconds": idle_seconds,
            "recent_events": (),
            "user_signals": {},
            "evidence": (),
            "claim_style": "",
        }

    def get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float):
        raw = self.capture_raw_telemetry(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )

        mood_str = "Trung lập"
        if mood_score >= 80:
            mood_str = "Hài lòng ngầm"
        elif mood_score <= 30:
            mood_str = "Thất vọng"

        pos_str = f"{inferred_pos_x:.0%}"
        if inferred_pos_x <= 0.15:
            pos_str = "mép trái"
        elif inferred_pos_x >= 0.85:
            pos_str = "mép phải"
        elif 0.4 <= inferred_pos_x <= 0.6:
            pos_str = "giữa màn hình"

        active_window = str(raw["active_window"])
        browser_url = str(raw["browser_url"])
        browser_tabs = tuple(raw["browser_tabs"])
        content_metadata = raw.get("content_metadata", {}) if isinstance(raw.get("content_metadata", {}), dict) else {}
        all_windows = list(raw["open_windows"])
        cpu = float(raw["cpu_percent"])
        ram = float(raw["ram_percent"])
        current_time = str(raw["captured_at"])
        idle_seconds = float(raw["idle_seconds"])

        content_str = ""
        if content_metadata:
            title = str(content_metadata.get("title", "") or "").strip()
            caption = str(content_metadata.get("caption_sample", "") or "").strip()
            source = str(content_metadata.get("source", "") or "").strip()
            tier = str(content_metadata.get("tier", "") or "").strip()
            confidence = content_metadata.get("confidence", 0.0)
            visible_piece = caption or title
            if visible_piece:
                if len(visible_piece) > 96:
                    visible_piece = visible_piece[:93].rstrip() + "..."
                content_str = f" Nội dung thấy được: [{visible_piece}] source={source}/{tier} conf={confidence}."

        if browser_url:
            tabs_str = ", ".join(browser_tabs[:10]) if browser_tabs else "Không rõ"
            active_window = f"{active_window} URL: {browser_url} | Tabs: [{tabs_str}]"

        other_windows = [window for window in all_windows if len(window) > 3 and window != raw["active_window"]]
        other_windows_str = ", ".join(other_windows[:15]) if other_windows else "Không có"

        return (
            f"Thời gian: {current_time}. "
            f"Tâm trạng: {mood_str} ({mood_score}/100). "
            f"Vị trí ERIS: {pos_str}. "
            f"Ứng dụng đang focus: [{active_window}]. "
            f"Tất cả cửa sổ đang mở: [{other_windows_str}]."
            f"{content_str} "
            f"CPU: {cpu}%. RAM: {ram}%. "
            f"Idle: {int(idle_seconds)}s."
        )
