# -*- coding: utf-8 -*-
"""Chạy benchmark JSONL cho living user memory.

Ví dụ:
    python tools/benchmark_living_user_memory.py config/memory_benchmark_cases_vi.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.living_user import LivingUserMemoryBenchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark living user memory")
    parser.add_argument("cases", help="File JSONL benchmark")
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--max-false-memory", type=float, default=0.05)
    args = parser.parse_args()

    runner = LivingUserMemoryBenchmark()
    metrics = runner.run(runner.load_cases(args.cases))
    print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
    healthy = metrics.recall_at_k >= args.min_recall and metrics.false_memory_rate <= args.max_false_memory
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(main())
