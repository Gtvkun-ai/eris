# -*- coding: utf-8 -*-
"""Regression cho Phase 3 + Phase 4 subconscious workers.

Các test này không kiểm tra "ERIS nói hay". Chúng kiểm tra đúng thứ Phase 3/4
cần làm: sinh fragment có rễ, giữ private by default, phân biệt idle thô với
thời gian chủ quan, và không biến thiếu sensor thành drama public. Thật kỳ diệu,
code biết im đúng lúc lại phải có test.
"""

from __future__ import annotations

from cortex.subconscious import WorkerContext, build_phase1234_workers
from cortex.subconscious.workers import (
    DaydreamInjector,
    IndependentAgendaAgent,
    SpatialMindAgent,
    SubjectiveTimeAgent,
)
from runtime.subconscious_loop import SubconsciousLoop


def _kinds(fragments):
    return {fragment.kind for fragment in fragments}


def test_daydream_injector_requires_grounded_memory_and_idle_pressure():
    worker = DaydreamInjector()
    context = WorkerContext(
        frame={"idle_seconds": 520, "user_text": "làm phase 3 + 4 đi"},
        memory_packet={
            "episodic": ["User từng chê status ping rỗng"],
            "semantic": ["ERIS cần continuity có evidence"],
        },
        internal_state={"boredom": 0.70, "fatigue": 0.22},
        relation={"rupture": 0.0, "repair_need": 0.0},
        now=1234.0,
    )

    fragments = tuple(worker.run(context))

    assert _kinds(fragments) == {"poetic_association_fragment", "weird_but_grounded_link"}
    assert all(fragment.privacy_level == "private" for fragment in fragments)
    assert all(not fragment.surface_allowed for fragment in fragments)
    assert any("memory_node.0" in fragment.evidence_ids for fragment in fragments)
    assert "chưa phải truth" in fragments[0].content


def test_daydream_injector_stays_silent_when_only_idle_without_memory_roots():
    worker = DaydreamInjector()
    context = WorkerContext(
        frame={"idle_seconds": 800, "user_text": ""},
        memory_packet={},
        internal_state={"boredom": 0.90},
        relation={"rupture": 0.0},
        now=1234.0,
    )

    assert tuple(worker.run(context)) == ()


def test_independent_agenda_creates_private_threads_without_stealing_current_goal():
    worker = IndependentAgendaAgent()
    context = WorkerContext(
        frame={
            "idle_seconds": 760,
            "user_text": "vá phase sau nhưng đừng phá runtime",
            "active_goal": "giữ SubconsciousLoop testable trước khi cắm coordinator",
            "unresolved_loop": "micro presence không được thành đồng hồ biết reo",
        },
        memory_packet={"episodic": ["Phase 0 tạo blackboard/synthesizer"], "semantic": []},
        internal_state={"curiosity": 0.75, "boredom": 0.45},
        relation={"rupture": 0.0, "repair_need": 0.0},
        now=1234.0,
    )

    fragments = tuple(worker.run(context))
    kinds = _kinds(fragments)

    assert {"obsession_candidate", "private_research_thread", "unresolved_internal_loop"}.issubset(kinds)
    assert all(fragment.privacy_level == "private" for fragment in fragments if fragment.kind != "later_surface_candidate")
    assert all("cướp goal" in fragment.content or "Private research" in fragment.content or "Unresolved" in fragment.content or "Later" in fragment.content for fragment in fragments)


def test_spatial_mind_distinguishes_sensor_missing_from_blocked_or_timed_out():
    worker = SpatialMindAgent()
    permission_context = WorkerContext(
        frame={
            "spatial": {
                "obstruction_risk": 0.72,
                "visible_area": 0.40,
                "shared_space_relation": "blocking",
                "sensor_visibility": "permission_blocked",
            }
        },
        now=1234.0,
    )
    permission_fragments = tuple(worker.run(permission_context))
    assert "blind_frustration_seed" not in _kinds(permission_fragments)
    assert "space_compression" in _kinds(permission_fragments)

    timeout_context = WorkerContext(
        frame={
            "spatial": {
                "obstruction_risk": 0.30,
                "visible_area": 0.70,
                "shared_space_relation": "parallel",
                "sensor_visibility": "vision_timeout",
            }
        },
        now=1234.0,
    )
    timeout_fragments = tuple(worker.run(timeout_context))
    assert "blind_frustration_seed" in _kinds(timeout_fragments)
    seed = next(fragment for fragment in timeout_fragments if fragment.kind == "blind_frustration_seed")
    assert seed.privacy_level == "private"
    assert not seed.surface_allowed


def test_subjective_time_dilates_after_rupture_but_compresses_during_deep_work():
    worker = SubjectiveTimeAgent()
    rupture_context = WorkerContext(
        frame={"idle_seconds": 300, "user_text": ""},
        internal_state={"boredom": 0.45, "affective_residue": 0.55},
        relation={"rupture": 0.80, "repair_need": 0.70},
        now=1234.0,
    )
    rupture_fragments = tuple(worker.run(rupture_context))
    assert "time_dilation" in _kinds(rupture_fragments)
    dilation = next(fragment for fragment in rupture_fragments if fragment.kind == "time_dilation")
    assert "silence_after_rupture" in dilation.tags
    assert dilation.privacy_level == "private"

    deep_work_context = WorkerContext(
        frame={"idle_seconds": 300, "user_text": "fix test runtime phase code", "focus_family": "deep_work_code"},
        internal_state={"active_task_density": 0.85, "boredom": 0.05},
        relation={"rupture": 0.0, "repair_need": 0.0},
        now=1234.0,
    )
    deep_work_fragments = tuple(worker.run(deep_work_context))
    assert "time_compression" in _kinds(deep_work_fragments)
    assert "time_dilation" not in _kinds(deep_work_fragments)


def test_phase1234_workers_run_through_subconscious_loop_without_public_surface_by_default():
    loop = SubconsciousLoop(workers=build_phase1234_workers())
    result = loop.tick(
        frame={
            "idle_seconds": 640,
            "user_text": "làm phase 3 + 4 đi",
            "active_goal": "vá subconscious workers có test",
            "unresolved_loop": "presence không được thành timer",
            "spatial": {
                "obstruction_risk": 0.64,
                "visible_area": 0.45,
                "shared_space_relation": "blocking",
                "sensor_visibility": "context_shift_without_refresh",
            },
        },
        memory_packet={
            "episodic": ["Phase 0 tạo ThoughtFragment Blackboard Synthesizer"],
            "semantic": ["Phase 2 thêm Rehearsal và CuriosityGap"],
        },
        internal_state={"curiosity": 0.70, "boredom": 0.62, "active_task_density": 0.20},
        relation={"trust": 0.60, "rupture": 0.0, "repair_need": 0.0},
        now=1234.0,
    )

    assert result.submitted_count >= 8
    assert loop.subconscious_report is not None
    assert result.thought_object is not None
    # Mặc định Phase 3/4 tạo pressure private/background, không ép public speech.
    assert result.surface_seed is None or result.surface_seed.get("surface_allowed") is True
