# -*- coding: utf-8 -*-
"""Đọc trace journal và in timeline debug dễ hiểu."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.living_user import LivingUserMemoryService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay living user memory trace")
    parser.add_argument("--memory-dir", default="memory_core")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = LivingUserMemoryService(args.memory_dir).replay_report(limit=max(1, args.limit))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Events: {report.event_count}")
        print(f"Operations: {report.operation_count}; rejected: {report.rejected_count}")
        print(f"Context compilations: {report.context_compilations}")
        for line in report.timeline:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
