# -*- coding: utf-8 -*-
"""CLI quản lý secret version cho Eris.

Ví dụ:
  python tools/manage_secret_versions.py stage v2026-07-15 config/secrets.next.json
  python tools/manage_secret_versions.py activate v2026-07-15
  python tools/manage_secret_versions.py rollback
  python tools/manage_secret_versions.py status

CLI chỉ in version/fingerprint, không in payload bí mật. Loài người đôi khi cần
được nhắc rằng console cũng là nơi rò dữ liệu.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from secret_versions import SecretVersionManager


def _status_payload(status) -> dict[str, object]:
    return {
        "active_version": status.active_version,
        "previous_version": status.previous_version,
        "pending_version": status.pending_version,
        "active_fingerprint": status.active_fingerprint,
        "updated_at": status.updated_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quản lý secret version Eris")
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="Ghi một version mới, không ghi đè")
    stage.add_argument("version")
    stage.add_argument("json_file", type=Path)

    activate = sub.add_parser("activate", help="Kích hoạt version cụ thể")
    activate.add_argument("version")

    sub.add_parser("rollback", help="Quay về previous_version")
    sub.add_parser("status", help="Xem manifest, không hiện secret")

    args = parser.parse_args()
    manager = SecretVersionManager()

    if args.command == "stage":
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
        fingerprint = manager.stage(args.version, payload)
        print(json.dumps({"staged_version": args.version, "fingerprint": fingerprint}, ensure_ascii=False))
        return 0
    if args.command == "activate":
        print(json.dumps(_status_payload(manager.activate(args.version)), ensure_ascii=False))
        return 0
    if args.command == "rollback":
        print(json.dumps(_status_payload(manager.rollback()), ensure_ascii=False))
        return 0
    print(json.dumps(_status_payload(manager.status()), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
