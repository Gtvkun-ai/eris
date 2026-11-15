# -*- coding: utf-8 -*-
"""Background Vision Perception Worker for Eris.

Runs in parallel with the main cognition loop:
- Detects screen and window changes (using change detector & active window provider).
- When a meaningful change occurs, captures the screen and sends it asynchronously to
  the Gemini Vision Docker API (http://localhost:8000/api/vision/decompose).
- Stores the latest VisionPerceptionSnapshot in a thread-safe singleton slot.
- Non-blocking: RootAgent and SurfaceWriter read from the slot in 0ms without waiting.
- Fail-soft: If Docker is down or network fails, logs quietly and continues without affecting chat.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from PIL import Image
from native.screen_capture import capture_screen
from runtime.privacy.environment_policy import EnvironmentPolicy, PrivacyScope

from .active_window_provider import ActiveWindowProvider
from .change_detector import ScreenChangeDetector
from .evidence_models import ActiveWindowInfo

try:
    from app_logging import get_logger
    _LOG = get_logger("Vision")
except Exception:
    _LOG = logging.getLogger("Eris.Vision")


def stitch_two_frames(
    frame1: Image.Image,
    frame2: Image.Image,
    time_gap_sec: float = 5.0,
    *,
    target_dim: tuple[int, int] = (640, 360),
    banner_height: int = 28,
) -> Image.Image:
    """Ghép 2 khung hình cạnh nhau (trái: frame 1, phải: frame 2) kèm nhãn thời gian.

    Giúp Gemini Vision nắm bắt ngay sự biến chuyển thời gian (temporal motion) giữa 2 mốc
    thay vì chỉ nhìn một khung hình tĩnh đơn lẻ.
    """
    tw, th = target_dim
    f1 = frame1.resize((tw, th), Image.Resampling.BILINEAR)
    f2 = frame2.resize((tw, th), Image.Resampling.BILINEAR)

    total_w = tw * 2
    total_h = th + banner_height
    composite = Image.new("RGB", (total_w, total_h), (24, 24, 28))
    composite.paste(f1, (0, banner_height))
    composite.paste(f2, (tw, banner_height))

    try:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(composite)
        gap_val = max(1, int(round(time_gap_sec))) if time_gap_sec > 0 else 0
        gap_str = f"~{gap_val}s truoc" if gap_val > 0 else "Qua khu"
        draw.text((12, 6), f"KHUNG HINH 1 ({gap_str})", fill=(255, 230, 100))
        draw.text((tw + 12, 6), "KHUNG HINH 2 (HIEN TAI - MOI NHAT)", fill=(100, 255, 120))
    except Exception:
        pass

    return composite


@dataclass(frozen=True, slots=True)
class VisionPerceptionSnapshot:
    """Ảnh chụp nhận thức thị giác nền từ Gemini Web."""

    summary: str = ""
    motion: str = ""
    recipe_or_menu: str = ""
    ingredients_and_tools: tuple[str, ...] = ()
    topic: str = ""
    inferred_story: str = ""
    mood_and_intent: str = ""
    key_elements: tuple[dict[str, str], ...] = ()
    detected_text: tuple[str, ...] = ()
    text_context: str = ""
    tags: tuple[str, ...] = ()
    window_title: str = ""
    process_name: str = ""
    captured_at: float = field(default_factory=time.time)
    raw_json: dict[str, Any] = field(default_factory=dict)

    def is_stale(self, max_age_seconds: float = 600.0) -> bool:
        """Kiểm tra xem snapshot thị giác có quá cũ không."""
        return (time.time() - self.captured_at) > max_age_seconds

    def prompt_context(self) -> str:
        """Định dạng context ngắn gọn, giàu ý nghĩa để chèn vào Grounding của Root/Writer."""
        if not self.summary and not self.inferred_story and not self.motion and not self.ingredients_and_tools:
            return ""

        age_sec = int(time.time() - self.captured_at)
        time_hint = f"vừa cập nhật {age_sec}s trước" if age_sec < 60 else f"cách đây {age_sec // 60} phút"

        lines = [
            f"[THỊ GIÁC MÀN HÌNH ({time_hint})]",
            f"- Cửa sổ: {self.window_title or '<không xác định>'}",
            f"- Trạng thái: {self.summary}",
        ]
        if self.motion:
            lines.append(f"- Biến chuyển (2 khung hình ~5s qua): {self.motion}")
        if self.ingredients_and_tools:
            clean_items = [str(x).strip() for x in self.ingredients_and_tools if str(x).strip()]
            if clean_items:
                lines.append(f"- Nguyên liệu & Đồ vật thấy trên màn hình: {', '.join(clean_items)}")
        if self.recipe_or_menu:
            lines.append(f"- Thực đơn/Nhiệm vụ: {self.recipe_or_menu}")
        if self.inferred_story and self.inferred_story != self.summary:
            lines.append(f"- Diễn biến: {self.inferred_story}")
        if self.detected_text:
            clean_text = [str(t).strip() for t in self.detected_text[:6] if str(t).strip()]
            if clean_text:
                lines.append(f"- Chữ/Nút trên màn hình: {', '.join(clean_text)}")
        if self.key_elements:
            elem_strs = [
                f"{e.get('name')}: {e.get('significance')}"
                for e in self.key_elements[:3]
                if isinstance(e, Mapping) and e.get("name")
            ]
            if elem_strs:
                lines.append(f"- Chi tiết: {' | '.join(elem_strs)}")
        if age_sec >= 25:
            lines.append(f"(Lưu ý: Ảnh chụp {age_sec}s trước, diễn biến game có thể đã bước sang pha mới, tránh khẳng định người dùng vẫn đứng yên tại chỗ).")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "motion": self.motion,
            "recipe_or_menu": self.recipe_or_menu,
            "ingredients_and_tools": list(self.ingredients_and_tools),
            "topic": self.topic,
            "inferred_story": self.inferred_story,
            "mood_and_intent": self.mood_and_intent,
            "key_elements": list(self.key_elements),
            "detected_text": list(self.detected_text),
            "text_context": self.text_context,
            "tags": list(self.tags),
            "window_title": self.window_title,
            "process_name": self.process_name,
            "captured_at": self.captured_at,
            "age_seconds": round(time.time() - self.captured_at, 1),
        }


class VisionPerceptionService:
    """Thread-safe singleton lưu trữ snapshot thị giác nền."""

    def __init__(self) -> None:
        self._latest_snapshot: VisionPerceptionSnapshot | None = None
        self._lock = threading.RLock()
        self._listeners: list[Callable[[VisionPerceptionSnapshot], None]] = []

    def register_listener(self, callback: Callable[[VisionPerceptionSnapshot], None]) -> None:
        """Đăng ký listener nhận thông báo khi có snapshot thị giác mới từ worker."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[VisionPerceptionSnapshot], None]) -> None:
        """Hủy đăng ký listener."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def get_latest_snapshot(self) -> VisionPerceptionSnapshot | None:
        """Đọc tức thì (0ms) từ RAM mà không bao giờ block luồng chat."""
        with self._lock:
            return self._latest_snapshot

    def publish_snapshot(self, snapshot: VisionPerceptionSnapshot) -> None:
        """Cập nhật nguyên tử snapshot mới từ worker chạy ngầm và thông báo cho listeners."""
        with self._lock:
            self._latest_snapshot = snapshot
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(snapshot)
            except Exception as exc:
                _LOG.debug("[VisionService] listener callback exception: %s", exc)


_GLOBAL_SERVICE: VisionPerceptionService | None = None
_GLOBAL_SERVICE_LOCK = threading.Lock()


def ensure_vision_perception_service() -> VisionPerceptionService:
    """Truy xuất singleton service của Vision Perception."""
    global _GLOBAL_SERVICE
    if _GLOBAL_SERVICE is None:
        with _GLOBAL_SERVICE_LOCK:
            if _GLOBAL_SERVICE is None:
                _GLOBAL_SERVICE = VisionPerceptionService()
    return _GLOBAL_SERVICE


class VisionPerceptionWorker:
    """Worker chạy ngầm thăm dò màn hình và gửi phân tích lên Gemini Vision Docker.

    Hỗ trợ cơ chế 2-frame temporal cadence:
    - Thu thập khung hình mỗi ~2.5s vào hàng đợi trượt (sliding window).
    - Khi gửi Docker, ghép Khung 1 (~5s trước) và Khung 2 (hiện tại) cạnh nhau.
    - Giúp Gemini Vision nhận diện chính xác biến chuyển động (motion), thao tác vừa làm,
      và trạng thái thực đơn/công thức/nhiệm vụ mà không bao giờ bị ảo giác lặp lại kịch bản cũ.
    """

    def __init__(
        self,
        service: VisionPerceptionService | None = None,
        *,
        store: Any = None,
        api_url: str | None = None,
        poll_interval: float = 2.5,
        cooldown: float = 5.0,
        diff_threshold: float = 0.03,
        logger: Any = None,
    ) -> None:
        self.service = service or ensure_vision_perception_service()
        self.screen_evidence_store = store
        self.logger = logger
        self.api_url = api_url or os.getenv("ERIS_VISION_API_URL", "http://127.0.0.1:8000/api/vision/decompose")
        self.poll_interval = max(1.0, float(os.getenv("ERIS_VISION_POLL_SEC", str(poll_interval))))
        self.cooldown = max(2.0, float(os.getenv("ERIS_VISION_COOLDOWN_SEC", str(cooldown))))
        self.diff_threshold = max(0.01, float(os.getenv("ERIS_VISION_DIFF_THRESHOLD", str(diff_threshold))))

        self._window_provider = ActiveWindowProvider()
        self._change_detector = ScreenChangeDetector(threshold=self.diff_threshold)
        self._frame_buffer: list[tuple[Image.Image, float]] = []
        self._last_sent_at: float = 0.0
        self._last_window_title: str = ""
        self._last_game_seen_at: float = 0.0
        self._last_active_time: float = time.time()
        self._is_sending: bool = False
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def trigger_now(self, force: bool = False) -> None:
        """Đánh thức worker lập tức để thăm dò màn hình mà không chờ hết chu kỳ ngủ."""
        if force:
            self._last_sent_at = 0.0
            self._last_window_title = ""
        self._wake_event.set()

    def start(self) -> None:
        """Khởi động worker chạy ngầm trong thread daemon độc lập."""
        enabled = os.getenv("ERIS_VISION_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
        if not enabled:
            _LOG.info("[Vision] Worker disabled by ERIS_VISION_ENABLED=0")
            return

        if self.is_alive:
            return

        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ErisVisionPerceptionWorker",
            daemon=True,
        )
        self._thread.start()
        _LOG.info("[Vision] Worker started (poll=%.1fs, cooldown=%.1fs, api=%s)",
                  self.poll_interval, self.cooldown, self.api_url)

    def stop(self) -> None:
        """Dừng worker an toàn."""
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

    def _is_gaming(self, window_info: ActiveWindowInfo) -> bool:
        """Nhận diện xem người dùng có đang trong phiên chơi game / livestream hay không."""
        title = window_info.title or ""
        proc = window_info.process_name or ""
        now = time.time()

        try:
            from .game_knowledge import detect_game_from_window, is_gaming_window
            if is_gaming_window(title, proc) or detect_game_from_window(title, proc) is not None:
                self._last_game_seen_at = now
                return True
        except Exception:
            pass

        # Duy trì gaming session 180s nếu người dùng tạm chuyển qua overlay/desktop/trình duyệt
        if (now - self._last_game_seen_at) < 180.0:
            low_title = title.lower()
            low_proc = proc.lower()
            if not title or any(k in low_title or k in low_proc for k in ("eris", "desktop", "chrome", "firefox", "msedge", "không xác định")):
                return True

        return False

    def _capture_screen(self, window: ActiveWindowInfo) -> Image.Image | None:
        privacy = EnvironmentPolicy().scope_for(process_name=window.process_name, window_title=window.title)
        if privacy.scope < PrivacyScope.SEMANTIC:
            return None
        use_fullscreen = os.getenv("ERIS_VISION_FULLSCREEN", "1").strip().lower() in ("1", "true", "yes", "on")
        try:
            if use_fullscreen:
                return capture_screen(None)
            if not window.bounds or min(window.bounds[2:]) <= 50:
                return capture_screen(None)
            return capture_screen(window.bounds)
        except Exception as exc:
            _LOG.debug("[Vision] capture failed: %s", exc)
            return None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                _LOG.debug("[Vision] Error in worker tick: %s", exc)

            self._wake_event.wait(self.poll_interval)
            self._wake_event.clear()

    def _tick(self) -> None:
        now = time.time()
        window_info = self._window_provider.get()
        title = window_info.title or ""
        window_changed = bool(self._last_window_title and title != self._last_window_title)

        # Chụp màn hình để kiểm tra thay đổi pixel
        image = self._capture_screen(window_info)
        if image is None:
            return

        # Lưu thumbnail nhẹ vào sliding window buffer (640x360)
        thumb = image.resize((640, 360), Image.Resampling.BILINEAR)
        if window_changed:
            self._frame_buffer.clear()
        self._frame_buffer.append((thumb, now))
        # Giữ các frame trong vòng 15s gần nhất (tối đa 12 frames)
        self._frame_buffer = [(img, ts) for img, ts in self._frame_buffer if (now - ts) <= 15.0][-12:]

        is_game = self._is_gaming(window_info)

        if self._is_sending:
            return

        # Kiểm tra độ biến đổi (change detector)
        change = self._change_detector.inspect(image, key=title)

        # Quyết định có gửi Docker hay không:
        # 1. Đổi cửa sổ -> gửi ngay (sau cooldown tối thiểu 2.0s)
        # 2. Đang chơi game:
        #    - Fast-track: Nếu có biến đổi pixel rõ rệt (change.changed - ví dụ từ menu vào bếp), gửi ngay sau 3.0s!
        #    - Định kỳ: gửi mỗi 8-10s để duy trì nhịp quan sát liên tục.
        # 3. Không chơi game (đọc tài liệu, desktop):
        #    - Chỉ gửi khi có thay đổi pixel (change.changed) và hết cooldown.
        should_send = False
        time_since_last = now - self._last_sent_at
        if window_changed:
            should_send = time_since_last >= 2.0
        elif is_game:
            if change.changed and time_since_last >= 3.0:
                should_send = True
            elif time_since_last >= 8.0:
                should_send = True
        else:
            if change.changed and time_since_last >= self.cooldown:
                should_send = True

        if not should_send:
            return

        # Cập nhật mốc
        self._last_window_title = title

        # Chọn frame 1 (~5s trước) từ buffer
        candidates = [f for f in self._frame_buffer if 2.5 <= (now - f[1]) <= 12.0]
        if candidates:
            frame1, f1_time = min(candidates, key=lambda f: abs((now - f[1]) - 5.0))
            time_gap = now - f1_time
        elif len(self._frame_buffer) > 1:
            frame1, f1_time = self._frame_buffer[0]
            time_gap = now - f1_time
        else:
            frame1, f1_time = thumb, now
            time_gap = 0.0

        # Ghép 2 khung hình: Trái (frame 1 ~5s trước), Phải (hiện tại)
        composite = stitch_two_frames(frame1, thumb, time_gap_sec=time_gap)

        # Nén JPEG nhẹ (khoảng 60-80KB)
        buffer = self._compress_image_for_upload(composite)
        if not buffer:
            return

        _LOG.info("[Vision] 2-frame combo ready: gap=%.1fs, window='%s' (game=%s, bytes=%d). Sending to Gemini...",
                  time_gap, title[:30], is_game, len(buffer))

        # Gửi sang Docker API (chạy ngầm trong daemon thread)
        self._is_sending = True
        self._last_sent_at = time.time()
        try:
            self._send_to_gemini_docker(buffer, window_info=window_info)
        finally:
            self._is_sending = False

    def decompose_data_uri(self, data_uri: str) -> VisionPerceptionSnapshot | None:
        """Bóc tách tức thời một frame data URI (dành cho lượt hỏi trực tiếp của người dùng)."""
        if not data_uri:
            return None
        try:
            import base64
            b64_data = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
            raw_bytes = base64.b64decode(b64_data)

            img = Image.open(io.BytesIO(raw_bytes))
            buf = self._compress_image_for_upload(img)
            if not buf:
                buf = raw_bytes

            window_info = self._window_provider.get()
            self._is_sending = True
            self._last_sent_at = time.time()
            try:
                _LOG.info("[Vision] Decomposing on-demand data URI from user chat (bytes=%d)...", len(buf))
                return self._send_to_gemini_docker(buf, window_info=window_info)
            finally:
                self._is_sending = False
        except Exception as exc:
            _LOG.warning("[Vision] decompose_data_uri error: %s", exc)
            return None

    def _compress_image_for_upload(self, image: Image.Image) -> bytes | None:
        try:
            img = image
            max_dim = 1280
            if max(img.width, img.height) > max_dim:
                scale = max_dim / float(max(img.width, img.height))
                new_w = max(1, int(img.width * scale))
                new_h = max(1, int(img.height * scale))
                img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

            out = io.BytesIO()
            img.save(out, format="JPEG", quality=82, optimize=True)
            return out.getvalue()
        except Exception as exc:
            _LOG.debug("[Vision] Image compression error: %s", exc)
            return None

    def _send_to_gemini_docker(self, image_bytes: bytes, window_info: ActiveWindowInfo) -> None:
        import re
        import requests

        try:
            files = {"file": ("screenshot.jpg", image_bytes, "image/jpeg")}
            prompt = os.getenv("ERIS_VISION_PROMPT", "").strip() or (
                "Bạn là trợ lý thị giác thời gian thực (Real-time Live Companion Vision) của Eris khi đồng hành cùng người dùng (đặc biệt khi đang chơi game / livestream).\n"
                "Ảnh đầu vào gồm 2 khung hình ghép cạnh nhau:\n"
                "- NỬA TRÁI (KHUNG HÌNH 1): Ảnh chụp cách đây khoảng 5 giây.\n"
                "- NỬA PHẢI (KHUNG HÌNH 2): Ảnh chụp hiện tại mới nhất.\n\n"
                "Nhiệm vụ của bạn:\n"
                "1. Biến chuyển & Thao tác (motion):\n"
                "   - So sánh Nửa Trái và Nửa Phải: Người chơi vừa thực hiện thao tác gì (kéo thả chuột, đưa vật gì vào nồi/chảo, mở ngăn tủ nào, di chuyển con trỏ đi đâu, hay màn hình giữ nguyên)?\n"
                "2. Trạng thái hiện tại (summary & inferred_story):\n"
                "   - Tên game / ứng dụng và màn hình hiện tại (ở Khung Hình 2).\n"
                "   - Người chơi / đầu bếp đang làm việc gì cụ thể?\n"
                "3. Nguyên liệu, Đồ vật & Dụng cụ (ingredients_and_tools):\n"
                "   - Liệt kê CỤ THỂ tất cả nguyên liệu nấu ăn nhìn thấy trên kệ, tủ, bàn bếp (ví dụ: mì ống pasta, hộp sữa MÜLK, bánh mì, vỉ trứng, túi khoai, hũ sốt đỏ trong tủ, hũ gia vị BiG...).\n"
                "   - Liệt kê các dụng cụ nấu nướng chính (ví dụ: nồi đen trên bếp điện, máy nướng bánh toaster, dao trên giá nam châm, bồn rửa chén, ruy-băng icon Mũ Đầu Bếp mở sổ công thức ở góc trên bên trái...).\n"
                "4. Thực đơn / Mục tiêu / Công thức (recipe_or_menu):\n"
                "   - Có nút hoặc biểu tượng mở sổ công thức (như icon Mũ Đầu Bếp) hay bảng order/timer nào không?\n"
                "   - Nếu là game kéo thả tự do / sandbox: ghi rõ 'Chế độ tự do, có thể click icon Mũ Đầu Bếp góc trên bên trái để mở công thức hoặc tự do kéo thả nguyên liệu vào nồi'.\n"
                "5. Chi tiết & Chữ: Các chữ/nhãn vẽ tay (như MÜLK, SHANE, BiG, Coming Soon...), nhãn dán, nút bấm.\n\n"
                "Trả về kết quả dưới dạng JSON:\n"
                "{\n"
                '  "summary": "1-2 câu tóm tắt cực kỳ trực diện về những gì đang diễn ra ở Khung Hình 2 (hiện tại).",\n'
                '  "motion": "Mô tả ngắn gọn biến động giữa Khung Hình 1 và Khung Hình 2 (thao tác chuột, kéo thả, di chuyển...).",\n'
                '  "recipe_or_menu": "Trạng thái thực đơn / công thức (hoặc gợi ý mở sổ công thức).",\n'
                '  "ingredients_and_tools": ["mì ống", "sữa MÜLK", "bánh mì", "vỉ trứng", "túi khoai", "hũ sốt đỏ", "nồi trên bếp điện", "máy nướng bánh mì", "icon Mũ Đầu Bếp"],\n'
                '  "inference": {\n'
                '    "topic": "gaming / cooking...",\n'
                '    "inferred_story": "Mô tả ngắn gọn người dùng đang làm gì trong game/ứng dụng",\n'
                '    "mood_and_intent": "Không khí/tình huống (thư giãn, tò mò, nghịch ngợm...)"\n'
                "  },\n"
                '  "key_elements": [\n'
                '    {"name": "tên chi tiết/vật thể/nút", "significance": "ý nghĩa ngắn gọn"}\n'
                "  ],\n"
                '  "ocr_and_text": {\n'
                '    "detected_text": ["các chữ/nút/nhãn chính"],\n'
                '    "text_context": "ngắn gọn"\n'
                "  },\n"
                '  "tags": ["gaming", "cooking", "tên_game_hoặc_app"]\n'
                "}\n\n"
                "LƯU Ý QUAN TRỌNG: Viết bằng tiếng Việt tự nhiên, trực diện và súc tích. Tuyệt đối KHÔNG viết văn miêu tả học thuật dài dòng và KHÔNG dùng các chú thích như [cite: 1]."
            )
            data = {"model": "gemini-flash", "thinking": "fast", "prompt": prompt}
            res = requests.post(self.api_url, files=files, data=data, timeout=35.0)

            if res.status_code == 200:
                payload = res.json()
                raw_data = payload.get("data", {})
                if not isinstance(raw_data, Mapping) or not raw_data:
                    raw_text = str(payload.get("raw_output", "") or "").strip()
                    if raw_text:
                        try:
                            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                            if match:
                                parsed = json.loads(match.group(0))
                                if isinstance(parsed, Mapping):
                                    raw_data = parsed
                        except Exception:
                            pass
                        if not raw_data:
                            raw_data = {"summary": raw_text[:300]}

                if isinstance(raw_data, Mapping):
                    inference = raw_data.get("inference", {}) or {}
                    ocr_data = raw_data.get("ocr_and_text", {}) or {}
                    elements = raw_data.get("key_elements", []) or []
                    items_raw = raw_data.get("ingredients_and_tools", []) or []
                    items_tuple = tuple(str(x).strip() for x in items_raw if str(x).strip()) if isinstance(items_raw, list) else ()

                    raw_sum = str(raw_data.get("summary", "") or "").strip()
                    raw_motion = str(raw_data.get("motion", "") or "").strip()
                    raw_recipe = str(raw_data.get("recipe_or_menu", "") or "").strip()
                    raw_story = str(inference.get("inferred_story", "") or "").strip()
                    clean_sum = re.sub(r'\[cite:\s*[^\]]+\]', '', raw_sum).strip()
                    clean_motion = re.sub(r'\[cite:\s*[^\]]+\]', '', raw_motion).strip()
                    clean_recipe = re.sub(r'\[cite:\s*[^\]]+\]', '', raw_recipe).strip()
                    clean_story = re.sub(r'\[cite:\s*[^\]]+\]', '', raw_story).strip()

                    snapshot = VisionPerceptionSnapshot(
                        summary=clean_sum,
                        motion=clean_motion,
                        recipe_or_menu=clean_recipe,
                        ingredients_and_tools=items_tuple,
                        topic=str(inference.get("topic", "") or "").strip(),
                        inferred_story=clean_story,
                        mood_and_intent=str(inference.get("mood_and_intent", "") or "").strip(),
                        key_elements=tuple(elements if isinstance(elements, list) else ()),
                        detected_text=tuple(ocr_data.get("detected_text", []) or ()),
                        text_context=str(ocr_data.get("text_context", "") or "").strip(),
                        tags=tuple(raw_data.get("tags", []) or ()),
                        window_title=window_info.title,
                        process_name=window_info.process_name,
                        captured_at=time.time(),
                        raw_json=dict(raw_data),
                    )

                    self.service.publish_snapshot(snapshot)
                    self._last_sent_at = time.time()
                    _LOG.info("[Vision] Decomposed successfully: %s | motion: %s | items=%d",
                              snapshot.summary[:50], snapshot.motion[:50], len(snapshot.ingredients_and_tools))

                    store = getattr(self, "screen_evidence_store", None)
                    if store is not None and snapshot.detected_text:
                        try:
                            from .evidence_models import ScreenTextBlock, ScreenTextSnapshot
                            blocks = tuple(
                                ScreenTextBlock(
                                    block_id=f"vp_{i}_{int(snapshot.captured_at)}",
                                    text=str(t).strip(),
                                    source="vision_perception",
                                    confidence=0.88,
                                    window_title=str(snapshot.window_title or ""),
                                    captured_at=snapshot.captured_at,
                                )
                                for i, t in enumerate(snapshot.detected_text)
                                if str(t).strip()
                            )
                            if blocks:
                                store.publish(ScreenTextSnapshot(
                                    blocks=blocks,
                                    window=window_info,
                                    captured_at=snapshot.captured_at,
                                ))
                        except Exception as store_exc:
                            _LOG.debug("[Vision] Error updating screen_evidence_store: %s", store_exc)

                    return snapshot
            else:
                _LOG.debug("[Vision] Docker responded %s: %s", res.status_code, res.text[:120])
        except requests.exceptions.ConnectionError:
            # Docker chưa bật hoặc đang tắt: fail-soft, yên lặng bỏ qua
            _LOG.debug("[Vision] Docker not reachable at %s. Waiting...", self.api_url)
            self._last_sent_at = time.time() + 15.0  # Backoff tạm thời
        except requests.exceptions.Timeout:
            _LOG.warning("[Vision] Docker upstream timeout (>35s) at %s", self.api_url)
            self._last_sent_at = time.time() + 5.0
        except Exception as exc:
            _LOG.warning("[Vision] Failed to decompose: %s", exc)

        return None


__all__ = [
    "VisionPerceptionSnapshot",
    "VisionPerceptionService",
    "VisionPerceptionWorker",
    "ensure_vision_perception_service",
    "stitch_two_frames",
]
