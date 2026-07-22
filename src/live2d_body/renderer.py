# -*- coding: utf-8 -*-
"""Cửa sổ Live2D trong suốt dùng live2d-py + GLFW."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .config import Live2DBodyConfig
from .stage_state import Live2DStageState
from .udp_receiver import Live2DStageReceiver


class Live2DDependencyError(RuntimeError):
    pass


def _load_dependencies() -> tuple[Any, Any]:
    try:
        import glfw  # type: ignore
    except ImportError as exc:
        raise Live2DDependencyError(
            "Thiếu glfw. Chạy install_live2d_body.bat trước."
        ) from exc
    try:
        import live2d.v3 as live2d  # type: ignore
    except ImportError as exc:
        raise Live2DDependencyError(
            "Thiếu live2d-py cho Cubism 3+. Chạy install_live2d_body.bat trước."
        ) from exc
    return glfw, live2d


class Live2DRenderer:
    def __init__(
        self,
        config: Live2DBodyConfig,
        state: Live2DStageState,
        receiver: Live2DStageReceiver,
    ) -> None:
        self.config = config
        self.state = state
        self.receiver = receiver
        self.available_parameters: set[str] = set()
        self._dragging_window = False
        self._drag_origin_cursor = (0.0, 0.0)
        self._drag_origin_window = (0, 0)
        self._eye_x = 0.0
        self._eye_y = 0.0

    def run(self) -> None:
        glfw, live2d = _load_dependencies()
        model_path = Path(self.config.model_path).resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"Không thấy model3.json: {model_path}")

        if not glfw.init():
            raise RuntimeError("GLFW không khởi tạo được OpenGL window")

        window = None
        model = None
        try:
            glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)
            glfw.window_hint(glfw.DECORATED, glfw.TRUE if self.config.decorated else glfw.FALSE)
            glfw.window_hint(glfw.FLOATING, glfw.TRUE if self.config.topmost else glfw.FALSE)
            if self.config.transparent:
                glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)

            window = glfw.create_window(
                self.config.width,
                self.config.height,
                "Eris Live2D",
                None,
                None,
            )
            if not window:
                raise RuntimeError("Không tạo được cửa sổ Live2D")
            glfw.make_context_current(window)
            glfw.swap_interval(1)
            screen_size, window_pos = self._position_window(glfw, window)
            self._show_window(glfw, window)

            live2d.init()
            live2d.glInit()
            model = live2d.LAppModel()
            model.LoadModelJson(str(model_path))
            fb_width, fb_height = glfw.get_framebuffer_size(window)
            model.Resize(max(1, fb_width), max(1, fb_height))
            model.SetScale(self.config.scale)
            model.SetOffset(self.config.offset_x, self.config.offset_y)
            model.SetAutoBlinkEnable(True)
            model.SetAutoBreathEnable(True)
            self.available_parameters = self._read_parameter_ids(model)
            canvas_size = self._safe_model_call(model, "GetCanvasSize")
            canvas_pixel_size = self._safe_model_call(model, "GetCanvasSizePixel")

            self._install_callbacks(glfw, window, model)
            self.receiver.send_avatar_ready()
            print(
                f"[Live2D] Đã mở {model_path.name} | UDP {self.config.listen_host}:{self.config.listen_port}",
                flush=True,
            )
            print(
                "[Live2D] Window "
                f"pos={window_pos} size=({self.config.width},{self.config.height}) "
                f"fb=({fb_width},{fb_height}) screen={screen_size} "
                f"canvas={canvas_size} canvas_px={canvas_pixel_size} "
                f"scale={self.config.scale:.2f} offset=({self.config.offset_x:.2f},{self.config.offset_y:.2f}) "
                f"transparent={self.config.transparent} decorated={self.config.decorated} topmost={self.config.topmost}",
                flush=True,
            )
            if "ParamMouthOpenY" not in self.available_parameters:
                print("[Live2D][WARN] Model thiếu ParamMouthOpenY, lip sync sẽ không hoạt động.", flush=True)

            last = time.monotonic()
            fps_count = 0
            fps_at = last
            while not glfw.window_should_close(window):
                glfw.poll_events()
                now = time.monotonic()
                dt = now - last
                last = now

                model.Update()
                snapshot = self.state.advance(dt, now=now)
                for parameter_id, value in snapshot.parameters.items():
                    if parameter_id in self.available_parameters:
                        model.SetParameterValue(parameter_id, float(value))
                # Model của bạn dùng ID mắt riêng thay vì ParamEyeBallX/Y chuẩn.
                # Gắn trực tiếp để con ngươi vẫn theo chuột, không bắt người dùng
                # quay lại rig chỉ vì một convention tên gọi.
                custom_eye_values = {
                    "eyeballxl": self._eye_x,
                    "eyeballxr": self._eye_x,
                    "eyebally": self._eye_y,
                    "eyeballyr": self._eye_y,
                }
                for parameter_id, value in custom_eye_values.items():
                    if parameter_id in self.available_parameters:
                        model.SetParameterValue(parameter_id, float(value))

                if self.config.transparent:
                    live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
                else:
                    live2d.clearBuffer(0.08, 0.08, 0.10, 1.0)
                model.Draw()
                glfw.swap_buffers(window)

                fps_count += 1
                if now - fps_at >= 1.0:
                    if self.config.decorated:
                        glfw.set_window_title(
                            window,
                            f"Eris Live2D | {fps_count} FPS | {snapshot.emotion}",
                        )
                    fps_count = 0
                    fps_at = now
        finally:
            self.receiver.close()
            try:
                if model is not None:
                    model.StopAllMotions()
            except Exception:
                pass
            try:
                live2d.dispose()
            except Exception:
                pass
            if window is not None:
                try:
                    glfw.destroy_window(window)
                except Exception:
                    pass
            glfw.terminate()

    @staticmethod
    def _read_parameter_ids(model: Any) -> set[str]:
        ids: set[str] = set()
        try:
            for index in range(int(model.GetParameterCount())):
                parameter = model.GetParameter(index)
                parameter_id = str(getattr(parameter, "id", "") or "")
                if parameter_id:
                    ids.add(parameter_id)
        except Exception as exc:
            print(f"[Live2D][WARN] Không đọc được parameter list: {exc}", flush=True)
        return ids

    @staticmethod
    def _safe_model_call(model: Any, method_name: str) -> Any:
        try:
            return getattr(model, method_name)()
        except Exception as exc:
            return f"unavailable:{exc}"

    def _position_window(self, glfw: Any, window: Any) -> tuple[tuple[int, int], tuple[int, int]]:
        screen_size = (0, 0)
        window_pos = (0, 0)
        try:
            monitor = glfw.get_primary_monitor()
            mode = glfw.get_video_mode(monitor)
            screen_width = int(mode.size.width)
            screen_height = int(mode.size.height)
            screen_size = (screen_width, screen_height)
            x = self.config.x if self.config.x is not None else max(0, screen_width - self.config.width - 30)
            y = self.config.y if self.config.y is not None else max(0, screen_height - self.config.height - 70)
            glfw.set_window_pos(window, x, y)
            window_pos = (int(x), int(y))
        except Exception:
            pass
        return screen_size, window_pos

    @staticmethod
    def _show_window(glfw: Any, window: Any) -> None:
        try:
            glfw.show_window(window)
        except Exception:
            pass
        try:
            glfw.focus_window(window)
        except Exception:
            pass
        try:
            hwnd = glfw.get_win32_window(window)
            if hwnd:
                import ctypes

                ctypes.windll.user32.SetForegroundWindow(int(hwnd))
        except Exception:
            pass

    def _install_callbacks(self, glfw: Any, window: Any, model: Any) -> None:
        def on_framebuffer_size(_window: Any, width: int, height: int) -> None:
            if width > 0 and height > 0:
                model.Resize(width, height)

        def on_key(_window: Any, key: int, _scancode: int, action: int, _mods: int) -> None:
            if action != glfw.PRESS:
                return
            if key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(window, True)
            elif key == glfw.KEY_R:
                model.StopAllMotions()
                model.ResetPose()
                model.ResetParameters()
            elif key in (glfw.KEY_EQUAL, glfw.KEY_KP_ADD):
                model.SetScale(min(3.0, self.config.scale + 0.1))
            elif key in (glfw.KEY_MINUS, glfw.KEY_KP_SUBTRACT):
                model.SetScale(max(0.2, self.config.scale - 0.1))

        def on_mouse_button(_window: Any, button: int, action: int, _mods: int) -> None:
            # Chuột phải yêu cầu chính Godot mở context menu hiện có. Nhờ vậy
            # Live2D không mọc thêm một bộ menu nửa mùa bằng toolkit khác.
            if button == glfw.MOUSE_BUTTON_RIGHT and action == glfw.PRESS:
                cursor_x, cursor_y = glfw.get_cursor_pos(window)
                window_x, window_y = glfw.get_window_pos(window)
                self.receiver.send_context_menu_request(
                    screen_x=int(window_x + cursor_x),
                    screen_y=int(window_y + cursor_y),
                )
                return

            # Chuột giữa kéo cửa sổ Live2D; chuột trái vẫn dành cho eye/face drag.
            if button != glfw.MOUSE_BUTTON_MIDDLE:
                return
            if action == glfw.PRESS:
                self._dragging_window = True
                self._drag_origin_cursor = glfw.get_cursor_pos(window)
                self._drag_origin_window = glfw.get_window_pos(window)
            elif action == glfw.RELEASE:
                self._dragging_window = False

        def on_cursor(_window: Any, x: float, y: float) -> None:
            try:
                width, height = glfw.get_window_size(window)
                if width > 0 and height > 0:
                    self._eye_x = max(-1.0, min(1.0, (x / width) * 2.0 - 1.0))
                    self._eye_y = max(-1.0, min(1.0, 1.0 - (y / height) * 2.0))
                model.Drag(x, y)
            except Exception:
                pass
            if self._dragging_window:
                dx = x - self._drag_origin_cursor[0]
                dy = y - self._drag_origin_cursor[1]
                glfw.set_window_pos(
                    window,
                    int(self._drag_origin_window[0] + dx),
                    int(self._drag_origin_window[1] + dy),
                )

        glfw.set_framebuffer_size_callback(window, on_framebuffer_size)
        glfw.set_key_callback(window, on_key)
        glfw.set_mouse_button_callback(window, on_mouse_button)
        glfw.set_cursor_pos_callback(window, on_cursor)


def run_renderer(config: Live2DBodyConfig) -> None:
    state = Live2DStageState()
    receiver = Live2DStageReceiver(
        state,
        host=config.listen_host,
        port=config.listen_port,
        backend_host=config.backend_host,
        backend_port=config.backend_port,
        body_host=config.body_host,
        body_port=config.body_port,
    )
    receiver.start()
    renderer = Live2DRenderer(config, state, receiver)
    renderer.run()
