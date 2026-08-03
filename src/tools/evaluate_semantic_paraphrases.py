# -*- coding: utf-8 -*-
"""Chấm dataset paraphrase semantic bằng contract expected-values."""
from __future__ import annotations

from typing import Any, Mapping


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def evaluate(dataset: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cases = [item for item in dataset.get("cases", ()) if isinstance(item, Mapping)]
    details: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        case_id = str(case.get("id", "") or "")
        expected = case.get("expect", {}) if isinstance(case.get("expect"), Mapping) else {}
        predicted = predictions.get(case_id, {})
        mismatches = [
            key for key, value in expected.items()
            if not _matches(predicted.get(key), value)
        ]
        ok = not mismatches
        passed += int(ok)
        details.append({"id": case_id, "ok": ok, "mismatches": mismatches})
    count = len(cases)
    accuracy = passed / count if count else 0.0
    return {
        "schema": "eris.semantic_paraphrase_evaluation.v1",
        "sample_count": count,
        "passed": passed,
        "accuracy": round(accuracy, 6),
        "acceptance_ge_95_percent": accuracy >= 0.95,
        "details": details,
    }


__all__ = ["evaluate"]
