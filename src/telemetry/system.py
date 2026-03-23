import ctypes
import datetime

import psutil
import uiautomation as auto
# TelemetryMixin là một lớp mixin cung cấp các phương thức để thu thập dữ liệu telemetry hệ thống,
#  bao gồm việc trích xuất thông tin từ trình duyệt web đang hoạt động,
#  liệt kê tất cả các cửa sổ đang mở, và thu thập thông tin về trạng thái tâm trạng và vị trí ước tính của hệ thống. 
# Lớp này sử dụng các thư viện như psutil để lấy thông tin về CPU và RAM,
#  và uiautomation để tương tác với giao diện người dùng của hệ điều hành Windows để lấy thông tin về cửa sổ đang hoạt động và trình duyệt.


class TelemetryMixin:
    def _get_browser_telemetry_uia(self) -> str:
        """Nội soi trực tiếp bộ nhớ giao diện của Chromium (Brave/Chrome) qua API Trợ năng."""
        try:
            window = auto.GetForegroundControl()
            if window.ClassName != "Chrome_WidgetWin_1":
                return ""

            edit_control = window.EditControl(searchDepth=4)
            url = edit_control.GetValuePattern().Value if edit_control.Exists(0.1, 0) else "Ẩn/Trống"

            tab_names = []
            for tab in auto.WalkTree(window, maxDepth=5):
                if tab[0].ControlType == auto.ControlType.TabItemControl and tab[0].Name:
                    tab_names.append(tab[0].Name)

            unique_tabs = list(dict.fromkeys(tab_names))[:10]
            tabs_str = ", ".join(unique_tabs) if unique_tabs else "Không rõ"
            return f"(Dữ liệu Thời gian thực) URL: {url} | Các Tab đang mở: [{tabs_str}]"
        except Exception:
            return "Không thể trích xuất DOM trình duyệt."

    def _get_all_windows(self) -> list:
        titles = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        blacklist = [
            "Program Manager", "Windows Input Experience", "Settings",
            "Taskbar", "NVIDIA GeForce Overlay", "Microsoft Text Input Application",
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

        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_callback), 0)
        return list(dict.fromkeys(titles))

    def get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            active_window = buff.value.strip() or "Desktop"
        except Exception:
            active_window = "Không xác định"

        browser_info = self._get_browser_telemetry_uia()
        if browser_info:
            active_window += f" {browser_info}"

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

        mood_str = "Trung lập"
        if mood_score >= 80:
            mood_str = "Hài lòng ngầm (dù bề ngoài vẫn lạnh nhạt)"
        elif mood_score <= 30:
            mood_str = "Thất vọng, cáu gắt vì sự lười biếng"

        pos_str = f"{inferred_pos_x:.0%}"
        if inferred_pos_x <= 0.15:
            pos_str = "mép trái"
        elif inferred_pos_x >= 0.85:
            pos_str = "mép phải"
        elif 0.4 <= inferred_pos_x <= 0.6:
            pos_str = "giữa màn hình"

        other_windows = [w for w in all_windows if len(w) > 3 and w != active_window]
        other_windows_str = ", ".join(other_windows[:15]) if other_windows else "Không có"

        return (
            f"Thời gian: {current_time}. "
            f"Tâm trạng: {mood_str} ({mood_score}/100). "
            f"Vị trí ERIS: {pos_str}. "
            f"Ứng dụng đang focus: [{active_window}]. "
            f"Tất cả cửa sổ đang mở: [{other_windows_str}]. "
            f"CPU: {cpu}%. RAM: {ram}%."
        )
