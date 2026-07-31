#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test tool: đọc browser_dom_state.json và in ra trạng thái hiện tại.

Dùng để kiểm tra extension + native host đang hoạt động đúng chưa.
"""
import json
import os
import time
from pathlib import Path


def find_cache_file() -> Path | None:
    candidates = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidates.append(Path(local_app) / "ERIS" / "browser_dom_state.json")
    candidates.append(Path.cwd() / "browser_dom_state.json")
    candidates.append(Path.cwd() / "memory_core" / "browser_dom_state.json")
    for p in candidates:
        if p.exists():
            return p
    return None


def main():
    print("ERIS Browser Bridge — Status Monitor")
    print("=" * 50)
    path = find_cache_file()
    if path is None:
        print("[ERROR] Khong tim thay browser_dom_state.json")
        print("  → Kiem tra extension da load va native host da cai chua.")
        return

    print(f"File: {path}")
    print()

    while True:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = float(data.get("timestamp", 0) or 0)
            age = time.time() - ts if ts > 0 else 9999
            print(f"\r[{age:.1f}s ago] URL: {str(data.get('url',''))[:50]:50} | "
                  f"Media: {str(data.get('media_title','(none)'))[:30]:30} | "
                  f"State: {data.get('media_state','?')}", end="", flush=True)
        except Exception as e:
            print(f"\r[ERROR] {e}", end="", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDone.")
