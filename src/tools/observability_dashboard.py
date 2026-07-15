from __future__ import annotations

import sys
import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runtime.observability import ErisObservability


def main() -> int:
    parser = argparse.ArgumentParser(description="Xuất dashboard JSON từ ERIS observability JSONL")
    parser.add_argument("--input", default="logs/eris_observability.jsonl")
    parser.add_argument("--output", default="logs/eris_dashboard_snapshot.json")
    args = parser.parse_args()
    store = ErisObservability.replay_jsonl(args.input)
    target = store.export_snapshot(args.output)
    payload = store.dashboard_payload()
    counts = {name: len(metrics) for name, metrics in payload["dashboards"].items()}
    print(json.dumps({"output": str(target), "dashboard_metric_counts": counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
