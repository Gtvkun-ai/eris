# -*- coding: utf-8 -*-
"""Cửa sổ Live2D trong suốt dùng live2d-py + GLFW.

Renderer này cố ý không dùng ``model.Drag``. Model INFJ có bốn parameter mắt
tự đặt tên và mắt phải được rig theo trục X đối xứng, nên Cubism drag mặc định
vừa không hiểu đủ mapping vừa dễ kéo hai con ngươi vào nhau.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import Live2DBodyConfig
from .gaze import GazeController, GazeSample
from .parameter_profile import INFJ_PARAMETER_PROFILE
from .stage_state import Live2DStageState
from .udp_receiver import Live2DStageReceiver
from .window_bridge import DesktopWindowBridge, WindowGeometry


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
        self._parameter_indices: dict[str, int] = {}
        self._dragging_window = False
        self._drag_origin_cursor_screen = (0.0, 0.0)
        self._drag_origin_window = (0, 0)
        self._runtime_scale = float(config.scale)
        self._bridge = DesktopWindowBridge(godot_pid=config.godot_pid)
        self._gaze = GazeController(
            strength_x=config.eye_strength_x,
            strength_y=config.eye_strength_y,
            right_x_sign=config.eye_right_x_sign,
            inner_eye_ratio=config.eye_inner_ratio,
            head_follow_degrees=config.head_follow_degrees,
            head_follow_left_degrees=config.head_follow_left_degrees,
            head_follow_right_degrees=config.head_follow_right_degrees,
        )
        self._last_geometry: WindowGeometry | None = None
        self._last_speaking = False
        self._mouth_probe_at = -1.0

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
            model.SetScale(self._runtime_scale)
            model.SetOffset(self.config.offset_x, self.config.offset_y)
            model.SetAutoBlinkEnable(True)
            model.SetAutoBreathEnable(True)
            self._parameter_indices = self._read_parameter_indices(model)
            self.available_parameters = set(self._parameter_indices)
            canvas_size = self._safe_model_call(model, "GetCanvasSize")
            canvas_pixel_size = self._safe_model_call(model, "GetCanvasSizePixel")

            self._install_callbacks(glfw, window, model)
            self._report_geometry(glfw, window, force=True)
            if self.config.z_order_sync:
                self._bridge.keep_live2d_below_godot(glfw, window)
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
            self._print_model_profile(model_path)

            last = time.monotonic()
            fps_count = 0
            fps_at = last
            maintenance_at = 0.0
            window_visible = True
            while not glfw.window_should_close(window):
                # UDP control không phát GLFW event, vì vậy poll ngắn rồi tự kiểm tra
                # visibility. Khi ẩn, process vẫn giữ model/GPU context nhưng không vẽ.
                glfw.poll_events()
                if self.receiver.shutdown_requested:
                    glfw.set_window_should_close(window, True)
                    continue

                desired_visible = self.receiver.desired_visible
                if desired_visible != window_visible:
                    if desired_visible:
                        self._show_window(glfw, window)
                        self._report_geometry(glfw, window, force=True)
                        if self.config.z_order_sync:
                            self._bridge.keep_live2d_below_godot(glfw, window)
                        print("[Live2D] renderer resumed (resident process)", flush=True)
                    else:
                        self._dragging_window = False
                        try:
                            glfw.hide_window(window)
                        except Exception:
                            pass
                        print("[Live2D] renderer hidden (resident process)", flush=True)
                    window_visible = desired_visible

                requested_geometry = self.receiver.requested_window_geometry
                if requested_geometry is not None:
                    current_geometry = self._bridge.geometry(glfw, window)
                    target_geometry = WindowGeometry(
                        requested_geometry["x"],
                        requested_geometry["y"],
                        requested_geometry["width"],
                        requested_geometry["height"],
                    )
                    if target_geometry != current_geometry:
                        if (
                            current_geometry.width != target_geometry.width
                            or current_geometry.height != target_geometry.height
                        ):
                            glfw.set_window_size(
                                window,
                                target_geometry.width,
                                target_geometry.height,
                            )
                        glfw.set_window_pos(window, target_geometry.x, target_geometry.y)
                        self._report_geometry(glfw, window, force=True)

                now = time.monotonic()
                dt = min(0.10, max(0.0, now - last))
                last = now
                snapshot = self.state.advance(dt, now=now)
                if snapshot.speaking and not self._last_speaking:
                    self._mouth_probe_at = now + 0.16
                if snapshot.speaking and self._mouth_probe_at > 0.0 and now >= self._mouth_probe_at:
                    print(
                        "[Live2D][Mouth] "
                        f"ratio={snapshot.mouth_open_ratio:.3f} "
                        f"form={float(snapshot.parameters.get('ParamMouthForm', 0.0)):.3f} "
                        f"open={float(snapshot.parameters.get('ParamMouthOpenY', -1.0)):.3f} "
                        f"cue={snapshot.speech_cue}",
                        flush=True,
                    )
                    self._mouth_probe_at = -1.0
                if not snapshot.speaking:
                    self._mouth_probe_at = -1.0
                self._last_speaking = snapshot.speaking
                if not window_visible:
                    # 20 Hz control check, gần như không tốn render CPU/GPU.
                    time.sleep(0.05)
                    continue

                self._update_window_drag(glfw, window)
                geometry = self._bridge.geometry(glfw, window)
                gaze = self._update_gaze(geometry, dt)

                model.Update()
                parameters = dict(snapshot.parameters)
                if "ParamAngleX" in self.available_parameters:
                    parameters["ParamAngleX"] = parameters.get("ParamAngleX", 0.0) + gaze.head_x_degrees
                for parameter_id, value in parameters.items():
                    if parameter_id in self.available_parameters:
                        model.SetParameterValue(
                            parameter_id,
                            INFJ_PARAMETER_PROFILE.sanitize(parameter_id, float(value)),
                        )
                self._apply_gaze(
                    model,
                    gaze,
                    bias_x=snapshot.gaze_bias_x,
                    bias_y=snapshot.gaze_bias_y,
                )
                self._apply_eyelids(
                    model,
                    left_scale=snapshot.eye_open_left * gaze.left_eye_open_scale,
                    right_scale=snapshot.eye_open_right * gaze.right_eye_open_scale,
                )

                if self.config.transparent:
                    live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
                else:
                    live2d.clearBuffer(0.08, 0.08, 0.10, 1.0)
                model.Draw()
                glfw.swap_buffers(window)

                if now >= maintenance_at:
                    self._report_geometry(glfw, window)
                    if self.config.z_order_sync:
                        self._bridge.keep_live2d_below_godot(glfw, window)
                    maintenance_at = now + 0.20

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

    def _update_gaze(self, geometry: WindowGeometry, dt: float) -> GazeSample:
        if not self.config.eye_tracking:
            cursor = None
        else:
            cursor = self._bridge.cursor_screen()
        face = (
            geometry.x + geometry.width * 0.5,
            geometry.y + geometry.height * self.config.face_anchor_y,
        )
        return self._gaze.update(
            cursor_screen=cursor,
            face_screen=face,
            span_x=max(180.0, geometry.width * 0.85),
            span_y=max(180.0, geometry.height * 0.38),
            dt=dt,
        )

    def _apply_gaze(
        self,
        model: Any,
        gaze: GazeSample,
        *,
        bias_x: float = 0.0,
        bias_y: float = 0.0,
    ) -> None:
        # ``bias_x`` dùng trục màn hình chung: âm nhìn trái, dương nhìn phải.
        # Chuyển nó sang hai trục riêng của model, vẫn giữ mắt phía trong có
        # biên nhỏ hơn để idle glance không tạo cảm giác lé.
        screen_bias_x = max(-0.16, min(0.16, float(bias_x)))
        vertical_bias = max(-0.12, min(0.12, float(bias_y)))
        if screen_bias_x >= 0.0:
            left_bias = screen_bias_x
            right_bias = -screen_bias_x * self.config.eye_inner_ratio
        else:
            left_bias = screen_bias_x * self.config.eye_inner_ratio
            right_bias = -screen_bias_x

        eye_values = {
            "eyeballxl": gaze.left_x + left_bias,
            "eyeballxr": gaze.right_x + right_bias,
            "eyebally": gaze.left_y + vertical_bias,
            "eyeballyr": gaze.right_y + vertical_bias,
        }
        if "ParamEyeBallX" in self.available_parameters:
            eye_values["ParamEyeBallX"] = gaze.left_x
        if "ParamEyeBallY" in self.available_parameters:
            eye_values["ParamEyeBallY"] = gaze.left_y
        for parameter_id, value in eye_values.items():
            if parameter_id in self.available_parameters:
                model.SetParameterValue(
                    parameter_id,
                    INFJ_PARAMETER_PROFILE.sanitize(parameter_id, float(value)),
                )

    def _apply_eyelids(self, model: Any, *, left_scale: float, right_scale: float) -> None:
        """Giữ auto-blink nhưng giới hạn độ mở mí theo mood và hướng nhìn."""
        self._scale_eye_parameter(model, "ParamEyeLOpen", left_scale)
        self._scale_eye_parameter(model, "ParamEyeROpen", right_scale)

    def _scale_eye_parameter(self, model: Any, parameter_id: str, scale: float) -> None:
        """Nhân mood/speech scale với giá trị mí *của frame hiện tại*.

        ``GetParameter()`` có thể trả một object snapshot. Cache object đó từ lúc
        load model rồi đọc ``.value`` ở các frame sau sẽ ghi đè auto-blink bằng
        giá trị cũ (thường là 1.0), khiến nhân vật mở mắt như đang trực ca đêm.
        Vì vậy chỉ cache index và đọc lại bằng ``GetParameterValue(index)`` sau
        ``model.Update()``.
        """

        index = self._parameter_indices.get(parameter_id)
        if index is None:
            return
        try:
            current = float(model.GetParameterValue(index))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            # Fallback cho build live2d-py cũ: lấy object mới ở chính frame này,
            # tuyệt đối không dùng object đã cache từ lúc load model.
            try:
                current = float(getattr(model.GetParameter(index), "value"))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                return
        normalized_scale = max(0.0, min(1.0, float(scale)))
        target = INFJ_PARAMETER_PROFILE.clamp_eye_open(current * normalized_scale)
        model.SetParameterValue(parameter_id, target)

    def _report_geometry(self, glfw: Any, window: Any, *, force: bool = False) -> None:
        geometry = self._bridge.geometry(glfw, window)
        if not force and geometry == self._last_geometry:
            return
        self._last_geometry = geometry
        self.receiver.send_window_geometry(
            screen_x=geometry.x,
            screen_y=geometry.y,
            width=geometry.width,
            height=geometry.height,
        )

    def _print_model_profile(self, model_path: Path) -> None:
        try:
            payload = json.loads(model_path.read_text(encoding="utf-8-sig"))
        except Exception:
            payload = {}
        refs = payload.get("FileReferences", {}) if isinstance(payload, dict) else {}
        expressions = refs.get("Expressions", []) if isinstance(refs, dict) else []
        motions = refs.get("Motions", {}) if isinstance(refs, dict) else {}
        custom_eye = all(
            item in self.available_parameters
            for item in ("eyeballxl", "eyeballxr", "eyebally", "eyeballyr")
        )
        print(
            "[Live2D] Model profile: "
            f"parameters={len(self.available_parameters)} "
            f"head={'X/Z' if {'ParamAngleX', 'ParamAngleZ'} <= self.available_parameters else 'partial'} "
            f"eyes={'custom mirrored pair' if custom_eye else 'standard/partial'} "
            f"mouth={'yes' if 'ParamMouthOpenY' in self.available_parameters else 'no'} "
            f"physics={'yes' if isinstance(refs, dict) and bool(refs.get('Physics')) else 'no'} "
            f"expressions={len(expressions) if isinstance(expressions, list) else 0} "
            f"motion_groups={len(motions) if isinstance(motions, dict) else 0}",
            flush=True,
        )

    @staticmethod
    def _read_parameter_indices(model: Any) -> dict[str, int]:
        indices: dict[str, int] = {}
        try:
            for index in range(int(model.GetParameterCount())):
                parameter = model.GetParameter(index)
                parameter_id = str(getattr(parameter, "id", "") or "")
                if parameter_id:
                    indices[parameter_id] = index
        except Exception as exc:
            print(f"[Live2D][WARN] Không đọc được parameter list: {exc}", flush=True)
        return indices

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
        # Không focus cưỡng bức. Việc giật focus vừa khó chịu vừa đẩy Live2D lên
        # trên bubble/context menu Godot trong topmost band.

    def _update_window_drag(self, glfw: Any, window: Any) -> None:
        if not self._dragging_window:
            return
        cursor = self._bridge.cursor_screen()
        if cursor is None:
            return
        dx = cursor[0] - self._drag_origin_cursor_screen[0]
        dy = cursor[1] - self._drag_origin_cursor_screen[1]
        glfw.set_window_pos(
            window,
            int(self._drag_origin_window[0] + dx),
            int(self._drag_origin_window[1] + dy),
        )

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
                self._runtime_scale = min(3.0, self._runtime_scale + 0.1)
                model.SetScale(self._runtime_scale)
            elif key in (glfw.KEY_MINUS, glfw.KEY_KP_SUBTRACT):
                self._runtime_scale = max(0.2, self._runtime_scale - 0.1)
                model.SetScale(self._runtime_scale)

        def on_mouse_button(_window: Any, button: int, action: int, _mods: int) -> None:
            if button == glfw.MOUSE_BUTTON_RIGHT and action == glfw.PRESS:
                cursor = self._bridge.cursor_screen()
                if cursor is None:
                    cursor_x, cursor_y = glfw.get_cursor_pos(window)
                    window_x, window_y = glfw.get_window_pos(window)
                    cursor = (window_x + cursor_x, window_y + cursor_y)
                self.receiver.send_context_menu_request(
                    screen_x=int(cursor[0]),
                    screen_y=int(cursor[1]),
                )
                return

            if button != glfw.MOUSE_BUTTON_MIDDLE:
                return
            if action == glfw.PRESS:
                cursor = self._bridge.cursor_screen()
                if cursor is None:
                    local_x, local_y = glfw.get_cursor_pos(window)
                    win_x, win_y = glfw.get_window_pos(window)
                    cursor = (win_x + local_x, win_y + local_y)
                self._dragging_window = True
                self._drag_origin_cursor_screen = cursor
                self._drag_origin_window = glfw.get_window_pos(window)
            elif action == glfw.RELEASE:
                self._dragging_window = False

        glfw.set_framebuffer_size_callback(window, on_framebuffer_size)
        glfw.set_key_callback(window, on_key)
        glfw.set_mouse_button_callback(window, on_mouse_button)


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
