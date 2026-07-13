# -*- coding: utf-8 -*-
"""Integration/regression tests for the canonical V3 completion layer."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.evidence import RawSignal, StateCommitRequest
from domain import Decision
from memory.memory_cognition import MemoryCognitionCore
from runtime.cognitive_pipeline import CognitivePipeline
from runtime.cognitive_runtime import CognitiveRuntime
from runtime.long_term_update import LongTermUpdateEngine
from runtime.state_committer import StateCommitter


def _plan(text: str, *, pipeline: CognitivePipeline | None = None, session_id: str = "canonical-test", snapshot=None, runtime_owner=None):
    pipeline = pipeline or CognitivePipeline()
    return pipeline, pipeline.run_from_signals(
        [RawSignal.from_chat(text)],
        channel="chat",
        user_text=text,
        session_id=session_id,
        snapshot=snapshot,
        runtime_owner=runtime_owner,
    )


def test_stage_suite_uses_dedicated_canonical_engines():
    pipeline = CognitivePipeline()
    stages = pipeline.stages
    expected = {
        "temporal_engine": "TemporalPerceptionEngine",
        "spatial_engine": "SpatialProprioceptionEngine",
        "homeostasis_engine": "HomeostasisEngine",
        "affect_engine": "AffectiveSubstrateEngine",
        "memory_engine": "MemoryCognitionAdapterEngine",
        "belief_engine": "BeliefCoreEngine",
        "value_engine": "ValueResolutionEngine",
        "simulation_engine": "PredictiveSimulationEngine",
        "arbitration_engine": "CognitiveArbitrationEngine",
        "agency_engine": "AgencyEngine",
        "permission_engine": "PermissionEngine",
        "noise_engine": "CalculatedNoiseEngine",
        "speech_planner_engine": "SpeechPlannerEngine",
        "body_planner_engine": "BodyActionPlannerEngine",
        "modality_engine": "ModalitySyncEngine",
    }
    assert {name: type(getattr(stages, name)).__name__ for name in expected} == expected


def test_temporal_engine_detects_real_recurrence_per_session():
    pipeline = CognitivePipeline()
    frames = []
    for _ in range(3):
        _, result = _plan("fix lại lỗi pipeline này", pipeline=pipeline, session_id="repeat-session")
        frames.append(result.frame)
    assert frames[0].temporal.recurrence == 0.0
    assert frames[2].temporal.recurrence >= 0.58
    assert frames[2].temporal.rhythm in {"repetitive", "escalating"}
    assert frames[2].temporal.repetition_fatigue > frames[0].temporal.repetition_fatigue


def test_spatial_engine_reads_renderer_telemetry_instead_of_pretending_defaults_are_observations():
    snapshot = SimpleNamespace(
        inferred_pos_x=0.17,
        inferred_pos_y=0.82,
        facing_x=-1.0,
        facing_y=0.0,
        gaze_target="code_editor",
        posture="focused",
        distance_to_focus=0.81,
        obstruction_risk=0.67,
        idle_seconds=2.0,
    )
    _, result = _plan("xem lỗi này", snapshot=snapshot)
    spatial = result.frame.spatial
    assert spatial.body_position == (0.17, 0.82)
    assert spatial.facing_direction[0] == -1.0
    assert spatial.gaze_target == "code_editor"
    assert spatial.obstruction_risk == 0.67
    assert spatial.shared_space_relation == "blocking"
    assert result.frame.body_plan.action not in {"step_closer", "approach_focus"}


def test_memory_adapter_calls_real_memory_cognition_core_when_available():
    class FakeMemoryCore:
        def __init__(self):
            self.calls = []

        def recall(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return SimpleNamespace(
                episodic=["đã sửa pipeline ở lượt trước"],
                semantic=["ERIS dùng V3"],
                relational=["user thích câu trả lời trực tiếp"],
                affective_residue=[],
                procedural=["kiểm test trước khi đóng gói"],
                temporal=[], spatial=[], worldview=[],
                confidence_notes=["retrieved-with-score"],
            )

    core = FakeMemoryCore()
    owner = SimpleNamespace(memory_cognition=core)
    _, result = _plan("tiếp tục sửa V3", runtime_owner=owner)
    packet = result.frame.memory_packet
    assert core.calls and core.calls[0][0] == "tiếp tục sửa V3"
    assert "ERIS dùng V3" in packet.semantic
    assert "kiểm test trước khi đóng gói" in packet.procedural
    assert any("MemoryCognitionCore" in note for note in packet.confidence_notes)


def test_cognitive_runtime_owns_guard_execution_outcome_and_commit(tmp_path: Path):
    memory = MemoryCognitionCore(str(tmp_path / "memory"))
    runtime = CognitiveRuntime(state_committer=StateCommitter(memory))

    def wording(frame, prompt_context):
        assert "[V3_COGNITIVE_PLAN]" in prompt_context
        return Decision(
            text="V3_COGNITIVE_PLAN nói rằng tôi có hidden state. Phần sửa hữu ích vẫn được giữ.",
            animation="stand",
            should_speak=True,
            confidence=0.9,
        )

    result = runtime.run_cycle(
        [RawSignal.from_chat("sửa lỗi này")],
        wording_adapter=wording,
        execution_adapter=lambda decision, frame: {"success": True, "played": bool(decision.text)},
        channel="chat",
        user_text="sửa lỗi này",
    )
    assert result.frame.status == "closed"
    assert result.frame.metadata["canonical_finalized_from_production"] is True
    assert "hidden state" not in result.decision.text.lower()
    assert "Phần sửa hữu ích" in result.decision.text
    assert result.frame.execution.status == "completed"
    assert result.frame.outcome is not None
    assert result.frame.self_observation is not None
    assert result.commit_report.committed >= 2
    assert (tmp_path / "memory" / "event_ledger.json").exists()
    assert (tmp_path / "memory" / "active_state_snapshot.json").exists()


def test_belief_and_worldview_commit_build_evidence_linked_concept_graph(tmp_path: Path):
    core = MemoryCognitionCore(str(tmp_path))
    requests = [
        StateCommitRequest(
            target="belief_core",
            content={"claim": "Eris uses canonical cognitive arbitration"},
            evidence_ids=["ev-1"],
            confidence=0.83,
            storage_permission=True,
            reason="test belief",
            source_module="test",
        ),
        StateCommitRequest(
            target="worldview_memory",
            content={"claim": "Grounding is more important than dramatic certainty"},
            evidence_ids=["ev-2"],
            confidence=0.86,
            storage_permission=True,
            reason="test worldview",
            source_module="test",
            decay_policy="slow",
        ),
    ]
    outcomes = core.commit_many(requests)
    assert all(item.outcome in {"accepted", "tentative"} and item.stored_id for item in outcomes)
    graph = core.concept_graph.load()
    assert "eris" in graph["nodes"]
    assert "grounding" in graph["nodes"]
    assert "ev-1" in graph["nodes"]["eris"]["evidence_ids"]
    assert graph["edges"]

    reloaded = MemoryCognitionCore(str(tmp_path))
    snapshot = reloaded.load()
    assert snapshot["belief_core"]
    assert snapshot["worldview_memory"]
    assert snapshot["concept_graph"]["nodes"]


def test_state_committer_routes_every_new_canonical_long_term_target(tmp_path: Path):
    pipeline, result = _plan("ghi lại nhịp canonical để test")
    frame = result.frame
    evidence_id = frame.evidence[0].id
    targets = {
        "sociocultural_memory": {"pattern": "Vietnamese technical register"},
        "spatial_memory": {"gaze_target": "editor"},
        "temporal_rhythm_memory": {"rhythm": "focused"},
        "body_rhythm_memory": {"action": "look_at_focus"},
        "tom_history": {"intent": "technical request", "overread_risk": 0.1},
        "homeostatic_baseline": {"energy_budget": 0.6},
        "self_continuity": {"principle": "grounding before performance"},
    }
    for target, content in targets.items():
        frame.add_commit_request(StateCommitRequest(
            target=target,
            content=content,
            evidence_ids=[evidence_id],
            confidence=0.78,
            storage_permission=True,
            source_module="test",
            reason=f"test {target}",
        ), actor="test")
    core = MemoryCognitionCore(str(tmp_path))
    report = StateCommitter(core).commit_frame(frame)
    committed_targets = {d.final_target for d in report.decisions if d.committed}
    assert set(targets).issubset(committed_targets)
    for filename in (
        "sociocultural_memory.json", "spatial_memory.json", "temporal_rhythm_memory.json",
        "body_rhythm_memory.json", "tom_history.json", "homeostatic_baseline.json",
        "self_continuity_memory.json",
    ):
        assert (tmp_path / filename).exists(), filename


def test_dream_scheduler_is_quiet_on_ordinary_turn_and_activates_on_correction():
    pipeline, result = _plan("giải thích module này")
    frame = pipeline.finalize_from_production(
        result,
        final_decision=Decision(text="Đây là giải thích kỹ thuật.", animation="stand", should_speak=True),
        execution={"success": True},
    ).frame
    first = frame.metadata["dream_schedule"]
    assert first["scheduled"] is False

    report = pipeline.outcome_observer.observe_user_feedback_for_previous_frame(
        frame, "không phải, ý tôi là sửa code", attach_to_frame=True
    )
    frame.self_observation = pipeline.self_observer.reflect(frame, outcome=report, attach_to_frame=False)
    decision, requests = LongTermUpdateEngine().prepare(frame)
    assert decision.scheduled is True
    assert "correction" in decision.tags
    assert requests
    targets = {req.target for req in requests}
    assert "temporal_rhythm_memory" in targets
    assert "episodic_memory" in targets


def test_long_term_update_deduplicates_same_consolidation_requests():
    pipeline, result = _plan("không phải, ý tôi là sửa tiếp phần V3")
    frame = pipeline.finalize_from_production(
        result,
        final_decision=Decision(text="Tôi sửa tiếp.", animation="stand", should_speak=True),
        execution={"success": True},
    ).frame
    frame.outcome = pipeline.outcome_observer.observe_user_feedback_for_previous_frame(
        frame, "sai, vẫn chưa đúng", attach_to_frame=True
    )
    frame.self_observation = pipeline.self_observer.reflect(frame, outcome=frame.outcome, attach_to_frame=False)
    engine = LongTermUpdateEngine()
    _, first = engine.prepare(frame)
    before = len(frame.commit_requests)
    _, second = engine.prepare(frame)
    assert first
    assert second == []
    assert len(frame.commit_requests) == before


def test_full_frame_has_all_canonical_slots_and_nonempty_audit_reports():
    pipeline, result = _plan("hoàn thành V3 full canonical rồi đóng gói")
    result = pipeline.finalize_from_production(
        result,
        final_decision=Decision(text="Đã hoàn thành và kiểm thử.", animation="stand", should_speak=True),
        execution={"success": True},
    )
    frame = result.frame
    slots = (
        "salience", "temporal", "spatial", "homeostasis", "affect", "working_memory", "workspace",
        "world_scene", "interpretation", "sociocultural", "meaning", "tom", "epistemic", "inquiry",
        "memory_packet", "belief", "value_resolution", "simulations", "arbitration", "agency",
        "relation", "permission", "noise", "speech_opportunity", "speech_plan", "body_plan", "modality",
        "wording", "grounding", "execution", "outcome", "self_observation",
    )
    assert all(getattr(frame, name) is not None for name in slots)
    assert frame.status == "closed"
    assert len(frame.module_reports) >= 30
    assert frame.debug_trace is not None
    assert frame.metadata["canonical_planning_complete"] is True
    assert frame.metadata["canonical_finalized_from_production"] is True


def test_state_committer_runs_decay_only_after_reflection_or_dream_commit():
    class FakeMemoryCore:
        def __init__(self):
            self.commits = []
            self.decay_calls = 0

        def commit(self, request, *, frame=None):
            self.commits.append(request)
            return {"accepted": True, "target": request.target}

        def decay_canonical_long_term(self):
            self.decay_calls += 1
            return {"belief_core": {"decayed": 1, "removed": 0}}

    # Ordinary committed state updates must not age the entire long-term model.
    _, ordinary = _plan("ghi active state bình thường")
    ordinary_frame = ordinary.frame
    ordinary_frame.commit_requests.clear()
    ordinary_frame.add_commit_request(StateCommitRequest(
        target="active_state",
        content={"goal": "ordinary update"},
        evidence_ids=[ordinary_frame.evidence[0].id],
        confidence=0.9,
        storage_permission=True,
        source_module="runtime",
        reason="ordinary active-state update",
    ), actor="test")
    core = FakeMemoryCore()
    StateCommitter(core).commit_frame(ordinary_frame)
    assert core.decay_calls == 0
    assert "canonical_decay" not in ordinary_frame.metadata

    # A dream consolidation request that survives the commit gate triggers one decay pass.
    _, dream = _plan("không phải, sửa lại pattern cũ")
    dream_frame = dream.frame
    dream_frame.commit_requests.clear()
    dream_frame.add_commit_request(StateCommitRequest(
        target="temporal_rhythm_memory",
        content={"rhythm": "repeated correction", "recurrence": 0.82},
        evidence_ids=[dream_frame.evidence[0].id],
        confidence=0.84,
        storage_permission=True,
        source_module="dream_consolidation",
        tags=["dream_consolidation", "correction"],
        reason="consolidate repeated correction pattern",
    ), actor="test")
    report = StateCommitter(core).commit_frame(dream_frame)
    assert report.committed == 1
    assert core.decay_calls == 1
    assert dream_frame.metadata["canonical_decay"]["trigger"] == "dream_consolidation"
    assert dream_frame.metadata["canonical_decay"]["result"]["belief_core"]["decayed"] == 1
