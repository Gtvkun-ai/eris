import json
import socket

from failure_meta import build_failure_meta, mark_transport_truncated, normalize_failure_meta


# Trần payload cho một datagram UDP. IPv4 cho tối đa 65507 bytes/datagram; quá
# ngưỡng đó sendto() của OS sẽ lỗi và KHÔNG gửi được gì. 63000 chừa lề an toàn,
# vẫn nằm gọn trong buffer nhận mặc định của Godot PacketPeerUdp (65536).
MAX_UDP_PAYLOAD_BYTES = 63000


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
        # inner_diary là thứ quan trọng nhất với UI nên giữ tối đa, nhưng vẫn phải
        # nén có giới hạn: một section/line nội tâm có thể phình rất to (vd dump thô),
        # nếu để NGUYÊN BẢN thì stage 1 vượt trần payload và rơi xuống stage rút gọn
        # cứng — nơi debug_api và emotion_debug.private_mind bị vứt mất. Nén ở đây giữ
        # được title/text/sections mà vẫn đủ nhỏ để stage 1 thành công.
        "inner_diary": _compact_inner_diary(value.get("inner_diary")),
        # Giữ anchor (Mô Hình Ngài / trục neo) NGUYÊN BẢN — nhỏ và là dữ liệu panel cần.
        "anchor": value.get("anchor") if isinstance(value.get("anchor"), dict) else {},
        "menu": compact_menu,
        "udp_debug_truncated": True,
    }


def _compact_inner_diary(diary):
    """Compact inner_diary giữ nguyên sections/items để C# có thể parse đúng."""
    if not isinstance(diary, dict):
        return {}
    sections = diary.get("sections")
    compact_sections = []
    if isinstance(sections, list):
        for sec in sections[:6]:
            if not isinstance(sec, dict):
                continue
            title = str(sec.get("title", ""))[:120]
            items = sec.get("items")
            compact_items = []
            if isinstance(items, list):
                for item in items[:6]:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text", "") or "")
                    badge = str(item.get("badge", "") or "")
                    if text:
                        compact_items.append({
                            "text": text[:200],
                            "badge": badge[:60],
                        })
            if title and compact_items:
                compact_sections.append({"title": title, "items": compact_items})
    return {
        "title": str(diary.get("title", ""))[:80],
        "text": str(diary.get("text", "") or "")[:800],
        "sections": compact_sections,
    }


def _slim_private_mind_core(private_mind):
    """Bản rút gọn cứng của private_mind_digest.

    Chỉ giữ đúng thứ UI cần để vẽ Inner Diary (current_thought / future_bias /
    open_concerns + inner_diary sections), bỏ các nhánh debug nặng. Dùng làm phao
    cuối khi bản compact thường vẫn vượt giới hạn payload.
    """
    if not isinstance(private_mind, dict):
        return {}
    menu = private_mind.get("menu")
    menu = menu if isinstance(menu, dict) else {}
    slim_menu = {}
    for key in ("current_thought", "future_bias", "open_concerns"):
        if key in menu:
            slim_menu[key] = _compact_debug_value(menu.get(key), depth=0)

    diary = private_mind.get("inner_diary")
    slim_diary = {}
    if isinstance(diary, dict):
        sections = []
        raw_sections = diary.get("sections")
        if isinstance(raw_sections, list):
            for sec in raw_sections[:4]:
                if not isinstance(sec, dict):
                    continue
                items = []
                raw_items = sec.get("items")
                if isinstance(raw_items, list):
                    for item in raw_items[:3]:
                        if isinstance(item, dict) and item.get("text"):
                            items.append({
                                "text": str(item.get("text", ""))[:120],
                                "badge": str(item.get("badge", "") or "")[:40],
                            })
                if sec.get("title") and items:
                    sections.append({"title": str(sec.get("title", ""))[:80], "items": items})
        slim_diary = {
            "title": str(diary.get("title", ""))[:60],
            "text": str(diary.get("text", "") or "")[:300],
            "sections": sections,
        }

    return {
        "last_tick_at": private_mind.get("last_tick_at", 0.0),
        "current": _compact_debug_value(private_mind.get("current", {}), depth=0),
        "inner_diary": slim_diary,
        # Giữ anchor qua cả bản rút gọn cứng nhất để panel Mô Hình Ngài không trống.
        "anchor": private_mind.get("anchor") if isinstance(private_mind.get("anchor"), dict) else {},
        "menu": slim_menu,
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


def _compact_reasoning_tags(value):
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        items = []
    cleaned = []
    for item in items[:8]:
        tag = str(item or "").strip()
        if tag:
            cleaned.append(tag[:40])
    return cleaned


def _compact_debug_trace(value, *, limit: int = 240) -> str:
    return _compact_scalar(value, limit) if isinstance(_compact_scalar(value, limit), str) else ""


def _core_udp_payload(payload: dict, *, text_limit: int | None = None, debug_limit: int = 240) -> dict:
    text = str(payload.get("text", "") or "")
    if text_limit is not None and len(text) > text_limit:
        text = text[:text_limit]
    failure_meta = normalize_failure_meta(payload.get("failure_meta"))
    core = {
        "text": text,
        "should_speak": bool(payload.get("should_speak", False)),
        "intent": str(payload.get("intent", "") or ""),
        "animation": str(payload.get("animation", "stand") or "stand"),
        "parse_mode": str(payload.get("parse_mode", "") or ""),
        "reasoning_tags": _compact_reasoning_tags(payload.get("reasoning_tags", [])),
        "debug_trace": _compact_debug_trace(payload.get("debug_trace", ""), limit=debug_limit),
        "udp_debug_truncated": True,
    }
    if "direction" in payload:
        core["direction"] = payload.get("direction", 0)
    if "target_x" in payload:
        core["target_x"] = payload.get("target_x", -1.0)
    if "bounce_action" in payload:
        core["bounce_action"] = str(payload.get("bounce_action", "") or "")
    if "next_animation" in payload:
        core["next_animation"] = str(payload.get("next_animation", "") or "")
    if failure_meta is None:
        core["failure_meta"] = build_failure_meta(
            kind="transport_truncated",
            stage="udp_send",
            origin="transport",
            public_surface="silent" if not core["should_speak"] else "service_fallback",
            recoverable=False,
            transport_truncated=True,
        )
    else:
        core["failure_meta"] = mark_transport_truncated(failure_meta)
    return core

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
        if len(message.encode("utf-8")) <= MAX_UDP_PAYLOAD_BYTES:
            self.send_text(message)
            return

        payload = dict(payload)
        payload.pop("private_mind_digest", None)
        payload.pop("emotion_debug", None)
        payload["failure_meta"] = mark_transport_truncated(payload.get("failure_meta"))
        payload["udp_debug_truncated"] = True
        # Stage 1: giữ lõi decision và failure_meta; bỏ emotion/private_mind trước.
        for text_limit, debug_limit in ((None, 480), (1200, 320), (500, 240), (220, 120)):
            minimal = _core_udp_payload(payload, text_limit=text_limit, debug_limit=debug_limit)
            message = json.dumps(minimal, ensure_ascii=False)
            if len(message.encode("utf-8")) <= MAX_UDP_PAYLOAD_BYTES:
                self.send_text(message)
                return

        # Stage 2: đường cùng, cắt text mạnh tay nhưng vẫn giữ failure_meta.
        minimal = _core_udp_payload(payload, text_limit=80, debug_limit=80)
        message = json.dumps(minimal, ensure_ascii=False)
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
