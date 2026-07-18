# -*- coding: utf-8 -*-
"""tests/test_development_bias.py — DevelopmentBias adapters (task 6.1).

Bất biến: bias chỉ chỉnh giọng/khoảng cách/độ-dám-đọc; KHÔNG đụng truth_guard/
không tạo public text.
- R3.1, R7.3: apply_to_slippage giữ truth/capability guard = 1.0.
- R7.4: tom boldness vẫn gated, trong [0,1].
- R8.2: không đụng layer micro (các hàm này thuần, không sờ MentalProcessSystem).
"""

from __future__ import annotations

import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.development_system import DevelopmentBias  # noqa: E402
from cortex.development_bias import (  # noqa: E402
    apply_to_slippage,
    effective_tom_boldness,
    personality_offsets,
)
from runtime.controlled_slippage import ControlledSlippageProfile  # noqa: E402


def test_apply_to_slippage_nudges_relational_but_keeps_truth_guard():
    base = ControlledSlippageProfile(mode="open", lane="relational", intuition_allowance=0.2, friction_permission=0.1)
    bias = DevelopmentBias(read_boldness=0.3, warmth_temperature=0.3, attachment_visibility=0.2)

    out = apply_to_slippage(base, bias)

    assert out.intuition_allowance > base.intuition_allowance
    assert out.friction_permission >= base.friction_permission
    # Bất biến: guard sự thật không bị bias đụng.
    assert out.truth_guard == 1.0
    assert not hasattr(out, "capability_guard")


def test_apply_to_slippage_zero_bias_keeps_guards():
    base = ControlledSlippageProfile(mode="warm")
    out = apply_to_slippage(base, DevelopmentBias())
    assert out.truth_guard == 1.0
    assert not hasattr(out, "capability_guard")


def test_effective_tom_boldness_gated():
    assert effective_tom_boldness(0.5, DevelopmentBias(read_boldness=0.3)) == pytest.approx(0.8)
    assert effective_tom_boldness(0.5, DevelopmentBias()) == pytest.approx(0.5)
    # Clamp trần:
    assert effective_tom_boldness(0.9, DevelopmentBias(read_boldness=0.5)) == pytest.approx(1.0)


def test_personality_offsets_warmth_and_closeness():
    offs = personality_offsets(DevelopmentBias(warmth_temperature=0.2, preferred_distance=-0.2))
    assert offs["warmth"] > 0.2  # ấm + muốn gần hơn → warmth offset lớn hơn warmth thuần
    assert offs["preferred_distance"] == pytest.approx(-0.2)


@settings(max_examples=80)
@given(
    read_boldness=st.floats(min_value=0.0, max_value=0.4, allow_nan=False),
    warmth=st.floats(min_value=0.0, max_value=0.45, allow_nan=False),
    attach=st.floats(min_value=0.0, max_value=0.45, allow_nan=False),
)
def test_property_truth_guard_invariant_under_any_bias(read_boldness, warmth, attach):
    """Với mọi bias, truth_guard luôn = 1.0 và capability_guard không còn tồn tại sau khi áp."""
    base = ControlledSlippageProfile(mode="open", lane="relational")
    bias = DevelopmentBias(read_boldness=read_boldness, warmth_temperature=warmth, attachment_visibility=attach)
    out = apply_to_slippage(base, bias)
    assert out.truth_guard == 1.0
    assert not hasattr(out, "capability_guard")
    assert 0.0 <= out.intuition_allowance <= 1.0
    assert 0.0 <= effective_tom_boldness(0.5, bias) <= 1.0
