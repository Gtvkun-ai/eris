"""Capture pixels locally with optional MSS and Pillow dependencies."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def capture_screen(bounds: tuple[int, int, int, int] | None = None) -> Image:
    """Capture a desktop region clipped to the virtual screen, or the whole screen."""
    import mss
    from PIL import Image

    last_exc = None
    try:
        with mss.mss() as grabber:
            desktop = grabber.monitors[0]
            region = desktop
            if bounds is not None:
                left, top, width, height = bounds
                right = min(left + width, desktop["left"] + desktop["width"])
                bottom = min(top + height, desktop["top"] + desktop["height"])
                left = max(left, desktop["left"])
                top = max(top, desktop["top"])
                if right <= left or bottom <= top:
                    raise ValueError("capture_bounds_outside_desktop")
                region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            try:
                shot = grabber.grab(region)
                return Image.frombytes("RGB", shot.size, shot.rgb)
            except Exception as grab_exc:
                last_exc = grab_exc
                # Thử primary monitor (monitors[1]) nếu monitors[0] (virtual desktop) bị BitBlt lỗi
                if bounds is None and len(grabber.monitors) > 1:
                    try:
                        shot = grabber.grab(grabber.monitors[1])
                        return Image.frombytes("RGB", shot.size, shot.rgb)
                    except Exception:
                        pass
                raise
    except Exception as exc:
        last_exc = exc

    # Fallback dự phòng qua PIL ImageGrab (dùng Windows GDI độc lập)
    try:
        from PIL import ImageGrab
        if bounds is not None:
            left, top, width, height = bounds
            bbox = (left, top, left + width, top + height)
            return ImageGrab.grab(bbox=bbox)
        return ImageGrab.grab()
    except Exception as pil_exc:
        if last_exc is not None:
            raise last_exc
        raise pil_exc
