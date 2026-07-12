from __future__ import annotations

import json

from llm.json_sanitizer import strip_reasoning_envelope
from llm.key_pool import ApiKeyPool
from llm.service import LlmService
from memory.memory_commit_policy import MemoryCommitPolicy
from memory.memory_query_executor import MemoryQueryExecutor
from memory.memory_query_ir import MemoryQueryIR, MemorySelector, QueryIntent
from memory.name_validation import is_plausible_user_name, is_valid_name_claim


def _decision_json(text: str = "Được.") -> str:
    return json.dumps(
        {
            "text": text,
            "intent": "chat",
            "action": "",
            "animation": "stand",
            "reasoning_tags": ["direct"],
            "should_speak": True,
            "confidence": 0.9,
            "direction": 0,
            "target_x": -1.0,
            "bounce_action": "",
            "extracted_fact": "",
            "debug_trace": "ok",
            "next_animation": "",
            "system_action": "",
            "action_input": "",
            "delivery_hint": "",
            "nonverbal_cue": "",
            "stage_motion": "",
        },
        ensure_ascii=False,
    )


def test_qwen_think_prefix_is_removed_before_strict_format_gate() -> None:
    payload = _decision_json()
    raw = f"<think>phân tích dài và có ví dụ {{\"x\": 1}}</think>\n```json\n{payload}\n```"

    assert strip_reasoning_envelope(raw) == payload

    service = object.__new__(LlmService)
    candidate = service._strict_decision_candidate_or_raise(raw, channel="chat")
    assert json.loads(candidate)["text"] == "Được."


def test_qwen_unclosed_think_uses_last_valid_json_object() -> None:
    payload = _decision_json("Không retry nữa.")
    raw = f"<think>draft {{\"not\": \"the answer\"}}\n{payload}"
    assert strip_reasoning_envelope(raw) == payload


def test_key_pool_stops_rotation_after_cross_key_429_burst(monkeypatch) -> None:
    monkeypatch.setenv("ERIS_KEY_POOL_429_BURST_KEYS", "2")
    monkeypatch.setenv("ERIS_KEY_POOL_429_BURST_WINDOW_S", "30")
    monkeypatch.setenv("ERIS_KEY_POOL_429_GLOBAL_COOLDOWN_S", "2")

    pool = ApiKeyPool(["k1", "k2", "k3", "k4"])
    first = pool.acquire()
    assert first is not None
    assert pool.mark_rate_limited(10, lease=first) is True

    second = pool.acquire(exclude_indices={first.index})
    assert second is not None and second.index != first.index
    assert pool.mark_rate_limited(10, lease=second) is False

    stats = pool.stats()
    assert stats["dead"] == 2  # k3/k4 chưa bị request này quét chết
    assert stats["rate_limit_bursts"] == 1
    assert stats["global_cooldown_ms"] > 0
    assert pool.acquire() is None


def test_pronoun_is_never_a_user_name() -> None:
    assert not is_plausible_user_name("bạn")
    assert not is_valid_name_claim("bạn", "Tên bạn là gì?")
    assert is_valid_name_claim("Nam Hoàng", "Tôi tên là Nam Hoàng")


def test_ai_memory_classification_cannot_turn_ban_into_user_name() -> None:
    policy = MemoryCommitPolicy()
    wrong = {
        "frames": [
            {
                "frame_type": "identity",
                "relation": "name",
                "target": {"text": "bạn", "kind": "person_name"},
                "memory_type": "fact",
                "storage_target": "semantic",
                "fact_key": "user.name",
                "value": "bạn",
                "claim": "Tên người dùng là bạn",
                "importance": 0.95,
                "confidence": 0.99,
                "surface_fn": "can_answer",
            }
        ]
    }
    assert policy.decide_from_user_turn("Bạn khá kiên nhẫn.", llm_structured=wrong) == []

    valid = {
        "frames": [
            {
                "frame_type": "identity",
                "relation": "name",
                "target": {"text": "Nam Hoàng", "kind": "person_name"},
                "memory_type": "fact",
                "storage_target": "semantic",
                "fact_key": "user.name",
                "value": "Nam Hoàng",
                "claim": "Tên người dùng là Nam Hoàng",
                "importance": 0.95,
                "confidence": 0.99,
                "surface_fn": "can_answer",
            }
        ]
    }
    decisions = policy.decide_from_user_turn("Tôi tên là Nam Hoàng.", llm_structured=valid)
    assert decisions and decisions[0].surface == "Nam Hoàng"


def test_invalid_stored_name_is_not_surfaced() -> None:
    ir = MemoryQueryIR(
        intent=QueryIntent.RECALL_FACT,
        target=MemorySelector(fact_key="user.name"),
        confidence=0.9,
        ambiguity=0.0,
        intercept_permission=True,
    )
    result = MemoryQueryExecutor().execute(ir, memory_core={"user": {"name": "bạn"}})
    assert result.found is False
    assert "Tên Ngài là bạn" not in (result.exact_text or "")
