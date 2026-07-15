from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


# ----------------------------------------------------------------------
# #3 — Inner life flows into speech: future_bias phải đồng bộ từ digest
#      sang các thuộc tính mà tầng wording đọc.
# ----------------------------------------------------------------------
def test_future_bias_syncs_from_digest_to_speech_attributes() -> None:
    from runtime.coordinator import RuntimeCoordinator

    sync = RuntimeCoordinator._sync_private_mind_future_bias
    obj = SimpleNamespace(
        private_mind_digest={
            "future_bias": {
                "speech_bias": {"tone": {"value": {"preference": "ấm hơn"}, "confidence": 0.7}},
                "inquiry_plan": [{"q": "hỏi về dự án"}],
                "thought_pressure": 0.42,
            }
        },
        private_mind_speech_bias={},
        private_mind_inquiry_plan=[],
        private_mind_thought_pressure=0.0,
    )

    sync(obj)

    assert obj.private_mind_speech_bias == {
        "tone": {"value": {"preference": "ấm hơn"}, "confidence": 0.7}
    }
    assert obj.private_mind_inquiry_plan == [{"q": "hỏi về dự án"}]
    assert obj.private_mind_thought_pressure == 0.42


def test_future_bias_sync_is_safe_on_empty_digest() -> None:
    from runtime.coordinator import RuntimeCoordinator

    sync = RuntimeCoordinator._sync_private_mind_future_bias
    obj = SimpleNamespace(
        private_mind_digest={},
        private_mind_speech_bias={},
        private_mind_inquiry_plan=[],
        private_mind_thought_pressure=0.0,
    )
    sync(obj)  # không ném lỗi, không đổi gì
    assert obj.private_mind_speech_bias == {}
    assert obj.private_mind_thought_pressure == 0.0


# ----------------------------------------------------------------------
# #4a — Trust tích lũy: quan hệ đã xây không reset về mức người lạ 0.25.
# ----------------------------------------------------------------------
def test_built_relationship_keeps_higher_trust_floor_across_gap() -> None:
    from cortex.relationship_dynamics import RelationshipDynamicsEngine

    engine = RelationshipDynamicsEngine()
    state = engine.create_state()
    state.familiarity = 0.80
    state.trust = 0.50

    engine._apply_gap_decay(state, hours=1000.0, notes=[])

    # earned_floor = 0.25 + 0.30*0.8 = 0.49 -> trust không rơi về 0.25.
    assert state.trust > 0.45


def test_stranger_relationship_still_collapses_to_baseline() -> None:
    from cortex.relationship_dynamics import RelationshipDynamicsEngine

    engine = RelationshipDynamicsEngine()
    state = engine.create_state()
    state.familiarity = 0.0
    state.ritual_strength = 0.0
    state.trust = 0.50

    engine._apply_gap_decay(state, hours=5000.0, notes=[])

    assert state.trust < 0.30  # về sát baseline người lạ


# ----------------------------------------------------------------------
# #4b — Bản sắc tích lũy: user tự khai trực tiếp -> belief ngay.
# ----------------------------------------------------------------------
def test_explicit_user_self_disclosure_becomes_counted_belief(tmp_path) -> None:
    from cortex.epistemic.kernel import EpistemicKernel
    from cortex.epistemic.store import EpistemicStore

    store = EpistemicStore(path=str(tmp_path / "epi.json"))
    kernel = EpistemicKernel(store)

    obs = kernel.observe(
        kind="user_message",
        content="tôi là kỹ sư phần mềm",
        source="user",
        directness=1.0,
        reliability=0.95,
        source_kind="user_direct",
        episode_id="ep1",
        independence_key="ep1:user_message:0",
    )
    hs = kernel.infer([obs])

    stored = kernel.record_explicit_user_facts(hs)
    assert len(stored) >= 1

    snap = kernel.user_model_snapshot()
    assert snap["belief_count"] >= 1


def test_private_mind_inference_does_not_create_counted_belief(tmp_path) -> None:
    # Suy diễn của ERIS (không phải direct_assertion) KHÔNG được tự thành belief.
    from cortex.epistemic.kernel import EpistemicKernel
    from cortex.epistemic.store import EpistemicStore

    store = EpistemicStore(path=str(tmp_path / "epi.json"))
    kernel = EpistemicKernel(store)

    obs = kernel.observe(
        kind="user_message",
        content="hôm nay trời đẹp nhỉ chắc bạn muốn đi chơi",
        source="user",
        directness=1.0,
        reliability=0.9,
        source_kind="user_direct",
        episode_id="ep1",
        independence_key="ep1:user_message:0",
    )
    hs = kernel.infer([obs])

    stored = kernel.record_explicit_user_facts(hs)
    assert stored == ()
    assert kernel.user_model_snapshot()["belief_count"] == 0
