# -*- coding: utf-8 -*-
"""Khóa kiến trúc để Cortex legacy không lén mọc lại sau một lần refactor."""

from __future__ import annotations

import inspect
from pathlib import Path

import core
import cortex
from runtime.ai_orchestrated.orchestrator import architecture_c_enabled
from runtime.coordinator import RuntimeCoordinator


ROOT = Path(__file__).resolve().parents[1]


def test_cortex_v2_is_the_only_production_architecture() -> None:
    assert architecture_c_enabled() is True
    assert core.CognitiveFrame.__module__ == "core.cognition.contracts"
    assert not hasattr(cortex, "CognitiveFrame")


def test_legacy_cognition_spines_are_physically_absent() -> None:
    removed = (
        "runtime/cognitive_frame_recorder.py",
        "runtime/cognitive_pipeline.py",
        "runtime/canonical_cognition.py",
        "runtime/shadow_pipeline.py",
        "runtime/social_observer.py",
        "runtime/social_cognition_v2.py",
        "runtime/autonomous_cycle.py",
        "runtime/force_speak_cycle.py",
        "runtime/cognitive_cycle.py",
        "cortex/ni.py",
        "cortex/ti.py",
        "cortex/fe.py",
        "cortex/meaning",
        "cortex/tom",
        "cortex/tom_advisor.py",
    )
    assert [path for path in removed if (ROOT / path).exists()] == []


def test_runtime_coordinator_has_no_legacy_cognition_mixin_or_frame_state() -> None:
    mro_names = {item.__name__ for item in RuntimeCoordinator.__mro__}
    assert "CognitiveFrameRecorderMixin" not in mro_names
    source = inspect.getsource(RuntimeCoordinator)
    forbidden = (
        "last_cognitive_frame",
        "cognitive_frames",
        "cognitive_cycle_index",
        "self.ni_engine",
        "self.ti_engine",
        "self.fe_engine",
    )
    assert [token for token in forbidden if token in source] == []


def test_cortex_v2_wiring_exposes_one_brief_and_one_gate() -> None:
    from runtime.cognition import CognitiveAcceptanceGate, PreResponseCognition

    cognition = PreResponseCognition()
    brief = cognition.analyze(
        user_text="ehm, rồi sao á",
        recent_history=(
            {"role": "assistant", "content": "Tôi không ồn, nhưng cũng không dễ bị bỏ qua."},
        ),
        turn_id="architecture-test",
        turn_seq=1,
    )
    assert brief.discourse_relation == "continue_assistant_move"
    assert brief.ambiguity_owner == "assistant"
    assert brief.response_move == "self_elaborate"
    violations = CognitiveAcceptanceGate().validate(
        "Bạn muốn mình nói tiếp phần nào?",
        brief,
    )
    assert tuple(item.code for item in violations) == ("ASSISTANT_OWNED_AMBIGUITY_DEFLECTED",)
