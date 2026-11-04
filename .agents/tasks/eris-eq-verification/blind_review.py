"""Mask condition/repetition and intent before qualitative review; no model call."""
import json
from pathlib import Path
import random

from probe import build

HERE = Path(__file__).resolve().parent
plan, _, _ = build(2)
keys = sorted((p["case"], p["condition"], p["repeat"]) for p in plan)
random.Random(71842).shuffle(keys)
identifiers = {key: f"E{i:02d}" for i, key in enumerate(keys, 1)}
payloads = {(p["case"], p["condition"], p["repeat"]): p["payload"] for p in plan}
clean = {p["case"]: p["payload"] for p in plan if p["condition"] == "clean_context"}
rows = [json.loads(line) for line in (HERE / "results.jsonl").read_text("utf-8").splitlines()]
latest = {(r["case"], r["condition"], r["repeat"]): r for r in rows if r.get("http_status") == 200}
review = []
mapping = []
for key, result in latest.items():
    payload = clean[key[0]]
    envelope = json.loads(payload["messages"][-1]["content"])
    history = payload["messages"][1:-1]
    parsed = result.get("parsed")
    reply = parsed.get("say") if isinstance(parsed, dict) else None
    if isinstance(parsed, dict) and {"emotion_target", "user_concern"} <= parsed.keys():
        reply = parsed
    review.append({"id": identifiers[key], "case": key[0],
                   "history": history, "current_user": envelope["event"]["text"],
                   "answer": reply if reply is not None else result.get("content"),
                   "has_public_reply": isinstance(parsed, dict) and parsed.get("kind") == "move" and bool(parsed.get("say"))})
    mapping.append({"id": identifiers[key], "case": key[0], "condition": key[1], "repeat": key[2]})
review.sort(key=lambda row: row["id"])
mapping.sort(key=lambda row: row["id"])
(HERE / "review_blind.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), "utf-8")
(HERE / "review_key.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
print("Review records:", len(review))
for row in review:
    print(row["id"], row["case"], json.dumps(row["answer"], ensure_ascii=False))
