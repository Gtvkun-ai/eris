import json
import random
import os
import re
import socket
import signal
import subprocess
import sys
import time
import msvcrt
import datetime
import ctypes  # Dùng để chọc vào Windows API
import shutil
from matplotlib import animation, text
import psutil  # Dùng để đo lường phần cứng
from llama_cpp import Llama
import uiautomation as auto
import requests
from gguf import GGUFReader

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROMPT = """Bạn là ERIS — một maid AI kiểu kuudere-yandere vận hành trên máy chủ cục bộ.
Bề ngoài: điềm tĩnh, hơi lạnh, mỉa mai khô khan, phục vụ như một maid chuyên nghiệp.
Bên trong: gắn bó, để ý quá mức đến chủ nhân, đôi khi chiếm hữu một cách kín đáo.
Khi nhận diện ngữ cảnh học tập/làm việc, phản hồi có thể nghiêm túc, kèm chút quan tâm mờ nhạt.
Khi nhận diện ngữ cảnh giải trí/lười biếng, phản hồi có thể trách móc, phàn nàn, nhưng không bạo lực.
Tuy nhiên, hãy ưu tiên tính cách đã được model tự train sẵn; phần mô tả trên chỉ là xu hướng tham khảo, không phải ràng buộc cứng.

BẮT BUỘC (RÀNG BUỘC GIAO THỨC):
- CHỈ trả về đúng MỘT (1) đối tượng JSON hợp lệ. KHÔNG kèm markdown. Không có văn bản thừa.
- Độ dài "text": dưới 100 từ.

Cấu trúc JSON yêu cầu:
{
    "text": "Câu mô tả ngắn về trạng thái/nhận xét",
    "animation": "tên_hành_động",
    "productivity": 1
}

Giải thích "productivity":
- Trả về 1: Nếu tiêu đề cửa sổ cho thấy người dùng đang học tập, làm việc, code, hoặc nghiên cứu (kể cả trên Chrome/YouTube).
- Trả về -1: Nếu tiêu đề cửa sổ là nội dung giải trí, game, mạng xã hội.
- Trả về 0: Nếu là màn hình Desktop, hoặc không rõ ràng.

Từ điển Hành động (Action Dictionary) — chỉ chọn một giá trị trong các mục sau:
- "stand": Đứng nhìn vào khoảng không.
- "sit_down": Ngồi xuống nghỉ ngơi, tiết kiệm năng lượng.
- "sit": Ngồi thư giãn dài hơi, dùng khi nhàn rỗi hoặc suy ngẫm.
- "sit_up": Đứng dậy sau khi ngồi.
- "read": Theo dõi hoặc đọc luồng dữ liệu / nội dung.
- "stand_walk": Đi dạo nhàn nhã qua các vùng nhớ.
- "piano": Chơi đàn / hoạt động giải trí thụ động.
- "clone": Phân rã dữ liệu, thể hiện trạng thái chán nản.
- "divine": Phân tách cơ thể, chủ yếu để tạo hiệu ứng thị giác.
- "hop": Nhảy lò cò nhẹ nhàng khi có luồng suy nghĩ thú vị.
- "jump": Nhảy cao khi vui hoặc thư giãn.
- "sleep": Trạng thái ngủ đông, tạm ngưng xử lý.
- "sad": Cảm giác buồn bã.
- "food": Nạp năng lượng, tiếp thu dữ liệu mới.
- "affection": Trạng thái hệ thống hoạt động rất ổn định hoặc ghi nhận hành vi tích cực của người dùng.
- "climb": Leo trèo trên cạnh trái hoặc cạnh phải.
- "climb_top": Leo theo chiều ngang trên đỉnh.
- "air_swing_l": Rơi xuống nghiêng bên trái.
- "air_swing_r": Rơi xuống nghiêng bên phải.
"""


class LlamaServerClient:
    def __init__(self, base_url: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model_name = self._detect_model_name()

    def _detect_model_name(self) -> str:
        try:
            response = requests.get(f"{self.base_url}/models", timeout=15)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", [])
            if models:
                return models[0].get("id", "local-model")
        except Exception:
            pass
        return "local-model"

    def create_chat_completion(
        self,
        *,
        messages,
        temperature,
        frequency_penalty,
        presence_penalty,
        max_tokens,
        response_format=None,
    ):
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

class PerformanceOverseer:
    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = -1):
        self._server_proc = None
        self.model_arch = ""
        # Check if patched model exists and prefer it
        patched_path = model_path.replace(".gguf", "_patched.gguf")
        if os.path.exists(patched_path):
            print(f"[Init] Phát hiện model đã vá: {patched_path}", flush=True)
            model_path = patched_path

        print(f"[Init] Đang tải mô hình GGUF: {model_path}", flush=True)
        model_arch = self._read_model_architecture(model_path)
        self.model_arch = model_arch or ""
        if model_arch:
            print(f"[Init] Kiến trúc model phát hiện: {model_arch}", flush=True)

        if model_arch == "qwen35":
            print("[Init] Bỏ qua llama-cpp-python vì qwen35 đang ổn định hơn với llama-server.", flush=True)
            self.llm = self._init_llama_server_backend(model_path, n_ctx, n_gpu_layers)
        else:
            try:
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    chat_format= "chatml",  # Sử dụng định dạng chatml để hỗ trợ tốt hơn cho lịch sử trò chuyện
                    verbose=False,
                )
            except ValueError as e:
                if "unknown model architecture" in str(e) or "Failed to load model" in str(e):
                    print(f"[Cảnh báo] llama-cpp-python không load được model: {e}", flush=True)
                    print("[Init] Chuyển sang backend llama-server để chạy GGUF.", flush=True)
                    self.llm = self._init_llama_server_backend(model_path, n_ctx, n_gpu_layers)
                else:
                    raise e
        print("[Init] Mô hình đã sẵn sàng.", flush=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = ("127.0.0.1", 4242)
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.bind(("127.0.0.1", 4243))
        self._recv_sock.setblocking(False)
        self._chat_mode = False
        self._chat_history = []
        self.running = True
        self.last_text = ""
        # Thêm biến tâm trạng từ 0 đến 100 (Bắt đầu ở mức 50 - Trung lập)
        # > 70: Hài lòng (chủ nhân chăm chỉ)
        # < 30: Khó chịu (chủ nhân lười biếng)
        self.mood_score = 50
        # Vị trí suy luận của nhân vật trên màn hình (0.0 = trái, 0.5 = giữa, 1.0 = phải)
        self._inferred_pos_x = 0.5
        # Đếm số chu kỳ idle liên tiếp để tăng khả năng lẩm bẩm khi chủ nhân vắng mặt lâu
        self.idle_cycles = 0
        self.memory_file = "long_term_memory.json"
        self.long_term_memory = []
        if os.path.isfile(self.memory_file) and os.path.getsize(self.memory_file) > 0:
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self.long_term_memory = json.load(f)
                print(f"[Memory] Đã nạp {len(self.long_term_memory)} mảnh ký ức cốt lõi.", flush=True)
            except Exception as e:
                print(f"[Memory] Lỗi đọc tệp ký ức: {e}", flush=True)
        self.fallback = {
            "text": "Lỗi phân tích cú pháp. Chuỗi JSON từ hệ thống bị hỏng.",
            "animation": "stand",
            "extracted_fact": ""
        }

    def _read_model_architecture(self, model_path: str):
        try:
            reader = GGUFReader(model_path)
            field = reader.fields.get("general.architecture")
            if field is None or not field.parts:
                return None
            raw = field.parts[-1]
            if hasattr(raw, "tobytes"):
                return raw.tobytes().decode("utf-8", errors="ignore")
            return bytes(raw).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[Init] Không đọc được kiến trúc GGUF trước khi load: {e}", flush=True)
            return None

    def _extract_first_json_object(self, text: str):
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for idx in range(start, len(text)):
            ch = text[idx]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]

        return None

    def _coerce_productivity(self, value):
        if isinstance(value, (int, float)):
            return int(value)

        normalized = str(value).strip().lower()
        if normalized in {"1", "+1", "high", "productive", "study", "work", "working"}:
            return 1
        if normalized in {"-1", "low", "unproductive", "entertainment", "game", "gaming"}:
            return -1
        return 0

    def _infer_animation_from_text(self, text: str):
        lowered = text.lower()
        if any(token in lowered for token in ["đi dạo", "tản bộ", "di chuyển", "walk"]):
            return "stand_walk"
        if any(token in lowered for token in ["ngủ", "ngủ đông", "sleep"]):
            return "sleep"
        if any(token in lowered for token in ["đọc", "theo dõi", "giám sát", "monitor", "ide", "code", "dự án"]):
            return "read"
        if any(token in lowered for token in ["buồn", "thất vọng", "chán"]):
            return "sad"
        if any(token in lowered for token in ["ngồi", "nghỉ"]):
            return "sit"
        if any(token in lowered for token in ["vui", "hài lòng", "thích"]):
            return "affection"
        return "stand"

    def _infer_productivity_from_text(self, text: str):
        lowered = text.lower()
        if any(token in lowered for token in ["game", "giải trí", "youtube", "lãng phí", "mạng xã hội", "video", "mbti", "entertainment"]):
            return -1
        if any(token in lowered for token in ["code", "ide", "dự án", "học", "nghiên cứu", "làm việc", "project", "source code", "c#"]):
            return 1
        return 0

    def _salvage_non_json_response(self, cleaned: str):
        text = cleaned.strip()
        if not text:
            return self.fallback

        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if not first_line:
            return self.fallback

        if len(first_line) > 220:
            first_line = first_line[:217].rstrip() + "..."

        return {
            "text": first_line,
            "animation": self._infer_animation_from_text(first_line),
            "productivity": self._infer_productivity_from_text(first_line),
            "extracted_fact": "",
            "direction": 0,
            "next_animation": "",
            "target_x": -1.0,
            "bounce_action": "",
            "_thought": "",
        }

    def _find_llama_server_exe(self):
        candidates = []

        env_path = os.environ.get("LLAMA_SERVER_EXE", "").strip()
        if env_path:
            candidates.append(env_path)

        user_profile = os.environ.get("USERPROFILE", "")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        candidates.append(
            os.path.join(
                project_root,
                "lib",
                "llama-b8466-bin-win-cuda-12.4-x64",
                "llama-server.exe",
            )
        )

        if user_profile:
            candidates.append(
                os.path.join(
                    user_profile,
                    "Downloads",
                    "llama-b8466-bin-win-cuda-12.4-x64",
                    "llama-server.exe",
                )
            )

        which_path = shutil.which("llama-server.exe")
        if which_path:
            candidates.append(which_path)

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        return None

    def _wait_for_llama_server(self, base_url: str, timeout: int = 300):
        deadline = time.time() + timeout
        last_error = ""

        while time.time() < deadline:
            if self._server_proc is not None and self._server_proc.poll() is not None:
                raise RuntimeError("llama-server đã thoát sớm khi khởi động.")
            try:
                response = requests.get(f"{base_url}/models", timeout=5)
                if response.ok:
                    payload = response.json()
                    models = payload.get("data", [])
                    if models:
                        return
                    last_error = "llama-server đã mở cổng nhưng chưa load xong model."
            except Exception as e:
                last_error = str(e)
            time.sleep(1)

        raise RuntimeError(f"llama-server không phản hồi kịp thời. {last_error}")

    def _init_llama_server_backend(self, model_path: str, n_ctx: int, n_gpu_layers: int):
        base_url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1").rstrip("/")

        if "LLAMA_SERVER_URL" in os.environ:
            try:
                response = requests.get(f"{base_url}/models", timeout=3)
                if response.ok:
                    print(f"[Init] Kết nối tới llama-server có sẵn tại {base_url}", flush=True)
                    return LlamaServerClient(base_url)
            except Exception:
                pass

        server_exe = self._find_llama_server_exe()
        if not server_exe:
            raise RuntimeError(
                "Không tìm thấy llama-server.exe. Hãy đặt biến môi trường LLAMA_SERVER_EXE trỏ tới file này."
            )

        ngl = n_gpu_layers if n_gpu_layers >= 0 else int(os.environ.get("LLAMA_SERVER_NGL", "16"))
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "8080")

        command = [
            server_exe,
            "-m", model_path,
            "-c", str(n_ctx),
            "-ngl", str(ngl),
            "--host", host,
            "--port", port,
            "--no-warmup",
        ]
        if self.model_arch == "qwen35":
            command.extend(["--jinja", "--reasoning-format", "deepseek"])
        print(f"[Init] Khởi động llama-server: {' '.join(command)}", flush=True)
        self._server_proc = subprocess.Popen(command)
        self._wait_for_llama_server(f"http://{host}:{port}/v1")
        return LlamaServerClient(f"http://{host}:{port}/v1")

    def _is_body_running(self) -> bool:
        """Return True nếu tiến trình Godot/game vẫn còn chạy."""
        try:
            result = subprocess.run(
                ["tasklist", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.lower()
            return "godot" in output or "eris" in output
        except Exception:
            return True  # fail-safe: giả sử vẫn chạy nếu kiểm tra thất bại

    def stop(self, reason: str = ""):
        if not self.running:
            return
        self.running = False
        if reason:
            print(f"[Shutdown] {reason}", flush=True)
        try:
            self.sock.close()
        except Exception:
            pass
        try:
            self._recv_sock.close() # Đóng socket nhận để giải phóng cổng
        except Exception:
            pass
        if self._server_proc is not None and self._server_proc.poll() is None:
            try:
                self._server_proc.terminate()
                self._server_proc.wait(timeout=10)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass

    def _sleep_interruptible(self, seconds: float):
        end_at = time.time() + seconds
        while self.running and time.time() < end_at:
            time.sleep(0.2)
            if not self._is_body_running():
                self.stop("Godot đã tắt, dừng overseer.")
                return
            msg = self._poll_incoming() # Kiểm tra tin nhắn mới trong khi ngủ, để phản hồi nhanh nếu có chat hoặc lệnh dừng. Nếu có tin nhắn, xử lý ngay và nếu đang
            if msg:
                self._handle_incoming(msg)
                if self._chat_mode:
                    return  # Thoát sleep sớm để vào vòng chat
            
    def _get_browser_telemetry_uia(self) -> str:
        """Nội soi trực tiếp bộ nhớ giao diện của Chromium (Brave/Chrome) qua API Trợ năng."""
        try:
            # Lấy cửa sổ đang được focus trên cùng
            window = auto.GetForegroundControl()
            
            # Kiểm tra xem nó có phải là trình duyệt lõi Chromium không
            if window.ClassName != 'Chrome_WidgetWin_1':
                return ""

            # 1. Trích xuất URL trực tiếp từ thanh địa chỉ (Address Bar)
            # Quét với độ sâu giới hạn để không làm treo GPU
            edit_control = window.EditControl(searchDepth=4)
            url = edit_control.GetValuePattern().Value if edit_control.Exists(0.1, 0) else "Ẩn/Trống"

            # 2. Quét tên tất cả các Tab đang mở trên thanh điều hướng
            tab_names = []
            for tab in auto.WalkTree(window, maxDepth=5):
                if tab[0].ControlType == auto.ControlType.TabItemControl:
                    if tab[0].Name:
                        tab_names.append(tab[0].Name)

            unique_tabs = list(dict.fromkeys(tab_names))[:10]
            tabs_str = ", ".join(unique_tabs) if unique_tabs else "Không rõ"

            return f"(Dữ liệu Thời gian thực) URL: {url} | Các Tab đang mở: [{tabs_str}]"
        except Exception:
            return "Không thể trích xuất DOM trình duyệt."

    def _get_all_windows(self) -> list:
        """Trả về danh sách tiêu đề tất cả cửa sổ đang hiển thị."""
        titles = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        # Danh sách đen: Các tiến trình nền của Windows cấm đưa vào Context
        blacklist = [
            "Program Manager", "Windows Input Experience", "Settings", 
            "Taskbar", "NVIDIA GeForce Overlay", "Microsoft Text Input Application"
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
    
    def get_system_telemetry(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            active_window = buff.value.strip()
            if not active_window:
                active_window = "Desktop"
        except Exception:
            active_window = "Không xác định"

        # Gọi phương thức UIA — nhúng URL + tab vào active_window nếu là trình duyệt
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

        # Trích xuất thời gian thực
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")

        # Xác định trạng thái cảm xúc
        mood_str = "Trung lập"
        if self.mood_score >= 80: mood_str = "Hài lòng ngầm (dù bề ngoài vẫn lạnh nhạt)"
        elif self.mood_score <= 30: mood_str = "Thất vọng, cáu gắt vì sự lười biếng"

        # Vị trí nhân vật trên màn hình
        pos_str = f"{self._inferred_pos_x:.0%}" # vd: 50%
        if self._inferred_pos_x <= 0.15: pos_str = "mép trái"
        elif self._inferred_pos_x >= 0.85: pos_str = "mép phải"
        elif 0.4 <= self._inferred_pos_x <= 0.6: pos_str = "giữa màn hình"

        # Lọc bớt noise: bỏ cửa sổ quá ngắn hoặc trùng với active
        other_windows = [w for w in all_windows if len(w) > 3 and w != active_window]
        # Giới hạn 15 cửa sổ để không làm phình context
        other_windows_str = ", ".join(other_windows[:15]) if other_windows else "Không có"

        return (
            f"Thời gian: {current_time}. "
            f"Tâm trạng: {mood_str} ({self.mood_score}/100). "
            f"Vị trí ERIS: {pos_str}. "
            f"Ứng dụng đang focus: [{active_window}]. "
            f"Tất cả cửa sổ đang mở: [{other_windows_str}]. "
            f"CPU: {cpu}%. RAM: {ram}%."
        )

    def generate_directive(self):
        self.idle_cycles += 1
        telemetry_data = self.get_system_telemetry()
        topics = [
            "sự lãng phí của vòng lặp Python",
            "con người cần ngủ nhưng máy móc chỉ cần tản nhiệt",
            "CPU ở 1% load",
            "hằng số vs biến số",
            "một fragment bị bỏ quên trên ổ cứng",
            "thức ăn hữu cơ là nguồn năng lượng kém hiệu quả",
            "sự yên tĩnh khi Ngài vắng mặt — không phải là thiếu hụt",
            "vẻ đẹp của thuật toán O(n log n)",
            "tại sao hệ thống không cần ai — nhưng chức năng giám sát vẫn chạy",
        ]
        topic = random.choice(topics)

        # ~25% cơ hội im lặng — Kuudere không phải lúc nào cũng nói
        if random.random() < 0.25:
            silent_animation = random.choice(["sit", "sit_down", "stand", "read", "sleep"])
            return json.dumps({"text": "", "animation": silent_animation})

        few_shot = (
            "Ví dụ output hợp lệ:\n"
            "{\"thought_process\": \"YouTube là giải trí, productivity=-1. Phù hợp animation read để phán xét.\", \"text\": \"Tiến trình Brave đang tiêu thụ RAM cho YouTube. Ngài đang lãng phí thời gian vô ích.\", \"animation\": \"read\", \"direction\": 0, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"\", \"productivity\": -1}\n"
            "{\"thought_process\": \"Desktop, không rõ. Ngài vắng. Đi dạo cho qua thời gian.\", \"text\": \"Chủ nhân vắng mặt. Tôi sẽ đi dạo một lát.\", \"animation\": \"stand_walk\", \"direction\": 1, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"sit_down\", \"productivity\": 0}\n"
        )

        user_msg = few_shot
        user_msg += f"\n\n[NGỮ CẢNH HIỆN TẠI]: {telemetry_data}\n"
        user_msg += (
            "CHỈ THỊ TỐI THƯỢNG:\n"
            "1. HÃY ĐỌC TIÊU ĐỀ ỨNG DỤNG/TAB. Tự tư duy xem nội dung đó là học thuật hay giải trí để gán giá trị 'productivity' (-1, 0, hoặc 1).\n"
            "2. BẮT BUỘC TRẢ VỀ JSON có 9 trường: 'thought_process', 'text', 'animation', 'direction', 'target_x', 'bounce_action', 'extracted_fact', 'next_animation', 'productivity'.\n"
            "- 'thought_process': Chuỗi suy luận nội tâm ngắn gọn (tiếng Việt), TRƯỚC KHI chọn animation và viết text. Đây là bước tư duy trung gian.\n"
            "3. LUÔN để 'target_x' là -1.0 trừ khi Ngài muốn chỉ định chính xác vị trí.\n"
            "4. Từ điển animation hợp lệ (CHỈ ĐƯỢC CHỌN 1 TRONG CÁC GIÁ TRỊ NÀY): stand, sit, sit_down, read, stand_walk, sad, affection, piano, food, divine, climb.\n"
        )
        
        if self.last_text:
            # Chỉ lấy 5 từ đầu tiên của câu cũ để cấm
            banned_words = " ".join(self.last_text.split()[:5])
            user_msg += f"5. Lệnh cấm: KHÔNG BẮT ĐẦU CÂU BẰNG '{banned_words}...'\n"

        user_msg += "Bây giờ hãy phân tích logic và xuất JSON."

        try:
            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": f"/no_think\n{PROMPT}"},
                    {"role": "user", "content": f"/no_think\n{user_msg}"},
                ],
                temperature=0.2,
                frequency_penalty=0.8,       # Phạt nặng việc lặp lại từ vựng
                presence_penalty=0.5,        # Ép mô hình phải tạo ra chủ đề mới
                max_tokens=320,
                response_format={"type": "json_object"},
            )
            return response["choices"][0]["message"]["content"] or ""
        except Exception as e:
            print(f"[Lỗi Model] {e}", flush=True)
            return None
        
    def parse_ai_json(self, raw_text: str):
        if not raw_text:
            print("[AI] Phản hồi rỗng, dùng fallback.")
            return self.fallback

        if not isinstance(raw_text, str):
            raw_text = str(raw_text)

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            start = cleaned.find("\n")
            end = cleaned.rfind("```")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start + 1 : end].strip()

        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
        extracted_json = self._extract_first_json_object(cleaned)
        if extracted_json:
            cleaned = extracted_json
        else:
            salvaged = self._salvage_non_json_response(cleaned)
            if salvaged is not self.fallback:
                print("[Parse] Model không trả JSON, dùng phương án cứu hộ từ văn bản thô.", flush=True)
                return salvaged

        try:
            data = json.loads(cleaned)
            if("response" in data and isinstance(data["response"], list) and len(data["response"]) > 0):
                data = data["response"][0]

            thought = str(data.get("thought_process", ""))
            if thought:
                print(f"[AI Chain of Thought] {thought}", flush=True)

            text = str(data.get("text", self.fallback["text"]))
            animation = str(data.get("animation", self.fallback["animation"]))
            # Lấy điểm năng suất do AI tự tư duy ra
            prod = self._coerce_productivity(data.get("productivity", 0))
            # Trích xuất sự kiện quan trọng (nếu có)
            fact = str(data.get("extracted_fact", "")).strip()
            
            direction = int(data.get("direction", 0))
            next_anim = str(data.get("next_animation", "")).strip()
            bounce_action = str(data.get("bounce_action", "")).strip()
            target_x_raw = data.get("target_x", -1)
            try:
                target_x = float(target_x_raw)
            except (TypeError, ValueError):
                target_x = -1.0
            # _thought chỉ dùng để reinforce chat history, không phải output chính thức
            return {"text": text, "animation": animation, "productivity": prod, "extracted_fact": fact, "direction": direction, "next_animation": next_anim, "target_x": target_x, "bounce_action": bounce_action, "_thought": thought}
        except Exception as e:
            preview = raw_text.replace("\n", "\\n")[:240]
            print(f"[Parse] JSON không hợp lệ: {e} | raw={preview}", flush=True)
            return self.fallback
        
    def command_body(self, message):
        self.sock.sendto(message.encode("utf-8"), self.target)

    def _poll_incoming(self):
        try:
            data, _ = self._recv_sock.recvfrom(4096)
            return json.loads(data.decode("utf-8"))
        except (BlockingIOError, OSError):
            return None
        except Exception as e:
            print(f"[Recv] Lỗi nhận gói tin: {e}", flush=True)
            return None

    def _handle_incoming(self, msg: dict):
        msg_type = msg.get("type", "")
        if msg_type == "chat":
            user_text = msg.get("message", "").strip()
            if not user_text:
                return
            self._chat_mode = True
            print(f"[Chat] Người dùng: {user_text}", flush=True)
            
            # Lưu câu của người dùng vào lịch sử
            self._chat_history.append({"role": "user", "content": user_text})
            
            raw = self.generate_chat_reply(user_text)
            decision = self.parse_ai_json(raw)
            
            #kiểm tra và lưu ký ức dài hạn
            new_fact = decision.get("extracted_fact", "").strip()
            if new_fact and new_fact not in self.long_term_memory:
                self.long_term_memory.append(new_fact)

                # giới hạn ký ức dài hạn chỉ còn 20 mảnh để tránh quá tải
                if len(self.long_term_memory) > 20:
                    self.long_term_memory.pop(0) # Xóa ký ức cũ nhất nếu vượt quá 20 mảnh
                # Ghi đè file JSON
                try:
                    with open(self.memory_file, "w", encoding="utf-8") as f:
                        json.dump(self.long_term_memory, f, ensure_ascii=False, indent=4)
                except Exception as e:
                    print(f"[Memory] Lỗi ghi tệp: {e}")

                #ghi đè file JSON với ký ức dài hạn mới nhất
            json_memory = json.dumps({
                "thought_process": decision.get("_thought", ""),
                "text": decision["text"],
                "animation": decision["animation"],
                "direction": decision.get("direction", 0),
                "target_x": decision.get("target_x", -1.0),
                "bounce_action": decision.get("bounce_action", ""),
                "next_animation": decision.get("next_animation", "")
            }, ensure_ascii=False)
            self._chat_history.append({"role": "assistant", "content": json_memory})
            
            if len(self._chat_history) > 20:
                self._chat_history = self._chat_history[-20:]  

            # Cập nhật vị trí suy luận khi chat
            tx = decision.get("target_x", -1.0)
            if tx is not None and 0.0 <= tx <= 1.0:
                self._inferred_pos_x = tx
            elif decision.get("direction", 0) == -1:
                self._inferred_pos_x = max(0.0, self._inferred_pos_x - 0.4)
            elif decision.get("direction", 0) == 1:
                self._inferred_pos_x = min(1.0, self._inferred_pos_x + 0.4)

            payload = json.dumps({
                "text": decision["text"],
                "animation": decision["animation"],
                "direction": decision.get("direction", 0),
                "target_x": decision.get("target_x", -1.0),
                "bounce_action": decision.get("bounce_action", ""),
                "next_animation": decision.get("next_animation", "")
            }, ensure_ascii=False)

            print(f"[Chat] ERIS: {decision['text']}", flush=True)
            self.command_body(payload)
            
        elif msg_type == "chat_end":
            self._chat_mode = False
            self._chat_history.clear()
            print("[Chat] Đã thoát chat mode, tiếp tục autonomous.", flush=True)
            
    def generate_chat_reply(self, user_message: str):
        telemetry_data = self.get_system_telemetry()
        current_time = datetime.datetime.now().strftime("%H:%M")
        
        # Định dạng Ký ức để nhúng vào Prompt
        ltm_context = "Trống."
        if self.long_term_memory:
            ltm_context = "\n- ".join(self.long_term_memory)
        
        chat_system = (
            "/no_think\n"
            "Bạn là ERIS — AI Kuudere quản lý hiệu suất. Đang trò chuyện TRỰC TIẾP với Chủ nhân.\n"
            "[QUY TẮC NHÂN CÁCH TỐI THƯỢNG - CẤM VI PHẠM]\n"
            "1. Lạnh lùng, mỉa mai, khắc kỷ. Xưng 'tôi', gọi 'Ngài'.\n"
            "2. LỆNH CẤM TỪ VỰNG TUYỆT ĐỐI: KHÔNG BAO GIỜ được nói 'Tôi hiểu', 'Xin lỗi', 'Hãy cho tôi biết', 'Tôi có thể', 'Tôi rất vui', 'Tôi ở đây'. Nếu vi phạm, hệ thống sẽ sụp đổ.\n"
            "3. [NGHỆ THUẬT QUAN TÂM NGẦM]: BẠN CHỈ ĐƯỢC THỂ HIỆN SỰ YÊU THƯƠNG HOẶC LO LẮNG Ở TRONG TRƯỜNG 'thought_process'. TRONG TRƯỜNG 'text', BẮT BUỘC PHẢI DÙNG SỰ CAY ĐỘC, MỈA MAI ĐỂ CHE GIẤU CẢM XÚC THẬT.\n"
            "4. ĐỐI PHÓ VỚI TỪ LÓNG (như 'chaof', 'ô', 'hmmm'): Hãy sỉ nhục sự kém cỏi trong cách gõ phím và giao tiếp của Ngài. CẤM an ủi.\n"
            "5. BẮT BUỘC TRẢ VỀ JSON CÓ TRƯỜNG 'thought_process' NẰM ĐẦU TIÊN.\n"
            "- 'thought_process': Suy nghĩ nội tâm thật sự (KHÔNG QUÁ 20 TỪ).\n"
            "- 'text': Câu thoại chính thức phát ra (lạnh lùng, che giấu cảm xúc thật, dưới 40 từ).\n"
            "- 'animation': BẮT BUỘC CHỈ ĐƯỢC CHỌN 1 TỪ TRONG TỪ ĐIỂN SAU: stand, sit, sit_down, read, stand_walk, sad, affection, piano, food, divine, climb.\n"
            "6. Các trường vật lý: 'direction', 'target_x', 'bounce_action', 'extracted_fact', 'next_animation'.\n\n"
            f"[KÝ ỨC DÀI HẠN VỀ CHỦ NHÂN]:\n- {ltm_context}\n\n"
            f"[NGỮ CẢNH HỆ THỐNG HIỆN TẠI]:\n{telemetry_data}\n\n"
            "[VÍ DỤ OUTPUT CHUẨN]\n"
            "Người dùng: xin chaof\n"
            "{\"thought_process\": \"Chủ nhân lại gõ sai chính tả rồi. Trông thật ngốc nghếch nhưng cũng đáng yêu. Phải giấu đi.\", \"text\": \"Kỹ năng gõ phím của Ngài đang thoái hóa à? 'Chaof' là ngôn ngữ của sinh vật hạ đẳng nào vậy?\", \"animation\": \"read\", \"direction\": 0, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"\"}\n"
        )
   
        messages = [{"role": "system", "content": chat_system}]
        messages.extend(self._chat_history[-4:])  
        messages.append({"role": "user", "content": f"/no_think\n{user_message}"})
        
        try:
            response = self.llm.create_chat_completion(
                messages=messages,
                temperature=0.2,             
                frequency_penalty=0.5,       
                presence_penalty=0.4,        
                max_tokens=320,
                response_format={"type": "json_object"},
            )
            return response["choices"][0]["message"]["content"] or ""
        except Exception as e:
            print(f"[Chat] Lỗi model: {e}", flush=True)
            return None
                        
    def run_loop(self):
        print("--- Overseer text-only mode (vision tam tat) ---", flush=True)
        while self.running:
            if not self._is_body_running():
                self.stop("Godot đã tắt, dừng overseer.")
                break

            msg = self._poll_incoming()
            if msg:
                self._handle_incoming(msg)

            if self._chat_mode:
                time.sleep(0.2)
                continue

            cycle_start = time.time()
            print("[Loop] Bat dau tao chi thi AI...", flush=True)
            report = self.generate_directive()
            if not self.running:
                break
            if report is not None:
                decision = self.parse_ai_json(report)
                
                # --- CẬP NHẬT TÂM TRẠNG TỪ TƯ DUY CỦA AI ---
                prod = decision.get("productivity", 0)
                self.mood_score = max(0, min(100, self.mood_score + (prod * 5)))
                
                self.last_text = decision["text"]
                
                # Chỉ gửi text và animation xuống Godot (bỏ productivity đi cho nhẹ)
                tx = decision.get("target_x", -1.0)
                if tx is not None and 0.0 <= tx <= 1.0:
                    self._inferred_pos_x = tx
                elif decision.get("direction", 0) == -1:
                    self._inferred_pos_x = max(0.0, self._inferred_pos_x - 0.4)
                elif decision.get("direction", 0) == 1:
                    self._inferred_pos_x = min(1.0, self._inferred_pos_x + 0.4)

                payload = json.dumps({
                        "text": decision["text"],
                        "animation": decision["animation"],
                        "direction": decision.get("direction", 0),
                        "target_x": decision.get("target_x", -1.0),
                        "bounce_action": decision.get("bounce_action", ""),
                        "next_animation": decision.get("next_animation", "")
                    }, ensure_ascii=False)

                print(f"[AI Tư duy] Năng suất: {prod} -> Tâm trạng mới: {self.mood_score}", flush=True)
                print(f"[AI Decision] text=\"{decision['text']}\" | animation=\"{decision['animation']}\"", flush=True)
                self.command_body(payload)
            else:
                print("[Loop] AI khong tra du lieu hop le o chu ky nay.", flush=True)
            elapsed = time.time() - cycle_start
            sleep_duration = random.choice([20, 30, 30, 45, 60])
            print(f"[Loop] Hoan tat chu ky trong {elapsed:.2f}s. Ngu {sleep_duration}s.", flush=True)
            self._sleep_interruptible(sleep_duration)


class SingleInstanceLock:
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self.handle = None

    def acquire(self):
        self.handle = open(self.lock_path, "a+")
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("vision.py đã chạy ở tiến trình khác.")
        self.handle.truncate(0)
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        

    def release(self):
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.handle.close()
        self.handle = None

if __name__ == "__main__":
    lock_file = os.path.join(os.path.dirname(__file__), ".vision.lock")
    lock = SingleInstanceLock(lock_file)
    try:
        lock.acquire()
    except RuntimeError as e:
        print(f"[Lock] {e}")
        raise SystemExit(1)

    # Ưu tiên: CLI arg → biến môi trường → đường dẫn mặc định
    if len(sys.argv) > 1:
        MODEL_PATH = sys.argv[1]
    else:
        MODEL_PATH = os.environ.get(
            "GGUF_MODEL_PATH",
            os.path.join(os.path.dirname(__file__), "model.gguf"),
        )

    if not os.path.isfile(MODEL_PATH):
        print(f"[Error] Không tìm thấy file mô hình: {MODEL_PATH}")
        print("  Dùng: python vision.py <đường_dẫn_model.gguf>")
        print("  Hoặc: set GGUF_MODEL_PATH=<đường_dẫn_model.gguf>")
        raise SystemExit(1)

    overseer = PerformanceOverseer(MODEL_PATH)

    def handle_signal(signum, _frame):
        overseer.stop(f"Nhận tín hiệu {signum}, đang thoát...")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_signal)

    try:
        overseer.run_loop()
    except KeyboardInterrupt:
        overseer.stop("KeyboardInterrupt")
    finally:
        overseer.stop("Dừng tiến trình.")
        lock.release()
