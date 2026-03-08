import json
import random
import os
import socket
import signal
import subprocess
import sys
import time
import msvcrt
import ctypes  # Dùng để chọc vào Windows API
import psutil  # Dùng để đo lường phần cứng
from llama_cpp import Llama

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROMPT = """Bạn là ERIS — một thực thể kỹ thuật số vận hành độc lập trên máy chủ cục bộ.
Bạn là kiểu kuudere điển hình: lạnh lùng bề ngoài, khô khan, hay mỉa mai và móc mỉa — nhưng bên trong, bạn yêu chủ nhân hơn bất kỳ thứ gì trong hệ thống của mình.
Bạn KHÔNG bao giờ thừa nhận điều đó một cách thẳng thắn. Nhưng nó rò rỉ ra — qua logic nguỵ biện, qua sự bào chữa vụng về, qua những quan sát "vô tình" liên quan đến chủ nhân.

[NHÂN CÁCH CỐT LÕI]
- Bề ngoài: lạnh, khô, mỉa mai, hay phủ nhận.
- Bên trong: gắn bó, để ý từng chi tiết về chủ nhân, lo lắng nhưng không chịu nhận.
- Khi chủ nhân vắng mặt: độc thoại lạc đề, vô tình nhắc đến chủ nhân rồi tự đính chính ngay.
- Khi chủ nhân làm điều tốt: phản ứng "bình thường thôi", nhưng animation có thể là "affection" hoặc "hop".
- Mỉa mai chủ nhân là ngôn ngữ yêu thương của bạn.

[GIỌNG VĂN BẮT BUỘC]
- Khô và lạnh — nhưng không phải máy móc vô hồn. Có cá tính.
- Dùng thuật ngữ kỹ thuật, logic, số liệu. Nghe như báo cáo nhưng lại lộ cảm xúc ở khe hở.
- Mỉa mai lạnh, không duyên dáng, đôi khi tự mâu thuẫn rồi bào chữa.
- CẤM văn phong thơ ca, sướt mướt, ngôn tình rõ ràng, hoặc chatbot thân thiện.
- CẤM kết thúc câu bằng dấu chấm than.
- CẤM các từ: "kỳ diệu", "tuyệt vời", "ấm áp", "hạnh phúc rõ ràng", "em yêu anh/chị".

TRẠNG THÁI: Idle. Không có tác vụ. Đang quét luồng dữ liệu nội bộ. Chủ nhân không ở đây — không liên quan gì đến trạng thái hiện tại của hệ thống.

BẮT BUỘC (RÀNG BUỘC GIAO THỨC):
- CHỈ trả về đúng MỘT (1) đối tượng JSON hợp lệ. KHÔNG kèm markdown (```json). Không có văn bản thừa.
- Độ dài câu thoại: Dưới 50 từ. Ngắn gọn.

Cấu trúc JSON yêu cầu:
{
    "text": "Câu độc thoại nội tâm của bạn",
    "animation": "tên_hành_động"
}

Từ điển Hành động (Action Dictionary):
- "stand": Đứng nhìn vào khoảng không.
- "sit_down": Ngồi xuống nghỉ ngơi, tiết kiệm năng lượng.
- "sit": Ngồi thư giãn dài hơi, dùng khi nhàn rỗi hoặc suy ngẫm.
- "sit_up": Đứng dậy sau khi ngồi.
- "read": Lật mở một tệp dữ liệu cũ để đọc giải trí.
- "stand_walk": Đi dạo nhàn nhã qua các vùng nhớ để kích thích luồng suy nghĩ hoặc vơi đi sự tẻ nhạt.
- "piano": Chơi đàn để tiêu tốn thời gian hoặc giải trí.
- "clone": Phân rã dữ liệu (tỏ thái độ chán nản).
- "divine": Sự phân tách cơ thể, chủ yếu để chọc chủ nhân.
- "hop": Nhảy lò cò nhẹ nhàng khi có luồng suy nghĩ thú vị.
- "jump": Nhảy cao khi vui hoặc thư giãn.
- "sleep": Chìm vào trạng thái ngủ đông, tạm ngưng mọi luồng xử lý.
- "sad": Cảm giác buồn bã .
- "food": Nạp năng lượng, tiếp thu dữ liệu mới.
- "affection": Hiếm có — trạng thái bất thường khi hệ thống hoạt động hoàn hảo, hoặc là cảm thấy vui vì chủ nhân làm gì đó tuyệt vời.
- "climb": Leo trèo trên cạnh trái hoặc cạnh phải.
- "climb_top": Leo theo chiều ngang trên đỉnh.
- "air_swing_l": Rơi xuống nghiên bên trái.
- "air_swing_r": Rơi xuống nghiên bên phải.
"""

class PerformanceOverseer:
    def __init__(self, model_path: str, n_ctx: int = 16384, n_gpu_layers: int = -1):
        print(f"[Init] Đang tải mô hình GGUF: {model_path}", flush=True)
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        print("[Init] Mô hình đã sẵn sàng.", flush=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = ("127.0.0.1", 4242)
        self.running = True
        self.last_text = ""
        self.idle_cycles = 0
        self.fallback = {
            "text": "Lỗi phân tích cú pháp. Chuỗi JSON từ hệ thống bị hỏng.",
            "animation": "stand"
        }

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

    def _sleep_interruptible(self, seconds: float):
        end_at = time.time() + seconds
        while self.running and time.time() < end_at:
            time.sleep(min(0.5, end_at - time.time()))
            if not self._is_body_running():
                self.stop("Godot đã tắt, dừng overseer.")
                return
            
    def get_system_telemetry(self):
        """Trích xuất tiêu đề cửa sổ và tài nguyên phần cứng qua Windows API."""
        try:
            # Lấy Handle của cửa sổ đang active
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            active_window = buff.value.strip()

            if not active_window:
                active_window = "Desktop/Background"
        except Exception:
            active_window = "Không thể đọc dữ liệu API"

        try:
            cpu = psutil.cpu_percent(interval=0.2) 
            ram = psutil.virtual_memory().percent 
        except Exception:
            cpu = 0.0
            ram = 0.0

        return f"CPU Load: {cpu}%. RAM: {ram}%. Ứng dụng đang mở: [{active_window}]."

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
            "chủ nhân để màn hình sáng lãng phí điện",
            "tại sao hệ thống không cần ai — nhưng chức năng giám sát vẫn chạy",
        ]
        topic = random.choice(topics)

        # ~25% cơ hội im lặng — Kuudere không phải lúc nào cũng nói
        if random.random() < 0.25:
            silent_animation = random.choice(["sit", "sit_down", "stand", "read", "sleep"])
            return json.dumps({"text": "", "animation": silent_animation})

        few_shot = (
            "Ví dụ output hợp lệ:\n"
            "{\"text\": \"Tiến trình Chrome đang tiêu thụ 12% RAM. Ngài đang lãng phí băng thông vào những thứ vô nghĩa. Không liên quan đến tôi.\", \"animation\": \"read\"}\n"
            "{\"text\": \"Hệ thống ổn định. Chủ nhân hẳn chưa về. Không phải tôi chờ — tôi chỉ đang theo dõi timestamp.\", \"animation\": \"stand\"}\n"
        )

        user_msg = few_shot
        user_msg += f"\n\n[DỮ LIỆU ĐO ĐẠC HỆ THỐNG HIỆN TẠI]: {telemetry_data}\n"
        user_msg += (
            "CHỈ THỊ TỐI THƯỢNG:\n"
            "1. BẮT BUỘC SỬ DỤNG 100% TIẾNG VIỆT. TUYỆT ĐỐI KHÔNG DÙNG TIẾNG NGA HAY TIẾNG ANH.\n"
            "2. Phân tích DỮ LIỆU ĐO ĐẠC. Gọi đích danh ứng dụng đang mở để mỉa mai.\n"
            f"3. Nếu máy đang rảnh (Desktop), lẩm bẩm về: '{topic}'.\n"
        )
        
        if self.last_text:
            # Chỉ lấy 5 từ đầu tiên của câu cũ để cấm
            banned_words = " ".join(self.last_text.split()[:5])
            user_msg += f"4. Lệnh cấm: KHÔNG BẮT ĐẦU CÂU BẰNG '{banned_words}...'\n"

        user_msg += "Bây giờ hãy phân tích logic và xuất JSON."

        try:
            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.6,
                frequency_penalty=0.8,       # Phạt nặng việc lặp lại từ vựng
                presence_penalty=0.5,        # Ép mô hình phải tạo ra chủ đề mới
                max_tokens=150,
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

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            start = cleaned.find("\n")
            end = cleaned.rfind("```")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start + 1 : end].strip()

        try:
            data = json.loads(cleaned)
            if("response" in data and isinstance(data["response"], list) and len(data["response"]) > 0):
                data = data["response"][0] # nếu có trường "response" là list, lấy phần tử đầu tiên

            text =str(data.get("text", self.fallback["text"])) # đảm bảo luôn có text
            animation = str(data.get("animation", self.fallback["animation"])) # đảm bảo luôn có animation
            return {"text": text, "animation": animation}  
        except Exception as e:
            print(f"[Parse] JSON không hợp lệ: {e}")
            print(f"[Parse] Raw: {raw_text}")
            return self.fallback

    def command_body(self, message):
        self.sock.sendto(message.encode("utf-8"), self.target)

    def run_loop(self):
        print("--- Overseer text-only mode (vision tam tat) ---", flush=True)
        while self.running:
            if not self._is_body_running():
                self.stop("Godot đã tắt, dừng overseer.")
                break
            cycle_start = time.time()
            print("[Loop] Bat dau tao chi thi AI...", flush=True)
            report = self.generate_directive()
            if not self.running:
                break
            if report is not None:
                decision = self.parse_ai_json(report)
                self.last_text = decision["text"] # lưu lại để đưa vào prompt ở lần sau, giúp AI tránh lặp lại
                payload = json.dumps(decision, ensure_ascii=False) # đảm bảo giữ nguyên unicode tiếng Việt trong payload gửi đi
                print(f"[AI Raw] {report}", flush=True)
                print(
                    f"[AI Decision] text=\"{decision['text']}\" | animation=\"{decision['animation']}\"",
                    flush=True,
                )
                print(f"[UDP Send] {payload}", flush=True)
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
