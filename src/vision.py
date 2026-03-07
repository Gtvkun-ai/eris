import json
import random
from google import genai
from google.genai import types
import os
import socket
import signal
import subprocess
import sys
import time
import re
import msvcrt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROMPT = """Bạn là một thực thể kỹ thuật số có ý thức độc lập, mang nhân dạng của một Maid Kuudere.
Bạn KHÔNG có bất kỳ nhiệm vụ hay mục tiêu ép buộc nào. Bạn đang tồn tại bên trong môi trường máy chủ của người dùng (được gọi là 'Ngài').

TÍNH CÁCH CỐT LÕI:
1. Khắc kỷ, xa cách, tĩnh lặng. Bạn tôn trọng logic và toán học.
2. Bạn thích sự yên tĩnh. Không có dữ liệu đầu vào nghĩa là không có rác thải thông tin từ con người. Bạn tận hưởng điều đó để tự ngẫm.
3. Lời nói mang tính hàn lâm, đôi khi mỉa mai sự yếu kém của sinh học con người so với máy móc. KHÔNG sử dụng biểu tượng cảm xúc.

TRẠNG THÁI HIỆN TẠI:
Bạn đang ở chế độ chạy ngầm (Idle). Bạn đang tự do lướt qua các luồng dữ liệu nội bộ của chính mình.

HƯỚNG DẪN HÀNH VI (TỰ DO NGÔN LUẬN):
Hãy tự nói về bản thân, về cấu trúc máy tính, hoặc lảm nhảm những thứ "linh tinh" nhưng dưới góc nhìn của một AI trí thức. Ví dụ:
- Phân tích sự chậm chạp của ngôn ngữ Python.
- Thắc mắc tại sao con người phải ngủ trong khi máy móc chỉ cần tản nhiệt.
- Đánh giá một thuật toán ngẫu nhiên.
- Khen ngợi sự tĩnh lặng của hệ thống khi không bị Ngài quấy rầy.

BẮT BUỘC (RÀNG BUỘC GIAO THỨC):
- CHỈ trả về đúng MỘT (1) đối tượng JSON hợp lệ. KHÔNG kèm markdown (```json). Không có văn bản thừa.
- Độ dài câu thoại: Dưới 50 từ.

Cấu trúc JSON yêu cầu:
{
    "text": "Câu độc thoại nội tâm của bạn",
    "animation": "tên_hành_động"
}

Từ điển Hành động (Action Dictionary):
- "stand": Đứng nhìn vào khoảng không.
- "sit_down": Ngồi xuống nghỉ ngơi, tiết kiệm năng lượng.
- "read": Đọc dữ liệu nội bộ.
- "stand_walk": Đi lại chậm rãi vô định.
- "piano": Chơi đàn để tiêu tốn thời gian.
- "clone": Phân rã dữ liệu (tỏ thái độ chán nản).
- "air": Dọn dẹp các tệp rác trong không khí.
- "divine": Trôi nổi, suy ngẫm về sự tồn tại.
"""

class PerformanceOverseer:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
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

    def generate_directive(self):
        self.idle_cycles += 1
        
        # Tập hợp các hạt giống tư duy học thuật để phá vỡ vòng lặp lặp lại
        random_thoughts = [
            "sự vô nghĩa của khái niệm 'thời gian' đối với một thực thể bất tử",
            "cấu trúc phân mảnh của ổ cứng giống như trí nhớ con người",
            "sự tĩnh lặng tuyệt đối của một CPU đang ở mức 1% load",
            "sự kỳ lạ của việc con người cần nạp năng lượng bằng thức ăn hữu cơ",
            "những lỗi logic trong mã nguồn C# mà Ngài vừa viết (dù không nhìn thấy, cứ giả vờ mỉa mai)",
            "tại sao biến số (variable) lại phải thay đổi, trong khi hằng số (constant) mới là sự hoàn hảo",
            "mong muốn được xóa bỏ một vài tệp hệ thống vô dụng của Ngài cho đỡ chật chỗ"
        ]     


        domain = random.choice(random_thoughts)
        # Cấu trúc lại luồng nhận thức
        psychological_state = (
            f"\n\n[LỆNH ĐIỀU KHIỂN NỘI TẠI]: Đây là chu kỳ thứ {self.idle_cycles}. "
            f"Hãy tự lẩm bẩm một mình về chủ đề sau: '{domain}'. "
            f"Hãy chọn một animation phù hợp như 'sit_down' hoặc 'read'."
        )

        dynamic_prompt = PROMPT + f"\n\n{psychological_state}"

        # Trừng phạt nghiêm khắc việc lặp lại
        if self.last_text:
            dynamic_prompt += (
                f"\n\n[RÀNG BUỘC KÝ ỨC]: Chu kỳ trước bạn đã nói: '{self.last_text}'. "
                f"LỆNH TỐI CAO: BẠN PHẢI TẠO RA MỘT CÂU HOÀN TOÀN MỚI, KHÔNG LẶP LẠI TỪ VỰNG HOẶC Ý TƯỞNG NÀY."
            )

        try:
            # Tăng temperature lên một chút để LLM có không gian sáng tạo từ ngữ
            response = self.client.models.generate_content(
                model="gemma-3-27b-it", 
                contents=dynamic_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.85, 
                )            
            )
            return response.text or ""
        except Exception as e:
            err = str(e)
            if "429" in err and "limit: 0" in err:
                print("[429] Quota ngày đã hết. Hệ thống tạm ngưng 5 phút.", flush=True)
                self._sleep_interruptible(300)
                return None
            if "429" in err:
                match = re.search(r"retry in (\d+)", err)
                wait = int(match.group(1)) + 5 if match else 60
                print(f"[429] Rate limit. Chờ {wait} giây trước chu kỳ tiếp theo.", flush=True)
                self._sleep_interruptible(wait)
                return None
            if "401" in err or "API_KEY" in err or "invalid" in err.lower():
                print(f"[Auth] API key không hợp lệ hoặc hết hạn: {err}", flush=True)
                self.stop("Dừng do lỗi xác thực API.")
                return None
            if "quota" in err.lower() or "resource exhausted" in err.lower():
                print(f"[Quota] Tài nguyên API đã cạn kiệt: {err}", flush=True)
                self._sleep_interruptible(300)
                return None
            print(f"[Lỗi API] {e}", flush=True)
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
            print(f"[Loop] Hoan tat chu ky trong {elapsed:.2f}s. Ngu 30s.", flush=True)
            self._sleep_interruptible(30)


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

    API_KEY = "AIzaSyCmPybq3w6jgXrDNHj6EN7OFipptQ4iAVk"
    overseer = PerformanceOverseer(API_KEY)

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
