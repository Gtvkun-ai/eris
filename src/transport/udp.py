import json
import socket


class UdpTransport:
    def __init__(self, send_host: str, send_port: int, recv_host: str, recv_port: int):
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_target = (send_host, send_port)
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.bind((recv_host, recv_port))
        self._recv_sock.setblocking(False)

    def send_text(self, message: str) -> None:
        self._send_sock.sendto(message.encode("utf-8"), self._send_target)

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
