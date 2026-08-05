#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.dialogue.body_adapter import SubjectPerformanceBodyAdapter  # noqa: E402


def main() -> int:
    path = ROOT / "body" / "SubjectPerformanceFrame.cs"
    source = path.read_text(encoding="utf-8")
    expected = {
        f'Protocol = "{SubjectPerformanceBodyAdapter.PROTOCOL}"': "protocol",
        f"CurrentSchemaVersion = {SubjectPerformanceBodyAdapter.SCHEMA_VERSION}": "schema version",
        f"MaxBodyCues = {SubjectPerformanceBodyAdapter.MAX_BODY_CUES}": "body cue limit",
        f"MaxTextField = {SubjectPerformanceBodyAdapter.MAX_TEXT_FIELD}": "text limit",
    }
    missing = [label for needle, label in expected.items() if needle not in source]
    if missing:
        print("BODY CONTRACT CHECK FAILED:", ", ".join(missing))
        return 1
    print("BODY CONTRACT CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
