"""Produce condition-masked utterances. Does not invoke a model."""
import json
from pathlib import Path
import random
import argparse

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--suffix", default="")
args = parser.parse_args()
stem = f"ab{args.suffix}"
plan = json.loads((HERE / f"{stem}_plan.json").read_text("utf-8"))
keys = sorted((t["case"], t["condition"], t["repeat"]) for t in plan)
random.Random(99183 if args.suffix else 87781).shuffle(keys)
ids = {key: f"{'C' if args.suffix else 'B'}{i:02d}" for i, key in enumerate(keys, 1)}
rows = [json.loads(line) for line in (HERE / f"{stem}_results.jsonl").read_text("utf-8").splitlines()]
review = []
mapping = []
for r in rows:
    if r.get("http_status") != 200:
        continue
    key = (r["case"], r["condition"], r["repeat"])
    parsed = r.get("parsed")
    if not isinstance(parsed, dict) and r["content"].lstrip().startswith("```"):
        try:
            parsed = json.loads("\n".join(r["content"].strip().splitlines()[1:-1]))
        except ValueError:
            pass
    review.append({"id": ids[key], "case": r["case"], "answer":
                   parsed.get("say", r["content"]) if isinstance(parsed, dict) else r["content"]})
    mapping.append({"id": ids[key], "case": r["case"], "condition": r["condition"], "repeat": r["repeat"]})
review.sort(key=lambda x: x["id"])
mapping.sort(key=lambda x: x["id"])
(HERE / f"{stem}_review_blind.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), "utf-8")
(HERE / f"{stem}_review_key.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
for row in review:
    print(row["id"], row["case"], json.dumps(row["answer"], ensure_ascii=False))
