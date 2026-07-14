from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.social_intent_head import SocialIntentHeadModel


def main() -> int:
    parser = argparse.ArgumentParser(description="Train social intent head nhẹ cho ERIS")
    parser.add_argument("--data", default="evals/social_intent_training.jsonl")
    parser.add_argument("--output", default="models/social_intent_head.json")
    parser.add_argument("--alpha", type=float, default=0.8)
    args = parser.parse_args()
    samples: list[tuple[str, str]] = []
    for raw in Path(args.data).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        samples.append((str(item["text"]), str(item["label"])))
    model = SocialIntentHeadModel.fit(samples, alpha=args.alpha)
    model.save(args.output)
    print(json.dumps({"samples": len(samples), "labels": model.labels, "output": args.output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
