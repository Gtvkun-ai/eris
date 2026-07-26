# -*- coding: utf-8 -*-
"""Score semantic-frame predictions against the PDF paraphrase suite.

PDF annotation, pages 17-19
---------------------------
The acceptance criterion requires >=95% correctness for Vietnamese greeting,
check-in and repair paraphrases.  This tool intentionally does not call a model;
it scores predictions captured from a real canary run, keeping evaluation
separate from generation and avoiding a self-grading model congratulating itself.

Prediction JSONL format::

    {"id":"checkin_01", "semantic_frame":{"user_act":"relational_check_in", ...}}
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} phải chứa JSON object")
    return payload


def _load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Prediction JSONL lỗi ở dòng {line_number}: {exc}") from exc
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id", "") or "").strip()
        frame = item.get("semantic_frame") if isinstance(item.get("semantic_frame"), dict) else item.get("frame")
        if case_id and isinstance(frame, dict):
            output[case_id] = dict(frame)
    return output


def _matches(actual: Any, allowed: Any) -> bool:
    actual_text = str(actual or "").strip().lower()
    options = allowed if isinstance(allowed, list) else [allowed]
    return actual_text in {str(value or "").strip().lower() for value in options}


def evaluate(dataset: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cases = list(dataset.get("cases", []) or [])
    results: list[dict[str, Any]] = []
    field_failures: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    category_passes: Counter[str] = Counter()

    for raw_case in cases:
        case = dict(raw_case or {})
        case_id = str(case.get("id", "") or "")
        category = case_id.split("_", 1)[0] if "_" in case_id else "unknown"
        category_counts[category] += 1
        frame = dict(predictions.get(case_id, {}) or {})
        expected = dict(case.get("expect", {}) or {})
        mismatches: list[str] = []
        for field, allowed in expected.items():
            if not _matches(frame.get(field), allowed):
                mismatches.append(field)
                field_failures[field] += 1
        passed = bool(frame) and not mismatches
        if passed:
            category_passes[category] += 1
        results.append({
            "id": case_id,
            "category": category,
            "passed": passed,
            "mismatches": mismatches,
            "predicted": {field: frame.get(field) for field in expected},
        })

    sample_count = len(cases)
    passed_count = sum(1 for item in results if item["passed"])
    accuracy = passed_count / sample_count if sample_count else 0.0
    return {
        "schema": "eris.semantic_paraphrase_eval.v1",
        "sample_count": sample_count,
        "prediction_count": len(predictions),
        "passed_count": passed_count,
        "accuracy": round(accuracy, 4),
        "acceptance_ge_95_percent": accuracy >= 0.95,
        "by_category": {
            category: {
                "sample_count": count,
                "passed_count": category_passes[category],
                "accuracy": round(category_passes[category] / count, 4) if count else 0.0,
            }
            for category, count in sorted(category_counts.items())
        },
        "field_failures": dict(sorted(field_failures.items())),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Đánh giá semantic frame trên tập paraphrase theo PDF")
    parser.add_argument("--dataset", default="tests/fixtures/semantic_paraphrases_vi.json")
    parser.add_argument("--predictions", required=True, help="JSONL semantic_frame từ canary")
    parser.add_argument("--output", default="", help="JSON kết quả; bỏ trống để in stdout")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    prediction_path = Path(args.predictions)
    if not dataset_path.exists():
        raise SystemExit(f"Không tìm thấy dataset: {dataset_path}")
    if not prediction_path.exists():
        raise SystemExit(f"Không tìm thấy predictions: {prediction_path}")
    report = evaluate(_load_json(dataset_path), _load_predictions(prediction_path))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(target)
    else:
        print(rendered)
    return 0 if report["acceptance_ge_95_percent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
