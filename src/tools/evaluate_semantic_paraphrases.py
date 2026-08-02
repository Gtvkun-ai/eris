# -*- coding: utf-8 -*-
"""Score typed semantic-frame predictions against paraphrase alternatives."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def evaluate(dataset: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cases = dataset.get("cases", []) if isinstance(dataset, Mapping) else []
    correct = 0
    total = 0
    case_results = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("id", "") or "")
        expected = case.get("expect", {}) if isinstance(case.get("expect"), Mapping) else {}
        predicted = predictions.get(case_id, {}) if isinstance(predictions, Mapping) else {}
        fields = {}
        case_ok = True
        for field, allowed_raw in expected.items():
            allowed = allowed_raw if isinstance(allowed_raw, list) else [allowed_raw]
            actual = predicted.get(field) if isinstance(predicted, Mapping) else None
            ok = actual in allowed
            fields[field] = {"actual": actual, "allowed": allowed, "correct": ok}
            case_ok = case_ok and ok
        total += 1
        correct += int(case_ok)
        case_results.append({"id": case_id, "correct": case_ok, "fields": fields})
    accuracy = correct / total if total else 0.0
    return {
        "schema": "eris.semantic_paraphrase_eval.v1",
        "sample_count": total,
        "correct": correct,
        "accuracy": round(accuracy, 6),
        "acceptance_ge_95_percent": accuracy >= 0.95,
        "cases": case_results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("predictions")
    args = parser.parse_args(argv)
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    predictions = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(dataset, predictions), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
