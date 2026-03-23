import json
import socket

# UdpTransport là một lớp để giao tiếp qua giao thức UDP,
#  nó cung cấp các phương thức để gửi và nhận dữ liệu dưới dạng văn bản hoặc
#  JSON. Lớp này sử dụng hai socket riêng biệt: một để gửi dữ liệu đến một địa chỉ và cổng cụ thể,
#  và một để nhận dữ liệu từ một địa chỉ và cổng khác. Phương thức send_text và send_json cho phép gửi dữ liệu dưới dạng chuỗi hoặc đối tượng JSON,
#  trong khi phương thức poll_json cho phép nhận dữ liệu và phân tích nó thành một
#  đối tượng Python. Lớp cũng bao gồm một phương thức close để đóng các socket khi không còn cần thiết.
class UdpTransport:
    def __init__(self, send_host: str, send_port: int, recv_host: str, recv_port: int):
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_target = (send_host, send_port)
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.bind((recv_host, recv_port))
        self._recv_sock.setblocking(False)

    def send_text(self, message: str) -> None:
        self._send_sock.sendto(message.encode("utf-8"), self._send_target)
    # send_json là một phương thức để gửi dữ liệu dưới dạng JSON,
    #  nó nhận một đối tượng Python, chuyển đổi nó thành một chuỗi JSON,
    #  và sau đó gửi chuỗi đó qua socket UDP đến địa chỉ và cổng
#  đã được cấu hình trong phương thức __init__. Việc sử dụng json.dumps với ensure_ascii=False đảm bảo rằng các ký tự Unicode được giữ nguyên trong chuỗi JSON,
#  cho phép gửi dữ liệu có chứa các ký tự đặc biệt hoặc ngôn ngữ khác một cách chính xác.
    def send_json(self, payload: dict) -> None:
        self.send_text(json.dumps(payload, ensure_ascii=False))

    def poll_json(self):
        try:
            data, _ = self._recv_sock.recvfrom(4096)
            return json.loads(data.decode("utf-8"))
        except (BlockingIOError, OSError):
            return None
        except Exception as exc:
            print(f"[Recv] Lỗi nhận gói tin: {exc}", flush=True)
            return None

    def close(self) -> None:
        try:
            self._send_sock.close()
        except Exception:
            pass
        try:
            self._recv_sock.close()
        except Exception:
            pass
