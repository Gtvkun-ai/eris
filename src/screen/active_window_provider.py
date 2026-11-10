from __future__ import annotations

"""Đọc cửa sổ foreground trên Windows mà không kéo VLM vào cuộc."""

import ctypes
from ctypes import wintypes
import os

from .evidence_models import ActiveWindowInfo
from native.process_resolver import ProcessResolver


class ActiveWindowProvider:
    def __init__(self) -> None:
        self._resolver = ProcessResolver()

    def get(self) -> ActiveWindowInfo:
        if os.name != "nt":
            return ActiveWindowInfo(title="Desktop")
        try:
            user32 = ctypes.windll.user32
            hwnd = int(user32.GetForegroundWindow() or 0)
            if not hwnd:
                return ActiveWindowInfo(title="Desktop")
            length = int(user32.GetWindowTextLengthW(hwnd) or 0)
            buff = ctypes.create_unicode_buffer(max(1, length + 1))
            user32.GetWindowTextW(hwnd, buff, len(buff))

            rect = wintypes.RECT()
            bounds = None
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                width = max(1, int(rect.right - rect.left))
                height = max(1, int(rect.bottom - rect.top))
                bounds = (int(rect.left), int(rect.top), width, height)
            title = buff.value.strip() or "Desktop"
            identity = self._resolver.resolve(hwnd, title=title)
            low_title = title.lower()
            low_proc = (identity.process_name or "").lower()
            if any(k in low_title or k in low_proc for k in ("radmin", "rvrvpngui", "eris")):
                PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                chosen = []
                def cb(candidate, _):
                    candidate = int(candidate or 0)
                    if not candidate or not user32.IsWindowVisible(candidate):
                        return True
                    length_c = int(user32.GetWindowTextLengthW(candidate) or 0)
                    buff_c = ctypes.create_unicode_buffer(max(1, length_c + 1))
                    user32.GetWindowTextW(candidate, buff_c, len(buff_c))
                    t_c = buff_c.value.strip()
                    if t_c:
                        id_c = self._resolver.resolve(candidate, title=t_c)
                        lt_c = t_c.lower()
                        lp_c = (id_c.process_name or "").lower()
                        if not any(k in lt_c or k in lp_c for k in ("radmin", "rvrvpngui", "eris")):
                            chosen.append((candidate, t_c, id_c))
                            return False
                    return True
                user32.EnumWindows(PROC(cb), 0)
                if chosen:
                    hwnd, title, identity = chosen[0]
                    rect_c = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect_c)):
                        width_c = max(1, int(rect_c.right - rect_c.left))
                        height_c = max(1, int(rect_c.bottom - rect_c.top))
                        bounds = (int(rect_c.left), int(rect_c.top), width_c, height_c)
                else:
                    title = "Desktop"

            return ActiveWindowInfo(
                title=title,
                hwnd=hwnd,
                bounds=bounds,
                process_name=identity.process_name,
                pid=identity.pid,
                window_class=identity.window_class,
                executable_path=identity.executable_path,
            )
        except Exception:
            return ActiveWindowInfo(title="Desktop")
