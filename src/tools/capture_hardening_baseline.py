# -*- coding: utf-8 -*-
"""Chụp baseline hardening từ log stable trước khi bật canary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.hardening_baseline import HardeningBaseline
from runtime.observability import ErisObservability


def main() -> int:
    parser = argparse.ArgumentParser(description="Chụp baseline hardening Eris từ observability JSONL")
    parser.add_argument("--input", default="logs/eris_observability.jsonl")
    parser.add_argument("--output", default="config/hardening_baseline.json")
    parser.add_argument("--min-turns", type=int, default=20)
    args = parser.parse_args()

    store = ErisObservability.replay_jsonl(args.input)
    baseline = HardeningBaseline.from_snapshot(store.metric_snapshot(), source=str(args.input))
    baseline.save(args.output)
    status = "ok" if baseline.public_turns >= max(1, args.min_turns) else "insufficient_samples"
    print(json.dumps({
        "status": status,
        "output": str(args.output),
        **baseline.to_dict(),
    }, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
