from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.banned_filler import BANNED_FILLER_LINES, is_banned_filler, normalize_banned
from cortex.micro_repeat_guard import SemanticRepeatGuard
from cortex.surface_seed_compiler import SurfaceSeedCompiler
from runtime.ambient_silence_policy import should_hold_ambient_silence


# Property 1: No banned output — banned lines are always recognized regardless
# of case/whitespace/trailing-punctuation noise.
@settings(max_examples=200)
@given(
    line=st.sampled_from(BANNED_FILLER_LINES),
    pad_left=st.text(alphabet=" \t\n", max_size=4),
    pad_right=st.text(alphabet=" \t\n.…!", max_size=4),
    upper=st.booleans(),
)
def test_property_banned_lines_always_detected(line, pad_left, pad_right, upper):
    variant = f"{pad_left}{line}{pad_right}"
    if upper:
        variant = variant.upper()
    assert is_banned_filler(variant) is True


# Property 3: No exact repeat within window — an identical line inside the
# exact-repeat window is always rejected.
@settings(max_examples=100)
@given(
    gap=st.floats(min_value=0.0, max_value=110.0),
    text=st.sampled_from(
        (
            "Panel kia vẫn mở năm file.",
            "Terminal đang chạy test nhỉ.",
            "Trình duyệt mở tab tài liệu.",
            "Đoạn code này treo lâu rồi.",
        )
    ),
)
def test_property_exact_repeat_within_window_rejected(gap, text):
    guard = SemanticRepeatGuard()
    guard.remember(text, timestamp=1000.0)
    result = guard.check(text, now=1000.0 + gap)
    # gap <= 110s is within the >=120s exact window, so a verbatim repeat rejects.
    assert result.rejected is True


# Property 2: Grounding dominance — a fresh specific vision fact ranks >= a
# generic private_life seed.
def test_property_grounding_dominance():
    compiler = SurfaceSeedCompiler()
    snapshot = SimpleNamespace(
        vision_facts=("Execution Changes (5 files) - eris - Kiro",),
        recent_events=(),
    )
    vision = compiler._from_vision(snapshot=snapshot, presence_cue=SimpleNamespace(confidence=0.5))
    private = compiler._from_private_life_digest(
        {"current": {"projects": [{"id": "p", "last_note": "mảnh đời riêng", "surface_permission": 0.9, "interest": 0.9}]}}
    )
    assert vision and private
    assert compiler._rank_key(vision[0]) >= compiler._rank_key(private[0])


# Property 7: Muse-cooldown independence — an active muse directive is never
# held purely on cooldown.
@settings(max_examples=100)
@given(
    last_spoken=st.floats(min_value=1.0, max_value=10_000.0),
    now_offset=st.floats(min_value=0.0, max_value=149.0),
)
def test_property_muse_never_held_on_cooldown(last_spoken, now_offset):
    held, reason = should_hold_ambient_silence(
        snapshot=SimpleNamespace(active_window_kind="coding"),
        ti_report=SimpleNamespace(mode="pattern_muse"),
        last_text="vừa nói",
        last_autonomous_spoken_at=last_spoken,
        now=last_spoken + now_offset,
    )
    assert held is False


# Property 9: Config safety — arbitrary env strings never raise and always
# clamp to a valid range.
@settings(max_examples=200)
@given(value=st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs"), max_codepoint=0x7F), max_size=20))
def test_property_config_never_raises(value):
    import runtime.liveliness_config as lc

    keys = (
        "ERIS_LIVELINESS_MAX_LINE_REPEAT",
        "ERIS_LIVELINESS_SIM_THRESHOLD_PCT",
        "ERIS_LIVELINESS_REPEAT_WINDOW_SEC",
        "ERIS_LIVELINESS_MIN_GROUNDED_PCT",
    )
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ[k] = value
        cfg = lc.load_liveliness_config()
        assert 1 <= cfg.max_line_repeat <= 10
        assert 0 <= cfg.sim_threshold_pct <= 100
        assert cfg.repeat_window_sec >= lc.MAX_IDLE_INTERVAL_SEC
        assert 0 <= cfg.min_grounded_pct <= 100
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
