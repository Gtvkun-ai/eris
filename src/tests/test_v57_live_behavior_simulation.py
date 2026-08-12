# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from experiments.v57_simulation.contracts import BehaviorScore, RunValidity, Scenario, ScenarioStep, TurnArtifact
from experiments.v57_simulation.quality import deterministic_failures, max_prior_similarity
from experiments.v57_simulation.report import write_report
from experiments.v57_simulation.runner import LiveSimulationRunner
from experiments.v57_simulation.scenarios import build_soak_scenario, select_scenarios


class _StubClient:
    is_simulation_stub = True


class _FakeHarness:
    provider = "stub"
    model = "unit-test"
    provider_real = False

    def __init__(self, *, run_root: Path, logger=None):
        self.run_root = run_root
        self.closed = False

    def judge_candidate_client(self):
        return _StubClient()

    def send_user(self, *, scenario_id, step_id, turn_index, day, text):
        return TurnArtifact(
            scenario_id=scenario_id,
            step_id=step_id,
            turn_index=turn_index,
            day=day,
            user_text=text,
            eris_text="Tôi hiểu ý bạn và sẽ bám đúng phần đó.",
            provider=self.provider,
            model=self.model,
            provider_real=self.provider_real,
            latency_ms=1.0,
        )

    def close(self):
        self.closed = True


class _FakeJudge:
    provider = "stub-judge"
    model = "unit-test"
    is_real = False

    def __init__(self, _client):
        pass

    def evaluate(self, **_kwargs):
        return BehaviorScore(
            relevance=95,
            coherence=95,
            naturalness=95,
            continuity=95,
            repair_quality=95,
            non_repetition=95,
            epistemic_calibration=95,
            relational_quality=95,
            total=95,
            passed=True,
            judge_provider=self.provider,
            judge_model=self.model,
            judge_real=False,
        )


def test_v57_mock_can_never_be_realism_pass(tmp_path: Path) -> None:
    scenario = Scenario(
        scenario_id="one",
        title="one",
        description="",
        steps=(ScenarioStep(step_id="s1", user_text="xin chào"),),
    )
    report = LiveSimulationRunner(
        run_root=tmp_path,
        harness_factory=_FakeHarness,
        judge_factory=_FakeJudge,
    ).run((scenario,))
    assert report.validity == RunValidity.INVALID_REALISM_RUN
    assert report.passed is False
    assert report.scenarios[0].turns[0].passed is False
    assert "public_reply_not_proven_real_provider" in report.scenarios[0].turns[0].deterministic_failures


def test_v57_repetition_guard_catches_near_duplicate() -> None:
    prior = ["Tôi hiểu chỗ này. Mình sẽ bám đúng phần state nhận thức của Eris."]
    current = "Tôi hiểu chỗ này, mình sẽ bám đúng phần state nhận thức của Eris."
    similarity = max_prior_similarity(current, prior)
    failures = deterministic_failures(
        user_text="ừ",
        eris_text=current,
        prior_replies=prior + [current],
        provider_real=True,
    )
    assert similarity > 0.85
    assert "near_duplicate_reply" in failures


def test_v57_builtin_restart_scenarios_exist() -> None:
    selected = select_scenarios(["goal_interruption_resume", "memory_restart"])
    assert len(selected) == 2
    assert any(step.restart_before for scenario in selected for step in scenario.steps)


def test_v57_report_contains_public_transcript(tmp_path: Path) -> None:
    scenario = Scenario(
        scenario_id="one",
        title="one",
        description="",
        steps=(ScenarioStep(step_id="s1", user_text="xin chào"),),
    )
    report = LiveSimulationRunner(
        run_root=tmp_path / "runs",
        harness_factory=_FakeHarness,
        judge_factory=_FakeJudge,
    ).run((scenario,))
    json_path, md_path = write_report(report, tmp_path / "reports")
    assert json_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "**User:** xin chào" in text
    assert "**Eris:** Tôi hiểu ý bạn" in text
    assert "INVALID_REALISM_RUN" in text


def test_v57_soak_builder_spans_days_and_real_restarts() -> None:
    scenario = build_soak_scenario(turns=35, restart_every=7)
    assert len(scenario.steps) == 35
    assert max(step.day for step in scenario.steps) == 7
    assert sum(1 for step in scenario.steps if step.restart_before) == 4
    assert all("soak" in step.tags for step in scenario.steps)
