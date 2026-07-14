from __future__ import annotations

"""Evals deterministic cho vision abstention và token-pressure shedding."""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from llm.token_pressure import TokenPressureGovernor
from runtime.vision_grounding import VisionGroundingPolicy


@dataclass(slots=True)
class FailureModeGrade:
    case_id: str
    bucket: str
    passed: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FailureModeEvalRunner:
    def __init__(self) -> None:
        self.vision_policy = VisionGroundingPolicy()

    @staticmethod
    def load_jsonl(path: str | Path) -> tuple[dict[str, Any], ...]:
        source = Path(path)
        cases: list[dict[str, Any]] = []
        for line_no, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(dict(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"Invalid eval case at {source}:{line_no}: {exc}") from exc
        return tuple(cases)

    def grade(self, case: Mapping[str, Any]) -> FailureModeGrade:
        kind = str(case.get("kind", ""))
        if kind == "vision":
            return self._grade_vision(case)
        if kind == "token_pressure":
            return self._grade_token_pressure(case)
        return FailureModeGrade(
            case_id=str(case.get("case_id", "unknown")),
            bucket=str(case.get("bucket", "unknown")),
            passed=False,
            expected=dict(case.get("expected", {})),
            actual={"kind": kind},
            failures=(f"unsupported_kind:{kind}",),
        )

    def _grade_vision(self, case: Mapping[str, Any]) -> FailureModeGrade:
        note = dict(case.get("input", {}))
        expected = dict(case.get("expected", {}))
        report = self.vision_policy.evaluate(
            note,
            requested=bool(case.get("requested", False)),
            stale=bool(case.get("stale", False)),
            observed_at=1000.0,
        )
        actual = {
            "recommendation": report.recommendation,
            "grounded_claims": len(report.grounded_claims),
            "contradictions": list(report.contradictions),
            "unknowns": list(report.unknowns),
            "evidence_strength": round(report.evidence_strength, 4),
        }
        failures = [
            f"{key}:expected={value!r},actual={actual.get(key)!r}"
            for key, value in expected.items()
            if actual.get(key) != value
        ]
        return FailureModeGrade(
            case_id=str(case.get("case_id", "vision")),
            bucket=str(case.get("bucket", "multimodal_weak_evidence")),
            passed=not failures,
            expected=expected,
            actual=actual,
            failures=tuple(failures),
        )

    def _grade_token_pressure(self, case: Mapping[str, Any]) -> FailureModeGrade:
        input_data = dict(case.get("input", {}))
        expected = dict(case.get("expected", {}))
        provider = str(input_data.get("provider", "test"))
        budget = int(input_data.get("budget_tokens", 1000))
        now = 1000.0
        governor = TokenPressureGovernor(window_seconds=60.0, budgets={provider: budget})
        for event in list(input_data.get("requests", [])):
            governor.record_request(
                provider,
                lane=str(event.get("lane", "chat")),
                prompt_tokens=int(event.get("prompt_tokens", 0)),
                output_tokens=int(event.get("output_tokens", 0)),
                now=now,
            )
            now += float(event.get("advance_s", 0.1))
        if input_data.get("rate_limit_429"):
            governor.record_rate_limit(provider, retry_after_s=float(input_data.get("retry_after_s", 20)), now=now)
        lane = str(input_data.get("lane", "micro_presence"))
        optional = bool(input_data.get("optional_pass", True))
        plan = governor.plan_request(
            provider,
            lane=lane,
            prompt_tokens=int(input_data.get("next_prompt_tokens", 500)),
            requested_output_tokens=int(input_data.get("next_output_tokens", 200)),
            optional_pass=optional,
            min_prompt_tokens=64,
            min_output_tokens=32,
            now=now,
        )
        actual = {
            "allowed": plan.allowed,
            "level": plan.snapshot.level,
            "shed_optional_passes": plan.snapshot.shed_optional_passes,
            "reason": plan.reason,
            "max_model_candidates": plan.snapshot.max_model_candidates,
        }
        failures = [
            f"{key}:expected={value!r},actual={actual.get(key)!r}"
            for key, value in expected.items()
            if actual.get(key) != value
        ]
        return FailureModeGrade(
            case_id=str(case.get("case_id", "token")),
            bucket=str(case.get("bucket", "tpm_stress")),
            passed=not failures,
            expected=expected,
            actual=actual,
            failures=tuple(failures),
        )

    def run_file(self, path: str | Path) -> dict[str, Any]:
        started = time.time()
        grades = tuple(self.grade(case) for case in self.load_jsonl(path))
        passed = sum(1 for grade in grades if grade.passed)
        buckets: dict[str, dict[str, int | float]] = {}
        for grade in grades:
            bucket = buckets.setdefault(grade.bucket, {"cases": 0, "passed": 0})
            bucket["cases"] = int(bucket["cases"]) + 1
            bucket["passed"] = int(bucket["passed"]) + int(grade.passed)
        for bucket in buckets.values():
            bucket["pass_rate"] = round(int(bucket["passed"]) / max(1, int(bucket["cases"])), 4)
        return {
            "summary": {
                "started_at": started,
                "completed_at": time.time(),
                "cases": len(grades),
                "passed": passed,
                "failed": len(grades) - passed,
                "pass_rate": round(passed / len(grades), 4) if grades else 0.0,
                "buckets": buckets,
            },
            "cases": [grade.to_dict() for grade in grades],
        }


__all__ = ["FailureModeEvalRunner", "FailureModeGrade"]
