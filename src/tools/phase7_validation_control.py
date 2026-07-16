# -*- coding: utf-8 -*-
"""Điều khiển production validation Phase 7 qua UDP hoặc đọc state local.

Ví dụ PowerShell:
  python tools/phase7_validation_control.py start
  python tools/phase7_validation_control.py mark greeting --pass --detail "xin chào eris"
  python tools/phase7_validation_control.py status
  python tools/phase7_validation_control.py finalize

Lệnh start/mark/finalize gửi control tới Brain (mặc định 127.0.0.1:4243).
Lệnh status đọc file state vì cổng trả về 4242 thường đang do Body giữ. Ít nhất ta
không tranh socket với chính giao diện rồi gọi đó là observability.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.hardening_config import HardeningConfig


def _send(host: str, port: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(raw, (host, int(port)))


def _state_path(config: HardeningConfig) -> Path:
    base = Path(config.production_validation_dir)
    if not base.is_absolute():
        base = _ROOT / base
    return base / "current.json"


def _read_status(config: HardeningConfig) -> dict:
    path = _state_path(config)
    if not path.is_file():
        return {
            "status": "not_started" if config.production_validation_enabled else "disabled",
            "state_path": str(path),
            "target_turns": config.production_validation_turns,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "invalid_state", "state_path": str(path), "error": type(exc).__name__}
    if not isinstance(payload, dict):
        payload = {"status": "invalid_state"}
    payload["state_path"] = str(path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Điều khiển Phase 7 production validation của Eris")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4243)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Bắt đầu cửa sổ validation")
    start.add_argument("--validation-id", default="")

    mark = sub.add_parser("mark", help="Đánh dấu scenario thủ công")
    mark.add_argument("scenario")
    result = mark.add_mutually_exclusive_group(required=True)
    result.add_argument("--pass", dest="passed", action="store_true")
    result.add_argument("--fail", dest="passed", action="store_false")
    mark.add_argument("--turn-id", default="")
    mark.add_argument("--detail", default="")

    finalize = sub.add_parser("finalize", help="Đóng cửa sổ và sinh report")
    finalize.add_argument("--reason", default="manual_operator")
    sub.add_parser("status", help="Đọc state local")

    args = parser.parse_args()
    config = HardeningConfig.load()
    if args.command == "status":
        print(json.dumps(_read_status(config), ensure_ascii=False, indent=2))
        return 0

    payload = {
        "type": "phase7_validation_control",
        "action": args.command,
        "request_id": f"phase7ctl-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
    }
    if args.command == "start":
        payload["validation_id"] = args.validation_id
    elif args.command == "mark":
        payload.update({
            "scenario": args.scenario,
            "passed": bool(args.passed),
            "turn_id": args.turn_id,
            "detail": args.detail,
        })
    elif args.command == "finalize":
        payload["reason"] = args.reason

    _send(args.host, args.port, payload)
    print(json.dumps({
        "sent": True,
        "host": args.host,
        "port": args.port,
        "request_id": payload["request_id"],
        "action": args.command,
        "note": "Dùng lệnh status để đọc state do Body thường đang giữ cổng UDP trả về.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
