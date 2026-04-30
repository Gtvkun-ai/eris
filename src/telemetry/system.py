import ctypes
import datetime

import psutil
import uiautomation as auto


class TelemetryMixin:
    def _get_browser_telemetry_uia(self) -> dict:
        try:
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

    def _get_all_windows(self) -> list:
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
                    if title and title not in blacklist:
                        titles.append(title)
            return True

        ctypes.windll.user32.EnumWindows(wnd_enum_proc(_callback), 0)
        return list(dict.fromkeys(titles))

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
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            active_window = buff.value.strip() or "Desktop"
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
        all_windows = list(raw["open_windows"])
        cpu = float(raw["cpu_percent"])
        ram = float(raw["ram_percent"])
        current_time = str(raw["captured_at"])
        idle_seconds = float(raw["idle_seconds"])

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
            f"Tất cả cửa sổ đang mở: [{other_windows_str}]. "
            f"CPU: {cpu}%. RAM: {ram}%. "
            f"Idle: {int(idle_seconds)}s."
        )
