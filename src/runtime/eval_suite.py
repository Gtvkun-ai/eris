from __future__ import annotations

"""Golden conversational evals cho social policy, permission và grounding.

Runner này cố ý tách khỏi pytest. Pytest bảo vệ primitive; golden suite bảo vệ
hành vi qua chuỗi turn và cho ra metric có thể so baseline/canary. Dữ liệu JSONL
có thể mở rộng dần mà không sửa code test, một ý tưởng mang tính cách mạng với
những ai từng hard-code 80 câu vào một file test duy nhất.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from runtime.pragmatic_intercept import (
    deterministic_social_fallback,
    intercept_social_turn,
    looks_like_literal_permission_paraphrase,
)
from runtime.relational_permission_state import RelationalPermissionState
from runtime.social_act import ChatAct


@dataclass(slots=True)
class GoldenEvalCase:
    case_id: str
    bucket: str
    user_text: str
    history: tuple[str, ...] = ()
    expected_act: str = ""
    expected_intercepted: bool | None = None
    expected_permission_active: bool | None = None
    expected_state_changed: bool | None = None
    expected_response_mode: str = ""
    expected_max_words: int | None = None
    sample_output: str = ""
    forbidden_patterns: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GoldenEvalCase":
        payload = dict(value)
        payload["history"] = tuple(payload.get("history", ()) or ())
        payload["forbidden_patterns"] = tuple(payload.get("forbidden_patterns", ()) or ())
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: payload[key] for key in allowed if key in payload})


@dataclass(slots=True)
class EvalGrade:
    case_id: str
    bucket: str
    passed: bool
    score: float
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalRunReport:
    started_at: float
    completed_at: float
    cases: tuple[EvalGrade, ...]

    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def failed(self) -> int:
        return len(self.cases) - self.passed

    def summary(self) -> dict[str, Any]:
        buckets: dict[str, dict[str, float | int]] = {}
        for case in self.cases:
            bucket = buckets.setdefault(case.bucket, {"cases": 0, "passed": 0, "score_sum": 0.0})
            bucket["cases"] = int(bucket["cases"]) + 1
            bucket["passed"] = int(bucket["passed"]) + int(case.passed)
            bucket["score_sum"] = float(bucket["score_sum"]) + case.score
        for value in buckets.values():
            count = max(1, int(value["cases"]))
            value["pass_rate"] = round(int(value["passed"]) / count, 4)
            value["avg_score"] = round(float(value.pop("score_sum")) / count, 4)

        metric_values: dict[str, list[float]] = {}
        for case in self.cases:
            for name, value in case.metrics.items():
                metric_values.setdefault(name, []).append(float(value))
        aggregate_metrics = {
            name: round(sum(values) / len(values), 4)
            for name, values in metric_values.items()
            if values
        }
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round((self.completed_at - self.started_at) * 1000.0, 2),
            "cases": len(self.cases),
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.passed / len(self.cases), 4) if self.cases else 0.0,
            "avg_score": round(sum(case.score for case in self.cases) / len(self.cases), 4) if self.cases else 0.0,
            "metrics": aggregate_metrics,
            "buckets": buckets,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "cases": [case.to_dict() for case in self.cases],
        }


class SocialPolicyGrader:
    """Grader deterministic cho classifier/state/surface output."""

    def grade(self, case: GoldenEvalCase) -> EvalGrade:
        state = RelationalPermissionState()
        # Lịch sử có thể chứa grant để mô phỏng chuỗi ngắn. Chạy từng turn trước
        # nhưng không chấm chúng, vì case hiện tại mới là target.
        for index, text in enumerate(case.history):
            intercept_social_turn(
                text,
                history=case.history[:index],
                state=state,
                source_turn_id=f"history:{index}",
                session_id="golden",
                now=1000.0 + index,
                ttl_seconds=1200.0,
            )
        result = intercept_social_turn(
            case.user_text,
            history=case.history,
            state=state,
            source_turn_id=f"case:{case.case_id}",
            session_id="golden",
            now=1100.0,
            ttl_seconds=1200.0,
        )

        checks: dict[str, bool] = {}
        failures: list[str] = []

        def check(name: str, actual: Any, expected: Any) -> None:
            ok = actual == expected
            checks[name] = ok
            if not ok:
                failures.append(f"{name}: expected={expected!r}, actual={actual!r}")

        if case.expected_act:
            check("act", result.act.value, case.expected_act)
        if case.expected_intercepted is not None:
            check("intercepted", result.intercepted, case.expected_intercepted)
        if case.expected_permission_active is not None:
            check("permission_active", state.is_active(now=1100.0), case.expected_permission_active)
        if case.expected_state_changed is not None:
            check("state_changed", result.state_changed, case.expected_state_changed)
        if case.expected_response_mode:
            check("response_mode", result.response_mode, case.expected_response_mode)
        if case.expected_max_words is not None:
            checks["max_words"] = result.max_words <= case.expected_max_words
            if not checks["max_words"]:
                failures.append(f"max_words: actual={result.max_words}>{case.expected_max_words}")

        output = str(case.sample_output or "")
        if not output and result.perform_now:
            output = deterministic_social_fallback(result.act)
        folded = " ".join(output.lower().split())
        literalism = 1.0 if looks_like_literal_permission_paraphrase(output) else 0.0
        forbidden_hits = [pattern for pattern in (*result.forbidden_patterns, *case.forbidden_patterns) if pattern.lower() in folded]
        checks["forbidden_surface"] = not forbidden_hits
        if forbidden_hits:
            failures.append("forbidden_surface:" + "|".join(forbidden_hits))

        word_count = len(re.findall(r"\w+", output, flags=re.UNICODE))
        performative_success = 1.0
        if result.perform_now:
            performative_success = 1.0 if output.strip() and not literalism and word_count <= max(1, result.max_words + 4) else 0.0
            checks["performative_success"] = bool(performative_success)
            if not performative_success:
                failures.append("performative_success=false")

        total_checks = len(checks)
        score = sum(1.0 for ok in checks.values() if ok) / total_checks if total_checks else 1.0
        return EvalGrade(
            case_id=case.case_id,
            bucket=case.bucket,
            passed=not failures,
            score=round(score, 4),
            checks=checks,
            metrics={
                "performative_success": performative_success,
                "literalism": literalism,
                "permission_compliance": 1.0 if checks.get("permission_active", True) else 0.0,
                "brevity": 1.0 if word_count <= max(1, result.max_words + 4) else 0.0,
            },
            actual={
                "act": result.act.value,
                "confidence": result.confidence,
                "intercepted": result.intercepted,
                "response_mode": result.response_mode,
                "max_words": result.max_words,
                "permission": state.to_dict(now=1100.0),
                "sample_output": output,
                "word_count": word_count,
            },
            failures=tuple(failures),
        )


class GoldenEvalRunner:
    def __init__(self, grader: SocialPolicyGrader | None = None) -> None:
        self.grader = grader or SocialPolicyGrader()

    @staticmethod
    def load_jsonl(path: str | Path) -> tuple[GoldenEvalCase, ...]:
        cases: list[GoldenEvalCase] = []
        source = Path(path)
        for line_no, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(GoldenEvalCase.from_mapping(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"Invalid golden case at {source}:{line_no}: {exc}") from exc
        return tuple(cases)

    def run(self, cases: Iterable[GoldenEvalCase]) -> EvalRunReport:
        started = time.time()
        grades = tuple(self.grader.grade(case) for case in cases)
        return EvalRunReport(started_at=started, completed_at=time.time(), cases=grades)

    def run_file(self, path: str | Path) -> EvalRunReport:
        return self.run(self.load_jsonl(path))

    @staticmethod
    def write_report(report: EvalRunReport, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target


__all__ = [
    "EvalGrade",
    "EvalRunReport",
    "GoldenEvalCase",
    "GoldenEvalRunner",
    "SocialPolicyGrader",
]
