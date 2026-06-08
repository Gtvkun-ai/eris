# -*- coding: utf-8 -*-
"""
tests/test_private_mind_contracts.py
====================================

Contract tests cho các trường epistemic mới trên ba hợp đồng dữ liệu:
- `InternalJudgment` và `SurfaceCandidate` (cortex.private_mind.contracts)
- `SurfaceImpulse` (cortex.surface_arbiter)

Bao phủ:
- Giá trị mặc định: `intent="sincere"`, `epistemic_stance=None` (Req 5.1/5.2/5.3/5.4/5.10).
- Chuẩn hoá `intent` ngoài tập -> `sincere` (Req 5.8).
- Chuẩn hoá `epistemic_stance` ngoài tập -> `None` (Req 5.9).
- `from_mapping` bỏ qua `epistemic_stance`/`intent` -> `intent=sincere`, `stance=None` (Req 5.5).
- `to_dict`/`to_context` luôn có cả hai trường, stance null khi chưa gán (Req 5.6/5.12).
- `intent` được giữ nguyên khi `SurfaceCandidate` dựng từ mapping (Req 5.7).

**Validates: Requirements 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.12**
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import (
    InternalJudgment,
    SurfaceCandidate,
    normalize_intent_field,
    normalize_stance,
)
from cortex.surface_arbiter import SurfaceImpulse


# ---------------------------------------------------------------------------
# Defaults (Req 5.1/5.2/5.3/5.4/5.10)
# ---------------------------------------------------------------------------

def test_surface_candidate_defaults():
    """SurfaceCandidate mặc định: intent=sincere, epistemic_stance=None."""
    cand = SurfaceCandidate(kind="x", topic_seed="hello world")
    assert cand.intent == "sincere"
    assert cand.epistemic_stance is None


def test_internal_judgment_defaults():
    """InternalJudgment mặc định: intent=sincere, epistemic_stance=None."""
    judgment = InternalJudgment(dominant_judgment="some judgment")
    assert judgment.intent == "sincere"
    assert judgment.epistemic_stance is None


def test_surface_impulse_defaults():
    """SurfaceImpulse mặc định: intent=sincere, epistemic_stance=None."""
    impulse = SurfaceImpulse(kind="x", source="private_mind")
    assert impulse.intent == "sincere"
    assert impulse.epistemic_stance is None


# ---------------------------------------------------------------------------
# Intent normalization: out-of-enum -> sincere (Req 5.8)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_intent", ["garbage", "", "123", "   ", None, "SINCERELY"])
def test_surface_candidate_out_of_enum_intent_becomes_sincere(bad_intent):
    """Req 5.8 — intent ngoài tập trên SurfaceCandidate bị loại -> sincere."""
    cand = SurfaceCandidate(kind="x", topic_seed="seed", intent=bad_intent)
    assert cand.intent == "sincere"


@pytest.mark.parametrize("bad_intent", ["garbage", "", "123", "   ", None, "SINCERELY"])
def test_internal_judgment_out_of_enum_intent_becomes_sincere(bad_intent):
    """Req 5.8 — intent ngoài tập trên InternalJudgment bị loại -> sincere."""
    judgment = InternalJudgment(dominant_judgment="j", intent=bad_intent)
    assert judgment.intent == "sincere"


def test_intent_normalization_lowercases_and_strips():
    """Giá trị hợp lệ được chuẩn hoá hoa/thường + khoảng trắng."""
    cand = SurfaceCandidate(kind="x", topic_seed="seed", intent="  PLAYFUL  ")
    assert cand.intent == "playful"


@pytest.mark.parametrize("valid", ["sincere", "playful", "teasing", "speculative"])
def test_valid_intents_pass_through(valid):
    """Mọi intent hợp lệ được giữ nguyên trên cả hai contract."""
    assert SurfaceCandidate(kind="x", topic_seed="s", intent=valid).intent == valid
    assert InternalJudgment(dominant_judgment="j", intent=valid).intent == valid


# ---------------------------------------------------------------------------
# Stance normalization: out-of-enum -> None (Req 5.9)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_stance", ["garbage", "", "123", "   ", "GROUND"])
def test_surface_candidate_out_of_enum_stance_becomes_none(bad_stance):
    """Req 5.9 — epistemic_stance ngoài tập trên SurfaceCandidate -> None."""
    cand = SurfaceCandidate(kind="x", topic_seed="seed", epistemic_stance=bad_stance)
    assert cand.epistemic_stance is None


@pytest.mark.parametrize("bad_stance", ["garbage", "", "123", "   ", "GROUND"])
def test_internal_judgment_out_of_enum_stance_becomes_none(bad_stance):
    """Req 5.9 — epistemic_stance ngoài tập trên InternalJudgment -> None."""
    judgment = InternalJudgment(dominant_judgment="j", epistemic_stance=bad_stance)
    assert judgment.epistemic_stance is None


@pytest.mark.parametrize("valid", ["grounded", "ungrounded_aware", "ungrounded_blind"])
def test_valid_stances_pass_through(valid):
    """Mọi stance hợp lệ được giữ nguyên (chuẩn hoá hoa/thường)."""
    assert SurfaceCandidate(kind="x", topic_seed="s", epistemic_stance=valid).epistemic_stance == valid
    assert SurfaceCandidate(kind="x", topic_seed="s", epistemic_stance=valid.upper()).epistemic_stance == valid
    assert InternalJudgment(dominant_judgment="j", epistemic_stance=valid).epistemic_stance == valid


def test_normalize_helpers_directly():
    """normalize_stance/normalize_intent_field hoạt động độc lập."""
    assert normalize_stance("grounded") == "grounded"
    assert normalize_stance("nope") is None
    assert normalize_stance(None) is None
    assert normalize_intent_field("teasing") == "teasing"
    assert normalize_intent_field("nope") == "sincere"
    assert normalize_intent_field(None) == "sincere"


# ---------------------------------------------------------------------------
# from_mapping omitting both fields (Req 5.5)
# ---------------------------------------------------------------------------

def test_internal_judgment_from_mapping_omits_fields():
    """Req 5.5 — mapping thiếu cả hai trường -> intent=sincere, stance=None."""
    judgment = InternalJudgment.from_mapping({"dominant_judgment": "j"})
    assert judgment.intent == "sincere"
    assert judgment.epistemic_stance is None


def test_surface_candidate_from_mapping_omits_fields():
    """SurfaceCandidate.from_mapping thiếu hai trường -> intent=sincere, stance=None."""
    cand = SurfaceCandidate.from_mapping({"topic_seed": "s"})
    assert cand.intent == "sincere"
    assert cand.epistemic_stance is None


# ---------------------------------------------------------------------------
# from_mapping copies intent unchanged (Req 5.7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valid", ["sincere", "playful", "teasing", "speculative"])
def test_surface_candidate_from_mapping_copies_intent_unchanged(valid):
    """Req 5.7 — intent hợp lệ trong mapping được giữ nguyên trên SurfaceCandidate."""
    cand = SurfaceCandidate.from_mapping({"topic_seed": "s", "intent": valid})
    assert cand.intent == valid


def test_internal_judgment_from_mapping_reads_both_fields():
    """from_mapping đọc cả epistemic_stance lẫn intent hợp lệ."""
    judgment = InternalJudgment.from_mapping(
        {"dominant_judgment": "j", "intent": "playful", "epistemic_stance": "ungrounded_aware"}
    )
    assert judgment.intent == "playful"
    assert judgment.epistemic_stance == "ungrounded_aware"


def test_surface_candidate_from_mapping_out_of_enum_values():
    """from_mapping áp dụng cùng quy tắc chuẩn hoá: intent->sincere, stance->None."""
    cand = SurfaceCandidate.from_mapping(
        {"topic_seed": "s", "intent": "garbage", "epistemic_stance": "garbage"}
    )
    assert cand.intent == "sincere"
    assert cand.epistemic_stance is None


# ---------------------------------------------------------------------------
# to_dict / to_context include both fields (Req 5.6/5.12)
# ---------------------------------------------------------------------------

def test_surface_candidate_to_dict_includes_both_fields():
    """Req 5.6 — to_dict luôn có epistemic_stance + intent; stance null khi chưa gán."""
    data = SurfaceCandidate(kind="x", topic_seed="s").to_dict()
    assert "epistemic_stance" in data
    assert "intent" in data
    assert data["epistemic_stance"] is None
    assert data["intent"] == "sincere"


def test_surface_candidate_to_dict_emits_set_values():
    """to_dict phát ra giá trị đã gán."""
    data = SurfaceCandidate(
        kind="x", topic_seed="s", epistemic_stance="grounded", intent="teasing"
    ).to_dict()
    assert data["epistemic_stance"] == "grounded"
    assert data["intent"] == "teasing"


def test_internal_judgment_to_dict_includes_both_fields():
    """Req 5.6 — InternalJudgment.to_dict luôn có cả hai trường."""
    data = InternalJudgment(dominant_judgment="j").to_dict()
    assert "epistemic_stance" in data
    assert "intent" in data
    assert data["epistemic_stance"] is None
    assert data["intent"] == "sincere"


def test_surface_impulse_to_context_includes_both_fields():
    """Req 5.12 — SurfaceImpulse.to_context luôn có cả hai trường; stance null khi chưa gán."""
    ctx = SurfaceImpulse(kind="x", source="private_mind").to_context()
    assert "epistemic_stance" in ctx
    assert "intent" in ctx
    assert ctx["epistemic_stance"] is None
    assert ctx["intent"] == "sincere"


def test_surface_impulse_to_context_emits_set_values():
    """to_context phát ra giá trị đã gán trên SurfaceImpulse."""
    ctx = SurfaceImpulse(
        kind="x", source="private_mind", epistemic_stance="ungrounded_aware", intent="playful"
    ).to_context()
    assert ctx["epistemic_stance"] == "ungrounded_aware"
    assert ctx["intent"] == "playful"


# ---------------------------------------------------------------------------
# Round-trip serialization (Req 5.6)
# ---------------------------------------------------------------------------

def test_surface_candidate_round_trip_preserves_fields():
    """to_dict -> from_mapping giữ nguyên epistemic_stance + intent hợp lệ."""
    original = SurfaceCandidate(
        kind="x", topic_seed="s", epistemic_stance="grounded", intent="speculative"
    )
    restored = SurfaceCandidate.from_mapping(original.to_dict())
    assert restored.epistemic_stance == "grounded"
    assert restored.intent == "speculative"


def test_internal_judgment_round_trip_preserves_fields():
    """to_dict -> from_mapping giữ nguyên epistemic_stance + intent hợp lệ."""
    original = InternalJudgment(
        dominant_judgment="j", epistemic_stance="ungrounded_blind", intent="teasing"
    )
    restored = InternalJudgment.from_mapping(original.to_dict())
    assert restored.epistemic_stance == "ungrounded_blind"
    assert restored.intent == "teasing"
