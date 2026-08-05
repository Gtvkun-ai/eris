"""Evaluate typed semantic-frame predictions against accepted paraphrases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _accepted(expected: Any) -> tuple[Any, ...]:
    if isinstance(expected, list):
        return tuple(expected)
    return (expected,)


def evaluate(dataset: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cases = dataset.get("cases", ()) if isinstance(dataset, Mapping) else ()
    details: list[dict[str, Any]] = []
    field_totals: dict[str, int] = {}
    field_correct: dict[str, int] = {}
    correct_cases = 0
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            continue
        case_id = str(raw_case.get("id", "") or "")
        expected = raw_case.get("expect", {})
        expected = expected if isinstance(expected, Mapping) else {}
        prediction = predictions.get(case_id, {})
        prediction = prediction if isinstance(prediction, Mapping) else {}
        mismatches: dict[str, Any] = {}
        for field, accepted_raw in expected.items():
            accepted = _accepted(accepted_raw)
            observed = prediction.get(field)
            field_totals[field] = field_totals.get(field, 0) + 1
            if observed in accepted:
                field_correct[field] = field_correct.get(field, 0) + 1
            else:
                mismatches[field] = {"observed": observed, "accepted": list(accepted)}
        passed = not mismatches
        correct_cases += int(passed)
        details.append({"id": case_id, "passed": passed, "mismatches": mismatches})
    sample_count = len(details)
    accuracy = correct_cases / sample_count if sample_count else 0.0
    return {
        "schema": "eris.semantic_paraphrase_evaluation.v1",
        "sample_count": sample_count,
        "correct_count": correct_cases,
        "accuracy": round(accuracy, 6),
        "acceptance_ge_95_percent": sample_count > 0 and accuracy >= 0.95,
        "field_accuracy": {
            field: round(field_correct.get(field, 0) / total, 6) if total else 0.0
            for field, total in sorted(field_totals.items())
        },
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    report = evaluate(dataset, predictions)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["acceptance_ge_95_percent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
