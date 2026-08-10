# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from cortex.subject.neuro_control import NeuroActionSelector
from cortex.subject.service import SubjectService, SubjectServiceConfig
from llm.client import _web_session_header
from runtime.ai_orchestrated.executive_cortex import ExecutiveCortex
from runtime.mind_loop import MindLoop
from runtime.inference_broker import inference_context
from runtime.subject_ingress import SubjectIngress


class Determinism:
    def __init__(self) -> None:
        self.now = 1000.0
        self.n = 0

    def clock(self) -> float:
        self.now += 0.01
        return self.now

    def id(self) -> str:
        self.n += 1
        return f"id-{self.n}"


def _frame():
    d = Determinism()
    service = SubjectService(
        config=SubjectServiceConfig(subject_id="eris", deterministic=True),
        clock=d.clock,
        id_factory=d.id,
    )
    session = SubjectIngress(service).prepare_user_session(
        "Kiểm tra giúp tôi.", created_at=d.clock(), turn_id="turn-neuro"
    )
    return d, service, session.frame


def test_fast_gate_commits_clear_winner_without_llm() -> None:
    d, service, frame = _frame()
    boosted = tuple(
        replace(item, score=(2.0 if index == 0 else -1.0), uncertainty=0.05)
        for index, item in enumerate(frame.coalitions)
    )
    frame = replace(frame, coalitions=boosted)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("routine action selection must not wake the LLM")

    executive = ExecutiveCortex(
        SimpleNamespace(), object(), invoke_structured=should_not_run, clock=d.clock
    )
    commit = executive.commit_subject_frame(frame, mode="interactive")
    assert commit is not None
    assert commit.source == "neuro_fast_gate"
    assert commit.selected_coalition_id == boosted[0].coalition_id
    assert commit.selected_proposal_ref == boosted[0].primary_proposal_ref
    MindLoop.run_sync(service.abandon_deliberation(frame, reason="test_cleanup"))


def test_homogeneous_social_tie_fast_commits_without_llm() -> None:
    d, service, frame = _frame()
    assert len(frame.coalitions) >= 2
    social = list(frame.coalitions[:2])
    social[0] = replace(
        social[0],
        action_kind="speak",
        score=1.0,
        uncertainty=0.78,
        arguments={
            **dict(social[0].arguments),
            "semantic_target": "reopen contact gently",
            "speech_act": "contact_bid",
        },
    )
    social[1] = replace(
        social[1],
        action_kind="speak",
        score=1.0,
        uncertainty=0.78,
        arguments={
            **dict(social[1].arguments),
            "semantic_target": "reopen contact with a second equivalent realization",
            "speech_act": "contact_bid",
        },
    )
    frame = replace(frame, coalitions=tuple(social))

    selection = NeuroActionSelector().select(frame)
    assert selection.margin < 0.075
    assert selection.entropy >= 0.82
    assert selection.requires_deliberation is False
    assert selection.reason == "fast_gate:homogeneous_social_tie"

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("homogeneous social tie must not wake the deliberator")

    executive = ExecutiveCortex(
        SimpleNamespace(), object(), invoke_structured=should_not_run, clock=d.clock
    )
    commit = executive.commit_subject_frame(frame, mode="autonomous")
    assert commit is not None
    assert commit.source == "neuro_fast_gate"
    MindLoop.run_sync(service.abandon_deliberation(frame, reason="test_cleanup"))


def test_deliberator_sees_ephemeral_indices_not_runtime_ids() -> None:
    d, service, frame = _frame()
    selector = NeuroActionSelector()
    selection = selector.select(frame)
    assert selection.requires_deliberation  # this real frame is intentionally ambiguous
    chosen_index = min(1, len(frame.coalitions) - 1)
    captured = {}

    def invoke(_client, **kwargs):
        captured.update(kwargs)
        payload = kwargs["payload"]
        assert all("coalition_id" not in choice for choice in payload["choices"])
        assert all("proposal" not in choice for choice in payload["choices"])
        return {
            "choice_index": chosen_index,
            "semantic_commitments": ["preserve the chosen semantic direction"],
            "cognitive_requests": [],
            "reason": "conflict resolved from current semantic choices",
            "confidence": 0.81,
            "review_conditions": [],
        }

    executive = ExecutiveCortex(
        SimpleNamespace(), object(), invoke_structured=invoke, clock=d.clock
    )
    commit = executive.commit_subject_frame(frame, mode="interactive")
    assert commit is not None
    assert commit.source == "neuro_deliberator"
    assert commit.selected_coalition_id == frame.coalitions[chosen_index].coalition_id
    assert captured["name"] == "eris_neuro_deliberation_interactive"
    MindLoop.run_sync(service.abandon_deliberation(frame, reason="test_cleanup"))


def test_invalid_deliberator_index_degrades_to_fast_gate_not_guessed_id() -> None:
    d, service, frame = _frame()
    fast = NeuroActionSelector().select(frame)

    def invoke(_client, **_kwargs):
        return {
            "choice_index": 999,
            "semantic_commitments": [],
            "cognitive_requests": [],
            "reason": "bad model output",
            "confidence": 0.9,
            "review_conditions": [],
        }

    executive = ExecutiveCortex(
        SimpleNamespace(), object(), invoke_structured=invoke, clock=d.clock
    )
    commit = executive.commit_subject_frame(frame, mode="interactive")
    assert commit is not None
    assert commit.source == "neuro_fast_gate_degraded"
    assert commit.selected_coalition_id == fast.winner(frame).coalition_id
    MindLoop.run_sync(service.abandon_deliberation(frame, reason="test_cleanup"))


def test_neuro_deliberation_lanes_are_provider_stateless(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_RUNTIME_SESSION_ID", "test-runtime")
    messages = [{"role": "system", "content": "bounded deliberator"}]
    with inference_context("neuro_deliberation_required", optional=False):
        assert _web_session_header(messages) == ""
    with inference_context("neuro_deliberation", optional=True):
        assert _web_session_header(messages) == ""
