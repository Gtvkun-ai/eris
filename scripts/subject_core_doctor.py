#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory.subject.repository import SubjectRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Subject Core SQLite integrity and optionally create a verified backup.")
    parser.add_argument("database", type=Path, help="Path to subject.db")
    parser.add_argument("--backup", type=Path, help="Optional destination for a verified SQLite backup")
    parser.add_argument("--persist-checkpoint", action="store_true", help="Append the report to subject_integrity_checkpoints")
    args = parser.parse_args()

    if not args.database.exists():
        parser.error(f"database does not exist: {args.database}")
    repo = SubjectRepository(args.database)
    try:
        report = repo.integrity_report(persist=args.persist_checkpoint)
        if args.backup:
            report["backup"] = str(repo.backup_to(args.backup))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("ok") else 2
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
