# -*- coding: utf-8 -*-
"""Regression tests cho PrivateMindDaemon.

Các test này khóa 3 ý chính:
- daemon sở hữu lifecycle/queue thay vì coordinator tự ôm từng mảnh;
- EvidenceDossier đủ dày để evaluator không phải bói từ input nghèo;
- StateMutationBus không được bypass SurfaceValve bằng cách enqueue raw candidate.
"""

from __future__ import annotations

from types import SimpleNamespace

from cortex.private_mind.evidence_dossier import EvidenceDossierBuilder
from runtime.private_mind_daemon import PrivateMindDaemon
from runtime.private_mind_loop import PrivateMindLoop, PrivateMindLoopConfig


class _Agenda:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, **kwargs):
        self.items.append(kwargs)
        return SimpleNamespace(to_dict=lambda: kwargs)

    def top_items(self, limit: int = 5):
        return self.items[-limit:]


class _Owner:
    pass


def _loop() -> PrivateMindLoop:
    return PrivateMindLoop(
        config=PrivateMindLoopConfig(min_interval_seconds=0, log_ticks=False),
        model_adapter=None,
        logger=None,
    )


def test_private_mind_daemon_ticks_and_owns_surface_queue() -> None:
    owner = _Owner()
    daemon = PrivateMindDaemon(loop=_loop(), runtime_owner=owner)
    tick = daemon.tick(
        user_text="Thiếu PrivateMindDaemon và StateMutationBus thật.",
        channel="chat",
        snapshot=SimpleNamespace(active_app="VS Code", focus_summary="ERIS private mind"),
        observer_frame=SimpleNamespace(
            summary="editing architecture",
            novelty=0.85,
            repetition=0.05,
            possible_error=0.35,
            user_presence=0.8,
            focus_kind="code",
        ),
        wake_decision=SimpleNamespace(
            level="think_only",
            should_speak=False,
            speech_value=0.2,
            interrupt_cost=0.15,
            budget_reason="ok",
        ),
        internal_agenda=_Agenda(),
        thought_stream=SimpleNamespace(private_mind_pressure_bias=0.1),
        runtime_owner=owner,
        force=True,
    )

    assert tick is not None and tick.ticked is True
    assert getattr(owner, "private_mind_surface_queue") is daemon.surface_queue
    # Chỉ SurfaceValve được quyền đẩy seed ra queue. Raw judgment.surface_candidate
    # không được StateMutationBus ném thẳng vào, kẻo private chain đội lốt public.
    assert len(daemon.surface_queue) <= 1
    digest = daemon.digest()
    assert digest["daemon"]["surface_queue_size"] == len(daemon.surface_queue)
    assert digest["inner_diary"]["title"] == "Inner Diary"
    assert isinstance(digest["inner_diary"]["text"], str)


def test_evidence_dossier_contains_private_runtime_and_thought_substrate() -> None:
    owner = _Owner()
    owner.private_mind_speech_bias = {"direct": {"confidence": 0.7, "value": {"preference": "answer directly"}}}
    owner.private_mind_inquiry_plan = [{"value": "check mutation path"}]
    owner.private_mind_active_state = {"theme": "private mind"}
    owner.private_mind_thought_pressure = 0.42
    thought_stream = SimpleNamespace(private_mind_pressure_bias=0.33, cognitive_momentum=0.5, unresolved_pressure=0.4)

    dossier = EvidenceDossierBuilder().build(
        user_text="Dossier phải đủ dày.",
        channel="chat",
        snapshot=SimpleNamespace(active_app="VS Code", focus_summary="private mind files"),
        observer_frame=SimpleNamespace(novelty=0.7, repetition=0.1, possible_error=0.2, focus_kind="code"),
        wake_decision=SimpleNamespace(level="think_only", speech_value=0.2, interrupt_cost=0.1),
        thought_stream=thought_stream,
        runtime_owner=owner,
        surface_candidate_queue=[{"id": "s1", "kind": "private_mind_surface", "topic_seed": "seed"}],
    )

    runtime = dossier.runtime_state
    assert runtime["thought_stream"]["private_mind_pressure_bias"] == 0.33
    assert runtime["private_runtime"]["thought_pressure"] == 0.42
    assert runtime["surface_queue"]["size"] == 1
    assert dossier.metadata["dossier_thickness"] > 0


def test_outcome_feedback_updates_concern_lifecycle() -> None:
    daemon = PrivateMindDaemon(loop=_loop(), runtime_owner=_Owner())
    daemon.tick(
        user_text="Private concern phải sống qua tick.",
        channel="chat",
        snapshot=SimpleNamespace(active_app="VS Code", focus_summary="concern lifecycle"),
        observer_frame=SimpleNamespace(novelty=0.8, repetition=0.0, possible_error=0.3, user_presence=0.8, focus_kind="code"),
        wake_decision=SimpleNamespace(level="think_only", speech_value=0.1, interrupt_cost=0.1, budget_reason="ok"),
        force=True,
    )
    reports = daemon.record_outcome(
        {"user_corrected": True, "action_success": 0.4, "body_match_success": 0.9, "evidence": ["ev.test"]},
        frame=SimpleNamespace(channel="chat", cycle_id="c1", debug_notes=[], final_decision={"text": "x", "should_speak": True}),
    )

    assert reports
    assert daemon.digest()["daemon"]["outcome_feedback_reports"]
