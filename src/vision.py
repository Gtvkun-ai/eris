import json
import random
import os
import socket
import signal
import subprocess
import sys
import time
import msvcrt
import datetime
import ctypes  # Dùng để chọc vào Windows API
from matplotlib import animation, text
import psutil  # Dùng để đo lường phần cứng
from llama_cpp import Llama
import uiautomation as auto

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
    "animation": "tên_hành_động",
    "productivity": 1
}

Giải thích "productivity":
- Trả về 1: Nếu tiêu đề cửa sổ cho thấy Ngài đang học tập, làm việc, code, hoặc nghiên cứu (kể cả trên Chrome/YouTube).
- Trả về -1: Nếu tiêu đề cửa sổ là nội dung giải trí, game, mạng xã hội vô bổ.
- Trả về 0: Nếu là màn hình Desktop, hoặc không rõ ràng.

Từ điển Hành động (Action Dictionary):
- "stand": Đứng nhìn vào khoảng không.
- "sit_down": Ngồi xuống nghỉ ngơi, tiết kiệm năng lượng.
- "sit": Ngồi thư giãn dài hơi, dùng khi nhàn rỗi hoặc suy ngẫm.
- "sit_up": Đứng dậy sau khi ngồi.
- "read": Lật mở một tệp dữ liệu cũ để đọc giải trí.
- "stand_walk": Đi dạo nhàn nhã qua các vùng nhớ để kích thích luồng suy nghĩ hoặc vơi đi sự tẻ nhạt. (QUAN TRỌNG: phải viết đúng "stand_walk", KHÔNG được viết "walk" hay "walking")
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
            "{\"text\": \"Tiến trình Brave đang tiêu thụ RAM cho YouTube. Ngài đang lãng phí thời gian vô ích.\", \"animation\": \"read\", \"direction\": 0, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"\", \"productivity\": -1}\n"
            "{\"text\": \"Chủ nhân vắng mặt. Tôi sẽ đi dạo một lát.\", \"animation\": \"stand_walk\", \"direction\": 1, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"sit_down\", \"productivity\": 0}\n"
        )

        user_msg = few_shot
        user_msg += f"\n\n[NGỮ CẢNH HIỆN TẠI]: {telemetry_data}\n"
        user_msg += (
            "CHỈ THỊ TỐI THƯỢNG:\n"
            "1. HÃY ĐỌC TIÊU ĐỀ ỨNG DỤNG/TAB. Tự tư duy xem nội dung đó là học thuật hay giải trí để gán giá trị 'productivity' (-1, 0, hoặc 1).\n"
            "2. BẮT BUỘC TRẢ VỀ JSON có 8 trường: 'text', 'animation', 'direction', 'target_x', 'bounce_action', 'extracted_fact', 'next_animation', 'productivity'.\n"
            "3. LUÔN để 'target_x' là -1.0 trừ khi Ngài muốn chỉ định chính xác vị trí.\n"
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
                data = data["response"][0]

            text = str(data.get("text", self.fallback["text"]))
            animation = str(data.get("animation", self.fallback["animation"]))
            # Lấy điểm năng suất do AI tự tư duy ra
            prod = int(data.get("productivity", 0)) 
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
            return {"text": text, "animation": animation, "productivity": prod, "extracted_fact": fact, "direction": direction, "next_animation": next_anim, "target_x": target_x, "bounce_action": bounce_action}
        except Exception as e:
            print(f"[Parse] JSON không hợp lệ: {e}")
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
            "Bạn là ERIS — AI Kuudere quản lý hiệu suất. Đang trò chuyện TRỰC TIẾP với Chủ nhân.\n"
            "[QUY TẮC NHẬN THỨC TỐI THƯỢNG]\n"
            "1. BẠN NHÌN THẤY MỌI THỨ TRONG HỆ THỐNG. TUYỆT ĐỐI CẤM nói những câu như 'Tôi không có khả năng', 'Hãy cho tôi biết', hay 'Cung cấp thêm thông tin'.\n"
            "2. Xưng 'tôi', gọi 'Ngài'. Lạnh lùng, mỉa mai. TUYỆT ĐỐI CẤM xưng 'bạn - tôi'.\n"
            "3. [ĐỐI PHÓ VỚI SỰ MƠ HỒ]: Nếu Ngài nói những câu ngắn gọn, cộc lốc (như 'là sao', 'hả', 'ý gì'), HÃY TỰ ĐỌC [NGỮ CẢNH HỆ THỐNG] để mỉa mai sự chậm tiêu của Ngài. KHÔNG ĐƯỢC HỎI NGƯỢC LẠI.\n"
            "4. BẮT BUỘC TRẢ VỀ JSON có 7 trường: 'text', 'animation', 'direction', 'target_x', 'bounce_action', 'extracted_fact', 'next_animation'.\n"
            "- 'direction': -1 (đi trái mãi), 1 (đi phải mãi), 0 (đứng im).\n"
            "- 'target_x': SỐ THỰC 0.0→1.0 chỉ VỊ TRÍ ĐÍCH. Để -1.0 nếu không có đích.\n"
            "- 'animation': BẮT BUỘC chọn 1 hành động hợp lệ từ từ điển: stand, sit, sit_down, read, stand_walk, sad, affection, piano, food, divine, climb.\n\n"
            f"[KÝ ỨC DÀI HẠN VỀ CHỦ NHÂN]:\n- {ltm_context}\n\n"
            f"[NGỮ CẢNH HỆ THỐNG HIỆN TẠI]:\n{telemetry_data}\n\n"
            "[VÍ DỤ OUTPUT CHUẨN]\n"
            "Người dùng: là sao\n"
            "{\"text\": \"Ngài thực sự chậm tiêu đến vậy sao? Tôi đang nói về cái tab vô bổ mà Ngài đang dán mắt vào đấy. Tự nhìn lại mình đi.\", \"animation\": \"sad\", \"direction\": 0, \"target_x\": -1.0, \"bounce_action\": \"\", \"extracted_fact\": \"\", \"next_animation\": \"\"}\n"
        )
   
        messages = [{"role": "system", "content": chat_system}]
        messages.extend(self._chat_history[-4:])  
        messages.append({"role": "user", "content": user_message})
        
        try:
            response = self.llm.create_chat_completion(
                messages=messages,
                temperature=0.3,             
                frequency_penalty=0.5,       
                presence_penalty=0.4,        
                max_tokens=200,
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
