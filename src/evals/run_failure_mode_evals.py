from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.failure_mode_evals import FailureModeEvalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy vision/TPM failure-mode evals của ERIS")
    parser.add_argument("--cases", default="evals/failure_modes_golden.jsonl")
    parser.add_argument("--output", default="evals/results/failure_modes_report.json")
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    report = FailureModeEvalRunner().run_file(args.cases)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if float(report["summary"]["pass_rate"]) >= args.min_pass_rate else 2


if __name__ == "__main__":
    raise SystemExit(main())
