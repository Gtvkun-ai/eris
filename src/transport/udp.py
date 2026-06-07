import json
import socket


MAX_UDP_PAYLOAD_BYTES = 60000


def _compact_private_mind_for_udp_overflow(value):
    if not isinstance(value, dict):
        return {}
    menu = value.get("menu")
    if not isinstance(menu, dict):
        menu = {}
    compact_menu = {}
    for key in (
        "current_thought",
        "temporary_thoughts",
        "open_concerns",
        "inner_judgment",
        "state_mutations",
        "future_bias",
        "surface_queue",
        "debug_api",
    ):
        if key in menu:
            compact_menu[key] = _compact_debug_value(menu.get(key), depth=0)
    return {
        "last_tick_at": value.get("last_tick_at", 0.0),
        "current": _compact_debug_value(value.get("current", {}), depth=0),
        "inner_diary": _compact_debug_value(value.get("inner_diary", {}), depth=0),
        "menu": compact_menu,
        "udp_debug_truncated": True,
    }


def _compact_debug_value(value, *, depth: int):
    if depth >= 3:
        return _compact_scalar(value, 180)
    if isinstance(value, dict):
        out = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 6:
                out["..."] = "truncated"
                break
            out[str(key)[:64]] = _compact_debug_value(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)
        return [_compact_debug_value(item, depth=depth + 1) for item in items[:4]] + (["... truncated"] if len(items) > 4 else [])
    return _compact_scalar(value, 240)


def _compact_scalar(value, limit: int):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text

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
        message = json.dumps(payload, ensure_ascii=False)
        if len(message.encode("utf-8")) > MAX_UDP_PAYLOAD_BYTES:
            payload = dict(payload)
            private_mind = _compact_private_mind_for_udp_overflow(payload.get("private_mind_digest"))
            if private_mind:
                payload["private_mind_digest"] = private_mind
            else:
                payload.pop("private_mind_digest", None)
            emotion = payload.get("emotion_debug")
            if isinstance(emotion, dict):
                emotion = dict(emotion)
                if private_mind:
                    emotion["private_mind"] = private_mind
                else:
                    emotion.pop("private_mind", None)
                payload["emotion_debug"] = emotion
            payload["udp_debug_truncated"] = True
            message = json.dumps(payload, ensure_ascii=False)
        if len(message.encode("utf-8")) > MAX_UDP_PAYLOAD_BYTES:
            payload = {
                "text": str(payload.get("text", ""))[:500],
                "should_speak": bool(payload.get("should_speak", False)),
                "animation": str(payload.get("animation", "stand") or "stand"),
                "parse_mode": str(payload.get("parse_mode", "") or ""),
                "debug_trace": "udp_payload_truncated",
                "udp_debug_truncated": True,
            }
            message = json.dumps(payload, ensure_ascii=False)
        self.send_text(message)

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
