from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.eval_suite import GoldenEvalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy golden conversational suite của ERIS")
    parser.add_argument("--cases", default="evals/social_policy_golden.jsonl")
    parser.add_argument("--output", default="evals/results/social_policy_report.json")
    parser.add_argument("--min-pass-rate", type=float, default=0.95)
    args = parser.parse_args()

    runner = GoldenEvalRunner()
    report = runner.run_file(args.cases)
    runner.write_report(report, args.output)
    summary = report.summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if float(summary["pass_rate"]) >= max(0.0, min(1.0, args.min_pass_rate)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
