# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.opening_contracts import OpeningInput, OpeningPlan

from tests.opening_test_helpers import make_opening_input


def test_opening_input_strips_cross_session_summary_without_consent() -> None:
    opening_input = make_opening_input()
    assert opening_input.schema == "opening_input.v1"
    assert opening_input.continuity.consent_scope == "session_only"
    assert opening_input.continuity.last_session_summary == ""
    assert opening_input.screen_evidence[0].evidence_id == "screen:facebook"


def test_opening_contract_roundtrip_is_typed_and_bounded() -> None:
    raw = {
        "decision": "speak",
        "plan_id": "opening-test",
        "encounter": {"kind": "plain_return", "required": True},
        "vibe": {"family": "anime_dry_warm", "intensity": 4, "warmth": -2},
        "beats": [
            {
                "beat_id": f"b{index}",
                "role": "recognition" if index == 1 else "presence",
                "objective": "test",
                "semantic_content": "test",
                "pause_after_ms": 9000,
            }
            for index in range(1, 6)
        ],
        "surface_contract": {"max_sentences": 99, "max_questions": 99},
    }
    plan = OpeningPlan.from_mapping(raw)
    assert len(plan.beats) == 3
    assert plan.vibe_intensity == 1.0
    assert plan.vibe_warmth == 0.0
    assert plan.surface_contract.max_sentences == 3
    assert plan.surface_contract.max_questions == 1
    assert all(beat.pause_after_ms <= 1200 for beat in plan.beats)
    assert OpeningPlan.from_mapping(plan.to_dict()).beat_shape == plan.beat_shape
