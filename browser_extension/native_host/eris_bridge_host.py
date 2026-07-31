#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ERIS Browser DOM Bridge — Native Messaging Host.

Nhận JSON từ Chrome/Brave extension qua stdin (Native Messaging Protocol)
rồi ghi vào %LOCALAPPDATA%\\ERIS\\browser_dom_state.json để ERIS đọc.

Protocol:
  - Extension gửi: 4-byte LE length + JSON payload
  - Host nhận  → ghi file → gửi ack: 4-byte LE length + {"ok": true}

Chạy bởi Chrome/Brave khi extension gọi chrome.runtime.connectNative().
KHÔNG chạy tay — dùng install.bat để đăng ký vào registry.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
import tempfile
from pathlib import Path


def _eris_dir() -> Path:
    """Thư mục chứa file cache của ERIS."""
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        d = Path(local_app) / "ERIS"
    else:
        # Fallback: bên cạnh script này
        d = Path(__file__).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


OUTPUT_FILE = _eris_dir() / "browser_dom_state.json"
LOCK_FILE   = _eris_dir() / "browser_dom_state.lock"


def read_message() -> dict | None:
    """Đọc một message theo Chrome Native Messaging Protocol."""
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len == 0 or msg_len > 1_048_576:  # tối đa 1 MB
        return None
    raw = sys.stdin.buffer.read(msg_len)
    if len(raw) < msg_len:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_message(data: dict) -> None:
    """Gửi ack về extension."""
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def atomic_write(path: Path, content: str) -> None:
    """Ghi file an toàn qua temp file để ERIS không đọc file rỗng/nửa chừng."""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def main() -> None:
    while True:
        msg = read_message()
        if msg is None:
            break

        # Thêm timestamp nếu extension không ghi
        if "timestamp" not in msg:
            msg["timestamp"] = time.time()

        try:
            payload_str = json.dumps(msg, ensure_ascii=False, indent=2)
            atomic_write(OUTPUT_FILE, payload_str)
            write_message({"ok": True, "written": str(OUTPUT_FILE)})
        except Exception as exc:
            write_message({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
